"""WebSocket listener for live football scores with Polymarket odds lookup."""

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime, timezone

import aiohttp
import websockets

from sports.football.api import parse_goal_event, was_tied

APIFOOTBALL_WS = "wss://wss.apifootball.com/livescore"

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

FOOTBALL_SERIES_IDS = [
    "10188",  # EPL
    "10193",  # La Liga
    "10194",  # Bundesliga
    "10203",  # Serie A
    "10195",  # Ligue 1
    "10204",  # UCL
    "10209",  # UEL
]

ODDS_POLL_INTERVAL = 60

TEAM_SUFFIXES = re.compile(r"\b(FC|CF|AFC|SC)\b", re.IGNORECASE)


def _normalize_team_name(name: str) -> str:
    """Strip common suffixes and extra whitespace for matching."""
    cleaned = TEAM_SUFFIXES.sub("", name).strip()
    return re.sub(r"\s+", " ", cleaned)


def _significant_words(name: str) -> set[str]:
    """Extract words with 4+ characters for fuzzy matching."""
    return {w.lower() for w in name.split() if len(w) >= 4}


def teams_match(api_name: str, poly_name: str) -> bool:
    """Check if an APIFootball team name matches a Polymarket team name."""
    norm_api = _normalize_team_name(api_name)
    norm_poly = _normalize_team_name(poly_name)

    if norm_api.lower() == norm_poly.lower():
        return True

    api_words = _significant_words(norm_api)
    poly_words = _significant_words(norm_poly)

    if not api_words or not poly_words:
        return False

    return api_words.issubset(poly_words) or poly_words.issubset(api_words)


def _normalize_market(market: dict) -> dict:
    """Parse JSON-encoded string fields in a market dict."""
    for field in ("outcomes", "outcomePrices", "clobTokenIds"):
        val = market.get(field)
        if isinstance(val, str):
            market[field] = json.loads(val)
    return market


class ScoreTracker:
    """Tracks live match scores and detects new goals."""

    def __init__(self):
        self.matches: dict[str, dict] = {}

    def update(self, matches: list[dict]) -> list[dict]:
        """Process a batch of match updates, return list of new goal events.

        Each returned event includes:
            match_id, home_team, away_team, time, player,
            home_score, away_score, was_tied
        """
        new_goals = []

        for match in matches:
            parsed = parse_goal_event(match)
            if parsed is None:
                match_id = match.get("match_id", "")
                if match_id and match_id not in self.matches:
                    try:
                        self.matches[match_id] = {
                            "home_score": int(match.get("match_hometeam_score", 0)),
                            "away_score": int(match.get("match_awayteam_score", 0)),
                            "goal_count": 0,
                        }
                    except (ValueError, TypeError):
                        pass
                continue

            match_id = parsed["match_id"]
            goals = parsed["goals"]
            stored = self.matches.get(match_id)

            if stored is None:
                self.matches[match_id] = {
                    "home_score": parsed["home_score"],
                    "away_score": parsed["away_score"],
                    "goal_count": len(goals),
                }
                continue

            old_count = stored["goal_count"]
            new_count = len(goals)

            if new_count <= old_count:
                continue

            for i in range(old_count, new_count):
                goal = goals[i]
                if i == 0:
                    prev_home, prev_away = 0, 0
                else:
                    prev_home = goals[i - 1]["home_score"]
                    prev_away = goals[i - 1]["away_score"]

                new_goals.append({
                    "match_id": match_id,
                    "home_team": parsed["home_team"],
                    "away_team": parsed["away_team"],
                    "time": goal["time"],
                    "player": goal["player"],
                    "home_score": goal["home_score"],
                    "away_score": goal["away_score"],
                    "was_tied": was_tied(prev_home, prev_away),
                })

            self.matches[match_id] = {
                "home_score": parsed["home_score"],
                "away_score": parsed["away_score"],
                "goal_count": new_count,
            }

        return new_goals


class OddsCache:
    """Background poller that caches Polymarket odds for live matches."""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._task: asyncio.Task | None = None

    def get(self, home_team: str, away_team: str) -> dict | None:
        """Look up cached odds by team names."""
        for title, odds in self._cache.items():
            if _event_matches_teams(title, home_team, away_team):
                return odds
        return None

    def start(self):
        self._task = asyncio.create_task(self._poll_loop())

    def stop(self):
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while True:
            await self._refresh()
            await asyncio.sleep(ODDS_POLL_INTERVAL)

    async def _refresh(self):
        try:
            events = await _fetch_all_football_events()
            new_cache: dict[str, dict] = {}
            for event in events:
                title = event.get("title", "")
                odds = _extract_match_odds(event)
                if title and odds:
                    new_cache[title] = odds
            self._cache = new_cache
        except Exception as e:
            print(f"  [odds cache] refresh failed: {e}")


