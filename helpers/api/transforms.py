"""Pure data transformation functions for NBA API responses."""

from typing import Any, Dict, List

from .types import (
    TeamPlayerStatistics,
    ProcessedPlayerStats,
    RawTeamStats,
    ProcessedTeamStats,
)

TOP_PLAYERS = 10
MIN_PLAYER_GAMES = 3


def parse_minutes(min_str: str) -> float:
    """Parse minutes string (e.g., '32:45') to float."""
    if not min_str or min_str == '--':
        return 0.0
    parts = min_str.split(":")
    # Handle '--' or non-numeric values in parts
    try:
        minutes = int(parts[0]) if parts[0] and parts[0] != '--' else 0
        seconds = int(parts[1]) if len(parts) > 1 and parts[1] and parts[1] != '--' else 0
    except ValueError:
        return 0.0
    return minutes + seconds / 60


def process_player_statistics(
    raw_stats: List[TeamPlayerStatistics],
    top_n: int = TOP_PLAYERS,
    min_games: int = MIN_PLAYER_GAMES
) -> List[ProcessedPlayerStats]:
    """
    Process raw player statistics into aggregated per-game stats.

    Args:
        raw_stats: Raw player game logs from API
        top_n: Number of top players to return (by minutes)
        min_games: Minimum games played to be included

    Returns:
        List of processed player stats, sorted by minutes per game
    """
    if not raw_stats:
        return []

    # Group stats by player id
    by_player: Dict[int, Dict[str, Any]] = {}

    for stat in raw_stats:
        player = stat.get("player")
        if not player or "id" not in player:
            continue
        pid = player["id"]
        if pid not in by_player:
            by_player[pid] = {
                "name": f"{player.get('firstname', '')} {player.get('lastname', '')}".strip(),
                "games": []
            }
        by_player[pid]["games"].append(stat)

    # Aggregate each player's stats
    aggregated: List[ProcessedPlayerStats] = []

    for player_id, data in by_player.items():
        games = data["games"]
        game_count = len(games)

        # Skip players with too few games
        if game_count < min_games:
            continue

        # Sum up all stats
        total_min = 0.0
        total_pts = 0
        total_reb = 0
        total_ast = 0
        total_stl = 0
        total_blk = 0
        total_tov = 0
        total_fgm = 0
        total_fga = 0
        total_tpm = 0
        total_tpa = 0
        total_ftm = 0
        total_fta = 0
        total_pm = 0

        for g in games:
            total_min += parse_minutes(g.get("min", ""))
            total_pts += g.get("points", 0) or 0
            total_reb += g.get("totReb", 0) or 0
            total_ast += g.get("assists", 0) or 0
            total_stl += g.get("steals", 0) or 0
            total_blk += g.get("blocks", 0) or 0
            total_tov += g.get("turnovers", 0) or 0
            total_fgm += g.get("fgm", 0) or 0
            total_fga += g.get("fga", 0) or 0
            total_tpm += g.get("tpm", 0) or 0
            total_tpa += g.get("tpa", 0) or 0
            total_ftm += g.get("ftm", 0) or 0
            total_fta += g.get("fta", 0) or 0
            pm_str = g.get("plusMinus", "0")
            try:
                total_pm += int(pm_str) if pm_str and pm_str != '--' else 0
            except ValueError:
                pass  # Skip invalid plus/minus values

        aggregated.append({
            "id": player_id,
            "name": data["name"],
            "games": game_count,
            "mpg": round(total_min / game_count, 1),
            "ppg": round(total_pts / game_count, 1),
            "rpg": round(total_reb / game_count, 1),
            "apg": round(total_ast / game_count, 1),
            "disruption": round((total_stl + total_blk) / game_count, 1),
            "fgp": round((total_fgm / total_fga) * 100, 1) if total_fga > 0 else 0.0,
            "tpp": round((total_tpm / total_tpa) * 100, 1) if total_tpa > 0 else 0.0,
            "plus_minus": round(total_pm / game_count, 1),
        })

    # Sort by minutes per game and return top N
    aggregated.sort(key=lambda x: x["mpg"], reverse=True)
    return aggregated[:top_n]


def process_team_stats(raw: RawTeamStats) -> ProcessedTeamStats:
    """Process raw team statistics into derived metrics."""
    games = raw.get("games", 1) or 1
    points = raw.get("points", 0) or 0
    ppg = round(points / games, 1)

    # Pace estimate: possessions ≈ FGA + 0.44*FTA + TOV - OREB
    fga = raw.get("fga", 0) or 0
    fta = raw.get("fta", 0) or 0
    turnovers = raw.get("turnovers", 0) or 0
    off_reb = raw.get("offReb", 0) or 0
    tot_reb = raw.get("totReb", 0) or 0

    possessions = fga + 0.44 * fta + turnovers - off_reb
    pace = round(possessions / games, 1)

    assists = raw.get("assists", 0) or 0
    steals = raw.get("steals", 0) or 0
    blocks = raw.get("blocks", 0) or 0
    plus_minus = raw.get("plusMinus", 0) or 0

    return {
        "games": raw.get("games", 0),
        "ppg": ppg,
        "apg": round(assists / games, 1),
        "rpg": round(tot_reb / games, 1),
        "topg": round(turnovers / games, 1),
        "disruption": round((steals + blocks) / games, 1),
        "net_rating": round(plus_minus / games, 2),
        "tpp": float(raw.get("tpp", "0") or "0"),
        "fgp": float(raw.get("fgp", "0") or "0"),
        "pace": pace,
    }
