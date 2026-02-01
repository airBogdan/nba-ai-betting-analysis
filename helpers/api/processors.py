"""Data processing functions and hybrid fetch+process functions."""

from typing import Any, Dict, List, Optional

from ..utils import get_current_nba_season_year
from .types import (
    TeamPlayerStatistics,
    ProcessedPlayerStats,
    RawTeamStats,
    ProcessedTeamStats,
    RecentGame,
    ScheduledGame,
)
from .client import fetch_nba_api, get_team_statistics, get_games_by_date


def parse_minutes(min_str: str) -> float:
    """Parse minutes string (e.g., '32:45') to float."""
    if not min_str:
        return 0.0
    parts = min_str.split(":")
    minutes = int(parts[0]) if parts[0] else 0
    seconds = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    return minutes + seconds / 60


def process_player_statistics(
    raw_stats: List[TeamPlayerStatistics],
    top_n: int = 8,
    min_games: int = 5
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
        pid = stat["player"]["id"]
        if pid not in by_player:
            by_player[pid] = {
                "name": f"{stat['player']['firstname']} {stat['player']['lastname']}",
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
            total_pm += int(pm_str) if pm_str else 0

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


async def get_all_standings(season: int) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Get standings for all teams in a season.

    Returns a dict keyed by team name with record info:
    {
        "Atlanta Hawks": {"wins": 11, "losses": 8, "win_pct": 0.579},
        ...
    }
    """
    raw = await fetch_nba_api(f"standings?league=standard&season={season}")
    if not raw:
        return None

    standings: Dict[str, Dict[str, Any]] = {}
    for entry in raw:
        team_name = entry.get("team", {}).get("name")
        if not team_name:
            continue

        win = entry.get("win", {})
        loss = entry.get("loss", {})
        wins = win.get("total", 0) or 0
        losses = loss.get("total", 0) or 0
        win_pct_str = win.get("percentage", "0")
        win_pct = float(win_pct_str) if win_pct_str else 0.0

        standings[team_name] = {
            "wins": wins,
            "losses": losses,
            "win_pct": win_pct,
        }

    return standings


async def get_team_statistics_for_seasons(
    team_id: int,
    num_seasons: int = 2,
    season: Optional[int] = None,
) -> Optional[Dict[int, ProcessedTeamStats]]:
    """Get processed team statistics for multiple seasons.

    Args:
        team_id: Team ID to fetch stats for
        num_seasons: Number of seasons to fetch (default 2)
        season: Base season year. If None, uses current season.
    """
    current_season = season or get_current_nba_season_year()
    if not current_season:
        return None

    seasons_stats: Dict[int, ProcessedTeamStats] = {}

    for i in range(num_seasons):
        season_year = current_season - i
        stats = await get_team_statistics(team_id, season_year)

        if stats and len(stats) > 0:
            seasons_stats[season_year] = process_team_stats(stats[0])

    return seasons_stats


async def get_team_recent_games(
    team_id: int,
    season: int,
    limit: int = 5,
    all_standings: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[RecentGame]:
    """
    Get recent completed games for a team.

    Args:
        team_id: Team ID to fetch games for
        season: Season year
        limit: Number of recent games to return
        all_standings: Optional dict of all team standings for opponent lookup
    """
    raw_games = await fetch_nba_api(f"games?team={team_id}&season={season}")
    if not raw_games:
        return []

    # Filter to completed games only (status.short === 3 means finished)
    completed = [
        g for g in raw_games
        if g.get("status", {}).get("short") == 3
        and g.get("scores", {}).get("home", {}).get("points") is not None
        and g.get("scores", {}).get("visitors", {}).get("points") is not None
    ]

    # Sort by date descending (most recent first)
    completed.sort(
        key=lambda g: g.get("date", {}).get("start", ""),
        reverse=True
    )

    # Take the last N games and process
    results: List[RecentGame] = []
    for game in completed[:limit]:
        is_home = game["teams"]["home"]["id"] == team_id
        team_points = (
            game["scores"]["home"]["points"]
            if is_home
            else game["scores"]["visitors"]["points"]
        )
        opp_points = (
            game["scores"]["visitors"]["points"]
            if is_home
            else game["scores"]["home"]["points"]
        )
        opponent = (
            game["teams"]["visitors"]["name"]
            if is_home
            else game["teams"]["home"]["name"]
        )

        # Look up opponent's record
        vs_record = "N/A"
        vs_win_pct = 0.0
        if all_standings and opponent in all_standings:
            opp_data = all_standings[opponent]
            vs_record = f"{opp_data['wins']}-{opp_data['losses']}"
            vs_win_pct = opp_data["win_pct"]

        results.append({
            "vs": opponent,
            "vs_record": vs_record,
            "vs_win_pct": vs_win_pct,
            "result": "W" if team_points > opp_points else "L",
            "score": f"{team_points}-{opp_points}",
            "home": is_home,
            "margin": team_points - opp_points,
            "date": game["date"]["start"].split("T")[0],
        })

    return results


async def get_scheduled_games(season: int, date: str) -> List[ScheduledGame]:
    """
    Get scheduled games for a date with filtered fields.

    Args:
        season: NBA season year (e.g., 2025)
        date: Date in YYYY-MM-DD format (e.g., '2026-02-01')

    Returns:
        List of games with id, date_start, status, and teams (id/name only)
    """
    raw_games = await get_games_by_date(season, date)
    if not raw_games:
        return []

    results: List[ScheduledGame] = []
    for game in raw_games:
        results.append({
            "id": game["id"],
            "date_start": game["date"]["start"],
            "status": {
                "clock": game["status"]["clock"],
                "halftime": game["status"]["halftime"],
                "long": game["status"]["long"],
            },
            "teams": {
                "visitors": {
                    "id": game["teams"]["visitors"]["id"],
                    "name": game["teams"]["visitors"]["name"],
                },
                "home": {
                    "id": game["teams"]["home"]["id"],
                    "name": game["teams"]["home"]["name"],
                },
            },
        })

    return results
