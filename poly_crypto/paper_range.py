"""Paper trading for Polymarket daily price range bracket markets."""

import html as html_lib
import json
import os
import re
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import requests
from dotenv import load_dotenv

load_dotenv()

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
SYNTHDATA_BASE_URL = "https://api.synthdata.co"

PAPER_DIR = Path(__file__).parent / "paper"
TRADES_FILE = PAPER_DIR / "range_trades.json"
HISTORY_FILE = PAPER_DIR / "range_history.json"
DASHBOARD_FILE = PAPER_DIR / "range_dashboard.html"

RANGE_ASSETS = ["BTC", "ETH", "SOL"]
MIN_EDGE = 0.05  # 5% min synth-vs-market edge
MAX_ASK = 0.25  # Only bet cheap tail brackets
GRACE_PERIOD_HOURS = 48


class RangePaperTrade(TypedDict, total=False):
    asset: str
    event_slug: str
    bracket: str  # e.g. "[66000, 68000]"
    cmp_type: str  # "lower", "between", "higher"
    ref_prices: list[float]
    entry_price: float
    synth_probability: float
    market_probability: float
    edge: float
    ev_per_dollar: float
    event_end: str
    market_id: str
    token_id: str
    created_at: str
    # Post-resolution
    result: str  # "win" / "loss" / "unresolved"
    resolved_at: str
    profit_loss: float  # win = +(1 - entry_price), loss = -entry_price


# --- IO helpers ---


def _load_trades() -> list[RangePaperTrade]:
    if not TRADES_FILE.exists():
        return []
    return json.loads(TRADES_FILE.read_text())


def _save_trades(trades: list[RangePaperTrade]) -> None:
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
    return f"{trade['asset']}:{trade['event_end']}"


