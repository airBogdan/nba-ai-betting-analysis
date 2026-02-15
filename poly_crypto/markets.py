"""Discover crypto candle prediction markets on Polymarket."""

import json
from datetime import datetime, timedelta, timezone
from typing import TypedDict

import requests

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

SYMBOLS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "xrp",
}

# Gamma API tag slugs are case-sensitive: 5M, 15M, 1H are uppercase; 4h is lowercase
TIMEFRAMES = {
    "5M": "5M",
    "15M": "15M",
    "1H": "1H",
    "4H": "4h",
}

# Duration in seconds for computing candle start from end time
TIMEFRAME_SECONDS = {
    "5M": 300,
    "15M": 900,
    "1H": 3600,
    "4H": 14400,
}


class CandleMarket(TypedDict):
    title: str
    slug: str
    event_id: str
    market_id: str
    symbol: str
    timeframe: str
    start_time: str
    end_time: str
    up_price: float
    down_price: float
    up_token_id: str
    down_token_id: str
    liquidity: float
    volume: float
    volume_24h: float
    resolution_source: str


def _parse_iso(s: str) -> datetime | None:
    """Parse an ISO 8601 timestamp to a timezone-aware datetime."""
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _normalize_event(event: dict) -> dict:
    """Parse JSON-encoded string fields in market dicts within an event."""
    for market in event.get("markets", []):
        for field in ("outcomes", "outcomePrices", "clobTokenIds"):
            val = market.get(field)
            if isinstance(val, str):
                market[field] = json.loads(val)
    return event


def _extract_candle_market(event: dict, symbol: str, timeframe: str) -> CandleMarket | None:
    """Extract a clean CandleMarket from a raw event dict."""
    markets = event.get("markets", [])
    if not markets:
        return None

    market = markets[0]
    outcomes = market.get("outcomes", [])
    prices = market.get("outcomePrices", [])
    token_ids = market.get("clobTokenIds", [])

    if len(outcomes) < 2 or len(prices) < 2 or len(token_ids) < 2:
        return None

    up_idx = next((i for i, o in enumerate(outcomes) if o == "Up"), 0)
    down_idx = 1 - up_idx

    end_time_str = market.get("endDate", event.get("endDate", ""))
    # Compute candle start from end_time - timeframe duration
    # (market/event startDate is creation time, not candle start)
    end_dt = _parse_iso(end_time_str)
    if end_dt:
        duration = TIMEFRAME_SECONDS.get(timeframe.upper(), 3600)
        start_dt = end_dt - timedelta(seconds=duration)
        start_time = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        start_time = ""
    end_time = end_time_str

    return CandleMarket(
        title=event.get("title", ""),
        slug=event.get("slug", ""),
        event_id=str(event.get("id", "")),
        market_id=str(market.get("id", "")),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        start_time=start_time,
        end_time=end_time,
        up_price=float(prices[up_idx]),
        down_price=float(prices[down_idx]),
        up_token_id=str(token_ids[up_idx]),
        down_token_id=str(token_ids[down_idx]),
        liquidity=float(event.get("liquidity", 0)),
        volume=float(event.get("volume", 0)),
        volume_24h=float(event.get("volume24hr", 0)),
        resolution_source=event.get("resolutionSource", ""),
    )


