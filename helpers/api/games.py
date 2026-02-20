"""Team game data: recent games, multi-season stats, and scheduling."""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..utils import get_current_nba_season_year
from .types import (
    ProcessedTeamStats,
    RecentGame,
    ScheduledGame,
)
from .client import fetch_nba_api, get_team_statistics, get_games_by_date
from .transforms import process_team_stats

_ET = ZoneInfo("America/New_York")

RECENT_GAMES_LIMIT = 10


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
    all_standings: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[RecentGame]:
    """
    Get recent completed games for a team.

    Args:
        team_id: Team ID to fetch games for
        season: Season year
        all_standings: Optional dict of all team standings for opponent lookup
    """
    raw_games = await fetch_nba_api(f"games?team={team_id}&season={season}")
    if not raw_games:
        return []

    def is_valid_score(score) -> bool:
        """Check if score is a valid integer (not None, not '--')."""
        if score is None:
            return False
        if isinstance(score, int):
            return True
        if isinstance(score, str):
            return score.isdigit() or (score.startswith('-') and score[1:].isdigit())
        return False

    # Filter to completed games only (status.short === 3 means finished)
    completed = [
        g for g in raw_games
        if g.get("status", {}).get("short") == 3
        and is_valid_score(g.get("scores", {}).get("home", {}).get("points"))
        and is_valid_score(g.get("scores", {}).get("visitors", {}).get("points"))
    ]

    # Sort by date descending (most recent first)
    completed.sort(
        key=lambda g: g.get("date", {}).get("start", ""),
        reverse=True
    )

    # Take the last N games and process
    results: List[RecentGame] = []
    for game in completed[:RECENT_GAMES_LIMIT]:
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


def _utc_to_et_date(date_start_str: Optional[str]) -> Optional[str]:
    """Convert a UTC ISO 8601 timestamp to a US Eastern date string (YYYY-MM-DD).

    Returns None if the input is missing or unparseable.
    """
    if not date_start_str:
        return None
    try:
        # Parse ISO 8601 UTC timestamp (e.g. "2026-02-11T00:30:00.000Z")
        utc_dt = datetime.fromisoformat(date_start_str.replace("Z", "+00:00"))
        et_dt = utc_dt.astimezone(_ET)
        return et_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


async def get_scheduled_games(season: int, target_date: str) -> List[ScheduledGame]:
    """
    Get scheduled games for a US Eastern date with filtered fields.

    Queries the API for both the target UTC date and the next day, then filters
    to games whose start time falls on the target date in US Eastern time.

    Args:
        season: NBA season year (e.g., 2025)
        target_date: Date in YYYY-MM-DD format (e.g., '2026-02-01')

    Returns:
        List of games with id, date_start, status, and teams (id/name only)
    """
    next_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    day1_games, day2_games = await asyncio.gather(
        get_games_by_date(season, target_date),
        get_games_by_date(season, next_date),
    )

    all_games = (day1_games or []) + (day2_games or [])

    # Deduplicate by game ID
    seen_ids: set[int] = set()
    unique_games = []
    for game in all_games:
        gid = game["id"]
        if gid not in seen_ids:
            seen_ids.add(gid)
            unique_games.append(game)

    results: List[ScheduledGame] = []
    for game in unique_games:
        et_date = _utc_to_et_date(game["date"]["start"])
        if et_date != target_date:
            continue
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
