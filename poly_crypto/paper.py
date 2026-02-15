"""Paper trading for crypto candle edge signals."""

import html as html_lib
import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import requests

from poly_crypto.markets import GAMMA_BASE_URL
from poly_crypto.signals import EdgeSignal, scan_edges

PAPER_DIR = Path(__file__).parent / "paper"
TRADES_FILE = PAPER_DIR / "trades.json"
HISTORY_FILE = PAPER_DIR / "history.json"

GRACE_PERIOD_HOURS = 2


class CandlePaperTrade(TypedDict, total=False):
    symbol: str
    title: str
    side: str
    candle_start: str
    candle_end: str
    entry_price: float
    edge: float
    edge_size: float
    net_edge: float
    synth_probability: float
    market_probability: float
    event_id: str
    up_token_id: str
    down_token_id: str
    created_at: str
    # Set after resolution
    result: str  # "win" / "loss" / "unresolved"
    winning_side: str
    resolved_at: str
    profit_loss: float  # +1 / -1 / 0


# --- IO helpers ---


def _load_trades() -> list[CandlePaperTrade]:
    if not TRADES_FILE.exists():
        return []
    return json.loads(TRADES_FILE.read_text())


def _save_trades(trades: list[CandlePaperTrade]) -> None:
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    TRADES_FILE.write_text(json.dumps(trades, indent=2) + "\n")


def _load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {"trades": [], "summary": {}}
    return json.loads(HISTORY_FILE.read_text())


def _save_history(history: dict) -> None:
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2) + "\n")


def _dedup_key(trade: dict) -> str:
    return f"{trade['symbol']}:{trade['candle_end']}"


