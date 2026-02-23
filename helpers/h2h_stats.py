"""H2H statistical analysis — summary and quarter breakdowns."""

from typing import Any, Dict, List, Optional, Tuple

from .types import H2HResults, H2HSummary, QuarterAnalysis
from .utils import get_current_nba_season_year

# Season-based decay weights for H2H games: (current, previous, oldest)
H2H_SEASON_WEIGHTS = (1.0, 0.6, 0.3)


def _weighted_h2h_games(h2h_results: H2HResults) -> List[Tuple[Dict[str, Any], float]]:
    """Assign season-based recency weights to H2H games.

    Sorts seasons most-recent-first, assigns weight from H2H_SEASON_WEIGHTS
    by index, divides each season's weight equally among its games, then
    normalizes so all per-game weights sum to 1.0.

    Returns list of (game, weight) tuples, most recent season first.
    Falls back to uniform weights if get_current_nba_season_year() returns None.
    """
    if not h2h_results:
        return []

    current_season = get_current_nba_season_year()
    seasons_desc = sorted(h2h_results.keys(), reverse=True)

    if current_season is None:
        # Off-season: uniform weights
        all_games = [g for s in seasons_desc for g in h2h_results[s]]
        if not all_games:
            return []
        w = 1.0 / len(all_games)
        return [(g, w) for g in all_games]

    # Assign raw per-game weights based on season index
    weighted: List[Tuple[Dict[str, Any], float]] = []
    for season in seasons_desc:
        games = h2h_results[season]
        if not games:
            continue
        idx = max(0, current_season - season)
        season_weight = H2H_SEASON_WEIGHTS[idx] if idx < len(H2H_SEASON_WEIGHTS) else H2H_SEASON_WEIGHTS[-1]
        per_game = season_weight / len(games)
        for game in games:
            weighted.append((game, per_game))

    if not weighted:
        return []

    # Normalize so weights sum to 1.0
    total = sum(w for _, w in weighted)
    return [(g, w / total) for g, w in weighted]


def compute_quarter_analysis(
    h2h_results: H2HResults,
    team1: str,
    team2: str
) -> Optional[QuarterAnalysis]:
    """Compute quarter-by-quarter analysis of H2H games with recency weighting."""
    weighted_games = _weighted_h2h_games(h2h_results)

    # Filter to games with quarter data, renormalize weights
    filtered = [
        (g, w) for g, w in weighted_games
        if g.get("home_linescore") and len(g["home_linescore"]) >= 4
        and g.get("visitor_linescore") and len(g["visitor_linescore"]) >= 4
    ]

    if not filtered:
        return None

    # Renormalize weights after filtering
    total_w = sum(w for _, w in filtered)
    filtered = [(g, w / total_w) for g, w in filtered]

    total_q1 = 0.0
    total_q2 = 0.0
    total_q3 = 0.0
    total_q4 = 0.0
    team1_q1 = 0.0
    team2_q1 = 0.0
    team1_q4 = 0.0
    team2_q4 = 0.0
    halftime_leader_wins = 0
    n = len(filtered)

    for game, w in filtered:
        home_qs = game["home_linescore"]
        visitor_qs = game["visitor_linescore"]

        # Weighted quarter totals (combined)
        total_q1 += (home_qs[0] + visitor_qs[0]) * w
        total_q2 += (home_qs[1] + visitor_qs[1]) * w
        total_q3 += (home_qs[2] + visitor_qs[2]) * w
        total_q4 += (home_qs[3] + visitor_qs[3]) * w

        # Team-specific quarter scores
        is_team1_home = game["home_team"] == team1
        team1_qs = home_qs if is_team1_home else visitor_qs
        team2_qs = visitor_qs if is_team1_home else home_qs

        team1_q1 += team1_qs[0] * w
        team2_q1 += team2_qs[0] * w
        team1_q4 += team1_qs[3] * w
        team2_q4 += team2_qs[3] * w

        # Halftime leader analysis (unweighted count)
        team1_halftime = team1_qs[0] + team1_qs[1]
        team2_halftime = team2_qs[0] + team2_qs[1]
        halftime_leader = team1 if team1_halftime > team2_halftime else team2
        if halftime_leader == game["winner"]:
            halftime_leader_wins += 1

    return {
        "avg_q1_total": round(total_q1, 1),
        "avg_q2_total": round(total_q2, 1),
        "avg_q3_total": round(total_q3, 1),
        "avg_q4_total": round(total_q4, 1),
        "avg_first_half": round(total_q1 + total_q2, 1),
        "avg_second_half": round(total_q3 + total_q4, 1),
        "team1_q1_avg": round(team1_q1, 1),
        "team2_q1_avg": round(team2_q1, 1),
        "team1_q4_avg": round(team1_q4, 1),
        "team2_q4_avg": round(team2_q4, 1),
        "halftime_leader_wins_pct": round(halftime_leader_wins / n, 2),
    }


