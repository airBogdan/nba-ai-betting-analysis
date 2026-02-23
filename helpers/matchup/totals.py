"""Totals/Over-Under analysis computations."""

import math
from typing import List, Optional

from ..api import RecentGame
from ..types import H2HResults, H2HSummary
from .types import (
    DEFAULT_LEAGUE_AVG_TOTAL,
    LEAGUE_AVG_TOTAL_MAX,
    LEAGUE_AVG_TOTAL_MIN,
    REGRESSION_FACTOR,
    TeamSnapshot,
    TotalsAnalysis,
)


def compute_totals_analysis(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    h2h_summary: Optional[H2HSummary],
    h2h_results: Optional[H2HResults],
    team1_recent: List[RecentGame],
    team2_recent: List[RecentGame]
) -> TotalsAnalysis:
    """Compute totals/O-U analysis."""
    # Current combined PPG
    current_total = team1["ppg"] + team2["ppg"]

    # Dynamic league average total from team data
    team1_game_avg = team1["ppg"] + team1["opp_ppg"]
    team2_game_avg = team2["ppg"] + team2["opp_ppg"]
    league_avg_total = round((team1_game_avg + team2_game_avg) / 2, 1)
    if league_avg_total < LEAGUE_AVG_TOTAL_MIN or league_avg_total > LEAGUE_AVG_TOTAL_MAX:
        league_avg_total = DEFAULT_LEAGUE_AVG_TOTAL

    # H2H historical average total
    h2h_avg_total = h2h_summary.get("avg_total_points", league_avg_total) if h2h_summary else league_avg_total

    # Expected total: weight current form vs H2H/baseline
    h2h_weight = 0.4 if h2h_summary else 0.2
    expected_total = round(current_total * (1 - h2h_weight) + h2h_avg_total * h2h_weight, 1)

    # Regression to mean
    deviation = expected_total - league_avg_total
    expected_total = round(expected_total - deviation * REGRESSION_FACTOR, 1)

    # How each team's current scoring compares to their H2H average
    team1_h2h_scoring_diff = round(team1["ppg"] - h2h_summary["team1_avg_points"], 1) if h2h_summary else 0.0
    team2_h2h_scoring_diff = round(team2["ppg"] - h2h_summary["team2_avg_points"], 1) if h2h_summary else 0.0

    # Calculate margin and total volatility
    margin_volatility = 0.0
    h2h_total_variance = 0.0
    if h2h_results:
        all_games = [g for games in h2h_results.values() for g in games]
        if len(all_games) > 1:
            # Margin volatility: std dev of point differentials
            margins = [abs(g["point_diff"]) for g in all_games]
            avg_margin = sum(margins) / len(margins)
            margin_var = sum((m - avg_margin) ** 2 for m in margins) / (len(margins) - 1)
            margin_volatility = round(math.sqrt(margin_var), 1)

            # H2H total variance: std dev of combined scores
            totals = [g["home_points"] + g["visitor_points"] for g in all_games]
            avg_total = sum(totals) / len(totals)
            total_var = sum((t - avg_total) ** 2 for t in totals) / (len(totals) - 1)
            h2h_total_variance = round(math.sqrt(total_var), 1)

    # Pace-adjusted total (both teams' expected scoring)
    combined_pace = (team1["pace"] + team2["pace"]) / 2
    pace_adjusted_total = round(combined_pace * (team1["ortg"] + team2["ortg"]) / 100, 1)

    # Defense factor
    defense_factor = round((team1["drtg"] + team2["drtg"]) / 2, 1)

    # Recent scoring trend (team PPG only, not combined game totals)
    recent_scoring_trend = 0.0
    if team1_recent and team2_recent:
        team1_recent_ppg = sum(int(g["score"].split("-")[0]) for g in team1_recent) / len(team1_recent)
        team2_recent_ppg = sum(int(g["score"].split("-")[0]) for g in team2_recent) / len(team2_recent)
        recent_combined = team1_recent_ppg + team2_recent_ppg
        season_combined = team1["ppg"] + team2["ppg"]
        recent_scoring_trend = round(recent_combined - season_combined, 1)

    return {
        "expected_total": expected_total,
        "total_diff_from_h2h": round(current_total - h2h_avg_total, 1),
        "team1_h2h_scoring_diff": team1_h2h_scoring_diff,
        "team2_h2h_scoring_diff": team2_h2h_scoring_diff,
        "margin_volatility": margin_volatility,
        "h2h_total_variance": h2h_total_variance,
        "pace_adjusted_total": pace_adjusted_total,
        "defense_factor": defense_factor,
        "recent_scoring_trend": recent_scoring_trend,
    }
