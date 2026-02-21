"""Strategy update workflow."""

import collections
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .history import _categorize_edge
from .io import BETS_DIR, JOURNAL_DIR, get_history, get_paper_history, get_paper_insights, read_text, write_text
from .llm import complete_json
from .prompts import (
    MIN_ACTIONABLE_SAMPLE,
    SYSTEM_ANALYST,
    SYSTEM_PROPS_ANALYST,
    UPDATE_PROPS_STRATEGY_PROMPT,
    UPDATE_STRATEGY_PROMPT,
    format_history_summary,
    format_paper_trade_insights,
)

def _compute_summary(bets: List[dict]) -> Dict[str, Any]:
    """Compute a summary dict from a list of resolved bets.

    Produces the same shape that format_history_summary() expects,
    allowing filtered bet lists (e.g. game-only or props-only) to
    generate accurate, isolated summaries.
    """
    wins = sum(1 for b in bets if b.get("result") == "win")
    losses = sum(1 for b in bets if b.get("result") == "loss")
    pushes = sum(1 for b in bets if b.get("result") == "push")
    total = wins + losses + pushes
    decided = wins + losses
    win_rate = wins / decided if decided else 0.0
    net_units = sum(b.get("profit_loss", 0) for b in bets)
    total_wagered = sum(b.get("units", 0) for b in bets if b.get("result") in ("win", "loss"))
    roi = net_units / total_wagered if total_wagered else 0.0

    # Current streak
    streak = ""
    for b in reversed(bets):
        r = b.get("result")
        if r in ("win", "loss"):
            ch = "W" if r == "win" else "L"
            if not streak:
                streak = ch
            elif streak[0] == ch:
                streak += ch
            else:
                break
    streak = streak or "—"

    def _breakdown(key: str, categorize: bool = False) -> Dict[str, Dict[str, Any]]:
        groups: Dict[str, Dict[str, Any]] = {}
        for b in bets:
            val = b.get(key, "unknown")
            if categorize:
                val = _categorize_edge(val)
            if val not in groups:
                groups[val] = {"wins": 0, "losses": 0, "pushes": 0, "win_rate": 0.0}
            r = b.get("result")
            if r == "win":
                groups[val]["wins"] += 1
            elif r == "loss":
                groups[val]["losses"] += 1
            elif r == "push":
                groups[val]["pushes"] += 1
        for stats in groups.values():
            denom = stats["wins"] + stats["losses"]
            stats["win_rate"] = stats["wins"] / denom if denom else 0.0
        return groups

    return {
        "total_bets": total,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": win_rate,
        "net_units": net_units,
        "roi": roi,
        "current_streak": streak,
        "by_confidence": _breakdown("confidence"),
        "by_bet_type": _breakdown("bet_type"),
        "by_primary_edge": _breakdown("primary_edge", categorize=True),
    }


MIN_BETS_FOR_STRATEGY = 15
MAX_ADJUSTMENTS_PER_RUN = 3
MAX_CHANGE_LOG_ENTRIES = 10


def load_recent_journals(count: int = 10) -> str:
    """Load the last *count* journal entries by date."""
    files = sorted(JOURNAL_DIR.glob("????-??-??.md"), reverse=True)[:count]

    entries = []
    for path in files:
        date_str = path.stem
        content = read_text(path)
        if content:
            entries.append(f"### {date_str}\n{content}")

    if not entries:
        return "No recent journal entries."

    return "\n\n".join(entries)


def format_recent_bets(bets: List[dict]) -> str:
    """Format recent bets for the prompt."""
    if not bets:
        return "No completed bets yet."

    lines = []
    for bet in bets:
        result_emoji = "W" if bet["result"] == "win" else "L"
        bet_type = bet.get("bet_type", "moneyline")
        line_str = f" {bet['line']}" if bet.get("line") is not None else ""
        date = bet.get("date", "?")
        lines.append(
            f"- [{result_emoji}] {date} {bet['matchup']}: {bet_type}{line_str} {bet['pick']} "
            f"({bet['confidence']}, {bet['units']}u) - {bet['primary_edge']}"
        )
        if bet.get("reflection"):
            lines.append(f"  Reflection: {bet['reflection']}")

    return "\n".join(lines)