def fetch_crypto_candle_markets(
    symbol: str,
    timeframe: str,
    limit: int = 10,
) -> list[dict]:
    """Fetch active crypto candle events from the Gamma API.

    Args:
        symbol: Crypto symbol (BTC, ETH, SOL, XRP).
        timeframe: Candle timeframe (5M, 15M, 1H, 4H).
        limit: Max number of events to return.

    Returns:
        List of raw event dicts sorted by end date (soonest first),
        filtered to future events only.
    """
    symbol = symbol.upper()
    timeframe = timeframe.upper()

    symbol_slug = SYMBOLS.get(symbol)
    if not symbol_slug:
        raise ValueError(f"Unknown symbol: {symbol}. Use one of {list(SYMBOLS)}")

    tf_slug = TIMEFRAMES.get(timeframe)
    if not tf_slug:
        raise ValueError(f"Unknown timeframe: {timeframe}. Use one of {list(TIMEFRAMES)}")

    # 5M generates many events; fetch enough to find future ones past stale results
    api_limit = max(limit * 10, 100) if timeframe == "5M" else max(limit * 4, 20)

    try:
        resp = requests.get(
            f"{GAMMA_BASE_URL}/events",
            params={
                "tag_slug": tf_slug,
                "closed": "false",
                "active": "true",
                "limit": str(api_limit),
            },
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Error fetching crypto markets: {e}")
        return []

    now = datetime.now(timezone.utc)
    filtered = []
    for event in events:
        event = _normalize_event(event)
        # Filter to matching symbol
        tag_slugs = {t.get("slug", "").lower() for t in event.get("tags", [])}
        if symbol_slug.lower() not in tag_slugs:
            continue
        # Skip past events
        end = _parse_iso(event.get("endDate", ""))
        if not end or end <= now:
            continue
        filtered.append(event)

    filtered.sort(key=lambda e: e.get("endDate", ""))
    return filtered[:limit]


def get_active_candle_market(symbol: str, timeframe: str) -> CandleMarket | None:
    """Get the currently active or next upcoming candle market.

    Args:
        symbol: Crypto symbol (BTC, ETH, SOL, XRP).
        timeframe: Candle timeframe (5M, 15M, 1H, 4H).

    Returns:
        CandleMarket for the current/next candle, or None if unavailable.
    """
    events = fetch_crypto_candle_markets(symbol, timeframe, limit=1)
    if events:
        return _extract_candle_market(events[0], symbol, timeframe)
    return None


def get_active_candle_markets_batch(
    symbols: list[str], timeframe: str
) -> dict[str, CandleMarket]:
    """Get active candle markets for multiple symbols in a single API call.

    Args:
        symbols: List of crypto symbols (e.g. ["BTC", "ETH", "SOL"]).
        timeframe: Candle timeframe (5M, 15M, 1H, 4H).

    Returns:
        Dict mapping symbol to its CandleMarket (only symbols with active markets).
    """
    timeframe = timeframe.upper()
    tf_slug = TIMEFRAMES.get(timeframe)
    if not tf_slug:
        raise ValueError(f"Unknown timeframe: {timeframe}. Use one of {list(TIMEFRAMES)}")

    # Build lookup of requested symbols
    requested = {}
    for sym in symbols:
        sym = sym.upper()
        slug = SYMBOLS.get(sym)
        if slug:
            requested[slug.lower()] = sym

    if not requested:
        return {}

    api_limit = 100 if timeframe == "5M" else 40

    try:
        resp = requests.get(
            f"{GAMMA_BASE_URL}/events",
            params={
                "tag_slug": tf_slug,
                "closed": "false",
                "active": "true",
                "limit": str(api_limit),
            },
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Error fetching crypto markets: {e}")
        return {}

    now = datetime.now(timezone.utc)
    # Collect earliest future event per symbol
    best: dict[str, tuple[str, dict]] = {}  # symbol -> (end_date, event)

    for event in events:
        event = _normalize_event(event)
        end = _parse_iso(event.get("endDate", ""))
        if not end or end <= now:
            continue

        tag_slugs = {t.get("slug", "").lower() for t in event.get("tags", [])}
        for slug, sym in requested.items():
            if slug in tag_slugs:
                end_str = event.get("endDate", "")
                if sym not in best or end_str < best[sym][0]:
                    best[sym] = (end_str, event)

    result: dict[str, CandleMarket] = {}
    for sym, (_, event) in best.items():
        cm = _extract_candle_market(event, sym, timeframe)
        if cm:
            result[sym] = cm

    return result


def get_upcoming_candle_markets(symbol: str, timeframe: str, count: int = 3) -> list[CandleMarket]:
    """Get multiple upcoming candle markets.

    Args:
        symbol: Crypto symbol (BTC, ETH, SOL, XRP).
        timeframe: Candle timeframe (5M, 15M, 1H, 4H).
        count: Number of upcoming markets to return.

    Returns:
        List of CandleMarket dicts for upcoming candles.
    """
    events = fetch_crypto_candle_markets(symbol, timeframe, limit=count)
    results = []
    for event in events:
        cm = _extract_candle_market(event, symbol, timeframe)
        if cm:
            results.append(cm)
    return results


def list_available_markets() -> dict[str, list[str]]:
    """Discover which symbol+timeframe combinations currently have live markets.

    Returns:
        Dict mapping "SYMBOL/TIMEFRAME" to list of active event titles.
    """
    available: dict[str, list[str]] = {}

    for tf_key in TIMEFRAMES:
        for sym_key in SYMBOLS:
            events = fetch_crypto_candle_markets(sym_key, tf_key, limit=10)
            if events:
                key = f"{sym_key}/{tf_key}"
                available[key] = [e.get("title", "") for e in events]

    return available


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print("=== Available Crypto Candle Markets ===\n")
        available = list_available_markets()
        for key in sorted(available):
            titles = available[key]
            print(f"{key}: {len(titles)} market(s)")
            for t in titles[:3]:
                print(f"  - {t}")
            if len(titles) > 3:
                print(f"  ... and {len(titles) - 3} more")
        sys.exit(0)

    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "1H"

    print(f"=== {symbol} {timeframe} Candle Markets ===\n")

    market = get_active_candle_market(symbol, timeframe)
    if market:
        print(f"Current/Next: {market['title']}")
        print(f"  Window:     {market['start_time']} -> {market['end_time']}")
        print(f"  Up:         {market['up_price']:.3f}  (token: ...{market['up_token_id'][-8:]})")
        print(f"  Down:       {market['down_price']:.3f}  (token: ...{market['down_token_id'][-8:]})")
        print(f"  Liquidity:  ${market['liquidity']:,.2f}")
        print(f"  Volume:     ${market['volume']:,.2f}")
        print(f"  Volume 24h: ${market['volume_24h']:,.2f}")
        print(f"  Source:     {market['resolution_source']}")
    else:
        print(f"No active {symbol} {timeframe} market found.")

    print(f"\n--- Upcoming ---")
    upcoming = get_upcoming_candle_markets(symbol, timeframe, count=5)
    for m in upcoming:
        print(f"  {m['title']}: Up={m['up_price']:.3f} Down={m['down_price']:.3f} | Vol ${m['volume']:,.2f}")
