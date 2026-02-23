"""Contextual signal generation for matchups."""

from typing import List, Optional

from ..api import RecentGame
from .types import (
    AWAY_STRONG_THRESHOLD,
    AWAY_WEAK_THRESHOLD,
    BACK_TO_BACK_THRESHOLD,
    FAST_PACE_THRESHOLD,
    FGP_DIFF_THRESHOLD,
    FORM_COLD_THRESHOLD,
    FORM_HOT_THRESHOLD,
    H2H_VARIANCE_THRESHOLD,
    HALF_SCORING_DIFF_THRESHOLD,
    HALFTIME_LEADER_THRESHOLD,
    HOME_STRONG_THRESHOLD,
    HOME_WEAK_THRESHOLD,
    NET_RATING_EDGE_THRESHOLD,
    PPG_EDGE_THRESHOLD,
    QUARTER_DIFF_THRESHOLD,
    REB_DIFF_THRESHOLD,
    REST_ADVANTAGE_THRESHOLD,
    SCORING_REGRESSION_THRESHOLD,
    SCORING_TREND_THRESHOLD,
    SLOW_PACE_THRESHOLD,
    STAR_DEPENDENCY_THRESHOLD,
    TOV_DIFF_THRESHOLD,
    TPP_DIFF_THRESHOLD,
    H2H,
    MatchupEdges,
    TeamPlayers,
    TeamSnapshot,
    TotalsAnalysis,
)
from .schedule import compute_days_rest, compute_streak


def _rest_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    team1_recent: List[RecentGame],
    team2_recent: List[RecentGame],
    game_date: Optional[str],
) -> List[str]:
    """Back-to-back detection and rest advantage signals."""
    signals: List[str] = []
    team1_rest = compute_days_rest(team1_recent, game_date)
    team2_rest = compute_days_rest(team2_recent, game_date)

    if team1_rest is not None and team1_rest <= BACK_TO_BACK_THRESHOLD:
        rest_label = "playing second game today" if team1_rest == 0 else "on back-to-back"
        signals.append(f"{team1['name']} {rest_label} (fatigue factor)")
    if team2_rest is not None and team2_rest <= BACK_TO_BACK_THRESHOLD:
        rest_label = "playing second game today" if team2_rest == 0 else "on back-to-back"
        signals.append(f"{team2['name']} {rest_label} (fatigue factor)")

    if team1_rest is not None and team2_rest is not None:
        rest_diff = team1_rest - team2_rest
        if rest_diff >= REST_ADVANTAGE_THRESHOLD:
            signals.append(f"{team1['name']} rest advantage ({team1_rest} days vs {team2_rest} days)")
        elif rest_diff <= -REST_ADVANTAGE_THRESHOLD:
            signals.append(f"{team2['name']} rest advantage ({team2_rest} days vs {team1_rest} days)")

    return signals


def _star_player_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    team1_players: Optional[TeamPlayers],
    team2_players: Optional[TeamPlayers],
) -> List[str]:
    """Star dependency when not at full strength."""
    signals: List[str] = []
    if team1_players and not team1_players["full_strength"] and team1_players["star_dependency"] > STAR_DEPENDENCY_THRESHOLD:
        signals.append(f"{team1['name']} missing {team1_players['star_dependency']:.0f}% of offense with key players limited")
    if team2_players and not team2_players["full_strength"] and team2_players["star_dependency"] > STAR_DEPENDENCY_THRESHOLD:
        signals.append(f"{team2['name']} missing {team2_players['star_dependency']:.0f}% of offense with key players limited")
    return signals


def _streak_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    team1_recent: List[RecentGame],
    team2_recent: List[RecentGame],
) -> List[str]:
    """Win/loss streak (3+) signals."""
    signals: List[str] = []
    team1_streak = compute_streak(team1_recent)
    team2_streak = compute_streak(team2_recent)

    if team1_streak["count"] >= 3:
        streak_word = "won" if team1_streak["type"] == "W" else "lost"
        signals.append(f"{team1['name']} {streak_word} {team1_streak['count']} straight")
    if team2_streak["count"] >= 3:
        streak_word = "won" if team2_streak["type"] == "W" else "lost"
        signals.append(f"{team2['name']} {streak_word} {team2_streak['count']} straight")
    return signals