def aggregate_reflections(bets: List[dict]) -> str:
    """Aggregate structured reflections into a pattern summary."""
    bets_with_refs = [b for b in bets if b.get("structured_reflection")]
    if not bets_with_refs:
        return "No structured reflections available yet."

    refs = [b["structured_reflection"] for b in bets_with_refs]
    total = len(refs)
    edge_valid_count = sum(1 for r in refs if r.get("edge_valid"))
    edge_invalid_count = total - edge_valid_count

    # Process assessments
    assessments = collections.Counter(r.get("process_assessment", "sound") for r in refs)

    # Edge validity by edge type
    edge_by_type: Dict[str, Dict[str, int]] = collections.defaultdict(lambda: {"valid": 0, "invalid": 0})
    for b in bets_with_refs:
        edge_type = b.get("primary_edge", "unknown")
        if b["structured_reflection"].get("edge_valid"):
            edge_by_type[edge_type]["valid"] += 1
        else:
            edge_by_type[edge_type]["invalid"] += 1

    # Most common missed factors
    all_missed = []
    for r in refs:
        all_missed.extend(r.get("missed_factors", []))
    missed_counter = collections.Counter(all_missed)
    top_missed = missed_counter.most_common(5)

    # Last 5 key lessons
    lessons = [r["key_lesson"] for r in refs[-5:] if r.get("key_lesson")]

    lines = [
        f"## Reflection Patterns ({total} bets analyzed)",
    ]

    if total < MIN_ACTIONABLE_SAMPLE:
        lines.append(
            f"**Note: Only {total} reflections — patterns below are not yet "
            f"actionable (need {MIN_ACTIONABLE_SAMPLE}+)**"
        )

    lines.extend([
        f"- Edge validity: {edge_valid_count}/{total} ({edge_valid_count/total:.0%}) edges were valid",
        f"- Edge invalid: {edge_invalid_count}/{total}",
        "",
        "### Edge Validity by Type",
    ])
    for etype, counts in sorted(edge_by_type.items()):
        et = counts["valid"] + counts["invalid"]
        lines.append(f"- {etype}: {counts['valid']}/{et} valid ({counts['valid']/et:.0%})")

    lines.extend(["", "### Process Assessments"])
    for assessment, count in assessments.most_common():
        lines.append(f"- {assessment}: {count} ({count/total:.0%})")

    if top_missed:
        lines.append("")
        lines.append("### Most Common Missed Factors")
        for factor, count in top_missed:
            lines.append(f"- {factor} ({count}x)")

    if lessons:
        lines.append("")
        lines.append("### Recent Key Lessons")
        for lesson in lessons:
            lines.append(f"- {lesson}")

    return "\n".join(lines)


# --- Section parsing / rebuilding ---


