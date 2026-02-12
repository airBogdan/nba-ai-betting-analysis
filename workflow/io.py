"""File I/O helpers for betting workflow."""

import json
from pathlib import Path
from typing import Any, List, Optional

from .types import ActiveBet, Bankroll, BetHistory

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
    """Load active.json, return empty list if missing."""
    data = read_json(BETS_DIR / "active.json")
    if data is None:
        return []
    return data


def save_active_bets(bets: List[ActiveBet]) -> None:
    """Save active bets to active.json."""
    write_json(BETS_DIR / "active.json", bets)



def get_history() -> BetHistory:
    """Load bet history from SQLite database."""
    from .db import get_history as db_get_history

    return db_get_history()


def get_bankroll() -> Bankroll:
    """Load bankroll.json, create with $1000 if missing."""
    data = read_json(BETS_DIR / "bankroll.json")
    if data is None:
        return {
            "starting": 1000.0,
            "current": 1000.0,
            "transactions": [],
        }
    return data


def save_bankroll(bankroll: Bankroll) -> None:
    """Save bankroll to bankroll.json."""
    write_json(BETS_DIR / "bankroll.json", bankroll)


def revert_bankroll_for_date(bankroll: Bankroll, date: str) -> Bankroll:
    """Revert all transactions for a specific date (for --force re-analysis)."""
    # Find transactions for this date
    date_txns = [t for t in bankroll["transactions"] if t["date"] == date]
    other_txns = [t for t in bankroll["transactions"] if t["date"] != date]

    # Reverse the amounts
    reverted_amount = sum(t["amount"] for t in date_txns)
    bankroll["current"] -= reverted_amount  # Undo the transactions
    bankroll["transactions"] = other_txns

    return bankroll
