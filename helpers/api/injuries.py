"""Injuries API client."""

import os
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

from .types import Injury

load_dotenv()


INJURIES_URL = "nba-injuries-reports.p.rapidapi.com"
INJURIES_HEADERS = {
    "x-rapidapi-key": os.environ.get("NBA_RAPID_API_KEY", ""),
    "x-rapidapi-host": INJURIES_URL,
}


async def fetch_injuries(date: str) -> Optional[List[Dict[str, Any]]]:
    """Fetch all injuries for a given date.

    Args:
        date: Date in YYYY-MM-DD format (e.g., '2026-02-03')

    Returns:
        List of injury records, each containing:
        - date: str
        - team: str (e.g., "Denver Nuggets")
        - player: str
        - status: str (e.g., "Out", "Questionable", "Probable")
        - reason: str
        - reportTime: str
    """
    url = f"https://{INJURIES_URL}/injuries/nba/{date}"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=INJURIES_HEADERS) as response:
                if response.status != 200:
                    print(f"Injuries API returned status {response.status}")
                    return None
                data = await response.json()
                if isinstance(data, list):
                    return data
                return None
    except Exception as e:
        print(f"Error fetching injuries: {e}")
        return None


def filter_injuries_by_teams(
    injuries: List[Dict[str, Any]],
    team_names: List[str],
) -> Dict[str, List[Injury]]:
    """Filter injuries by team names and format for output.

    Args:
        injuries: Raw injury records from API
        team_names: List of team names to filter for

    Returns:
        Dict mapping team name to list of injuries for that team
    """
    result: Dict[str, List[Injury]] = {name: [] for name in team_names}

    for injury in injuries:
        team = injury.get("team", "")
        if team in team_names:
            result[team].append({
                "player": injury.get("player", ""),
                "status": injury.get("status", ""),
                "reason": injury.get("reason", ""),
                "report_time": injury.get("reportTime", ""),
            })

    return result