def _parse_utc(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _edge_bucket(edge_size: float) -> str:
    if edge_size >= 0.15:
        return "15%+"
    if edge_size >= 0.10:
        return "10-15%"
    return "6-10%"


# --- Signal to trade conversion ---


def _signal_to_trade(signal: EdgeSignal) -> CandlePaperTrade:
    return CandlePaperTrade(
        symbol=signal["symbol"],
        title=signal["title"],
        side=signal["side"],
        candle_start=signal["candle_start"],
        candle_end=signal["candle_end"],
        entry_price=signal["best_ask"],
        edge=signal["edge"],
        edge_size=signal["edge_size"],
        net_edge=signal["net_edge"],
        synth_probability=signal["synth_probability_up"],
        market_probability=signal["market_probability_up"],
        event_id=signal["event_id"],
        up_token_id=signal["up_token_id"],
        down_token_id=signal["down_token_id"],
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# --- Resolution ---


def _fetch_event(event_id: str) -> dict | None:
    try:
        resp = requests.get(f"{GAMMA_BASE_URL}/events/{event_id}", timeout=10)
        if resp.status_code != 200:
            return None
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def _resolve_outcome(event: dict) -> str | None:
    """Determine winning side from a resolved event.

    Returns winning side ("Up" or "Down") or None if not yet resolved.
    """
    markets = event.get("markets", [])
    if not markets:
        return None

    market = markets[0]
    if not market.get("closed"):
        return None

    outcomes = market.get("outcomes", [])
    prices = market.get("outcomePrices", [])

    # Parse JSON-encoded strings if needed
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(prices, str):
        prices = json.loads(prices)

    if len(outcomes) < 2 or len(prices) < 2:
        return None

    prices = [float(p) for p in prices]

    winner_idx = prices.index(max(prices))
    if prices[winner_idx] < 0.99:
        return None  # Not cleanly resolved yet

    return outcomes[winner_idx]


def _resolve_trade(trade: CandlePaperTrade) -> CandlePaperTrade | None:
    """Try to resolve a trade. Returns updated trade or None if not resolved."""
    event = _fetch_event(trade["event_id"])
    if not event:
        return None

    winning_side = _resolve_outcome(event)
    if not winning_side:
        return None
    won = trade["side"] == winning_side
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    trade["result"] = "win" if won else "loss"
    trade["winning_side"] = winning_side
    trade["resolved_at"] = now
    trade["profit_loss"] = 1.0 if won else -1.0
    return trade


# --- Summary stats ---


def _compute_summary(trades: list[CandlePaperTrade]) -> dict:
    resolved = [t for t in trades if t.get("result") in ("win", "loss")]
    if not resolved:
        return {}

    wins = sum(1 for t in resolved if t["result"] == "win")
    losses = sum(1 for t in resolved if t["result"] == "loss")
    unresolved = sum(1 for t in trades if t.get("result") == "unresolved")
    total = wins + losses

    def _bucket_stats(filtered: list[CandlePaperTrade]) -> dict:
        w = sum(1 for tr in filtered if tr["result"] == "win")
        lo = sum(1 for tr in filtered if tr["result"] == "loss")
        n = w + lo
        return {"wins": w, "losses": lo, "win_rate": round(w / n, 3) if n else 0}

    by_symbol: dict[str, dict] = {}
    by_side: dict[str, dict] = {}
    by_edge_bucket: dict[str, dict] = {}

    for key_fn, bucket_dict in [
        (lambda t: t["symbol"], by_symbol),
        (lambda t: t["side"], by_side),
        (lambda t: _edge_bucket(t.get("edge_size", 0)), by_edge_bucket),
    ]:
        groups: dict[str, list] = {}
        for t in resolved:
            k = key_fn(t)
            groups.setdefault(k, []).append(t)
        for k, group in sorted(groups.items()):
            bucket_dict[k] = _bucket_stats(group)

    # Current streak
    streak = ""
    if resolved:
        sorted_trades = sorted(resolved, key=lambda t: t.get("resolved_at", ""), reverse=True)
        streak_type = sorted_trades[0]["result"][0].upper()  # "W" or "L"
        streak_count = 0
        for t in sorted_trades:
            if t["result"][0].upper() == streak_type:
                streak_count += 1
            else:
                break
        streak = f"{streak_type}{streak_count}"

    summary = {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "unresolved": unresolved,
        "win_rate": round(wins / total, 3) if total else 0,
        "net_units": round(wins - losses, 1),
        "by_symbol": by_symbol,
        "by_side": by_side,
        "by_edge_bucket": by_edge_bucket,
        "current_streak": streak,
    }
    return summary


# --- Public API ---


def run_scan_and_trade() -> None:
    """Scan for edges, record paper trades, and resolve expired ones."""
    signals = scan_edges()

    trades = _load_trades()
    existing_keys = {_dedup_key(t) for t in trades}

    recorded = 0
    for signal in signals:
        key = f"{signal['symbol']}:{signal['candle_end']}"
        if key in existing_keys:
            print(f"  SKIP {signal['symbol']} {signal['candle_end']} (already traded)")
            continue

        trade = _signal_to_trade(signal)
        trades.append(trade)
        existing_keys.add(key)
        recorded += 1
        print(f"  TRADE {trade['symbol']} {trade['side']} | edge {trade['edge_size']:.1%} net {trade['net_edge']:.1%} | {trade['candle_end']}")

    if not signals and not trades:
        print("No edges found. No open trades.")
        return

    if recorded:
        print(f"{recorded} new trade(s) recorded, {len(trades)} open total.")

    _resolve_open_trades(trades)


def _resolve_open_trades(trades: list[CandlePaperTrade]) -> None:
    """Resolve expired candle trades."""
    if not trades:
        return

    now = datetime.now(timezone.utc)
    still_open: list[CandlePaperTrade] = []
    newly_resolved: list[CandlePaperTrade] = []

    for trade in trades:
        end = _parse_utc(trade["candle_end"])
        if not end or end > now:
            still_open.append(trade)
            continue

        hours_past = (now - end).total_seconds() / 3600

        resolved = _resolve_trade(trade)
        if resolved:
            newly_resolved.append(resolved)
            print(f"  {resolved['result'].upper()} {resolved['symbol']} {resolved['side']} (actual: {resolved['winning_side']}) | {resolved['candle_end']}")
        elif hours_past > GRACE_PERIOD_HOURS:
            trade["result"] = "unresolved"
            trade["resolved_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            trade["profit_loss"] = 0.0
            newly_resolved.append(trade)
            print(f"  UNRESOLVED {trade['symbol']} {trade['side']} | {trade['candle_end']} (>{GRACE_PERIOD_HOURS}h past)")
        else:
            still_open.append(trade)
            print(f"  PENDING {trade['symbol']} {trade['side']} | {trade['candle_end']} (waiting for oracle)")

    if newly_resolved:
        history = _load_history()
        history["trades"].extend(newly_resolved)
        history["summary"] = _compute_summary(history["trades"])
        _save_history(history)

    _save_trades(still_open)
    if newly_resolved:
        print(f"{len(newly_resolved)} resolved, {len(still_open)} still open.")
