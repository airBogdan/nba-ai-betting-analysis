"""Strategy update workflow."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from .io import BETS_DIR, get_history, get_paper_history, get_paper_insights, read_text, write_text
from .llm import complete_json
from .prompts import (
    SYSTEM_ANALYST,
    SYSTEM_PROPS_ANALYST,
    UPDATE_PROPS_STRATEGY_PROMPT,
    UPDATE_STRATEGY_PROMPT,
    format_history_summary,
    format_paper_trade_insights,
)
from .strategy_format import (
    _compute_summary,
    aggregate_reflections,
    format_recent_bets,
    format_recent_prop_bets,
    load_recent_journals,
)
from .strategy_sections import (
    MAX_CHANGE_LOG_ENTRIES,
    apply_adjustments,
    append_change_log,
)

MIN_BETS_FOR_STRATEGY = 15
MAX_ADJUSTMENTS_PER_RUN = 3


def _build_date_context(all_bets: List[dict]) -> str:
    """Build a date context line from the bet history."""
    today = datetime.now().strftime("%Y-%m-%d")
    dates = sorted(b["date"] for b in all_bets if b.get("date"))
    if not dates:
        return f"Today: {today}. No bet dates available."
    first, last = dates[0], dates[-1]
    span = (datetime.strptime(last, "%Y-%m-%d") - datetime.strptime(first, "%Y-%m-%d")).days + 1
    return (
        f"Today: {today}. Data spans {first} to {last} "
        f"({len(all_bets)} bets over {span} days). "
        f"Be cautious about codifying patterns from short windows or unusual conditions "
        f"(e.g. trade deadline, All-Star break, injury waves)."
    )


async def generate_adjustments(
    current: str,
    all_bets: List[dict],
    recent_bets: List[dict],
    recent_journals: str,
) -> Optional[Dict[str, Any]]:
    """Generate targeted adjustments via LLM. Returns parsed JSON or None."""
    summary = _compute_summary(all_bets)
    reflection_patterns = aggregate_reflections(recent_bets)

    paper_history = get_paper_history()
    paper_insights = format_paper_trade_insights(paper_history["summary"])

    # Append persisted insights from paper strategy reviews
    saved_insights = get_paper_insights()
    if saved_insights:
        lines = ["\nActionable insights from paper trading analysis:"]
        for entry in saved_insights:
            lines.append(f"- [{entry['date']}] {entry['insight']}")
        paper_insights += "\n".join(lines)

    prompt = UPDATE_STRATEGY_PROMPT.format(
        date_context=_build_date_context(all_bets),
        current_strategy=current,
        history_summary=format_history_summary(summary),
        recent_bets=format_recent_bets(recent_bets),
        recent_journals=recent_journals,
        reflection_patterns=reflection_patterns,
        paper_trade_insights=paper_insights,
        wins=summary["wins"],
        losses=summary["losses"],
        roi=round(summary["roi"] * 100, 1),
    )

    return await complete_json(prompt, system=SYSTEM_ANALYST)


async def generate_props_adjustments(
    current: str,
    prop_bets: List[dict],
) -> Optional[Dict[str, Any]]:
    """Generate targeted adjustments for props strategy via LLM."""
    summary = _compute_summary(prop_bets)

    prompt = UPDATE_PROPS_STRATEGY_PROMPT.format(
        date_context=_build_date_context(prop_bets),
        current_strategy=current,
        history_summary=format_history_summary(summary),
        recent_bets=format_recent_prop_bets(prop_bets[-20:]),
        wins=summary["wins"],
        losses=summary["losses"],
        roi=round(summary["roi"] * 100, 1),
    )

    return await complete_json(prompt, system=SYSTEM_PROPS_ANALYST)


async def _update_props_strategy(all_bets: List[dict]) -> None:
    """Run the props strategy update pass."""
    prop_bets = [b for b in all_bets if b.get("bet_type") == "player_prop"]

    if len(prop_bets) < MIN_BETS_FOR_STRATEGY:
        print(
            f"\nProps strategy: need {MIN_BETS_FOR_STRATEGY} completed prop bets "
            f"(have {len(prop_bets)}). Skipping."
        )
        return

    current = read_text(BETS_DIR / "props_strategy.md")
    if not current:
        print("\nNo props_strategy.md found. Run 'betting.py init' first.")
        return

    print("\nAnalyzing prop bet performance for adjustments...")
    result = await generate_props_adjustments(current, prop_bets)

    if result is None:
        print("Props strategy analysis failed.")
        return

    required_keys = {"section", "updated_content", "change_description", "reasoning"}
    adjustments = [
        adj
        for adj in result.get("adjustments", [])
        if isinstance(adj, dict) and required_keys <= adj.keys()
    ]

    if not adjustments:
        print("No props strategy adjustments needed.")
        for reason in result.get("no_change_reasons", []):
            print(f"  - {reason}")
        return

    if len(adjustments) > MAX_ADJUSTMENTS_PER_RUN:
        adjustments = adjustments[:MAX_ADJUSTMENTS_PER_RUN]

    # Archive previous props strategy
    versions_dir = BETS_DIR / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    (versions_dir / f"props_strategy_{ts}.md").write_text(current)
    for old in sorted(versions_dir.glob("props_strategy_*.md"), reverse=True)[10:]:
        old.unlink()
    print(f"  Archived → versions/props_strategy_{ts}.md")

    updated = apply_adjustments(current, adjustments)
    date_str = datetime.now().strftime("%Y-%m-%d")
    updated = append_change_log(updated, adjustments, date_str)
    write_text(BETS_DIR / "props_strategy.md", updated)

    print(f"\nApplied {len(adjustments)} props adjustment(s):")
    for adj in adjustments:
        print(f"  - [{adj['section']}] {adj['change_description']}")

    if result.get("summary"):
        print(f"\n{result['summary']}")


async def _update_game_strategy(history_bets: List[dict]) -> None:
    current = read_text(BETS_DIR / "strategy.md")
    if not current:
        print("No strategy.md found. Run 'betting.py init' first.")
        return

    print("Loading context...")
    game_bets = [b for b in history_bets if b.get("bet_type") != "player_prop"]
    recent_bets = game_bets[-20:]
    recent_journals = load_recent_journals()

    print("Analyzing performance for adjustments...")
    result = await generate_adjustments(
        current, game_bets, recent_bets, recent_journals
    )

    if result is None:
        print("Strategy analysis failed. Check LLM errors above.")
        return

    required_keys = {"section", "updated_content", "change_description", "reasoning"}
    adjustments = [
        adj
        for adj in result.get("adjustments", [])
        if isinstance(adj, dict) and required_keys <= adj.keys()
    ]

    if not adjustments:
        print("No adjustments needed based on current data.")
        for reason in result.get("no_change_reasons", []):
            print(f"  - {reason}")
        return

    if len(adjustments) > MAX_ADJUSTMENTS_PER_RUN:
        print(
            f"LLM proposed {len(adjustments)} adjustments "
            f"(max {MAX_ADJUSTMENTS_PER_RUN}). Taking first {MAX_ADJUSTMENTS_PER_RUN}."
        )
        adjustments = adjustments[:MAX_ADJUSTMENTS_PER_RUN]

    # Archive previous strategy
    versions_dir = BETS_DIR / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    (versions_dir / f"strategy_{ts}.md").write_text(current)
    for old in sorted(versions_dir.glob("strategy_*.md"), reverse=True)[10:]:
        old.unlink()
    print(f"  Archived → versions/strategy_{ts}.md")

    updated = apply_adjustments(current, adjustments)
    date_str = datetime.now().strftime("%Y-%m-%d")
    updated = append_change_log(updated, adjustments, date_str)
    write_text(BETS_DIR / "strategy.md", updated)

    print(f"\nApplied {len(adjustments)} adjustment(s):")
    for adj in adjustments:
        print(f"  - [{adj['section']}] {adj['change_description']}")

    if result.get("summary"):
        print(f"\n{result['summary']}")


async def run_strategy_workflow() -> None:
    """Run the strategy update workflow."""
    history = get_history()

    if history["summary"]["total_bets"] < MIN_BETS_FOR_STRATEGY:
        print(
            f"Need at least {MIN_BETS_FOR_STRATEGY} completed bets to update strategy. "
            f"Currently have {history['summary']['total_bets']}."
        )
        return

    await _update_game_strategy(history["bets"])
    await _update_props_strategy(history["bets"])
