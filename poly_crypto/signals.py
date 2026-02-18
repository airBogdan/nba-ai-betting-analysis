"""Synthdata edge detection for Polymarket 1H crypto candle markets."""

import os
from typing import TypedDict

import requests
from dotenv import load_dotenv

from poly_crypto.markets import get_active_candle_markets_batch, _parse_iso

SYNTHDATA_BASE_URL = "https://api.synthdata.co"
SYNTH_SYMBOLS = ["BTC", "ETH", "SOL"]
EDGE_THRESHOLD = 0.09


class EdgeSignal(TypedDict):
    symbol: str
    title: str
    candle_start: str
    candle_end: str
    current_price: float
    start_price: float
    current_direction: str
    synth_probability_up: float
    market_probability_up: float
    edge: float
    side: str
    edge_size: float
    best_bid: float
    best_ask: float
    spread: float
    net_edge: float
    up_token_id: str
    down_token_id: str
    event_id: str


load_dotenv()


def fetch_synth_hourly(symbol: str) -> dict | None:
    """Fetch Synthdata's hourly Polymarket signal for a crypto asset.

    Args:
        symbol: Crypto symbol (BTC, ETH, SOL).

    Returns:
        Raw response dict or None on error.
    """
    api_key = os.environ.get("SYNTHDATA_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{SYNTHDATA_BASE_URL}/insights/polymarket/up-down/hourly",
            params={"asset": symbol.upper()},
            headers={"Authorization": f"Apikey {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("synth_probability_up") is None:
            return None
        return data
    except (requests.RequestException, ValueError):
        return None


def _build_signal(synth: dict, market: dict, symbol: str) -> EdgeSignal:
    """Build an EdgeSignal from matched Synthdata and Polymarket data."""
    synth_prob = synth["synth_probability_up"]
    market_prob = synth["polymarket_probability_up"]
    edge = synth_prob - market_prob

    best_bid = synth.get("best_bid_price") or 0
    best_ask = synth.get("best_ask_price") or 0
    spread = round(best_ask - best_bid, 4) if best_ask and best_bid else 0
    net_edge = round(abs(edge) - spread, 4)

    return EdgeSignal(
        symbol=symbol.upper(),
        title=market["title"],
        candle_start=market["start_time"],
        candle_end=market["end_time"],
        current_price=synth["current_price"],
        start_price=synth["start_price"],
        current_direction=synth.get("current_outcome", ""),
        synth_probability_up=synth_prob,
        market_probability_up=market_prob,
        edge=round(edge, 4),
        side="Up" if edge > 0 else "Down",
        edge_size=round(abs(edge), 4),
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        net_edge=net_edge,
        up_token_id=market["up_token_id"],
        down_token_id=market["down_token_id"],
        event_id=market["event_id"],
    )



def scan_edges(
    threshold: float = EDGE_THRESHOLD,
    traded_keys: set[str] | None = None,
) -> list[EdgeSignal]:
    """Scan all supported assets for 1H candle edges.

    Uses a single Polymarket API call for all symbols.
    Skips Synthdata calls for candles already in traded_keys.

    Returns:
        List of EdgeSignal dicts sorted by edge_size descending.
    """
    if traded_keys is None:
        traded_keys = set()

    # Single API call for all Polymarket markets
    markets = get_active_candle_markets_batch(SYNTH_SYMBOLS, "1H")

    signals = []
    for symbol in SYNTH_SYMBOLS:
        market = markets.get(symbol)
        if not market:
            continue

        # Skip paid Synthdata call if this candle is already traded
        if f"{symbol}:{market['end_time']}" in traded_keys:
            continue

        synth = fetch_synth_hourly(symbol)
        if not synth:
            continue

        synth_end = _parse_iso(synth.get("event_end_time", ""))
        market_end = _parse_iso(market["end_time"])
        if not synth_end or not market_end or synth_end != market_end:
            continue

        signal = _build_signal(synth, market, symbol)
        if signal["edge_size"] >= threshold:
            signals.append(signal)

    signals.sort(key=lambda s: s["edge_size"], reverse=True)
    return signals


