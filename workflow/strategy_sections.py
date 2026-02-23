"""Section parsing and manipulation for strategy markdown files."""

import re
from typing import Dict, List, Optional, Tuple

MAX_CHANGE_LOG_ENTRIES = 10


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
