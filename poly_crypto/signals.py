"""Synthdata edge detection for Polymarket 1H crypto candle markets."""

import os
import sys
from pathlib import Path
from typing import TypedDict

# Allow running as script or module
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from dotenv import load_dotenv

from poly_crypto.markets import get_active_candle_market, _parse_iso

SYNTHDATA_BASE_URL = "https://api.synthdata.co"
SYNTH_SYMBOLS = ["BTC", "ETH", "SOL"]
EDGE_THRESHOLD = 0.06


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


def fetch_synth_hourly(symbol: str) -> dict | None:
    """Fetch Synthdata's hourly Polymarket signal for a crypto asset.

    Args:
        symbol: Crypto symbol (BTC, ETH, SOL).

    Returns:
        Raw response dict or None on error.
    """
    load_dotenv()
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


def _fetch_and_match(symbol: str) -> tuple[dict, dict] | tuple[None, str]:
    """Fetch Synthdata + Polymarket data and validate they match.

    Returns:
        (synth_data, market_data) on success, or (None, reason) on failure.
    """
    synth = fetch_synth_hourly(symbol)
    if not synth:
        return None, "Synthdata unavailable"

    market = get_active_candle_market(symbol, "1H")
    if not market:
        return None, "No Polymarket 1H market"

    synth_end = _parse_iso(synth.get("event_end_time", ""))
    market_end = _parse_iso(market["end_time"])
    if not synth_end or not market_end or synth_end != market_end:
        return None, "Candle mismatch (Synthdata/Polymarket out of sync)"

    return synth, market


def detect_edge(symbol: str, threshold: float = EDGE_THRESHOLD) -> EdgeSignal | None:
    """Detect edge between Synthdata model and Polymarket price for a 1H candle.

    Args:
        symbol: Crypto symbol (BTC, ETH, SOL).
        threshold: Minimum abs(edge) to return a signal.

    Returns:
        EdgeSignal if edge exceeds threshold, None otherwise.
    """
    result = _fetch_and_match(symbol)
    if result[0] is None:
        return None

    synth, market = result
    signal = _build_signal(synth, market, symbol)

    if signal["edge_size"] < threshold:
        return None

    return signal


def scan_edges(threshold: float = EDGE_THRESHOLD) -> list[EdgeSignal]:
    """Scan all supported assets for 1H candle edges.

    Returns:
        List of EdgeSignal dicts sorted by edge_size descending.
    """
    signals = []
    for symbol in SYNTH_SYMBOLS:
        signal = detect_edge(symbol, threshold)
        if signal:
            signals.append(signal)
    signals.sort(key=lambda s: s["edge_size"], reverse=True)
    return signals


def _format_price(price: float) -> str:
    if price >= 1000:
        return f"${price:,.0f}"
    elif price >= 1:
        return f"${price:,.2f}"
    return f"${price:.4f}"


def _print_signal(signal: EdgeSignal) -> None:
    print(f"\n{signal['symbol']} | {signal['title']}")
    print(f"  Candle:  {_format_price(signal['start_price'])} -> {_format_price(signal['current_price'])} (currently {signal['current_direction']})")
    print(f"  Synth:   {signal['synth_probability_up']:.1%} Up")
    print(f"  Market:  {signal['market_probability_up']:.1%} Up")
    edge_sign = "+" if signal["edge"] > 0 else ""
    print(f"  Edge:    {edge_sign}{signal['edge']:.1%} -> BET {signal['side'].upper()}")
    print(f"  Bid/Ask: {signal['best_bid']:.2f} / {signal['best_ask']:.2f} (spread {signal['spread']:.1%})")
    print(f"  Net:     {signal['net_edge']:.1%} (edge after spread)")
    print(f"  Tokens:  Up=...{signal['up_token_id'][-8:]}  Down=...{signal['down_token_id'][-8:]}")


def _print_scan_result(symbol: str, threshold: float = EDGE_THRESHOLD) -> bool:
    """Fetch data once and print result. Returns True if edge found."""
    result = _fetch_and_match(symbol)
    if result[0] is None:
        print(f"\n{symbol} | {result[1]}")
        return False

    synth, market = result
    signal = _build_signal(synth, market, symbol)

    if signal["edge_size"] >= threshold:
        _print_signal(signal)
        return True

    print(f"\n{symbol} | No edge (synth={signal['synth_probability_up']:.1%} market={signal['market_probability_up']:.1%} edge={signal['edge_size']:.1%})")
    return False


if __name__ == "__main__":
    symbols = [sys.argv[1].upper()] if len(sys.argv) > 1 else SYNTH_SYMBOLS

    print("=== Crypto 1H Edge Scanner ===")

    results = [_print_scan_result(s) for s in symbols]

    if not any(results):
        print("\nNo edges above threshold.")
