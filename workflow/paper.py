"""Paper trading workflow for skipped games."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from .io import (
    PAPER_DIR,
    PAPER_JOURNAL_DIR,
    get_paper_history,
    get_paper_insights,
    get_paper_trades,
    read_text,
    save_paper_insights,
    save_paper_trades,
    write_text,
)
from .llm import complete_json
from .prompts import (
    PAPER_TRADE_PROMPT,
    SYSTEM_PAPER_ANALYST,
    UPDATE_PAPER_STRATEGY_PROMPT,
    compact_json,
    format_paper_history_summary,
)
from .strategy import apply_adjustments, append_change_log

CONFIDENCE_TO_UNITS = {"low": 0.5, "medium": 1.0, "high": 2.0}
MIN_PAPER_TRADES_FOR_STRATEGY = 15
MAX_PAPER_ADJUSTMENTS = 3

INITIAL_PAPER_STRATEGY = """# Paper Trading Strategy

## Purpose
Find value in games the primary analyst skips. Track contrarian picks to discover
which skip patterns leave money on the table.

## Approach
- Challenge skip reasoning — look for edges dismissed too quickly
- Focus on games skipped for "no clear edge" — these often have subtle value
- Be honest about confidence — low confidence is fine for paper trading
- Track which skip categories yield the best results

## What to Look For
- Injury uncertainty games where the line overreacted
- "Coin flip" games where one side actually has a lean
- Games skipped due to variance where statistical edges exist
- Sizing vetos where the edge was real but below threshold
"""


def create_paper_trade(llm_pick: Dict[str, Any], date: str, skip_reason: str) -> dict:
    """Create a PaperTrade dict from LLM output."""
    confidence = llm_pick.get("confidence", "low")
    return {
        "matchup": llm_pick["matchup"],
        "date": date,
        "bet_type": llm_pick["bet_type"],
        "pick": llm_pick["pick"],
        "line": llm_pick.get("line"),
        "confidence": confidence,
        "reasoning": llm_pick.get("reasoning", ""),
        "primary_edge": llm_pick.get("primary_edge", ""),
        "skip_reason": skip_reason,
        "game_id": llm_pick.get("game_id", ""),
        "units": CONFIDENCE_TO_UNITS.get(confidence, 0.5),
    }


async def run_paper_trades(
    enriched_skips: List[Dict[str, Any]],
    date: str,
    games_data: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Run contrarian paper trading on skipped games.

    Called at the end of run_analyze_workflow after real bets are saved.
    """
    if not enriched_skips:
        return

    # Build skip context for the LLM
    skip_context = []
    for skip in enriched_skips:
        entry = {
            "matchup": skip.get("matchup", "Unknown"),
            "game_id": skip.get("game_id", ""),
            "skip_reason": skip.get("reason", "No clear edge"),
        }
        # Attach matchup data if available
        if games_data:
            for game in games_data:
                gid = str(game.get("api_game_id", ""))
                if gid and gid == str(skip.get("game_id", "")):
                    clean = {k: v for k, v in game.items()
                             if not k.startswith("_") and k not in ("search_context",)}
                    entry["matchup_data"] = clean
                    break
        skip_context.append(entry)

    # Load paper strategy and history
    paper_strategy = read_text(PAPER_DIR / "strategy.md")
    paper_history = get_paper_history()
    history_summary = format_paper_history_summary(paper_history["summary"])

    prompt = PAPER_TRADE_PROMPT.format(
        skipped_games_json=compact_json(skip_context),
        paper_strategy=paper_strategy or "No paper trading strategy defined yet. This is a new system — focus on finding genuine contrarian edges.",
        paper_history_summary=history_summary,
    )

    result = await complete_json(prompt, system=SYSTEM_PAPER_ANALYST)
    if not result:
        print("  Paper trade analysis failed.")
        return

    # Create paper trade entries
    skip_reason_lookup = {s.get("matchup", ""): s.get("reason", "No clear edge") for s in enriched_skips}
    new_trades = []
    for pick in result.get("paper_trades", []):
        if not pick.get("matchup") or not pick.get("pick"):
            continue
        skip_reason = skip_reason_lookup.get(pick["matchup"], "No clear edge")
        trade = create_paper_trade(pick, date, skip_reason)
        new_trades.append(trade)

    if not new_trades:
        return

    # Save paper trades (append to existing)
    existing = get_paper_trades()
    save_paper_trades(existing + new_trades)

    # Write paper journal entry
    write_paper_journal(date, new_trades, result.get("summary", ""))

    print(f"  Paper traded {len(new_trades)} skipped game(s)")
    for t in new_trades:
        line_str = f" {t['line']}" if t.get("line") is not None else ""
        print(f"    {t['matchup']}: [{t['bet_type'].upper()}] {t['pick']}{line_str} ({t['confidence']})")


