"""Low-level API client and simple endpoint wrappers."""

import os
from typing import Any, List, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()


URL = "v2.nba.api-sports.io"
HEADERS = {
    "x-rapidapi-key": os.environ.get("NBA_RAPID_API_KEY", ""),
    "x-rapidapi-host": URL,
}


async def fetch_nba_api(endpoint: str) -> Optional[List[Any]]:
    """Fetch data from NBA API."""
    url = f"https://{URL}/{endpoint}"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=HEADERS) as response:
            data = await response.json()
            if data and "response" in data and len(data["response"]) > 0:
                return data["response"]
            return None


async def get_teams() -> Optional[List[Any]]:
    """Get all NBA teams."""
    return await fetch_nba_api("teams")


async def get_game_statistics(game_id: int) -> Optional[List[Any]]:
    """Get statistics for a specific game."""
    return await fetch_nba_api(f"games/statistics?id={game_id}")


async def get_team_id_by_name(name: str) -> Optional[int]:
    """Get team ID by team name."""
    teams = await get_teams()
    if not teams:
        return None

    team = next(
        (t for t in teams if t["name"].lower() == name.lower()),
        None
    )
    return team["id"] if team else None


async def get_head_to_head_games(team1_id: int, team2_id: int) -> Optional[List[Any]]:
    """Get head-to-head games between two teams."""
    return await fetch_nba_api(f"games?h2h={team1_id}-{team2_id}")


async def get_team_standings(team_id: int, season: int) -> Optional[List[Any]]:
    """Get team standings for a season."""
    return await fetch_nba_api(f"standings?team={team_id}&league=standard&season={season}")


async def get_team_statistics(team_id: int, season: int) -> Optional[List[Any]]:
    """Get team statistics for a season."""
    return await fetch_nba_api(f"teams/statistics?id={team_id}&season={season}")


async def get_team_players_statistics(team_id: int, season: int) -> Optional[List[Any]]:
    """Get all player statistics for a team in a season."""
    return await fetch_nba_api(f"players/statistics?team={team_id}&season={season}")


async def get_games_by_date(season: int, date: str) -> Optional[List[Any]]:
    """Get all games for a specific date and season.

    Args:
        season: NBA season year (e.g., 2025)
        date: Date in YYYY-MM-DD format (e.g., '2026-02-01')
    """
    return await fetch_nba_api(f"games?season={season}&league=standard&date={date}")
