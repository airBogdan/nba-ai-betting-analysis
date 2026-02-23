"""Formatting helpers for strategy workflow."""

import collections
from typing import Any, Dict, List

from .history import _categorize_edge
from .io import JOURNAL_DIR, read_text
from .prompts import MIN_ACTIONABLE_SAMPLE


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
