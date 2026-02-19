"""Position re-evaluation workflow.

Checks open Polymarket positions, computes P&L, re-evaluates adverse
positions via search + LLM, and auto-closes positions where the edge
is invalidated.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from polymarket_helpers.gamma import fetch_nba_events
from polymarket import create_clob_client, resolve_token_id, sell_position
from .io import (
    JOURNAL_DIR,
    append_text,
    get_active_bets,
    get_dollar_pnl,
    get_history,
    save_active_bets,
    save_history,
)
from .history import update_history_with_bet
from .llm import complete, complete_json
from .prompts import (
    CHECK_POSITION_PROMPT,
    SEARCH_POSITION_CONTEXT_PROMPT,
    SYSTEM_POSITION_MANAGER,
)
from .search import DEFAULT_PERPLEXITY_MODEL

ADVERSE_THRESHOLD = 0.10  # 10 percentage points


def compute_position_pnl(
    entry_price: float, live_price: float, amount: float
) -> Dict[str, Any]:
    """Compute P&L for a position.

    Args:
        entry_price: Price paid per share (0-1).
        live_price: Current market price (0-1).
        amount: Dollar amount wagered.

    Returns:
        Dict with shares, current_value, unrealized_pnl, pnl_pct, price_move.
    """
    shares = amount / entry_price
    current_value = shares * live_price
    unrealized_pnl = current_value - amount
    pnl_pct = (unrealized_pnl / amount) * 100 if amount else 0.0
    price_move = live_price - entry_price

    return {
        "shares": round(shares, 4),
        "current_value": round(current_value, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "pnl_pct": round(pnl_pct, 1),
        "price_move": round(price_move, 4),
    }


def is_adverse(pnl_info: Dict[str, Any], threshold: float = ADVERSE_THRESHOLD) -> bool:
    """Check if position has moved adversely beyond threshold.

    A position is adverse when the price moved against us by more than
    `threshold` (in absolute price terms, e.g., 0.10 = 10pp).
    """
    return pnl_info["price_move"] < -threshold


async def search_position_context(matchup_str: str) -> Optional[str]:
    """Search for injury/lineup changes via Perplexity."""
    prompt = SEARCH_POSITION_CONTEXT_PROMPT.format(matchup=matchup_str)
    perplexity_model = os.environ.get("PERPLEXITY_MODEL", DEFAULT_PERPLEXITY_MODEL)
    try:
        result = await complete(prompt, model=perplexity_model)
        return result
    except Exception as e:
        print(f"  Search failed for {matchup_str}: {e}")
        return None


async def reevaluate_position(
    bet: Dict[str, Any],
    pnl_info: Dict[str, Any],
    search_context: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Ask LLM whether to HOLD or CLOSE a position."""
    line = bet.get("line")
    if line is not None:
        line_str = f"{line:+.1f}" if bet.get("bet_type") == "spread" else f"{line:.1f}"
    else:
        line_str = "N/A"

    prompt = CHECK_POSITION_PROMPT.format(
        matchup=bet["matchup"],
        bet_type=bet.get("bet_type", "moneyline"),
        pick=bet["pick"],
        line=line_str,
        confidence=bet["confidence"],
        primary_edge=bet["primary_edge"],
        reasoning=bet["reasoning"],
        entry_price=bet["poly_price"],
        live_price=bet["poly_price"] + pnl_info["price_move"],
        pnl_pct=pnl_info["pnl_pct"],
        unrealized_pnl=pnl_info["unrealized_pnl"],
        search_context=search_context or "No additional context available.",
    )

    return await complete_json(prompt, system=SYSTEM_POSITION_MANAGER)


def _get_live_price(bet: Dict[str, Any], events: List[dict]) -> Optional[float]:
    """Get live price for a bet from Polymarket events.

    Returns None if market is closed or not found.
    """
    result = resolve_token_id(bet, events)
    if result is None:
        return None
    _, live_price = result
    return live_price


