"""Paper trading for crypto candle edge signals."""

import html as html_lib
import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import requests

from poly_crypto.markets import GAMMA_BASE_URL
from poly_crypto.signals import SYNTH_SYMBOLS, EdgeSignal, scan_edges

PAPER_DIR = Path(__file__).parent / "paper"
TRADES_FILE = PAPER_DIR / "trades.json"
HISTORY_FILE = PAPER_DIR / "history.json"

GRACE_PERIOD_HOURS = 48


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
    print(f"--- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ---")

    trades = _load_trades()
    existing_keys = {_dedup_key(t) for t in trades}

    # Skip scan if we already have an open trade for a future candle
    now = datetime.now(timezone.utc)
    has_active_trade = any(
        (_parse_utc(t.get("candle_end", "")) or datetime.min.replace(tzinfo=timezone.utc)) > now
        for t in trades
    )
    if has_active_trade:
        print("Active trade for current candle. Skipping scan.")
        _resolve_open_trades(trades)
        return

    signals = scan_edges(traded_keys=existing_keys)

    # One asset per candle: pick the highest net_edge signal only
    if signals:
        signals = [max(signals, key=lambda s: s["net_edge"])]

    recorded = 0
    for signal in signals:
        key = f"{signal['symbol']}:{signal['candle_end']}"
        if key in existing_keys:
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
            print(f"  PENDING {trade['symbol']} {trade['side']} | {trade['candle_end']} (candle in progress)")
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


# --- Dashboard ---


DASHBOARD_FILE = PAPER_DIR / "dashboard.html"


def _cumulative_pnl(trades: list[CandlePaperTrade]) -> list[dict]:
    """Compute cumulative P&L over time, aggregated by resolved date."""
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
        by_date[date] = {"date": date, "cumulative_units": round(cum, 2)}
    return list(by_date.values())


def _rolling_win_rate(trades: list[CandlePaperTrade], window: int = 10) -> list[dict]:
    """Compute rolling win rate over a window."""
    wl = [t for t in trades if t.get("result") in ("win", "loss")]
    if not wl:
        return []

    results = []
    for i, t in enumerate(wl):
        start = max(0, i - window + 1)
        chunk = wl[start : i + 1]
        wins = sum(1 for c in chunk if c["result"] == "win")
        results.append({"trade_number": i + 1, "rolling_win_rate": round(wins / len(chunk), 3)})
    return results


def _render_dashboard(
    summary: dict,
    cumulative_pnl: list[dict],
    rolling_wr: list[dict],
    trades: list[CandlePaperTrade],
) -> str:
    """Render self-contained HTML dashboard."""
    pnl_dates = json.dumps([p["date"] for p in cumulative_pnl])
    pnl_units = json.dumps([p["cumulative_units"] for p in cumulative_pnl])

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

    # Overview values
    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)
    total = summary.get("total_trades", 0)
    win_rate = summary.get("win_rate", 0.0)
    net_units = summary.get("net_units", 0.0)
    streak = summary.get("current_streak", "")
    nu_style = _color(net_units)

    # Breakdown tables
    def _breakdown_rows(bucket_dict: dict) -> str:
        out = ""
        for key in sorted(bucket_dict, key=lambda k: bucket_dict[k].get("wins", 0) + bucket_dict[k].get("losses", 0), reverse=True):
            b = bucket_dict[key]
            w = b.get("wins", 0)
            lo = b.get("losses", 0)
            n = w + lo
            wr = b.get("win_rate", 0.0)
            nu = round(w - lo, 1)
            nu_s = _color(nu)
            out += (
                f"<tr><td>{_esc(key)}</td><td>{w}</td><td>{lo}</td>"
                f"<td>{n}</td><td>{wr * 100:.1f}%</td>"
                f'<td style="{nu_s}">{nu:+.1f}</td></tr>\n'
            )
        return out

    by_symbol = _breakdown_rows(summary.get("by_symbol", {}))
    by_side = _breakdown_rows(summary.get("by_side", {}))
    by_edge = _breakdown_rows(summary.get("by_edge_bucket", {}))

    # Recent trades (last 20 resolved, newest first)
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
        pnl_style = _color(pnl)
        result_style = "color: #22c55e" if result == "win" else "color: #ef4444"
        edge_pct = f"{t.get('edge_size', 0) * 100:.1f}%"
        recent_rows += (
            f'<tr><td>{_esc(date)}</td><td>{_esc(t.get("symbol", ""))}</td>'
            f'<td>{_esc(t.get("side", ""))}</td><td>{edge_pct}</td>'
            f'<td style="{result_style}">{result.upper()}</td>'
            f'<td style="{pnl_style}">{pnl:+.1f}</td></tr>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Crypto Paper Trading Dashboard</title>
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
<h1>Crypto Paper Trading Dashboard</h1>

<div class="cards">
  <div class="card"><div class="label">Record</div><div class="value">{wins}-{losses}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value">{win_rate * 100:.1f}%</div></div>
  <div class="card"><div class="label">Net Units</div><div class="value" style="{nu_style}">{net_units:+.1f}</div></div>
  <div class="card"><div class="label">Streak</div><div class="value">{streak}</div></div>
  <div class="card"><div class="label">Total Trades</div><div class="value">{total}</div></div>
</div>

<h2>Cumulative P&amp;L</h2>
<div class="chart-container"><canvas id="pnlChart"></canvas></div>

<h2>Rolling Win Rate (10-trade window)</h2>
<div class="chart-container"><canvas id="wrChart"></canvas></div>

<h2>By Symbol</h2>
<table>
<tr><th>Symbol</th><th>W</th><th>L</th><th>Total</th><th>Win%</th><th>Net Units</th></tr>
{by_symbol}</table>

<h2>By Side</h2>
<table>
<tr><th>Side</th><th>W</th><th>L</th><th>Total</th><th>Win%</th><th>Net Units</th></tr>
{by_side}</table>

<h2>By Edge Bucket</h2>
<table>
<tr><th>Edge</th><th>W</th><th>L</th><th>Total</th><th>Win%</th><th>Net Units</th></tr>
{by_edge}</table>

<h2>Recent Trades</h2>
<table>
<tr><th>Date</th><th>Symbol</th><th>Side</th><th>Edge</th><th>Result</th><th>P&amp;L</th></tr>
{recent_rows}</table>

<script>
new Chart(document.getElementById('pnlChart'), {{
  type: 'line',
  data: {{
    labels: {pnl_dates},
    datasets: [
      {{ label: 'Units', data: {pnl_units}, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3 }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ title: {{ display: true, text: 'Units', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
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


def generate_dashboard() -> None:
    """Generate HTML dashboard and open in browser."""
    history = _load_history()
    trades = history.get("trades", [])

    resolved = [t for t in trades if t.get("result") in ("win", "loss")]
    if not resolved:
        print("No resolved trades yet.")
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
