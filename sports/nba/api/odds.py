"""Odds API client for betting lines from the-odds-api."""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

ODDS_API_URL = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"

# Map API-Sports team names to the-odds-api team names
TEAM_NAME_MAP = {
    "LA Clippers": "Los Angeles Clippers",
    "LA Lakers": "Los Angeles Lakers",
}


def _get_api_key() -> str:
    load_dotenv()
    return os.environ.get("THE_ODDS_API", "")


def normalize_team_name(name: str) -> str:
    """Normalize team name to match the-odds-api format."""
    return TEAM_NAME_MAP.get(name, name)


async def fetch_nba_odds(
    regions: str = "us",
    markets: str = "spreads,totals,h2h",
) -> Optional[List[Dict[str, Any]]]:
    """Fetch current NBA odds from the-odds-api.

    Returns list of events with odds from all available bookmakers.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    url = f"{ODDS_API_URL}/sports/{SPORT}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american"
    }

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    print(f"Odds API error {response.status}: {error_text[:100]}")
                    return None
                return await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logging.error("Odds API error: %s", e)
        return None


async def fetch_event_alternates(event_id: str) -> Optional[Dict[str, Any]]:
    """Fetch alternate spreads and totals for a specific event."""
    api_key = _get_api_key()
    if not api_key:
        return None

    url = f"{ODDS_API_URL}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "alternate_spreads,alternate_totals",
        "oddsFormat": "american",
    }

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return None
                return await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def find_game_odds(
    odds_data: List[Dict[str, Any]],
    home_team: str,
    away_team: str,
) -> Optional[Dict[str, Any]]:
    """Find odds for a specific game by team names.

    Handles team name normalization (e.g., 'LA Clippers' -> 'Los Angeles Clippers').
    """
    home_normalized = normalize_team_name(home_team)
    away_normalized = normalize_team_name(away_team)

    for event in odds_data:
        if (event.get("home_team") == home_normalized and
            event.get("away_team") == away_normalized):
            return event
    return None


def _filter_alternates_near_line(
    outcomes: List[Dict[str, Any]],
    main_line: float,
    team_name: Optional[str],
    count: int = 2,
) -> List[Dict[str, Any]]:
    """Filter alternate outcomes to those near the main line.

    Returns `count` alternates on each side of the main line.
    For spreads: filters by team_name, returns line and price.
    For totals: filters by Over outcomes, returns line and price.
    """
    if team_name:
        # Spread: filter by team
        relevant = [o for o in outcomes if o.get("name") == team_name]
    else:
        # Totals: get Over outcomes
        relevant = [o for o in outcomes if o.get("name") == "Over"]

    # Split into below and above main line, sorted by proximity to main
    below = sorted(
        [o for o in relevant if o.get("point", 0) < main_line],
        key=lambda o: o.get("point", 0),
        reverse=True,  # Highest first (closest to main)
    )
    above = sorted(
        [o for o in relevant if o.get("point", 0) > main_line],
        key=lambda o: o.get("point", 0),  # Lowest first (closest to main)
    )

    selected = below[:count] + above[:count]
    return [{"line": o.get("point"), "price": o.get("price")} for o in selected]


def extract_odds(
    event: Dict[str, Any],
    alternates: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Extract structured odds from an event.

    Uses first available bookmaker. Returns None if no bookmakers available.

    Args:
        event: Main odds event data
        alternates: Optional alternate lines data from fetch_event_alternates
    """
    bookmakers = event.get("bookmakers", [])
    if not bookmakers:
        return None

    book = bookmakers[0]
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")

    result: Dict[str, Any] = {
        "spread": None,
        "total": None,
        "moneyline": None,
    }

    main_spread_line = None
    main_total_line = None

    for market in book.get("markets", []):
        key = market.get("key")
        outcomes = market.get("outcomes", [])

        if key == "spreads":
            home = next((o for o in outcomes if o.get("name") == home_team), None)
            away = next((o for o in outcomes if o.get("name") == away_team), None)
            if home and away:
                main_spread_line = home.get("point")
                result["spread"] = {
                    "home": {"line": home.get("point"), "price": home.get("price")},
                    "away": {"line": away.get("point"), "price": away.get("price")},
                }

        elif key == "totals":
            over = next((o for o in outcomes if o.get("name") == "Over"), None)
            under = next((o for o in outcomes if o.get("name") == "Under"), None)
            if over:
                main_total_line = over.get("point")
                result["total"] = {
                    "line": over.get("point"),
                    "over": over.get("price"),
                    "under": under.get("price") if under else None,
                }

        elif key == "h2h":
            home = next((o for o in outcomes if o.get("name") == home_team), None)
            away = next((o for o in outcomes if o.get("name") == away_team), None)
            if home and away:
                result["moneyline"] = {
                    "home": home.get("price"),
                    "away": away.get("price"),
                }

    # Add alternates if available
    if alternates and alternates.get("bookmakers"):
        alt_book = alternates["bookmakers"][0]
        for market in alt_book.get("markets", []):
            key = market.get("key")
            outcomes = market.get("outcomes", [])

            if key == "alternate_spreads" and main_spread_line is not None:
                # Get alternates for home team (away is just the inverse)
                home_alts = _filter_alternates_near_line(
                    outcomes, main_spread_line, home_team, count=2
                )
                if home_alts:
                    result["alternate_spreads"] = home_alts

            elif key == "alternate_totals" and main_total_line is not None:
                total_alts = _filter_alternates_near_line(
                    outcomes, main_total_line, None, count=2
                )
                if total_alts:
                    result["alternate_totals"] = total_alts

    # Return None if no useful odds were extracted
    if result["spread"] is None and result["total"] is None and result["moneyline"] is None:
        return None

    return result