def _h2h_quarter_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    h2h: Optional[H2H],
) -> List[str]:
    """Q1/Q4 tendencies, halftime leader, half scoring from H2H."""
    signals: List[str] = []
    if not h2h:
        signals.append("No recent H2H history - projections based on current season stats only")
        return signals

    if not h2h.get("quarters"):
        return signals

    q = h2h["quarters"]

    q1_diff = q["team1_q1_avg"] - q["team2_q1_avg"]
    if abs(q1_diff) >= QUARTER_DIFF_THRESHOLD:
        q1_leader = team1["name"] if q1_diff > 0 else team2["name"]
        signals.append(f"{q1_leader} starts faster (+{abs(q1_diff):.1f} Q1 avg in H2H)")

    q4_diff = q["team1_q4_avg"] - q["team2_q4_avg"]
    if abs(q4_diff) >= QUARTER_DIFF_THRESHOLD:
        q4_leader = team1["name"] if q4_diff > 0 else team2["name"]
        signals.append(f"{q4_leader} stronger closer (+{abs(q4_diff):.1f} Q4 avg in H2H)")

    if q["halftime_leader_wins_pct"] >= HALFTIME_LEADER_THRESHOLD:
        signals.append(f"Halftime leader wins {q['halftime_leader_wins_pct'] * 100:.0f}% in this matchup")

    half_diff = q["avg_first_half"] - q["avg_second_half"]
    if abs(half_diff) >= HALF_SCORING_DIFF_THRESHOLD:
        if half_diff > 0:
            signals.append(f"H2H games front-loaded (1H avg {q['avg_first_half']} vs 2H avg {q['avg_second_half']})")
        else:
            signals.append(f"H2H games back-loaded (2H avg {q['avg_second_half']} vs 1H avg {q['avg_first_half']})")

    return signals


def _availability_and_form_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    home_snapshot: TeamSnapshot,
    away_snapshot: TeamSnapshot,
    team1_players: Optional[TeamPlayers],
    team2_players: Optional[TeamPlayers],
) -> List[str]:
    """Injury concerns, L10 form, home/away performance."""
    signals: List[str] = []

    if team1_players and not team1_players["full_strength"]:
        concerns = team1_players["availability_concerns"][:2]
        signals.append(f"{team1['name']} injury concerns: {', '.join(concerns)}")
    if team2_players and not team2_players["full_strength"]:
        concerns = team2_players["availability_concerns"][:2]
        signals.append(f"{team2['name']} injury concerns: {', '.join(concerns)}")

    if team1["last_ten_pct"] >= FORM_HOT_THRESHOLD:
        signals.append(f"{team1['name']} hot form ({team1['last_ten']} L10)")
    elif team1["last_ten_pct"] <= FORM_COLD_THRESHOLD:
        signals.append(f"{team1['name']} struggling ({team1['last_ten']} L10)")

    if team2["last_ten_pct"] >= FORM_HOT_THRESHOLD:
        signals.append(f"{team2['name']} hot form ({team2['last_ten']} L10)")
    elif team2["last_ten_pct"] <= FORM_COLD_THRESHOLD:
        signals.append(f"{team2['name']} struggling ({team2['last_ten']} L10)")

    if home_snapshot["home_win_pct"] > HOME_STRONG_THRESHOLD:
        signals.append(f"{home_snapshot['name']} strong at home ({home_snapshot['home_record']})")
    elif home_snapshot["home_win_pct"] < HOME_WEAK_THRESHOLD:
        signals.append(f"{home_snapshot['name']} struggling at home ({home_snapshot['home_record']})")

    if away_snapshot["away_win_pct"] > AWAY_STRONG_THRESHOLD:
        signals.append(f"{away_snapshot['name']} solid on road ({away_snapshot['away_record']})")
    elif away_snapshot["away_win_pct"] < AWAY_WEAK_THRESHOLD:
        signals.append(f"{away_snapshot['name']} poor on road ({away_snapshot['away_record']})")

    return signals


def _edge_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    comparison: MatchupEdges,
) -> List[str]:
    """PPG edge, net rating edge, SOS signals."""
    signals: List[str] = []

    if abs(comparison["ppg"]) >= PPG_EDGE_THRESHOLD:
        better = team1["name"] if comparison["ppg"] > 0 else team2["name"]
        signals.append(f"{better} +{abs(comparison['ppg']):.1f} PPG edge")

    if abs(comparison["net_rating"]) >= NET_RATING_EDGE_THRESHOLD:
        better = team1["name"] if comparison["net_rating"] > 0 else team2["name"]
        signals.append(f"{better} significantly better net rating (+{abs(comparison['net_rating']):.1f})")

    sos_diff = abs(team1.get("sos", 0.5) - team2.get("sos", 0.5))
    if sos_diff > 0.05:
        t1_sos = team1.get("sos", 0.5)
        t2_sos = team2.get("sos", 0.5)
        harder = team1["name"] if t1_sos > t2_sos else team2["name"]
        signals.append(f"{harder} faced tougher schedule (SOS: {max(t1_sos, t2_sos):.3f} vs {min(t1_sos, t2_sos):.3f})")

    return signals