def execute_close(
    bet: Dict[str, Any],
    pnl_info: Dict[str, Any],
    recommendation: Dict[str, Any],
    client: Any,
    events: List[dict],
    active_bets: List[Dict[str, Any]],
) -> bool:
    """Execute a SELL order and record to history.

    Returns True if sell succeeded, False otherwise.
    """
    # Resolve token ID for sell
    result = resolve_token_id(bet, events)
    if result is None:
        print(f"  Cannot resolve market for sell: {bet['matchup']}")
        return False

    token_id, live_price = result
    shares = pnl_info["shares"]

    try:
        resp = sell_position(client, token_id, shares)
        print(f"  SOLD: {bet['matchup']} - {shares:.2f} shares @ ~{live_price:.2f}")
        print(f"        Response: {resp}")
    except Exception as e:
        print(f"  SELL FAILED: {bet['matchup']} - {e}")
        return False

    # Compute proceeds
    sell_proceeds = pnl_info["current_value"]
    cost_basis = bet["amount"]
    profit_loss_dollars = sell_proceeds - cost_basis

    # Record as completed bet in history
    completed_bet = {
        **bet,
        "result": "early_exit",
        "winner": "",
        "final_score": "",
        "actual_total": None,
        "actual_margin": None,
        "profit_loss": round(profit_loss_dollars * bet["units"] / bet["amount"], 2) if bet["amount"] else 0.0,
        "dollar_pnl": round(profit_loss_dollars, 2),
        "reflection": (
            f"Early exit: {recommendation.get('reasoning', 'Edge invalidated')}. "
            f"P&L: ${profit_loss_dollars:+.2f} ({pnl_info['pnl_pct']:+.1f}%)"
        ),
    }
    # Remove polymarket fields that aren't in CompletedBet
    for key in ("placed_polymarket",):
        completed_bet.pop(key, None)
    history = get_history()
    update_history_with_bet(history, completed_bet)
    save_history(history)

    # Remove from active bets
    active_bets[:] = [b for b in active_bets if b["id"] != bet["id"]]

    return True


def append_journal_check(
    date: str,
    positions: List[Dict[str, Any]],
    recommendations: List[Dict[str, Any]],
    executions: List[Dict[str, Any]],
) -> None:
    """Append position check results to the daily journal."""
    journal_path = JOURNAL_DIR / f"{date}.md"

    lines = []
    # Add header if journal doesn't exist
    existing = ""
    if journal_path.exists():
        existing = journal_path.read_text()
    if not existing:
        lines.extend([f"# NBA Betting Journal - {date}", "", ""])

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines.extend([f"## Position Check ({now})", ""])

    # Position table
    lines.append("### Open Positions")
    lines.append("")
    for pos in positions:
        bet = pos["bet"]
        pnl = pos["pnl"]
        status = "ADVERSE" if pos.get("adverse") else "OK"
        lines.append(
            f"- {bet['matchup']} | {bet['bet_type'].upper()} {bet['pick']} | "
            f"Entry: {bet['poly_price']:.2f} → Live: {bet['poly_price'] + pnl['price_move']:.2f} | "
            f"P&L: {pnl['pnl_pct']:+.1f}% (${pnl['unrealized_pnl']:+.2f}) | {status}"
        )
    lines.append("")

    # Recommendations
    if recommendations:
        lines.append("### Re-evaluations")
        lines.append("")
        for rec in recommendations:
            bet = rec["bet"]
            action = rec["recommendation"].get("action", "HOLD")
            reasoning = rec["recommendation"].get("reasoning", "")
            lines.append(f"- **{bet['matchup']}**: {action} — {reasoning}")
        lines.append("")

    # Executions
    if executions:
        lines.append("### Executions")
        lines.append("")
        for exe in executions:
            bet = exe["bet"]
            pnl = exe["pnl"]
            lines.append(
                f"- **SOLD** {bet['matchup']} | "
                f"P&L: ${pnl['unrealized_pnl']:+.2f} ({pnl['pnl_pct']:+.1f}%)"
            )
        lines.append("")

    if not recommendations and not executions:
        lines.append("*No adverse positions — all positions look healthy.*")
        lines.append("")

    lines.append("---")
    lines.append("")

    append_text(journal_path, "\n".join(lines))


