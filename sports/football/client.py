"""APIFootball REST API client for match data."""

import asyncio
import logging
import os
import time
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

API_BASE = "https://apiv2.apifootball.com/"

LEAGUES = {
    "epl": "152",
    "la_liga": "302",
    "bundesliga": "175",
    "serie_a": "207",
    "ligue_1": "168",
    "eredivisie": "244",
    "ucl": "3",
    "uel": "4",
}

_session: Optional[aiohttp.ClientSession] = None
_last_request_time: float = 0
_MIN_REQUEST_INTERVAL = 1.0  # seconds between API calls


def _get_api_key() -> str:
    key = os.environ.get("APIFOOTBAL")
    if not key:
        raise ValueError("APIFOOTBAL environment variable not set")
    return key


async def _get_session() -> aiohttp.ClientSession:
    """Get or create a shared aiohttp session."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
    return _session


async def close_session():
    """Close the shared session. Call at end of analysis run."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _throttle():
    """Enforce minimum interval between API requests."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


async def _fetch(action: str, params: dict) -> list | dict:
    """Shared HTTP helper for APIFootball REST calls.

    Returns the parsed JSON response (list or dict), or [] on error.
    """
    await _throttle()
    query = {"action": action, "APIkey": _get_api_key(), **params}
    try:
        session = await _get_session()
        async with session.get(API_BASE, params=query) as resp:
            if resp.status != 200:
                logger.error("APIFootball error: HTTP %d", resp.status)
                return []
            data = await resp.json()
            if isinstance(data, dict) and "error" in data:
                msg = data.get("message", data["error"])
                logger.warning("    APIFootball: %s", msg)
                return []
            if isinstance(data, (list, dict)):
                return data
            return []
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error("APIFootball request failed: %s", e)
        return []


def _as_list(data: list | dict) -> list[dict]:
    """Ensure API response is a list."""
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else []


async def fetch_matches_for_date(
    date: str, league_id: Optional[str] = None, to_date: Optional[str] = None
) -> list[dict]:
    """Fetch matches for a date or date range. Optional league_id filter."""
    params = {"from": date, "to": to_date or date}
    if league_id:
        params["league_id"] = league_id
    return _as_list(await _fetch("get_events", params))


async def fetch_h2h(home_id: str, away_id: str) -> list[dict]:
    """Fetch head-to-head history between two teams."""
    data = await _fetch("get_H2H", {
        "firstTeamId": home_id,
        "secondTeamId": away_id,
    })
    # API returns either {"firstTeam_VS_secondTeam": [...]} directly
    # or wrapped in a list: [{"firstTeam_VS_secondTeam": [...]}]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    if isinstance(data, dict):
        return data.get("firstTeam_VS_secondTeam", [])
    return []


async def fetch_team_matches(
    team_id: str, from_date: str, to_date: str
) -> list[dict]:
    """Fetch a team's matches within a date range."""
    return _as_list(await _fetch("get_events", {
        "from": from_date,
        "to": to_date,
        "team_id": team_id,
    }))


async def fetch_standings(league_id: str) -> list[dict]:
    """Fetch current league standings."""
    return _as_list(await _fetch("get_standings", {"league_id": league_id}))


async def fetch_leagues() -> list[dict]:
    """Fetch all available leagues to verify IDs."""
    return _as_list(await _fetch("get_leagues", {}))


def extract_match_stats(match: dict) -> dict:
    """Pull key stats from a match's statistics list.

    Returns dict with shots_total, shots_on_target, possession, corners
    for home and away.
    """
    stats = match.get("statistics", [])
    result = {"home": {}, "away": {}}

    stat_map = {
        "Shots Total": "shots_total",
        "Shots On Goal": "shots_on_target",
        "Ball Possession": "possession",
        "Corner Kicks": "corners",
    }

    for stat in stats:
        stat_type = stat.get("type", "")
        key = stat_map.get(stat_type)
        if not key:
            continue
        home_val = stat.get("home") or "0"
        away_val = stat.get("away") or "0"
        if key == "possession":
            home_val = home_val.replace("%", "")
            away_val = away_val.replace("%", "")
        try:
            result["home"][key] = int(float(home_val)) if home_val else 0
        except (ValueError, TypeError):
            logger.debug("Could not parse home %s: %r", stat_type, home_val)
        try:
            result["away"][key] = int(float(away_val)) if away_val else 0
        except (ValueError, TypeError):
            logger.debug("Could not parse away %s: %r", stat_type, away_val)

    return result