def _h2h_record_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    h2h: Optional[H2H],
) -> List[str]:
    """Recent H2H record, patterns, O/U from H2H."""
    if not h2h:
        return []

    signals: List[str] = []
    summary = h2h["summary"]
    patterns = h2h["patterns"]
    recent = h2h["recent"]

    if recent["games_last_2_seasons"] >= 3:
        if recent["team1_wins_last_2_seasons"] > recent["team2_wins_last_2_seasons"] + 1:
            signals.append(f"{team1['name']} {recent['team1_wins_last_2_seasons']}-{recent['team2_wins_last_2_seasons']} in recent H2H")
        elif recent["team2_wins_last_2_seasons"] > recent["team1_wins_last_2_seasons"] + 1:
            signals.append(f"{team2['name']} {recent['team2_wins_last_2_seasons']}-{recent['team1_wins_last_2_seasons']} in recent H2H")

    if summary["recent_trend"] != "balanced":
        hot_team = team1["name"] if summary["recent_trend"] == "team1_hot" else team2["name"]
        signals.append(f"{hot_team} won 4+ of last 5 H2H meetings")

    if patterns["high_scoring_pct"] > 0.6:
        signals.append(f"High-scoring matchup ({patterns['high_scoring_pct'] * 100:.0f}% H2H games over 220)")
    elif patterns["high_scoring_pct"] < 0.3:
        signals.append(f"Lower-scoring matchup (only {patterns['high_scoring_pct'] * 100:.0f}% H2H games over 220)")
    if patterns["close_game_pct"] > 0.4:
        signals.append(f"Competitive series ({patterns['close_game_pct'] * 100:.0f}% decided by 5 or less)")

    return signals


def _totals_signals(
    comparison: MatchupEdges,
    totals_analysis: TotalsAnalysis,
) -> List[str]:
    """Pace O/U, scoring trend, variance warning."""
    signals: List[str] = []

    if comparison["combined_pace"] > FAST_PACE_THRESHOLD:
        signals.append(f"Fast-paced matchup (avg {comparison['combined_pace']} possessions) - lean OVER")
    elif comparison["combined_pace"] < SLOW_PACE_THRESHOLD:
        signals.append(f"Slow-paced matchup (avg {comparison['combined_pace']} possessions) - lean UNDER")

    if abs(totals_analysis["recent_scoring_trend"]) > SCORING_TREND_THRESHOLD:
        if totals_analysis["recent_scoring_trend"] > 0:
            signals.append(f"Both teams scoring above season avg in recent games (+{totals_analysis['recent_scoring_trend']} combined)")
        else:
            signals.append(f"Both teams scoring below season avg in recent games ({totals_analysis['recent_scoring_trend']} combined)")

    if totals_analysis["h2h_total_variance"] > H2H_VARIANCE_THRESHOLD:
        signals.append(f"High-variance H2H (±{totals_analysis['h2h_total_variance']} pts std dev in totals)")

    return signals


