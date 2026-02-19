"""History tracking and categorization for bets and paper trades."""

from .types import CompletedBet


def _categorize_edge(edge: str) -> str:
    """Normalize edge description to a category for tracking."""
    edge_lower = edge.lower()

    if any(w in edge_lower for w in ["home", "home court", "home advantage"]):
        return "home_court"
    if any(w in edge_lower for w in ["rest", "fatigue", "back-to-back", "b2b", "tired"]):
        return "rest_advantage"
    if any(w in edge_lower for w in ["injury", "injured", "missing", "out", "questionable"]):
        return "injury_edge"
    if any(w in edge_lower for w in ["form", "streak", "momentum", "hot", "cold", "recent"]):
        return "form_momentum"
    if any(w in edge_lower for w in ["h2h", "head-to-head", "matchup history"]):
        return "h2h_history"
    if any(w in edge_lower for w in ["rating", "net rating", "offensive", "defensive", "efficiency"]):
        return "ratings_edge"
    if any(w in edge_lower for w in ["mismatch", "size", "pace", "style"]):
        return "style_mismatch"
    if any(w in edge_lower for w in ["total", "over", "under", "scoring"]):
        return "totals_edge"

    return edge[:25] if len(edge) > 25 else edge


def update_history_with_bet(history: dict, bet: CompletedBet) -> None:
    """Add a completed bet to history and recompute summary."""
    history["bets"].append(bet)
    summary = history["summary"]

    result = bet["result"]
    units = bet["units"]
    profit_loss = bet["profit_loss"]

    # early_exit: track dollar_pnl and net_units but don't count in W/L/P
    if result == "early_exit":
        summary["net_units"] = summary.get("net_units", 0.0) + profit_loss
        summary["net_dollar_pnl"] = summary.get("net_dollar_pnl", 0.0) + bet.get("dollar_pnl", 0.0)
        return

    summary["total_bets"] = summary.get("total_bets", 0) + 1

    if result == "win":
        summary["wins"] = summary.get("wins", 0) + 1
    elif result == "loss":
        summary["losses"] = summary.get("losses", 0) + 1
    elif result == "push":
        summary["pushes"] = summary.get("pushes", 0) + 1

    summary["net_units"] = summary.get("net_units", 0.0) + profit_loss
    summary["net_dollar_pnl"] = summary.get("net_dollar_pnl", 0.0) + bet.get("dollar_pnl", 0.0)

    if result in ("win", "loss"):
        summary["total_units_wagered"] = summary.get("total_units_wagered", 0.0) + units

    total = summary["total_bets"]
    summary["win_rate"] = round(summary["wins"] / total, 3) if total > 0 else 0.0
    wagered = summary["total_units_wagered"]
    summary["roi"] = round(summary["net_units"] / wagered, 3) if wagered > 0 else 0.0

    # Update by_confidence, by_primary_edge, by_bet_type
    if result in ("win", "loss"):
        result_key = "wins" if result == "win" else "losses"

        confidence = bet["confidence"]
        by_conf = summary.setdefault("by_confidence", {})
        entry = by_conf.setdefault(confidence, {"wins": 0, "losses": 0, "win_rate": 0.0})
        entry[result_key] = entry.get(result_key, 0) + 1
        ct = entry["wins"] + entry["losses"]
        entry["win_rate"] = round(entry["wins"] / ct, 3) if ct > 0 else 0.0

        edge_cat = _categorize_edge(bet["primary_edge"])
        by_edge = summary.setdefault("by_primary_edge", {})
        entry = by_edge.setdefault(edge_cat, {"wins": 0, "losses": 0, "win_rate": 0.0})
        entry[result_key] = entry.get(result_key, 0) + 1
        ct = entry["wins"] + entry["losses"]
        entry["win_rate"] = round(entry["wins"] / ct, 3) if ct > 0 else 0.0

        bet_type = bet.get("bet_type", "moneyline")
        by_type = summary.setdefault("by_bet_type", {})
        entry = by_type.setdefault(bet_type, {"wins": 0, "losses": 0, "win_rate": 0.0})
        entry[result_key] = entry.get(result_key, 0) + 1
        ct = entry["wins"] + entry["losses"]
        entry["win_rate"] = round(entry["wins"] / ct, 3) if ct > 0 else 0.0

    # Recompute current_streak from last 10 results
    recent = [
        b["result"]
        for b in reversed(history["bets"])
        if b["result"] in ("win", "loss")
    ][:10]
    if recent:
        latest = recent[0]
        count = 1
        for r in recent[1:]:
            if r == latest:
                count += 1
            else:
                break
        summary["current_streak"] = f"{'W' if latest == 'win' else 'L'}{count}"


def _categorize_skip_reason(reason: str) -> str:
    """Categorize skip reason for tracking patterns."""
    reason_lower = reason.lower()
    if any(w in reason_lower for w in ["injury", "injured", "missing", "out"]):
        return "injury_uncertainty"
    if any(w in reason_lower for w in ["coin flip", "coin-flip", "no edge", "no clear edge"]):
        return "no_edge"
    if any(w in reason_lower for w in ["uncertain", "unpredictable", "variance"]):
        return "high_variance"
    if any(w in reason_lower for w in ["kelly", "veto", "sizing"]):
        return "sizing_veto"
    return "other"


def update_paper_history_with_trade(history: dict, trade: dict) -> None:
    """Add a resolved paper trade to history and recompute summary."""
    history["trades"].append(trade)
    summary = history["summary"]

    result = trade["result"]
    profit_loss = trade.get("profit_loss", 0.0)

    summary["total_trades"] = summary.get("total_trades", 0) + 1

    if result == "win":
        summary["wins"] = summary.get("wins", 0) + 1
    elif result == "loss":
        summary["losses"] = summary.get("losses", 0) + 1
    elif result == "push":
        summary["pushes"] = summary.get("pushes", 0) + 1

    summary["net_units"] = summary.get("net_units", 0.0) + profit_loss

    total = summary["total_trades"]
    summary["win_rate"] = round(summary["wins"] / total, 3) if total > 0 else 0.0

    # Update breakdowns
    if result in ("win", "loss"):
        result_key = "wins" if result == "win" else "losses"

        # By confidence
        conf = trade.get("confidence", "low")
        by_conf = summary.setdefault("by_confidence", {})
        entry = by_conf.setdefault(conf, {"wins": 0, "losses": 0, "win_rate": 0.0})
        entry[result_key] += 1
        ct = entry["wins"] + entry["losses"]
        entry["win_rate"] = round(entry["wins"] / ct, 3) if ct > 0 else 0.0

        # By bet type
        bt = trade.get("bet_type", "moneyline")
        by_bt = summary.setdefault("by_bet_type", {})
        entry = by_bt.setdefault(bt, {"wins": 0, "losses": 0, "win_rate": 0.0})
        entry[result_key] += 1
        ct = entry["wins"] + entry["losses"]
        entry["win_rate"] = round(entry["wins"] / ct, 3) if ct > 0 else 0.0

        # By skip reason category
        reason_cat = _categorize_skip_reason(trade.get("skip_reason", ""))
        by_reason = summary.setdefault("by_skip_reason_category", {})
        entry = by_reason.setdefault(reason_cat, {"wins": 0, "losses": 0, "win_rate": 0.0})
        entry[result_key] += 1
        ct = entry["wins"] + entry["losses"]
        entry["win_rate"] = round(entry["wins"] / ct, 3) if ct > 0 else 0.0