def _extract_match_odds(event: dict) -> dict | None:
    """Extract draw/home/away market prices from a Polymarket football event."""
    odds = {}
    for market in event.get("markets", []):
        market = _normalize_market(market)
        accepting = market.get("acceptingOrders")
        if not accepting or str(accepting).lower() == "false":
            continue

        outcomes = market.get("outcomes", [])
        prices = market.get("outcomePrices", [])
        if len(outcomes) != 2 or len(prices) != 2:
            continue

        yes_price = _find_yes_price(outcomes, prices)
        if yes_price is None:
            continue

        question = market.get("question", "").lower()
        if "draw" in question:
            odds["draw"] = yes_price
        elif "win" in question or "beat" in question:
            label = market.get("groupItemTitle", question)
            odds[label] = yes_price

    return odds if odds else None


def _find_yes_price(outcomes: list, prices: list) -> float | None:
    """Find the price corresponding to the 'Yes' outcome."""
    for i, outcome in enumerate(outcomes):
        if str(outcome).lower() == "yes":
            return float(prices[i])
    return None


async def _fetch_series_events(session: aiohttp.ClientSession, series_id: str) -> list[dict]:
    """Fetch active events for a single football series."""
    try:
        async with session.get(
            f"{GAMMA_BASE_URL}/events",
            params={
                "series_id": series_id,
                "closed": "false",
                "active": "true",
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return []
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return []


async def _fetch_all_football_events() -> list[dict]:
    """Fetch all active football events across all leagues in parallel."""
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *[_fetch_series_events(session, sid) for sid in FOOTBALL_SERIES_IDS]
        )
    return [e for batch in results for e in batch]


async def fetch_polymarket_odds(home_team: str, away_team: str) -> dict | None:
    """Query Polymarket Gamma API for current odds on a football match.

    Searches across all football leagues in parallel. Returns market odds
    dict or None if no matching event found.
    """
    all_events = await _fetch_all_football_events()

    for event in all_events:
        title = event.get("title", "")
        if _event_matches_teams(title, home_team, away_team):
            odds = _extract_match_odds(event)
            if odds:
                return {"event": title, "odds": odds}

    return None


def _event_matches_teams(title: str, home_team: str, away_team: str) -> bool:
    """Check if a Polymarket event title matches both team names."""
    parts = re.split(r"\s+vs\.?\s+", title, flags=re.IGNORECASE)
    if len(parts) != 2:
        return False
    return (
        teams_match(home_team, parts[0]) and teams_match(away_team, parts[1])
    ) or (
        teams_match(home_team, parts[1]) and teams_match(away_team, parts[0])
    )


async def run():
    """Connect to APIFootball WebSocket and monitor live scores."""
    api_key = os.environ.get("APIFOOTBAL")
    if not api_key:
        print("Error: APIFOOTBAL environment variable not set")
        return

    tracker = ScoreTracker()
    odds_cache = OddsCache()
    odds_cache.start()
    backoff = 1

    try:
        while True:
            try:
                url = f"{APIFOOTBALL_WS}?APIkey={api_key}"
                async with websockets.connect(url) as ws:
                    print("Connected to APIFootball WebSocket.")
                    backoff = 1

                    async for message in ws:
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            continue

                        if not isinstance(data, list):
                            data = [data]

                        new_goals = tracker.update(data)

                        for goal in new_goals:
                            await _handle_goal(goal, odds_cache)

            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                print(f"Disconnected: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        odds_cache.stop()


SOUND_GOAL = "/System/Library/Sounds/Glass.aiff"
SOUND_TIE_BREAKER = "/System/Library/Sounds/Hero.aiff"


def _play_sound(path: str):
    """Play a system sound non-blocking."""
    try:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


async def _handle_goal(goal: dict, odds_cache: OddsCache):
    """Print goal info with before/after Polymarket odds comparison."""
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    score = f"{goal['home_score']}-{goal['away_score']}"
    tied = " ** TIE-BREAKER **" if goal["was_tied"] else ""

    _play_sound(SOUND_TIE_BREAKER if goal["was_tied"] else SOUND_GOAL)

    print(
        f"[GOAL {now}] {goal['home_team']} vs {goal['away_team']} "
        f"({score}) - {goal['player']} {goal['time']}'{tied}"
    )

    before = odds_cache.get(goal["home_team"], goal["away_team"])

    after_result = await fetch_polymarket_odds(
        goal["home_team"], goal["away_team"]
    )
    after = after_result["odds"] if after_result else None

    if before or after:
        event_name = after_result["event"] if after_result else "?"
        print(f"  Polymarket: {event_name}")
        _print_odds_comparison(before, after)
    else:
        print("  No Polymarket market found for this match.")


def _print_odds_comparison(before: dict | None, after: dict | None):
    """Print before/after odds side by side."""
    all_labels = list(dict.fromkeys(
        list((before or {}).keys()) + list((after or {}).keys())
    ))

    width = max((len(l) for l in all_labels), default=10) + 2
    print(f"  {'':>{width}s} {'Before':>8s} → {'After':>8s}  {'Δ':>6s}")
    for label in all_labels:
        b = before.get(label) if before else None
        a = after.get(label) if after else None
        b_str = f"{b:.3f}" if b is not None else "   -  "
        a_str = f"{a:.3f}" if a is not None else "   -  "
        if b is not None and a is not None:
            delta = a - b
            d_str = f"{delta:+.3f}"
        else:
            d_str = "     -"
        print(f"    {label:<{width - 2}s} {b_str:>8s} → {a_str:>8s}  {d_str:>6s}")