def _parse_sections(text: str) -> List[Tuple[Optional[str], str]]:
    """Parse strategy.md into list of (header, content) tuples.

    The first tuple has header=None for the preamble (title line, etc.).
    Subsequent tuples correspond to ## sections.
    """
    sections: List[Tuple[Optional[str], str]] = []
    current_header: Optional[str] = None
    current_lines: List[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            sections.append((current_header, "\n".join(current_lines)))
            current_header = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    sections.append((current_header, "\n".join(current_lines)))
    return sections


def _rebuild_strategy(sections: List[Tuple[Optional[str], str]]) -> str:
    """Rebuild strategy text from parsed sections."""
    parts: List[str] = []
    for header, content in sections:
        if header is not None:
            parts.append(f"## {header}")
        parts.append(content)
    return "\n".join(parts)


def apply_adjustments(
    strategy_text: str, adjustments: List[Dict[str, str]]
) -> str:
    """Apply section-level adjustments to strategy text.

    Each adjustment replaces the content of a named ## section,
    or adds a new section if it doesn't exist.
    """
    sections = _parse_sections(strategy_text)

    for adj in adjustments:
        section_name = adj["section"]
        new_content = adj["updated_content"].strip()

        # Strip the ## header if the LLM included it
        header_line = f"## {section_name}"
        if new_content.startswith(header_line):
            new_content = new_content[len(header_line):].strip()

        # Find existing section
        found = False
        for i, (header, _content) in enumerate(sections):
            if header == section_name:
                sections[i] = (header, new_content.strip() + "\n")
                found = True
                break

        if not found:
            # Insert new section before Change Log, or at end
            insert_idx = len(sections)
            for i, (header, _) in enumerate(sections):
                if header == "Change Log":
                    insert_idx = i
                    break
            sections.insert(insert_idx, (section_name, new_content.strip() + "\n"))

    return _rebuild_strategy(sections)


def append_change_log(
    strategy_text: str, adjustments: List[Dict[str, str]], date_str: str
) -> str:
    """Append adjustment descriptions to a Change Log section in strategy text."""
    # Format new entry
    entry_lines = [f"### {date_str}"]
    for adj in adjustments:
        entry_lines.append(
            f"- **{adj['section']}**: {adj['change_description']}. "
            f"_{adj['reasoning']}_"
        )
    new_entry = "\n".join(entry_lines)

    sections = _parse_sections(strategy_text)

    # Find Change Log section
    log_idx = None
    for i, (header, _) in enumerate(sections):
        if header == "Change Log":
            log_idx = i
            break

    if log_idx is not None:
        existing = sections[log_idx][1].strip()
        if existing:
            # Split into dated entries, keep last (MAX - 1)
            entries = re.split(r"\n(?=### )", existing)
            entries = [e.strip() for e in entries if e.strip()]
            entries = entries[: MAX_CHANGE_LOG_ENTRIES - 1]
            updated_log = new_entry + "\n\n" + "\n\n".join(entries) + "\n"
        else:
            updated_log = new_entry + "\n"
        sections[log_idx] = ("Change Log", updated_log)
    else:
        sections.append(("Change Log", new_entry + "\n"))

    return _rebuild_strategy(sections)


# --- LLM integration ---


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


def format_recent_prop_bets(bets: List[dict]) -> str:
    """Format recent prop bets for the props strategy prompt."""
    if not bets:
        return "No completed prop bets yet."

    lines = []
    for bet in bets:
        result_emoji = "W" if bet["result"] == "win" else "L"
        player = bet.get("player_name", "?")
        prop_type = bet.get("prop_type", "?")
        line = bet.get("line", "?")
        pick = bet.get("pick", "?")
        date = bet.get("date", "?")
        lines.append(
            f"- [{result_emoji}] {date} {bet.get('matchup', '?')}: {player} {prop_type} "
            f"{pick} {line} ({bet.get('confidence', '?')}, {bet.get('units', '?')}u) "
            f"- {bet.get('primary_edge', '?')}"
        )
        if bet.get("reflection"):
            lines.append(f"  Reflection: {bet['reflection']}")

    return "\n".join(lines)


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


async def run_strategy_workflow() -> None:
    """Run the strategy update workflow."""
    history = get_history()

    if history["summary"]["total_bets"] < MIN_BETS_FOR_STRATEGY:
        print(
            f"Need at least {MIN_BETS_FOR_STRATEGY} completed bets to update strategy. "
            f"Currently have {history['summary']['total_bets']}."
        )
        return

    # --- Game-level strategy pass ---
    current = read_text(BETS_DIR / "strategy.md")
    if not current:
        print("No strategy.md found. Run 'betting.py init' first.")
    else:
        print("Loading context...")
        game_bets = [b for b in history["bets"] if b.get("bet_type") != "player_prop"]
        recent_bets = game_bets[-20:]
        recent_journals = load_recent_journals()

        print("Analyzing performance for adjustments...")
        result = await generate_adjustments(
            current, game_bets, recent_bets, recent_journals
        )

        if result is None:
            print("Strategy analysis failed. Check LLM errors above.")
        else:
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
            else:
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

                # Apply adjustments to existing strategy
                updated = apply_adjustments(current, adjustments)

                # Append change log entry
                date_str = datetime.now().strftime("%Y-%m-%d")
                updated = append_change_log(updated, adjustments, date_str)

                write_text(BETS_DIR / "strategy.md", updated)

                print(f"\nApplied {len(adjustments)} adjustment(s):")
                for adj in adjustments:
                    print(f"  - [{adj['section']}] {adj['change_description']}")

                if result.get("summary"):
                    print(f"\n{result['summary']}")

    # --- Props strategy pass ---
    await _update_props_strategy(history["bets"])