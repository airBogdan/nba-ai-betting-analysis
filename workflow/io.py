"""File I/O helpers for betting workflow."""

import json
from pathlib import Path
from typing import Any, List, Optional

from .types import ActiveBet, BetHistory

BETS_DIR = Path(__file__).parent.parent / "bets"
JOURNAL_DIR = BETS_DIR / "journal"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def ensure_dir(path: Path) -> None:
    """Create directory and parents if needed."""
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Optional[Any]:
    """Return None if file doesn't exist or is invalid."""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_json(path: Path, data: Any) -> None:
    """Create parent dirs if needed."""
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2))


def read_text(path: Path) -> Optional[str]:
    """Return None if file doesn't exist."""
    try:
        if not path.exists():
            return None
        return path.read_text()
    except OSError:
        return None


def write_text(path: Path, content: str) -> None:
    """Write text to file, creating parents if needed."""
    ensure_dir(path.parent)
    path.write_text(content)


def append_text(path: Path, content: str) -> None:
    """Append text to file, creating if needed."""
    ensure_dir(path.parent)
    with open(path, "a") as f:
        f.write(content)


def clear_output_dir() -> None:
    """Remove all files from the output directory."""
    if OUTPUT_DIR.exists():
        for file in OUTPUT_DIR.iterdir():
            if file.is_file():
                file.unlink()


def get_active_bets() -> List[ActiveBet]:
    """Load active bets from bets/active.json."""
    data = read_json(BETS_DIR / "active.json")
    if isinstance(data, list):
        return data
    return []


def save_active_bets(bets: List[ActiveBet]) -> None:
    """Save active bets to bets/active.json."""
    write_json(BETS_DIR / "active.json", bets)


def get_history() -> BetHistory:
    """Load bet history from bets/history.json."""
    data = read_json(BETS_DIR / "history.json")
    if isinstance(data, dict) and "bets" in data and "summary" in data:
        return data
    return {"bets": [], "summary": _empty_summary()}


def save_history(history: BetHistory) -> None:
    """Save bet history to bets/history.json."""
    write_json(BETS_DIR / "history.json", history)


def _empty_summary() -> dict:
    """Return an empty BetHistorySummary dict."""
    return {
        "total_bets": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "win_rate": 0.0,
        "total_units_wagered": 0.0,
        "net_units": 0.0,
        "roi": 0.0,
        "by_confidence": {},
        "by_primary_edge": {},
        "by_bet_type": {},
        "current_streak": "",
        "net_dollar_pnl": 0.0,
    }


def get_dollar_pnl() -> float:
    """Get total dollar P&L from all completed bets in history."""
    history = get_history()
    return sum(b.get("dollar_pnl", 0.0) for b in history["bets"])


def get_open_exposure() -> float:
    """Get total dollar amount committed in active bets."""
    active = get_active_bets()
    return sum(b.get("amount", 0.0) for b in active)