async def run_check_workflow() -> None:
    """Check open positions, re-evaluate adverse ones, auto-close if needed."""
    load_dotenv()

    # Load active bets — only those placed on Polymarket with a price
    active_bets = get_active_bets()
    placed_bets = [
        b for b in active_bets
        if b.get("placed_polymarket") and b.get("poly_price") and b.get("amount")
    ]

    if not placed_bets:
        print("No placed positions to check.")
        return

    print(f"Checking {len(placed_bets)} position(s)...")

    # Get dates and fetch events
    dates = sorted({b["date"] for b in placed_bets})
    events_by_date: Dict[str, List[dict]] = {}
    for date in dates:
        events = fetch_nba_events(date)
        events_by_date[date] = events
        if not events:
            print(f"  {date}: no Polymarket events found")

    # Compute P&L for each position
    positions: List[Dict[str, Any]] = []
    for bet in placed_bets:
        events = events_by_date.get(bet["date"], [])
        live_price = _get_live_price(bet, events)

        if live_price is None:
            print(f"  {bet['matchup']}: market closed or not found, skipping")
            continue

        pnl = compute_position_pnl(bet["poly_price"], live_price, bet["amount"])
        adverse = is_adverse(pnl)
        positions.append({"bet": bet, "pnl": pnl, "adverse": adverse})

    if not positions:
        print("No open markets found for positions.")
        return

    # Log position table
    print(f"\n{'Matchup':<45} {'Type':<8} {'Entry':>6} {'Live':>6} {'P&L':>8} {'Status':<8}")
    print("-" * 85)
    for pos in positions:
        bet = pos["bet"]
        pnl = pos["pnl"]
        live = bet["poly_price"] + pnl["price_move"]
        status = "ADVERSE" if pos["adverse"] else "ok"
        print(
            f"  {bet['matchup']:<43} {bet['bet_type']:<8} "
            f"{bet['poly_price']:>6.2f} {live:>6.2f} "
            f"{pnl['pnl_pct']:>+7.1f}% {status:<8}"
        )

    # Find adverse positions
    adverse_positions = [p for p in positions if p["adverse"]]
    if not adverse_positions:
        print("\nAll positions within threshold. No action needed.")
        # Still log to journal
        date = dates[0] if len(dates) == 1 else dates[-1]
        append_journal_check(date, positions, [], [])
        return

    print(f"\n{len(adverse_positions)} adverse position(s) — running re-evaluation...")

    # Search + LLM re-evaluation for adverse positions
    recommendations: List[Dict[str, Any]] = []
    for pos in adverse_positions:
        bet = pos["bet"]
        pnl = pos["pnl"]
        print(f"\n  Evaluating: {bet['matchup']}...")

        # Search for context
        context = await search_position_context(bet["matchup"])
        if context:
            print(f"    Search: {len(context)} chars")
        else:
            print(f"    Search: no results")

        # LLM re-evaluation
        result = await reevaluate_position(bet, pnl, context)
        if result:
            action = result.get("action", "HOLD")
            print(f"    Recommendation: {action} — {result.get('reasoning', '')[:80]}")
            recommendations.append({"bet": bet, "pnl": pnl, "recommendation": result})
        else:
            print(f"    LLM failed — defaulting to HOLD")
            recommendations.append({
                "bet": bet,
                "pnl": pnl,
                "recommendation": {"action": "HOLD", "reasoning": "LLM evaluation failed"},
            })

    # Execute CLOSE recommendations
    close_recs = [r for r in recommendations if r["recommendation"].get("action") == "CLOSE"]
    executions: List[Dict[str, Any]] = []

    if close_recs:
        print(f"\n{len(close_recs)} position(s) recommended for close. Executing...")

        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
        funder = os.environ.get("POLYMARKET_FUNDER")
        if not private_key or not funder:
            print("Error: POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER must be set for selling")
        else:
            client = create_clob_client(private_key, funder)

            for rec in close_recs:
                bet = rec["bet"]
                pnl = rec["pnl"]
                events = events_by_date.get(bet["date"], [])

                success = execute_close(
                    bet, pnl, rec["recommendation"],
                    client, events, active_bets,
                )
                if success:
                    executions.append({"bet": bet, "pnl": pnl})

            # Save updated state
            save_active_bets(active_bets)
            total_pnl = get_dollar_pnl()
            print(f"\nDollar P&L: ${total_pnl:+.2f}")
    else:
        print("\nAll adverse positions recommended HOLD. No sells executed.")

    # Journal
    date = dates[0] if len(dates) == 1 else dates[-1]
    append_journal_check(date, positions, recommendations, executions)
    print(f"\nSee bets/journal/{date}.md for details")