def _parse_utc(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- Synth API ---


def _fetch_synth_range(asset: str) -> list[dict] | None:
    """Fetch Synth range bracket data for an asset."""
    api_key = os.environ.get("SYNTHDATA_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            f"{SYNTHDATA_BASE_URL}/insights/polymarket/range",
            params={"asset": asset.upper()},
            headers={"Authorization": f"Apikey {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, list):
            return data
        # Some responses wrap in a dict
        return data.get("brackets") or data.get("items") or data.get("data") or [data]
    except (requests.RequestException, ValueError):
        return None


# --- Gamma API ---


def _fetch_event_by_slug(slug: str) -> dict | None:
    """Fetch a Polymarket event by slug from the Gamma API."""
    try:
        resp = requests.get(
            f"{GAMMA_BASE_URL}/events",
            params={"slug": slug, "limit": "1"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        events = resp.json()
        if not events:
            return None
        event = events[0]
        # Parse JSON-encoded string fields
        for market in event.get("markets", []):
            for field in ("outcomes", "outcomePrices", "clobTokenIds"):
                val = market.get(field)
                if isinstance(val, str):
                    market[field] = json.loads(val)
        return event
    except (requests.RequestException, ValueError):
        return None


def _parse_dollar_amounts(text: str) -> list[float]:
    """Extract dollar amounts from market question text.

    Handles formats like "$66,000", "$68,000.50", "$66000".
    """
    matches = re.findall(r"\$([0-9,]+(?:\.[0-9]+)?)", text)
    amounts = []
    for m in matches:
        try:
            amounts.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return amounts


def _match_market(event: dict, ref_prices: list, cmp_type: str) -> dict | None:
    """Find the Gamma market within an event that matches the given ref_prices."""
    ref_set = set(float(p) for p in ref_prices)

    for market in event.get("markets", []):
        question = market.get("question", "")
        amounts = _parse_dollar_amounts(question)
        if not amounts or set(amounts) != ref_set:
            continue
        # For single-ref-price brackets, also check direction keywords
        # to avoid confusing "below $X" with "above $X"
        if len(ref_prices) == 1:
            q = question.lower()
            if cmp_type == "lower" and not any(
                w in q for w in ("below", "less", "lower", "under")
            ):
                continue
            if cmp_type == "higher" and not any(
                w in q for w in ("above", "greater", "more", "higher", "over")
            ):
                continue
        return market

    return None


def _get_yes_index(market: dict) -> int | None:
    """Find the index of 'Yes' in the outcomes list."""
    outcomes = market.get("outcomes", [])
    for i, o in enumerate(outcomes):
        if o.lower() == "yes":
            return i
    return None


# --- Signal detection ---


def _scan_range_signals(traded_keys: set[str]) -> list[dict]:
    """Scan all range assets for edge signals.

    Returns list of signal dicts ready to convert to trades.
    """
    signals = []

    for asset in RANGE_ASSETS:
        brackets = _fetch_synth_range(asset)
        if not brackets:
            print(f"  {asset}: no Synth range data")
            continue

        # Get event slug from first bracket that has one
        slug = None
        for b in brackets:
            slug = b.get("slug")
            if slug:
                break

        if not slug:
            print(f"  {asset}: no event slug in Synth data")
            continue

        # Fetch event from Gamma
        event = _fetch_event_by_slug(slug)
        if not event:
            print(f"  {asset}: could not fetch event '{slug}' from Gamma")
            continue

        event_end = event.get("endDate", "")
        dedup = f"{asset}:{event_end}"
        if dedup in traded_keys:
            print(f"  {asset}: already traded this event")
            continue

        # Score each bracket
        candidates = []
        for bracket in brackets:
            synth_prob = bracket.get("synth_probability")
            poly_prob = bracket.get("polymarket_probability")
            if synth_prob is None or poly_prob is None:
                continue

            synth_prob = float(synth_prob)
            poly_prob = float(poly_prob)

            ref_prices = bracket.get("ref_prices", [])
            cmp_type = bracket.get("cmp_type", "")

            # Match to Gamma market to get actual ask price
            gamma_market = _match_market(event, ref_prices, cmp_type)
            if not gamma_market:
                continue

            yes_idx = _get_yes_index(gamma_market)
            if yes_idx is None:
                continue

            prices = gamma_market.get("outcomePrices", [])
            token_ids = gamma_market.get("clobTokenIds", [])
            if yes_idx >= len(prices) or yes_idx >= len(token_ids):
                continue

            ask = float(prices[yes_idx])
            if ask <= 0:
                continue
            edge = round(synth_prob - poly_prob, 4)
            ev = round(synth_prob - ask, 4)

            # Filter
            if edge < MIN_EDGE:
                continue
            if ask > MAX_ASK:
                continue
            if ev <= 0:
                continue

            candidates.append(
                {
                    "asset": asset,
                    "event_slug": slug,
                    "bracket": str(ref_prices),
                    "cmp_type": cmp_type,
                    "ref_prices": ref_prices,
                    "entry_price": ask,
                    "synth_probability": synth_prob,
                    "market_probability": poly_prob,
                    "edge": edge,
                    "ev_per_dollar": ev,
                    "event_end": event_end,
                    "market_id": str(gamma_market.get("id", "")),
                    "token_id": str(token_ids[yes_idx]),
                }
            )

        if candidates:
            # One trade per asset: pick highest EV
            best = max(candidates, key=lambda c: c["ev_per_dollar"])
            signals.append(best)
            print(
                f"  {asset}: best bracket {best['bracket']} |"
                f" edge {best['edge']:.1%} ev ${best['ev_per_dollar']:.3f}"
                f" ask ${best['entry_price']:.3f}"
            )
        else:
            print(
                f"  {asset}: no qualifying brackets"
                f" (edge >= {MIN_EDGE:.0%}, ask <= ${MAX_ASK:.2f})"
            )

    return signals


# --- Resolution ---


def _resolve_trade(trade: RangePaperTrade) -> RangePaperTrade | None:
    """Try to resolve a range trade. Returns updated trade or None."""
    event = _fetch_event_by_slug(trade["event_slug"])
    if not event:
        return None

    # Find our market by market_id
    market = None
    for m in event.get("markets", []):
        if str(m.get("id", "")) == trade["market_id"]:
            market = m
            break

    if not market or not market.get("closed"):
        return None

    yes_idx = _get_yes_index(market)
    if yes_idx is None:
        return None

    prices = market.get("outcomePrices", [])
    if yes_idx >= len(prices):
        return None

    price = float(prices[yes_idx])

    if price > 0.99:
        won = True
    elif price < 0.01:
        won = False
    else:
        return None  # Not cleanly resolved

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = trade["entry_price"]

    trade["result"] = "win" if won else "loss"
    trade["resolved_at"] = now
    trade["profit_loss"] = round(1.0 - entry, 4) if won else round(-entry, 4)
    return trade


def _resolve_open_trades(trades: list[RangePaperTrade]) -> None:
    """Resolve expired range trades."""
    if not trades:
        return

    now = datetime.now(timezone.utc)
    still_open: list[RangePaperTrade] = []
    newly_resolved: list[RangePaperTrade] = []

    for trade in trades:
        end = _parse_utc(trade.get("event_end", ""))
        if not end or end > now:
            still_open.append(trade)
            print(
                f"  PENDING {trade['asset']} {trade['bracket']}"
                f" @ ${trade['entry_price']:.3f} | {trade['event_end']}"
            )
            continue

        hours_past = (now - end).total_seconds() / 3600

        resolved = _resolve_trade(trade)
        if resolved:
            newly_resolved.append(resolved)
            pnl = resolved["profit_loss"]
            print(
                f"  {resolved['result'].upper()} {resolved['asset']}"
                f" {resolved['bracket']} | P&L ${pnl:+.4f}"
            )
        elif hours_past > GRACE_PERIOD_HOURS:
            trade["result"] = "unresolved"
            trade["resolved_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            trade["profit_loss"] = 0.0
            newly_resolved.append(trade)
            print(
                f"  UNRESOLVED {trade['asset']} {trade['bracket']}"
                f" | {trade['event_end']} (>{GRACE_PERIOD_HOURS}h past)"
            )
        else:
            still_open.append(trade)
            print(
                f"  PENDING {trade['asset']} {trade['bracket']}"
                f" | {trade['event_end']} (waiting for oracle)"
            )

    if newly_resolved:
        history = _load_history()
        history["trades"].extend(newly_resolved)
        history["summary"] = _compute_summary(history["trades"])
        _save_history(history)

    _save_trades(still_open)
    if newly_resolved:
        print(f"{len(newly_resolved)} resolved, {len(still_open)} still open.")


# --- Summary stats ---


def _compute_summary(trades: list[RangePaperTrade]) -> dict:
    resolved = [t for t in trades if t.get("result") in ("win", "loss")]
    if not resolved:
        return {}

    wins = sum(1 for t in resolved if t["result"] == "win")
    losses = sum(1 for t in resolved if t["result"] == "loss")
    unresolved = sum(1 for t in trades if t.get("result") == "unresolved")
    total = wins + losses

    total_pnl = round(sum(t.get("profit_loss", 0.0) for t in resolved), 4)
    total_invested = round(sum(t.get("entry_price", 0.0) for t in resolved), 4)
    avg_entry = round(total_invested / total, 4) if total else 0.0
    roi = round(total_pnl / total_invested, 4) if total_invested else 0.0

    # By asset
    by_asset: dict[str, dict] = {}
    groups: dict[str, list] = {}
    for t in resolved:
        groups.setdefault(t["asset"], []).append(t)
    for k, group in sorted(groups.items()):
        w = sum(1 for t in group if t["result"] == "win")
        lo = sum(1 for t in group if t["result"] == "loss")
        n = w + lo
        pnl = round(sum(t.get("profit_loss", 0.0) for t in group), 4)
        inv = round(sum(t.get("entry_price", 0.0) for t in group), 4)
        by_asset[k] = {
            "wins": w,
            "losses": lo,
            "win_rate": round(w / n, 3) if n else 0,
            "pnl": pnl,
            "roi": round(pnl / inv, 4) if inv else 0.0,
        }

    # Streak
    streak = ""
    if resolved:
        sorted_trades = sorted(
            resolved, key=lambda t: t.get("resolved_at", ""), reverse=True
        )
        streak_type = sorted_trades[0]["result"][0].upper()
        streak_count = 0
        for t in sorted_trades:
            if t["result"][0].upper() == streak_type:
                streak_count += 1
            else:
                break
        streak = f"{streak_type}{streak_count}"

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "unresolved": unresolved,
        "win_rate": round(wins / total, 3) if total else 0,
        "total_pnl": total_pnl,
        "avg_entry_price": avg_entry,
        "roi": roi,
        "by_asset": by_asset,
        "current_streak": streak,
    }


# --- Public API ---


def run_range_scan_and_trade() -> None:
    """Scan for range bracket edges, record paper trades, resolve expired."""
    print(
        f"--- Range Brackets |"
        f" {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ---"
    )

    trades = _load_trades()
    existing_keys = {_dedup_key(t) for t in trades}

    # Also exclude events already in history (resolved trades)
    history = _load_history()
    for t in history.get("trades", []):
        existing_keys.add(_dedup_key(t))

    print("Scanning range brackets...")
    signals = _scan_range_signals(existing_keys)

    recorded = 0
    for signal in signals:
        key = f"{signal['asset']}:{signal['event_end']}"
        if key in existing_keys:
            continue

        trade = RangePaperTrade(
            asset=signal["asset"],
            event_slug=signal["event_slug"],
            bracket=signal["bracket"],
            cmp_type=signal["cmp_type"],
            ref_prices=signal["ref_prices"],
            entry_price=signal["entry_price"],
            synth_probability=signal["synth_probability"],
            market_probability=signal["market_probability"],
            edge=signal["edge"],
            ev_per_dollar=signal["ev_per_dollar"],
            event_end=signal["event_end"],
            market_id=signal["market_id"],
            token_id=signal["token_id"],
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        trades.append(trade)
        existing_keys.add(key)
        recorded += 1
        print(
            f"  TRADE {trade['asset']} {trade['bracket']}"
            f" | edge {trade['edge']:.1%} ev ${trade['ev_per_dollar']:.3f}"
            f" @ ${trade['entry_price']:.3f}"
        )

    if not signals and not trades:
        print("No edges found. No open trades.")
        return

    if recorded:
        print(f"{recorded} new trade(s) recorded, {len(trades)} open total.")

    _resolve_open_trades(trades)


# --- Dashboard ---


def _cumulative_pnl(trades: list[RangePaperTrade]) -> list[dict]:
    resolved = sorted(
        [t for t in trades if t.get("result") in ("win", "loss")],
        key=lambda t: t.get("resolved_at", ""),
    )
    if not resolved:
        return []

    cum = 0.0
    by_date: dict[str, dict] = {}
    for t in resolved:
        date = t.get("resolved_at", "")[:10]
        cum += t.get("profit_loss", 0.0)
        by_date[date] = {"date": date, "cumulative_pnl": round(cum, 4)}
    return list(by_date.values())


def _rolling_win_rate(
    trades: list[RangePaperTrade], window: int = 10
) -> list[dict]:
    wl = [t for t in trades if t.get("result") in ("win", "loss")]
    if not wl:
        return []
    results = []
    for i, t in enumerate(wl):
        start = max(0, i - window + 1)
        chunk = wl[start : i + 1]
        wins = sum(1 for c in chunk if c["result"] == "win")
        results.append(
            {"trade_number": i + 1, "rolling_win_rate": round(wins / len(chunk), 3)}
        )
    return results


def _render_dashboard(
    summary: dict,
    cumulative_pnl: list[dict],
    rolling_wr: list[dict],
    trades: list[RangePaperTrade],
) -> str:
    pnl_dates = json.dumps([p["date"] for p in cumulative_pnl])
    pnl_values = json.dumps([p["cumulative_pnl"] for p in cumulative_pnl])

    wr_numbers = json.dumps([r["trade_number"] for r in rolling_wr])
    wr_rates = json.dumps([r["rolling_win_rate"] for r in rolling_wr])

    def _color(val: float) -> str:
        if val > 0:
            return "color: #22c55e"
        if val < 0:
            return "color: #ef4444"
        return ""

    def _esc(val: object) -> str:
        return html_lib.escape(str(val))

    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)
    total = summary.get("total_trades", 0)
    win_rate = summary.get("win_rate", 0.0)
    total_pnl = summary.get("total_pnl", 0.0)
    avg_entry = summary.get("avg_entry_price", 0.0)
    roi = summary.get("roi", 0.0)
    streak = summary.get("current_streak", "")
    pnl_style = _color(total_pnl)
    roi_style = _color(roi)

    # By asset rows
    by_asset = summary.get("by_asset", {})
    asset_rows = ""
    for key in sorted(by_asset):
        b = by_asset[key]
        w = b.get("wins", 0)
        lo = b.get("losses", 0)
        n = w + lo
        wr = b.get("win_rate", 0.0)
        pnl = b.get("pnl", 0.0)
        r = b.get("roi", 0.0)
        ps = _color(pnl)
        rs = _color(r)
        asset_rows += (
            f"<tr><td>{_esc(key)}</td><td>{w}</td><td>{lo}</td>"
            f"<td>{n}</td><td>{wr * 100:.1f}%</td>"
            f'<td style="{ps}">${pnl:+.4f}</td>'
            f'<td style="{rs}">{r * 100:+.1f}%</td></tr>\n'
        )

    # Recent trades
    resolved = sorted(
        [t for t in trades if t.get("result") in ("win", "loss")],
        key=lambda t: t.get("resolved_at", ""),
        reverse=True,
    )[:20]

    recent_rows = ""
    for t in resolved:
        date = t.get("resolved_at", "")[:10]
        result = t.get("result", "")
        pnl = t.get("profit_loss", 0.0)
        ps = _color(pnl)
        rs = "color: #22c55e" if result == "win" else "color: #ef4444"
        recent_rows += (
            f'<tr><td>{_esc(date)}</td><td>{_esc(t.get("asset", ""))}</td>'
            f'<td>{_esc(t.get("bracket", ""))}</td>'
            f'<td>${t.get("entry_price", 0):.3f}</td>'
            f'<td>{t.get("edge", 0) * 100:.1f}%</td>'
            f'<td style="{rs}">{result.upper()}</td>'
            f'<td style="{ps}">${pnl:+.4f}</td></tr>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Range Bracket Paper Trading Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ text-align: center; margin-bottom: 24px; font-size: 1.8rem; }}
  h2 {{ margin: 32px 0 16px; font-size: 1.3rem; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 8px; padding: 16px; text-align: center; }}
  .card .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; }}
  .chart-container {{ background: #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; margin-bottom: 24px; }}
  th {{ background: #334155; padding: 10px 12px; text-align: left; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 8px 12px; border-top: 1px solid #334155; font-size: 0.9rem; }}
  tr:hover {{ background: #253347; }}
</style>
</head>
<body>
<h1>Range Bracket Paper Trading</h1>

<div class="cards">
  <div class="card"><div class="label">Record</div><div class="value">{wins}-{losses}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value">{win_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Total P&amp;L</div><div class="value" style="{pnl_style}">${total_pnl:+.4f}</div></div>
  <div class="card"><div class="label">ROI</div><div class="value" style="{roi_style}">{roi * 100:+.1f}%</div></div>
  <div class="card"><div class="label">Avg Entry</div><div class="value">${avg_entry:.3f}</div></div>
  <div class="card"><div class="label">Streak</div><div class="value">{streak}</div></div>
  <div class="card"><div class="label">Total Trades</div><div class="value">{total}</div></div>
</div>

<h2>Cumulative P&amp;L</h2>
<div class="chart-container"><canvas id="pnlChart"></canvas></div>

<h2>Rolling Win Rate (10-trade window)</h2>
<div class="chart-container"><canvas id="wrChart"></canvas></div>

<h2>By Asset</h2>
<table>
<tr><th>Asset</th><th>W</th><th>L</th><th>Total</th><th>Win%</th><th>P&amp;L</th><th>ROI</th></tr>
{asset_rows}</table>

<h2>Recent Trades</h2>
<table>
<tr><th>Date</th><th>Asset</th><th>Bracket</th><th>Entry</th><th>Edge</th><th>Result</th><th>P&amp;L</th></tr>
{recent_rows}</table>

<script>
new Chart(document.getElementById('pnlChart'), {{
  type: 'line',
  data: {{
    labels: {pnl_dates},
    datasets: [
      {{ label: 'P&L ($)', data: {pnl_values}, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3 }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ title: {{ display: true, text: 'P&L ($)', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
  }}
}});

new Chart(document.getElementById('wrChart'), {{
  type: 'line',
  data: {{
    labels: {wr_numbers},
    datasets: [
      {{ label: 'Win Rate', data: {wr_rates}, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', fill: true, tension: 0.3 }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ title: {{ display: true, text: 'Trade #', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ min: 0, max: 1, title: {{ display: true, text: 'Win Rate', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8', callback: function(v) {{ return (v * 100) + '%'; }} }}, grid: {{ color: '#334155' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
  }}
}});
</script>
</body>
</html>"""


def generate_range_dashboard() -> None:
    """Generate HTML dashboard for range bracket trades and open in browser."""
    history = _load_history()
    trades = history.get("trades", [])

    resolved = [t for t in trades if t.get("result") in ("win", "loss")]
    if not resolved:
        print("No resolved range trades yet.")
        return

    summary = history.get("summary", {})
    cum_pnl = _cumulative_pnl(trades)
    rolling_wr = _rolling_win_rate(
        sorted(resolved, key=lambda t: t.get("resolved_at", ""))
    )

    html_str = _render_dashboard(summary, cum_pnl, rolling_wr, trades)

    DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_FILE.write_text(html_str)
    print(f"Dashboard written to {DASHBOARD_FILE}")

    try:
        webbrowser.open(f"file://{DASHBOARD_FILE.resolve()}")
    except Exception:
        pass
