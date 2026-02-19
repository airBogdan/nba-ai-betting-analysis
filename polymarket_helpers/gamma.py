import json
import requests

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
NBA_SERIES_ID = "10345"
NBA_TAG_ID = "100639"

BET_TYPE_TO_SPORTS_MARKET_TYPE = {
    "moneyline": {"moneyline"},
    "spread": {"spread", "spreads"},
    "total": {"total", "totals"},
    "player_prop_points": {"points"},
    "player_prop_rebounds": {"rebounds"},
    "player_prop_assists": {"assists"},
}

PROP_MARKET_TYPES = {"points", "rebounds", "assists"}


def _normalize_market(market: dict) -> dict:
    """Parse JSON-encoded string fields in a market dict.

    Mutates in place and is idempotent. Callers (find_market, find_prop_market,
    extract_polymarket_odds, etc.) depend on the mutation so that the returned
    market dict has Python lists, not JSON strings.
    """
    for field in ("outcomes", "outcomePrices", "clobTokenIds"):
        val = market.get(field)
        if isinstance(val, str):
            market[field] = json.loads(val)
    return market


def fetch_nba_events(date: str) -> list[dict]:
    """Fetch NBA events from Gamma API for a given date (YYYY-MM-DD)."""
    try:
        resp = requests.get(
            f"{GAMMA_BASE_URL}/events",
            params={
                "series_id": NBA_SERIES_ID,
                "tag_id": NBA_TAG_ID,
                "closed": "false",
                "active": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Error fetching events: {e}")
        return []

    return [e for e in events if date in e.get("ticker", "")]


def find_market(event: dict, bet_type: str, line: float | None) -> dict | None:
    """Find a matching market in an event by bet type and line."""
    valid_types = BET_TYPE_TO_SPORTS_MARKET_TYPE.get(bet_type)
    if not valid_types:
        return None

    for market in event.get("markets", []):
        market = _normalize_market(market)
        sport_type = market.get("sportsMarketType", "")
        if sport_type not in valid_types:
            continue

        # Skip markets not accepting orders (handle both bool and string)
        accepting = market.get("acceptingOrders")
        if not accepting or str(accepting).lower() == "false":
            continue

        if bet_type == "moneyline":
            return market

        # For spread/total, require exact line match
        if line is None:
            continue
        market_line = market.get("line")
        if market_line is not None and float(market_line) == float(line):
            return market

    return None


def extract_polymarket_odds(event: dict) -> dict:
    """Extract all market prices from a matched event into a structured dict.

    Returns:
        {
            "moneyline": {"outcomes": [...], "prices": [...]},
            "available_spreads": [{"line": -4.5, "outcomes": [...], "prices": [...]}],
            "available_totals": [{"line": 224.5, "outcomes": [...], "prices": [...]}],
        }
    """
    result: dict = {}

    for market in event.get("markets", []):
        market = _normalize_market(market)

        # Skip markets not accepting orders
        accepting = market.get("acceptingOrders")
        if not accepting or str(accepting).lower() == "false":
            continue

        sport_type = market.get("sportsMarketType", "")
        outcomes = market.get("outcomes", [])
        prices = [float(p) for p in market.get("outcomePrices", [])]

        if sport_type == "moneyline":
            result["moneyline"] = {"outcomes": outcomes, "prices": prices}
        elif sport_type in ("spread", "spreads"):
            result.setdefault("available_spreads", []).append({
                "line": float(market.get("line", 0)),
                "outcomes": outcomes,
                "prices": prices,
            })
        elif sport_type in ("total", "totals"):
            result.setdefault("available_totals", []).append({
                "line": float(market.get("line", 0)),
                "outcomes": outcomes,
                "prices": prices,
            })

    return result


def extract_player_props(event: dict) -> list[dict]:
    """Extract player prop markets from a Polymarket event.

    Returns list of dicts with: prop_type, player_name, line, outcomes, prices, clob_token_ids.
    """
    props = []
    for market in event.get("markets", []):
        market = _normalize_market(market)

        sport_type = market.get("sportsMarketType", "")
        if sport_type not in PROP_MARKET_TYPES:
            continue

        accepting = market.get("acceptingOrders")
        if not accepting or str(accepting).lower() == "false":
            continue

        # Parse player name from question field: "LeBron James: 25.5 or more points?"
        question = market.get("question", "")
        if ":" not in question:
            continue
        player_name = question.split(":", 1)[0].strip()
        if not player_name:
            continue

        line = market.get("line")
        if line is not None:
            try:
                line = float(line)
            except (ValueError, TypeError):
                continue

        outcomes = market.get("outcomes", [])
        prices = [float(p) for p in market.get("outcomePrices", [])]
        clob_token_ids = market.get("clobTokenIds", [])

        props.append({
            "prop_type": sport_type,
            "player_name": player_name,
            "line": line,
            "outcomes": outcomes,
            "prices": prices,
            "clob_token_ids": clob_token_ids,
        })

    return props


def find_prop_market(
    event: dict, prop_type: str, player_name: str, line: float | None
) -> dict | None:
    """Find a specific prop market by type, player name, and line.

    Uses fuzzy name matching to handle diacritics and abbreviations.
    """
    from workflow.names import names_match

    for market in event.get("markets", []):
        market = _normalize_market(market)

        sport_type = market.get("sportsMarketType", "")
        if sport_type != prop_type:
            continue

        accepting = market.get("acceptingOrders")
        if not accepting or str(accepting).lower() == "false":
            continue

        # Parse player name from question
        question = market.get("question", "")
        if ":" not in question:
            continue
        market_player = question.split(":", 1)[0].strip()

        if not names_match(player_name, market_player):
            continue

        # Match line
        if line is not None:
            market_line = market.get("line")
            if market_line is None:
                continue
            try:
                if float(market_line) != float(line):
                    continue
            except (ValueError, TypeError):
                continue

        return market

    return None
