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
    """Load active bets from SQLite database."""
    from .db import get_active_bets_db

    return get_active_bets_db()


def save_active_bets(bets: List[ActiveBet]) -> None:
    """Save active bets to SQLite database."""
    from .db import save_active_bets_db

    save_active_bets_db(bets)


def get_history() -> BetHistory:
    """Load bet history from SQLite database."""
    from .db import get_history as db_get_history

    return db_get_history()


