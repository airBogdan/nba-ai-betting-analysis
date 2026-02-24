"""File I/O helpers for betting workflow."""

import json
from pathlib import Path
from typing import Any, List, Optional

from .types import ActiveBet, BetHistory

BETS_DIR = Path(__file__).parent.parent / "bets"
JOURNAL_DIR = BETS_DIR / "journal"
PAPER_DIR = BETS_DIR / "paper"
PAPER_JOURNAL_DIR = PAPER_DIR / "journal"
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
    """Get total dollar amount committed in active bets not yet placed on Polymarket.

    Bets already placed on-chain have already debited the wallet balance,
    so counting them here would double-subtract from available funds.
    """
    active = get_active_bets()
    return sum(b.get("amount", 0.0) for b in active if not b.get("placed_polymarket"))


VOIDS_PATH = BETS_DIR / "voids.json"


def get_voids() -> List[dict]:
    """Load voided bets from bets/voids.json."""
    data = read_json(VOIDS_PATH)
    return data if isinstance(data, list) else []


def save_void(bet: dict, reason: str) -> None:
    """Append a voided bet to bets/voids.json."""
    voids = get_voids()
    entry = {**bet, "void_reason": reason}
    voids.append(entry)
    write_json(VOIDS_PATH, voids)


SKIPS_PATH = BETS_DIR / "skips.json"


def get_skips() -> List[dict]:
    """Load skipped games from bets/skips.json."""
    data = read_json(SKIPS_PATH)
    return data if isinstance(data, list) else []


def save_skips_all(skips: List[dict]) -> None:
    """Save all skips to bets/skips.json."""
    write_json(SKIPS_PATH, skips)


def save_skips(date: str, new_skips: List[dict]) -> None:
    """Append skips for a date, replacing any existing for that date (supports --force)."""
    all_skips = get_skips()
    all_skips = [s for s in all_skips if s.get("date") != date]
    all_skips.extend(new_skips)
    save_skips_all(all_skips)


# --- Paper trading IO ---


def get_paper_trades() -> list:
    """Load paper trades from bets/paper/trades.json."""
    data = read_json(PAPER_DIR / "trades.json")
    return data if isinstance(data, list) else []


def save_paper_trades(trades: list) -> None:
    """Save paper trades to bets/paper/trades.json."""
    write_json(PAPER_DIR / "trades.json", trades)


def get_paper_history() -> dict:
    """Load paper trade history from bets/paper/history.json."""
    data = read_json(PAPER_DIR / "history.json")
    if isinstance(data, dict) and "trades" in data and "summary" in data:
        return data
    return {"trades": [], "summary": _empty_paper_summary()}


def save_paper_history(history: dict) -> None:
    """Save paper trade history to bets/paper/history.json."""
    write_json(PAPER_DIR / "history.json", history)


MAX_PAPER_INSIGHTS = 10

PAPER_INSIGHTS_PATH = PAPER_DIR / "insights.json"


def get_paper_insights() -> list:
    """Load paper trading insights for main strategy."""
    data = read_json(PAPER_INSIGHTS_PATH)
    return data if isinstance(data, list) else []


def save_paper_insights(insights: list) -> None:
    """Save paper trading insights, keeping the most recent entries."""
    write_json(PAPER_INSIGHTS_PATH, insights[:MAX_PAPER_INSIGHTS])


def _empty_paper_summary() -> dict:
    """Return an empty PaperHistorySummary dict."""
    return {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "win_rate": 0.0,
        "net_units": 0.0,
        "by_confidence": {},
        "by_bet_type": {},
        "by_skip_reason_category": {},
    }

