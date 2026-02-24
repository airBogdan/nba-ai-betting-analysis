"""H2H-based signal generation for matchups."""

from typing import List, Optional

from .types import (
    FGP_DIFF_THRESHOLD,
    HALF_SCORING_DIFF_THRESHOLD,
    HALFTIME_LEADER_THRESHOLD,
    QUARTER_DIFF_THRESHOLD,
    REB_DIFF_THRESHOLD,
    TOV_DIFF_THRESHOLD,
    TPP_DIFF_THRESHOLD,
    H2H,
    TeamSnapshot,
)


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
