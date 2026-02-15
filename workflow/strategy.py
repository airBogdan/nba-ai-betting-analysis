"""Strategy update workflow."""

import collections
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .io import BETS_DIR, JOURNAL_DIR, get_history, get_paper_history, read_text, write_text
from .llm import complete_json
from .prompts import (
    MIN_ACTIONABLE_SAMPLE,
    SYSTEM_ANALYST,
    UPDATE_STRATEGY_PROMPT,
    format_history_summary,
    format_paper_trade_insights,
)

MIN_BETS_FOR_STRATEGY = 15
MAX_ADJUSTMENTS_PER_RUN = 3
MAX_CHANGE_LOG_ENTRIES = 10


def load_recent_journals(days: int = 7) -> str:
    """Load journal entries from the last N days."""
    entries = []
    today = datetime.now()

    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        journal_path = JOURNAL_DIR / f"{date_str}.md"

        content = read_text(journal_path)
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
        lines.append(
            f"- [{result_emoji}] {bet['matchup']}: {bet['pick']} "
            f"({bet['confidence']}, {bet['units']}u) - {bet['primary_edge']}"
        )
        if bet.get("reflection"):
            lines.append(f"  Reflection: {bet['reflection']}")

    return "\n".join(lines)


def aggregate_reflections(bets: List[dict]) -> str:
    """Aggregate structured reflections into a pattern summary."""
    refs = [b["structured_reflection"] for b in bets if b.get("structured_reflection")]
    if not refs:
        return "No structured reflections available yet."

    total = len(refs)
    edge_valid_count = sum(1 for r in refs if r.get("edge_valid"))
    edge_invalid_count = total - edge_valid_count

    # Process assessments
    assessments = collections.Counter(r.get("process_assessment", "sound") for r in refs)

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
        "### Process Assessments",
    ])
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


async def generate_adjustments(
    current: str,
    summary: dict,
    recent_bets: List[dict],
    recent_journals: str,
) -> Optional[Dict[str, Any]]:
    """Generate targeted adjustments via LLM. Returns parsed JSON or None."""
    reflection_patterns = aggregate_reflections(recent_bets)

    paper_history = get_paper_history()
    paper_insights = format_paper_trade_insights(paper_history["summary"])

    prompt = UPDATE_STRATEGY_PROMPT.format(
        current_strategy=current,
        history_summary=format_history_summary(summary),
        recent_bets=format_recent_bets(recent_bets),
        recent_journals=recent_journals,
        reflection_patterns=reflection_patterns,
        paper_trade_insights=paper_insights,
        wins=summary.get("wins", 0),
        losses=summary.get("losses", 0),
        roi=round(summary.get("roi", 0) * 100, 1),
    )

    return await complete_json(prompt, system=SYSTEM_ANALYST)


async def run_strategy_workflow() -> None:
    """Run the strategy update workflow."""
    history = get_history()

    if history["summary"]["total_bets"] < MIN_BETS_FOR_STRATEGY:
        print(
            f"Need at least {MIN_BETS_FOR_STRATEGY} completed bets to update strategy. "
            f"Currently have {history['summary']['total_bets']}."
        )
        return

    current = read_text(BETS_DIR / "strategy.md")
    if not current:
        print("No strategy.md found. Run 'betting.py init' first.")
        return

    print("Loading context...")
    recent_bets = history["bets"][-20:]
    recent_journals = load_recent_journals(days=7)

    print("Analyzing performance for adjustments...")
    result = await generate_adjustments(
        current, history["summary"], recent_bets, recent_journals
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