"""Bet creation, normalization, and journal writing."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..io import JOURNAL_DIR, write_text
from ..types import ActiveBet, SelectedBet

VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_BET_TYPES = {"moneyline", "spread", "total", "player_prop"}
CONFIDENCE_TO_UNITS = {"low": 0.5, "medium": 1.0, "high": 2.0}
VALID_PROP_TYPES = {"points", "rebounds", "assists"}


def _normalize_confidence(raw: str) -> str:
    """Normalize confidence value to valid enum."""
    if raw in VALID_CONFIDENCE:
        return raw
    # Try to infer from common variations
    raw_lower = raw.lower() if raw else ""
    if "high" in raw_lower or "strong" in raw_lower:
        return "high"
    if "med" in raw_lower or "moderate" in raw_lower:
        return "medium"
    return "low"


def _normalize_bet_type(raw: str) -> str:
    """Normalize bet type to valid enum."""
    if raw in VALID_BET_TYPES:
        return raw
    raw_lower = raw.lower() if raw else ""
    if "spread" in raw_lower:
        return "spread"
    if "total" in raw_lower or "over" in raw_lower or "under" in raw_lower:
        return "total"
    return "moneyline"


def _normalize_units(raw_units: float, confidence: str) -> float:
    """Normalize units to valid values based on confidence."""
    if raw_units in (0.5, 1.0, 2.0):
        return raw_units
    # Fall back to confidence-based units
    return CONFIDENCE_TO_UNITS.get(confidence, 0.5)


def create_active_bet(selected: SelectedBet, date: str) -> ActiveBet:
    """Create an ActiveBet from a SelectedBet."""
    raw_confidence = selected.get("confidence", "low")
    confidence = _normalize_confidence(raw_confidence)
    units = _normalize_units(selected.get("units", 0.5), confidence)
    bet_type = _normalize_bet_type(selected.get("bet_type", "moneyline"))

    return {
        "id": str(uuid.uuid4()),
        "game_id": selected.get("game_id", "unknown"),
        "matchup": selected.get("matchup", "Unknown @ Unknown"),
        "bet_type": bet_type,
        "pick": selected.get("pick", "Unknown"),
        "line": selected.get("line"),
        "confidence": confidence,
        "units": units,
        "reasoning": selected.get("reasoning", "No reasoning provided"),
        "primary_edge": selected.get("primary_edge", "Unknown"),
        "date": date,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_prop_pick(raw: str) -> Optional[str]:
    """Normalize LLM-generated over/under pick to canonical form.

    Returns "over", "under", or None if unrecognizable.
    """
    val = raw.lower().strip()
    if val in ("over", "yes", "o"):
        return "over"
    if val in ("under", "no", "u"):
        return "under"
    return None


def create_prop_bet(selected: dict, date: str) -> Optional[ActiveBet]:
    """Create an ActiveBet for a player prop from a synthesis selection.

    Returns None if the pick value is unrecognizable or prop type is unsupported.
    """
    prop_type = selected.get("prop_type", "")
    if prop_type not in VALID_PROP_TYPES:
        print(f"  Skipping prop with unsupported type: {prop_type!r}")
        return None

    pick = _normalize_prop_pick(selected.get("pick", ""))
    if pick is None:
        print(f"  Skipping prop with unrecognized pick: {selected.get('pick')!r}")
        return None

    raw_confidence = selected.get("confidence", "low")
    confidence = _normalize_confidence(raw_confidence)
    units = _normalize_units(selected.get("units", 0.5), confidence)

    bet: ActiveBet = {
        "id": str(uuid.uuid4()),
        "game_id": selected.get("game_id", "unknown"),
        "matchup": selected.get("matchup", "Unknown @ Unknown"),
        "bet_type": "player_prop",
        "pick": pick,
        "line": selected.get("line"),
        "confidence": confidence,
        "units": units,
        "reasoning": selected.get("reasoning", "No reasoning provided"),
        "primary_edge": selected.get("primary_edge", "Unknown"),
        "date": date,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prop_type": selected.get("prop_type", "points"),
        "player_name": selected.get("player_name", "Unknown"),
    }
    return bet


def write_journal_pre_game(
    date: str,
    selected: List[ActiveBet],
    skipped: List[Dict[str, str]],
    summary: str,
) -> None:
    """Write pre-game section to daily journal."""
    journal_path = JOURNAL_DIR / f"{date}.md"

    lines = [
        f"# NBA Betting Journal - {date}",
        "",
        "## Pre-Game Analysis",
        "",
        summary,
        "",
    ]

    if selected:
        lines.append("### Selected Bets")
        lines.append("")

        # Show total wagered if amounts are present
        total_wagered = sum(b.get("amount", 0) for b in selected)
        if total_wagered > 0:
            lines.append(f"**Total wagered: ${total_wagered:.2f}**")
            lines.append("")

        for bet in selected:
            bet_type = bet.get('bet_type', 'moneyline')
            pick = bet.get('pick', 'Unknown')
            line = bet.get('line')

            # Format the pick display based on bet type
            if bet_type == "player_prop":
                player = bet.get('player_name', '?')
                prop = bet.get('prop_type', '?')
                pick_display = f"{player} {prop} {pick} {line}" if line else f"{player} {prop} {pick}"
            elif bet_type == "spread" and line is not None:
                pick_display = f"{pick} {line:+.1f}"
            elif bet_type == "total" and line is not None:
                pick_display = f"{pick} {line:.1f}"
            else:
                pick_display = pick

            lines.append(f"**{bet.get('matchup', 'Unknown')}** - {bet_type.upper()}")
            lines.append(f"- Pick: {pick_display} ({bet.get('confidence', 'unknown')} confidence)")
            # Show amount if present, otherwise show units
            amount = bet.get('amount')
            if amount:
                lines.append(f"- Amount: ${amount:.2f}")
            else:
                lines.append(f"- Units: {bet.get('units', '?')}")
            lines.append(f"- Edge: {bet.get('primary_edge', 'Unknown')}")
            lines.append(f"- Reasoning: {bet.get('reasoning', 'No reasoning provided')}")
            lines.append("")
    else:
        lines.append("*No bets selected today.*")
        lines.append("")

    if skipped:
        lines.append("### Skipped Games")
        lines.append("")
        for skip in skipped:
            lines.append(f"- {skip.get('matchup', 'Unknown')}: {skip.get('reason', 'No clear edge')}")
        lines.append("")

    lines.append("---")
    lines.append("")

    write_text(journal_path, "\n".join(lines))
