"""Pure data computation functions for betting analytics."""

from typing import Any, Callable, Dict, List, Optional

from .history import _categorize_edge, _categorize_skip_reason


def _pick_side(bet: dict) -> Optional[str]:
    """Determine if the pick was home or away. Returns None for totals."""
    bet_type = bet.get("bet_type", "")
    if bet_type == "total":
        return None
    matchup = bet.get("matchup", "")
    parts = matchup.split(" @ ")
    if len(parts) != 2:
        return None
    away, home = parts
    pick = bet.get("pick", "")
    pick_lower = pick.lower().strip()
    if pick_lower and (pick_lower in home.lower() or home.lower() in pick_lower):
        return "home"
    if pick_lower and (pick_lower in away.lower() or away.lower() in pick_lower):
        return "away"
    return None


def compute_overview(history: dict) -> dict:
    """Compute overview card data from history."""
    summary = history.get("summary", {})

    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)
    pushes = summary.get("pushes", 0)
    total = summary.get("total_bets", 0)
    net_units = summary.get("net_units", 0.0)
    net_dollars = summary.get("net_dollar_pnl", 0.0)
    roi = summary.get("roi", 0.0)
    streak = summary.get("current_streak", "")
    win_rate = summary.get("win_rate", 0.0)
    wagered = summary.get("total_units_wagered", 0.0)
    avg_units = round(wagered / total, 2) if total > 0 else 0.0

    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "total_bets": total,
        "win_rate": win_rate,
        "net_units": net_units,
        "net_dollars": net_dollars,
        "roi": roi,
        "streak": streak,
        "avg_units": avg_units,
    }


def compute_cumulative_pnl(bets: list) -> list:
    """Compute cumulative P&L over time, aggregated by date."""
    if not bets:
        return []

    # Sort by date
    sorted_bets = sorted(bets, key=lambda b: b.get("date", ""))
    cum_units = 0.0
    cum_dollars = 0.0
    by_date: Dict[str, dict] = {}

    for bet in sorted_bets:
        date = bet.get("date", "unknown")
        cum_units += bet.get("profit_loss", 0.0)
        cum_dollars += bet.get("dollar_pnl", 0.0)
        by_date[date] = {
            "date": date,
            "cumulative_units": round(cum_units, 2),
            "cumulative_dollars": round(cum_dollars, 2),
        }

    return list(by_date.values())


def compute_rolling_win_rate(bets: list, window: int = 10) -> list:
    """Compute rolling win rate over a window, excluding pushes."""
    # Filter to win/loss only, maintain chronological order
    wl_bets = [b for b in bets if b.get("result") in ("win", "loss")]
    if not wl_bets:
        return []

    results = []
    for i, bet in enumerate(wl_bets):
        start = max(0, i - window + 1)
        window_bets = wl_bets[start : i + 1]
        wins = sum(1 for b in window_bets if b["result"] == "win")
        rate = round(wins / len(window_bets), 3)
        results.append({"bet_number": i + 1, "rolling_win_rate": rate})

    return results


def compute_breakdown_table(
    bets: list, key_fn: Callable[[dict], Optional[str]]
) -> list:
    """Compute breakdown table grouped by key_fn."""
    groups: Dict[str, dict] = {}

    for bet in bets:
        key = key_fn(bet)
        if key is None:
            continue
        if key not in groups:
            groups[key] = {"category": key, "wins": 0, "losses": 0, "pushes": 0, "net_units": 0.0, "units_wagered": 0.0}
        entry = groups[key]
        result = bet.get("result", "")
        units = bet.get("units", 0.0)
        pnl = bet.get("profit_loss", 0.0)

        if result == "win":
            entry["wins"] += 1
            entry["units_wagered"] += units
        elif result == "loss":
            entry["losses"] += 1
            entry["units_wagered"] += units
        elif result == "push":
            entry["pushes"] += 1
        entry["net_units"] += pnl

    rows = []
    for entry in groups.values():
        total = entry["wins"] + entry["losses"] + entry["pushes"]
        wl = entry["wins"] + entry["losses"]
        win_rate = round(entry["wins"] / wl, 3) if wl > 0 else 0.0
        roi = round(entry["net_units"] / entry["units_wagered"], 3) if entry["units_wagered"] > 0 else 0.0
        rows.append({
            "category": entry["category"],
            "wins": entry["wins"],
            "losses": entry["losses"],
            "pushes": entry["pushes"],
            "total": total,
            "win_rate": win_rate,
            "net_units": round(entry["net_units"], 2),
            "roi": roi,
        })

    return sorted(rows, key=lambda r: r["total"], reverse=True)


def compute_all_breakdowns(bets: list) -> dict:
    """Compute all breakdown tables."""
    return {
        "by_confidence": compute_breakdown_table(bets, lambda b: b.get("confidence")),
        "by_edge_type": compute_breakdown_table(bets, lambda b: _categorize_edge(b.get("primary_edge", ""))),
        "by_bet_type": compute_breakdown_table(bets, lambda b: b.get("bet_type")),
        "by_pick_side": compute_breakdown_table(bets, _pick_side),
    }


def compute_skip_stats(skips: list) -> dict:
    """Compute skip statistics."""
    resolved = sum(1 for s in skips if s.get("outcome_resolved"))
    return {
        "total_skipped": len(skips),
        "resolved": resolved,
        "skips": skips,
    }


def compute_paper_overview(paper_history: dict) -> dict:
    """Compute overview card data from paper trade history."""
    summary = paper_history.get("summary", {})
    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)
    pushes = summary.get("pushes", 0)
    total = summary.get("total_trades", 0)
    net_units = summary.get("net_units", 0.0)
    win_rate = summary.get("win_rate", 0.0)

    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "total_trades": total,
        "win_rate": win_rate,
        "net_units": net_units,
    }


def compute_paper_breakdowns(trades: list) -> dict:
    """Compute paper trade breakdown tables."""
    return {
        "by_confidence": compute_breakdown_table(trades, lambda t: t.get("confidence")),
        "by_bet_type": compute_breakdown_table(trades, lambda t: t.get("bet_type")),
        "by_skip_reason": compute_breakdown_table(trades, lambda t: _categorize_skip_reason(t.get("skip_reason", ""))),
    }