def write_paper_journal(date: str, trades: List[dict], summary: str) -> None:
    """Write paper trade journal entry."""
    lines = [
        f"# Paper Trading Journal - {date}",
        "",
        "## Contrarian Analysis",
        "",
        summary,
        "",
    ]

    for trade in trades:
        bt = trade.get("bet_type", "moneyline")
        pick = trade["pick"]
        line = trade.get("line")
        if bt == "spread" and line is not None:
            pick_display = f"{pick} {line:+.1f}"
        elif bt == "total" and line is not None:
            pick_display = f"{pick} {line:.1f}"
        else:
            pick_display = pick

        lines.append(f"### {trade['matchup']} - {bt.upper()}")
        lines.append(f"- Pick: {pick_display} ({trade.get('confidence', 'low')} confidence)")
        lines.append(f"- Units: {trade.get('units', 0.5)}")
        lines.append(f"- Edge: {trade.get('primary_edge', 'Unknown')}")
        lines.append(f"- Reasoning: {trade.get('reasoning', '')}")
        lines.append(f"- Skip reason: {trade.get('skip_reason', '')}")
        lines.append("")

    lines.append("---")
    lines.append("")

    write_text(PAPER_JOURNAL_DIR / f"{date}.md", "\n".join(lines))


async def run_paper_strategy_workflow() -> None:
    """Update the paper trading strategy based on results."""
    paper_history = get_paper_history()

    if paper_history["summary"].get("total_trades", 0) < MIN_PAPER_TRADES_FOR_STRATEGY:
        print(
            f"Need at least {MIN_PAPER_TRADES_FOR_STRATEGY} paper trades to update strategy. "
            f"Currently have {paper_history['summary'].get('total_trades', 0)}."
        )
        return

    current = read_text(PAPER_DIR / "strategy.md")
    if not current:
        current = INITIAL_PAPER_STRATEGY
        write_text(PAPER_DIR / "strategy.md", current)

    summary = paper_history["summary"]
    recent_trades = paper_history["trades"][-20:]

    # Load paper journal entries
    recent_journals = _load_paper_journals()

    # Format recent trades
    trade_lines = []
    for t in recent_trades:
        result_emoji = "W" if t.get("result") == "win" else "L"
        bet_type = t.get("bet_type", "moneyline")
        line_str = f" {t['line']}" if t.get("line") is not None else ""
        date = t.get("date", "?")
        trade_lines.append(
            f"- [{result_emoji}] {date} {t['matchup']}: {bet_type}{line_str} {t['pick']} "
            f"({t.get('confidence', 'low')}, {t.get('units', 0.5)}u) - "
            f"Skip reason: {t.get('skip_reason', 'unknown')}"
        )
    recent_trades_str = "\n".join(trade_lines) if trade_lines else "No recent trades."

    # Date context
    all_trades = paper_history["trades"]
    dates = sorted(t["date"] for t in all_trades if t.get("date"))
    today = datetime.now().strftime("%Y-%m-%d")
    if dates:
        span = (datetime.strptime(dates[-1], "%Y-%m-%d") - datetime.strptime(dates[0], "%Y-%m-%d")).days + 1
        date_context = f"Today: {today}. Data spans {dates[0]} to {dates[-1]} ({len(all_trades)} trades over {span} days)."
    else:
        date_context = f"Today: {today}."

    prompt = UPDATE_PAPER_STRATEGY_PROMPT.format(
        date_context=date_context,
        current_strategy=current,
        history_summary=format_paper_history_summary(summary),
        recent_trades=recent_trades_str,
        recent_journals=recent_journals,
        wins=summary.get("wins", 0),
        losses=summary.get("losses", 0),
        win_rate=summary.get("win_rate", 0.0),
        net_units=summary.get("net_units", 0.0),
    )

    result = await complete_json(prompt, system=SYSTEM_PAPER_ANALYST)
    if not result:
        print("Paper strategy analysis failed.")
        return

    # Persist insights for main strategy update (before early return)
    new_insights = result.get("insights_for_main_strategy", [])
    if new_insights:
        date_str = datetime.now().strftime("%Y-%m-%d")
        existing = get_paper_insights()
        entries = [{"date": date_str, "insight": i} for i in new_insights]
        save_paper_insights(entries + existing)
        print("Insights saved for main strategy:")
        for insight in new_insights:
            print(f"  * {insight}")

    required_keys = {"section", "updated_content", "change_description", "reasoning"}
    adjustments = [
        adj for adj in result.get("adjustments", [])
        if isinstance(adj, dict) and required_keys <= adj.keys()
    ]

    if not adjustments:
        print("No paper strategy adjustments needed.")
        return

    if len(adjustments) > MAX_PAPER_ADJUSTMENTS:
        adjustments = adjustments[:MAX_PAPER_ADJUSTMENTS]

    updated = apply_adjustments(current, adjustments)
    date_str = datetime.now().strftime("%Y-%m-%d")
    updated = append_change_log(updated, adjustments, date_str)
    write_text(PAPER_DIR / "strategy.md", updated)

    print(f"\nApplied {len(adjustments)} paper strategy adjustment(s):")
    for adj in adjustments:
        print(f"  - [{adj['section']}] {adj['change_description']}")


def _load_paper_journals(count: int = 10) -> str:
    """Load the last *count* paper journal entries by date."""
    files = sorted(PAPER_JOURNAL_DIR.glob("????-??-??.md"), reverse=True)[:count]
    entries = []
    for path in files:
        content = read_text(path)
        if content:
            entries.append(f"### {path.stem}\n{content}")
    return "\n\n".join(entries) if entries else "No recent paper journal entries."