def compute_h2h_summary(h2h_results: H2HResults, team1: str, team2: str) -> H2HSummary:
    """Compute summary statistics for H2H matchup with recency-weighted averages."""
    weighted_games = _weighted_h2h_games(h2h_results)

    # Also build season-sorted flat list for unweighted counts
    all_items: List[Dict[str, Any]] = []
    for season, games in h2h_results.items():
        for game in games:
            all_items.append({"game": game, "season": int(season)})
    all_items.sort(key=lambda x: x["season"], reverse=True)

    team1_wins = 0
    team2_wins = 0
    team1_home_wins = 0
    team1_home_losses = 0
    team1_away_wins = 0
    team1_away_losses = 0
    close_games = 0
    blowouts = 0

    # Weighted accumulators for averages
    weighted_point_diff = 0.0
    weighted_team1_points = 0.0
    weighted_team2_points = 0.0

    for game, w in weighted_games:
        is_team1_home = game["home_team"] == team1
        team1_points = game["home_points"] if is_team1_home else game["visitor_points"]
        team2_points = game["visitor_points"] if is_team1_home else game["home_points"]
        diff = team1_points - team2_points

        # Weighted averages
        weighted_point_diff += diff * w
        weighted_team1_points += team1_points * w
        weighted_team2_points += team2_points * w

        # Unweighted counts
        if abs(diff) <= 5:
            close_games += 1
        if abs(diff) >= 15:
            blowouts += 1

        if game["winner"] == team1:
            team1_wins += 1
            if is_team1_home:
                team1_home_wins += 1
            else:
                team1_away_wins += 1
        elif game["winner"] == team2:
            team2_wins += 1
            if is_team1_home:
                team1_home_losses += 1
            else:
                team1_away_losses += 1

    total_games = len(weighted_games)
    last_5 = [item["game"]["winner"] for item in all_items[:5]]

    # Determine recent trend based on last 5 games
    recent_team1_wins = sum(1 for w in last_5 if w == team1)
    if recent_team1_wins >= 4:
        recent_trend = "team1_hot"
    elif recent_team1_wins <= 1:
        recent_trend = "team2_hot"
    else:
        recent_trend = "balanced"

    return {
        "team1": team1,
        "team2": team2,
        "total_games": total_games,
        "team1_wins_all_time": team1_wins,
        "team2_wins_all_time": team2_wins,
        "team1_win_pct": round(team1_wins / total_games, 3) if total_games > 0 else 0.0,
        "team1_home_wins": team1_home_wins,
        "team1_home_losses": team1_home_losses,
        "team1_away_wins": team1_away_wins,
        "team1_away_losses": team1_away_losses,
        "avg_point_diff": round(weighted_point_diff, 1) if total_games > 0 else 0.0,
        "avg_total_points": round(weighted_team1_points + weighted_team2_points, 1) if total_games > 0 else 0.0,
        "team1_avg_points": round(weighted_team1_points, 1) if total_games > 0 else 0.0,
        "team2_avg_points": round(weighted_team2_points, 1) if total_games > 0 else 0.0,
        "last_5_games": last_5,
        "recent_trend": recent_trend,
        "close_games": close_games,
        "blowouts": blowouts,
    }
