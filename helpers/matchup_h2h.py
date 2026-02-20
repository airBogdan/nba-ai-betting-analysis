"""Head-to-head matchup computations."""

from typing import Dict, List, Optional

from .games import _weighted_h2h_games
from .matchup_types import H2HMatchupStats, H2HPatterns, H2HRecent
from .types import H2HResults
from .utils import get_current_nba_season_year


def compute_recent_h2h(
    h2h_results: Optional[H2HResults],
    team1_name: str,
    home_team: str
) -> Optional[H2HRecent]:
    """Compute recent H2H data (last 2 seasons)."""
    if not h2h_results:
        return None

    current_year = get_current_nba_season_year()
    if not current_year:
        return None

    # Get games from last 2 seasons only
    recent_seasons = [current_year, current_year - 1]
    recent_games: List[Dict[str, str]] = []

    for season in recent_seasons:
        season_games = h2h_results.get(season)
        if season_games:
            recent_games.extend([
                {"winner": g["winner"], "home_team": g["home_team"]}
                for g in season_games
            ])

    if len(recent_games) == 0:
        return None

    team1_wins = sum(1 for g in recent_games if g["winner"] == team1_name)
    team2_wins = len(recent_games) - team1_wins

    # Home team's record when hosting this matchup
    home_games = [g for g in recent_games if g["home_team"] == home_team]
    home_wins = sum(1 for g in home_games if g["winner"] == home_team)

    return {
        "team1_wins_last_2_seasons": team1_wins,
        "team2_wins_last_2_seasons": team2_wins,
        "last_winner": recent_games[-1]["winner"] if recent_games else "N/A",
        "home_team_home_record": f"{home_wins}-{len(home_games) - home_wins}",
        "games_last_2_seasons": len(recent_games),
    }


def compute_h2h_matchup_stats(
    h2h_results: Optional[H2HResults],
    team1_name: str,
    team2_name: str
) -> Optional[H2HMatchupStats]:
    """Compute recency-weighted aggregated stats for each team from H2H box scores."""
    if not h2h_results:
        return None

    weighted_games = _weighted_h2h_games(h2h_results)

    # Filter to games with box scores and collect weighted stats
    t1_accum = {"fgp": 0.0, "tpp": 0.0, "rebounds": 0.0, "assists": 0.0, "turnovers": 0.0, "disruption": 0.0}
    t2_accum = {"fgp": 0.0, "tpp": 0.0, "rebounds": 0.0, "assists": 0.0, "turnovers": 0.0, "disruption": 0.0}
    total_weight = 0.0

    for game, w in weighted_games:
        home_stats = game.get("home_statistics")
        visitor_stats = game.get("visitor_statistics")

        if not home_stats or not visitor_stats:
            continue

        is_team1_home = game["home_team"] == team1_name
        t1_stats = home_stats if is_team1_home else visitor_stats
        t2_stats = visitor_stats if is_team1_home else home_stats

        t1_accum["fgp"] += float(t1_stats.get("fgp", 0) or 0) * w
        t1_accum["tpp"] += float(t1_stats.get("tpp", 0) or 0) * w
        t1_accum["rebounds"] += (t1_stats.get("totReb", 0) or 0) * w
        t1_accum["assists"] += (t1_stats.get("assists", 0) or 0) * w
        t1_accum["turnovers"] += (t1_stats.get("turnovers", 0) or 0) * w
        t1_accum["disruption"] += ((t1_stats.get("steals", 0) or 0) + (t1_stats.get("blocks", 0) or 0)) * w

        t2_accum["fgp"] += float(t2_stats.get("fgp", 0) or 0) * w
        t2_accum["tpp"] += float(t2_stats.get("tpp", 0) or 0) * w
        t2_accum["rebounds"] += (t2_stats.get("totReb", 0) or 0) * w
        t2_accum["assists"] += (t2_stats.get("assists", 0) or 0) * w
        t2_accum["turnovers"] += (t2_stats.get("turnovers", 0) or 0) * w
        t2_accum["disruption"] += ((t2_stats.get("steals", 0) or 0) + (t2_stats.get("blocks", 0) or 0)) * w

        total_weight += w

    if total_weight == 0:
        return None

    def wavg(val: float) -> float:
        return round(val / total_weight, 1)

    return {
        "team1": {
            "avg_fgp": wavg(t1_accum["fgp"]),
            "avg_tpp": wavg(t1_accum["tpp"]),
            "avg_rebounds": wavg(t1_accum["rebounds"]),
            "avg_assists": wavg(t1_accum["assists"]),
            "avg_turnovers": wavg(t1_accum["turnovers"]),
            "avg_disruption": wavg(t1_accum["disruption"]),
        },
        "team2": {
            "avg_fgp": wavg(t2_accum["fgp"]),
            "avg_tpp": wavg(t2_accum["tpp"]),
            "avg_rebounds": wavg(t2_accum["rebounds"]),
            "avg_assists": wavg(t2_accum["assists"]),
            "avg_turnovers": wavg(t2_accum["turnovers"]),
            "avg_disruption": wavg(t2_accum["disruption"]),
        },
    }


def compute_h2h_patterns(h2h_results: Optional[H2HResults]) -> Optional[H2HPatterns]:
    """Compute recency-weighted H2H patterns from results."""
    if not h2h_results:
        return None

    weighted_games = _weighted_h2h_games(h2h_results)
    if not weighted_games:
        return None

    weighted_total_score = 0.0
    weighted_home_wins = 0.0
    weighted_high_scoring = 0.0
    weighted_close_games = 0.0

    for game, w in weighted_games:
        combined = game["home_points"] + game["visitor_points"]
        weighted_total_score += combined * w

        if game["winner"] == game["home_team"]:
            weighted_home_wins += w
        if combined > 220:
            weighted_high_scoring += w
        if abs(game["point_diff"]) <= 5:
            weighted_close_games += w

    return {
        "avg_total": round(weighted_total_score, 1),
        "home_win_pct": round(weighted_home_wins, 3),
        "high_scoring_pct": round(weighted_high_scoring, 2),
        "close_game_pct": round(weighted_close_games, 2),
    }