def _matchup_stats_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    h2h: Optional[H2H],
) -> List[str]:
    """FG%, 3P%, TOV, REB — H2H vs season performance."""
    if not h2h or not h2h.get("matchup_stats"):
        return []

    signals: List[str] = []
    ms = h2h["matchup_stats"]
    t1_h2h = ms["team1"]
    t2_h2h = ms["team2"]

    # FG%
    t1_fgp_diff = t1_h2h["avg_fgp"] - team1["fgp"]
    t2_fgp_diff = t2_h2h["avg_fgp"] - team2["fgp"]
    if abs(t1_fgp_diff) >= FGP_DIFF_THRESHOLD:
        direction = "elevated" if t1_fgp_diff > 0 else "suppressed"
        signals.append(f"{team1['name']} FG% {direction} vs {team2['name']}: {t1_h2h['avg_fgp']}% H2H vs {team1['fgp']}% season")
    if abs(t2_fgp_diff) >= FGP_DIFF_THRESHOLD:
        direction = "elevated" if t2_fgp_diff > 0 else "suppressed"
        signals.append(f"{team2['name']} FG% {direction} vs {team1['name']}: {t2_h2h['avg_fgp']}% H2H vs {team2['fgp']}% season")

    # 3P%
    t1_tpp_diff = t1_h2h["avg_tpp"] - team1["tpp"]
    t2_tpp_diff = t2_h2h["avg_tpp"] - team2["tpp"]
    if abs(t1_tpp_diff) >= TPP_DIFF_THRESHOLD:
        direction = "hot" if t1_tpp_diff > 0 else "cold"
        signals.append(f"{team1['name']} {direction} from 3 vs {team2['name']}: {t1_h2h['avg_tpp']}% H2H vs {team1['tpp']}% season")
    if abs(t2_tpp_diff) >= TPP_DIFF_THRESHOLD:
        direction = "hot" if t2_tpp_diff > 0 else "cold"
        signals.append(f"{team2['name']} {direction} from 3 vs {team1['name']}: {t2_h2h['avg_tpp']}% H2H vs {team2['tpp']}% season")

    # Turnovers
    t1_tov_diff = t1_h2h["avg_turnovers"] - team1["topg"]
    t2_tov_diff = t2_h2h["avg_turnovers"] - team2["topg"]
    if abs(t1_tov_diff) >= TOV_DIFF_THRESHOLD:
        direction = "careless" if t1_tov_diff > 0 else "careful"
        signals.append(f"{team1['name']} more {direction} vs {team2['name']}: {t1_h2h['avg_turnovers']} H2H vs {team1['topg']} season TOV")
    if abs(t2_tov_diff) >= TOV_DIFF_THRESHOLD:
        direction = "careless" if t2_tov_diff > 0 else "careful"
        signals.append(f"{team2['name']} more {direction} vs {team1['name']}: {t2_h2h['avg_turnovers']} H2H vs {team2['topg']} season TOV")

    # Rebounding
    t1_reb_diff = t1_h2h["avg_rebounds"] - team1["rpg"]
    t2_reb_diff = t2_h2h["avg_rebounds"] - team2["rpg"]
    if abs(t1_reb_diff) >= REB_DIFF_THRESHOLD:
        direction = "dominates" if t1_reb_diff > 0 else "struggles on"
        signals.append(f"{team1['name']} {direction} boards vs {team2['name']}: {t1_h2h['avg_rebounds']} H2H vs {team1['rpg']} season")
    if abs(t2_reb_diff) >= REB_DIFF_THRESHOLD:
        direction = "dominates" if t2_reb_diff > 0 else "struggles on"
        signals.append(f"{team2['name']} {direction} boards vs {team1['name']}: {t2_h2h['avg_rebounds']} H2H vs {team2['rpg']} season")

    return signals


def _regression_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
) -> List[str]:
    """Scoring above/below season avg — regression/bounce-back signals."""
    signals: List[str] = []
    for team in (team1, team2):
        diff = team.get("recent_ppg", team["ppg"]) - team["ppg"]
        if abs(diff) >= SCORING_REGRESSION_THRESHOLD:
            if diff > 0:
                signals.append(f"{team['name']} scoring {diff:+.1f} PPG above season avg recently — regression likely")
            else:
                signals.append(f"{team['name']} scoring {diff:+.1f} PPG below season avg recently — bounce-back likely")
    return signals


def generate_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    home_team: str,
    comparison: MatchupEdges,
    h2h: Optional[H2H],
    team1_players: Optional[TeamPlayers],
    team2_players: Optional[TeamPlayers],
    totals_analysis: TotalsAnalysis,
    team1_recent: List[RecentGame],
    team2_recent: List[RecentGame],
    game_date: Optional[str] = None,
) -> List[str]:
    """Generate contextual signals for the matchup."""
    is_team1_home = team1["name"] == home_team
    home_snapshot = team1 if is_team1_home else team2
    away_snapshot = team2 if is_team1_home else team1

    signals: List[str] = []
    signals.extend(_rest_signals(team1, team2, team1_recent, team2_recent, game_date))
    signals.extend(_star_player_signals(team1, team2, team1_players, team2_players))
    signals.extend(_streak_signals(team1, team2, team1_recent, team2_recent))
    signals.extend(_h2h_quarter_signals(team1, team2, h2h))
    signals.extend(_availability_and_form_signals(team1, team2, home_snapshot, away_snapshot, team1_players, team2_players))
    signals.extend(_edge_signals(team1, team2, comparison))
    signals.extend(_h2h_record_signals(team1, team2, h2h))
    signals.extend(_totals_signals(comparison, totals_analysis))
    signals.extend(_matchup_stats_signals(team1, team2, h2h))
    signals.extend(_regression_signals(team1, team2))
    return signals
