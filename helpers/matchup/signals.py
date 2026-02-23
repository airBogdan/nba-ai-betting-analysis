"""Contextual signal generation for matchups."""

from typing import List, Optional

from ..api import RecentGame
from .types import (
    AWAY_STRONG_THRESHOLD,
    AWAY_WEAK_THRESHOLD,
    BACK_TO_BACK_THRESHOLD,
    FAST_PACE_THRESHOLD,
    FORM_COLD_THRESHOLD,
    FORM_HOT_THRESHOLD,
    H2H_VARIANCE_THRESHOLD,
    HOME_STRONG_THRESHOLD,
    HOME_WEAK_THRESHOLD,
    NET_RATING_EDGE_THRESHOLD,
    PPG_EDGE_THRESHOLD,
    REST_ADVANTAGE_THRESHOLD,
    SCORING_REGRESSION_THRESHOLD,
    SCORING_TREND_THRESHOLD,
    SLOW_PACE_THRESHOLD,
    STAR_DEPENDENCY_THRESHOLD,
    H2H,
    MatchupEdges,
    TeamPlayers,
    TeamSnapshot,
    TotalsAnalysis,
)
from .schedule import compute_days_rest, compute_streak
from .signals_h2h import _h2h_quarter_signals, _h2h_record_signals, _matchup_stats_signals


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
