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


def _group_stats_by_player(
    raw_stats: List[TeamPlayerStatistics],
) -> Dict[int, Dict[str, Any]]:
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
    return by_player


def _safe_int(value: Any, default: int = 0) -> int:
    if not value or value == '--':
        return default
    try:
        return int(value)
    except ValueError:
        return default


_STAT_FIELDS = [
    ("points", "pts"), ("totReb", "reb"), ("assists", "ast"),
    ("steals", "stl"), ("blocks", "blk"), ("turnovers", "tov"),
    ("fgm", "fgm"), ("fga", "fga"), ("tpm", "tpm"),
    ("tpa", "tpa"), ("ftm", "ftm"), ("fta", "fta"),
]


def _aggregate_player_stats(
    player_id: int, data: Dict[str, Any], min_games: int
) -> ProcessedPlayerStats | None:
    games = data["games"]
    game_count = len(games)
    if game_count < min_games:
        return None

    totals = {short: 0 for _, short in _STAT_FIELDS}
    total_min = 0.0
    total_pm = 0

    for g in games:
        total_min += parse_minutes(g.get("min", ""))
        for api_key, short in _STAT_FIELDS:
            totals[short] += g.get(api_key, 0) or 0
        total_pm += _safe_int(g.get("plusMinus", "0"))

    t = totals
    return {
        "id": player_id,
        "name": data["name"],
        "games": game_count,
        "mpg": round(total_min / game_count, 1),
        "ppg": round(t["pts"] / game_count, 1),
        "rpg": round(t["reb"] / game_count, 1),
        "apg": round(t["ast"] / game_count, 1),
        "disruption": round((t["stl"] + t["blk"]) / game_count, 1),
        "fgp": round((t["fgm"] / t["fga"]) * 100, 1) if t["fga"] > 0 else 0.0,
        "tpp": round((t["tpm"] / t["tpa"]) * 100, 1) if t["tpa"] > 0 else 0.0,
        "plus_minus": round(total_pm / game_count, 1),
    }


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

    by_player = _group_stats_by_player(raw_stats)
    aggregated: List[ProcessedPlayerStats] = []
    for player_id, data in by_player.items():
        result = _aggregate_player_stats(player_id, data, min_games)
        if result is not None:
            aggregated.append(result)

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
