"""SQLite storage for completed bets and active bets."""

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from .types import ActiveBet, BetHistory, BetHistorySummary, CompletedBet

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "nba.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS completed_bets (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    matchup TEXT NOT NULL,
    bet_type TEXT NOT NULL DEFAULT 'moneyline',
    pick TEXT NOT NULL,
    line REAL,
    confidence TEXT NOT NULL,
    units REAL NOT NULL,
    reasoning TEXT NOT NULL,
    primary_edge TEXT NOT NULL,
    edge_category TEXT NOT NULL,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result TEXT NOT NULL,
    winner TEXT NOT NULL,
    final_score TEXT NOT NULL,
    actual_total INTEGER,
    actual_margin INTEGER,
    profit_loss REAL NOT NULL,
    reflection TEXT NOT NULL DEFAULT '',
    amount REAL,
    odds_price INTEGER,
    poly_price REAL,
    structured_reflection TEXT,
    dollar_pnl REAL
);

CREATE INDEX IF NOT EXISTS idx_date ON completed_bets(date);
CREATE INDEX IF NOT EXISTS idx_result ON completed_bets(result);
CREATE INDEX IF NOT EXISTS idx_edge_category ON completed_bets(edge_category);
CREATE INDEX IF NOT EXISTS idx_bet_type ON completed_bets(bet_type);
CREATE INDEX IF NOT EXISTS idx_confidence ON completed_bets(confidence);

CREATE TABLE IF NOT EXISTS active_bets (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    matchup TEXT NOT NULL,
    bet_type TEXT NOT NULL DEFAULT 'moneyline',
    pick TEXT NOT NULL,
    line REAL,
    confidence TEXT NOT NULL,
    units REAL NOT NULL,
    reasoning TEXT NOT NULL,
    primary_edge TEXT NOT NULL,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    amount REAL,
    odds_price INTEGER,
    poly_price REAL,
    placed_polymarket INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_active_date ON active_bets(date);
"""


def _categorize_edge(edge: str) -> str:
    """Normalize edge description to a category for tracking."""
    edge_lower = edge.lower()

    if any(w in edge_lower for w in ["home", "home court", "home advantage"]):
        return "home_court"
    if any(w in edge_lower for w in ["rest", "fatigue", "back-to-back", "b2b", "tired"]):
        return "rest_advantage"
    if any(w in edge_lower for w in ["injury", "injured", "missing", "out", "questionable"]):
        return "injury_edge"
    if any(w in edge_lower for w in ["form", "streak", "momentum", "hot", "cold", "recent"]):
        return "form_momentum"
    if any(w in edge_lower for w in ["h2h", "head-to-head", "matchup history"]):
        return "h2h_history"
    if any(w in edge_lower for w in ["rating", "net rating", "offensive", "defensive", "efficiency"]):
        return "ratings_edge"
    if any(w in edge_lower for w in ["mismatch", "size", "pace", "style"]):
        return "style_mismatch"
    if any(w in edge_lower for w in ["total", "over", "under", "scoring"]):
        return "totals_edge"

    return edge[:25] if len(edge) > 25 else edge


def _maybe_add_dollar_pnl(conn: sqlite3.Connection) -> None:
    """Add dollar_pnl column to completed_bets if missing (existing DB migration)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(completed_bets)").fetchall()}
    if "dollar_pnl" in cols:
        return
    conn.execute("ALTER TABLE completed_bets ADD COLUMN dollar_pnl REAL")
    conn.execute("""
        UPDATE completed_bets SET dollar_pnl = CASE
            WHEN result = 'loss' THEN ROUND(-amount, 2)
            WHEN result = 'push' THEN 0.0
            WHEN result = 'win' AND odds_price < 0 THEN ROUND(amount * 100.0 / ABS(odds_price), 2)
            WHEN result = 'win' AND odds_price > 0 THEN ROUND(amount * odds_price / 100.0, 2)
            WHEN result = 'win' THEN ROUND(amount * 100.0 / 110, 2)
        END
        WHERE amount IS NOT NULL AND odds_price IS NOT NULL AND dollar_pnl IS NULL
    """)
    conn.commit()


def _get_conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get a connection with WAL mode, auto-create schema, auto-migrate."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _maybe_add_dollar_pnl(conn)
    # When using a custom db_path (tests), look for JSON in same dir as DB
    json_path = (path.parent / "history.json") if db_path else None
    _maybe_migrate_json(conn, path, json_path)
    active_json = (path.parent / "active.json") if db_path else None
    _maybe_migrate_active_json(conn, active_json)
    return conn


def _maybe_migrate_active_json(conn: sqlite3.Connection, json_path: Optional[Path] = None) -> None:
    """Import active.json if it exists, then rename to .migrated.

    Unlike completed_bets (which only grow), active_bets can become empty
    when all bets resolve. We rename the JSON after migration to prevent
    re-importing stale data when the table is legitimately empty.
    """
    if json_path is None:
        json_path = Path(__file__).parent.parent / "bets" / "active.json"
    if not json_path.exists():
        return

    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return

    if isinstance(data, list) and data:
        for bet in data:
            _insert_active_row(conn, bet)
        conn.commit()

    # Rename regardless of content to prevent future re-migration attempts
    json_path.rename(json_path.with_suffix(".json.migrated"))


def _maybe_migrate_json(conn: sqlite3.Connection, db_path: Path, json_path: Optional[Path] = None) -> None:
    """Import history.json if DB is empty and JSON exists."""
    count = conn.execute("SELECT COUNT(*) FROM completed_bets").fetchone()[0]
    if count > 0:
        return

    if json_path is None:
        json_path = Path(__file__).parent.parent / "bets" / "history.json"
    if not json_path.exists():
        return

    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return

    bets = data.get("bets", [])
    if not bets:
        return

    for bet in bets:
        _insert_bet_row(conn, bet)
    conn.commit()


def _insert_bet_row(conn: sqlite3.Connection, bet: CompletedBet) -> None:
    """Insert a single bet row."""
    bet_type = bet.get("bet_type", "moneyline")
    edge_category = _categorize_edge(bet["primary_edge"])
    structured_ref = bet.get("structured_reflection")
    structured_json = json.dumps(structured_ref) if structured_ref else None

    conn.execute(
        """INSERT OR IGNORE INTO completed_bets
        (id, game_id, matchup, bet_type, pick, line, confidence, units,
         reasoning, primary_edge, edge_category, date, created_at,
         result, winner, final_score, actual_total, actual_margin,
         profit_loss, reflection, amount, odds_price, poly_price,
         structured_reflection, dollar_pnl)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            bet["id"],
            bet["game_id"],
            bet["matchup"],
            bet_type,
            bet["pick"],
            bet.get("line"),
            bet["confidence"],
            bet["units"],
            bet["reasoning"],
            bet["primary_edge"],
            edge_category,
            bet["date"],
            bet["created_at"],
            bet["result"],
            bet["winner"],
            bet["final_score"],
            bet.get("actual_total"),
            bet.get("actual_margin"),
            bet["profit_loss"],
            bet.get("reflection", ""),
            bet.get("amount"),
            bet.get("odds_price"),
            bet.get("poly_price"),
            structured_json,
            bet.get("dollar_pnl"),
        ),
    )


def insert_bet(bet: CompletedBet, db_path: Optional[Path] = None) -> None:
    """Insert a completed bet into the database."""
    conn = _get_conn(db_path)
    try:
        _insert_bet_row(conn, bet)
        conn.commit()
    finally:
        conn.close()


def _row_to_bet(row: sqlite3.Row) -> CompletedBet:
    """Convert a database row to CompletedBet dict."""
    bet: CompletedBet = {
        "id": row["id"],
        "game_id": row["game_id"],
        "matchup": row["matchup"],
        "bet_type": row["bet_type"],
        "pick": row["pick"],
        "line": row["line"],
        "confidence": row["confidence"],
        "units": row["units"],
        "reasoning": row["reasoning"],
        "primary_edge": row["primary_edge"],
        "date": row["date"],
        "created_at": row["created_at"],
        "result": row["result"],
        "winner": row["winner"],
        "final_score": row["final_score"],
        "actual_total": row["actual_total"],
        "actual_margin": row["actual_margin"],
        "profit_loss": row["profit_loss"],
        "reflection": row["reflection"],
    }
    # Optional fields
    if row["amount"] is not None:
        bet["amount"] = row["amount"]
    if row["odds_price"] is not None:
        bet["odds_price"] = row["odds_price"]
    if row["poly_price"] is not None:
        bet["poly_price"] = row["poly_price"]
    if row["structured_reflection"]:
        bet["structured_reflection"] = json.loads(row["structured_reflection"])
    if row["dollar_pnl"] is not None:
        bet["dollar_pnl"] = row["dollar_pnl"]
    return bet


def get_all_bets(db_path: Optional[Path] = None) -> List[CompletedBet]:
    """Get all bets ordered by date, created_at."""
    conn = _get_conn(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM completed_bets ORDER BY date, created_at"
        ).fetchall()
        return [_row_to_bet(row) for row in rows]
    finally:
        conn.close()


def get_recent_bets(n: int = 20, db_path: Optional[Path] = None) -> List[CompletedBet]:
    """Get most recent n bets."""
    conn = _get_conn(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM completed_bets ORDER BY date DESC, created_at DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [_row_to_bet(row) for row in reversed(rows)]
    finally:
        conn.close()


def get_dollar_pnl(db_path: Optional[Path] = None) -> float:
    """Get total dollar P&L from all completed bets."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute("SELECT COALESCE(SUM(dollar_pnl), 0.0) FROM completed_bets").fetchone()
        return row[0]
    finally:
        conn.close()


def get_open_exposure(db_path: Optional[Path] = None) -> float:
    """Get total dollar amount committed in active bets."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute("SELECT COALESCE(SUM(amount), 0.0) FROM active_bets").fetchone()
        return row[0]
    finally:
        conn.close()


def _get_summary_from_conn(conn: sqlite3.Connection) -> BetHistorySummary:
    """Compute summary from SQL aggregation using an existing connection."""
    row = conn.execute("""
        SELECT
            COUNT(*) as total_bets,
            SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) as pushes,
            SUM(profit_loss) as net_units,
            SUM(CASE WHEN result IN ('win', 'loss') THEN units ELSE 0 END) as total_units_wagered,
            (SELECT COALESCE(SUM(dollar_pnl), 0.0) FROM completed_bets) as net_dollar_pnl
        FROM completed_bets
        WHERE result != 'early_exit'
    """).fetchone()

    total_bets = row[0] or 0
    wins = row[1] or 0
    losses = row[2] or 0
    pushes = row[3] or 0
    net_units = row[4] or 0.0
    total_units_wagered = row[5] or 0.0
    net_dollar_pnl = row[6] or 0.0

    win_rate = round(wins / total_bets, 3) if total_bets > 0 else 0.0
    roi = round(net_units / total_units_wagered, 3) if total_units_wagered > 0 else 0.0

    # by_confidence (wins/losses only)
    by_confidence = {}
    for conf_row in conn.execute("""
        SELECT confidence,
               SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) as losses
        FROM completed_bets
        WHERE result IN ('win', 'loss')
        GROUP BY confidence
    """).fetchall():
        conf, c_wins, c_losses = conf_row
        c_total = c_wins + c_losses
        by_confidence[conf] = {
            "wins": c_wins,
            "losses": c_losses,
            "win_rate": round(c_wins / c_total, 3) if c_total > 0 else 0.0,
        }

    # by_primary_edge (use edge_category, wins/losses only)
    by_primary_edge = {}
    for edge_row in conn.execute("""
        SELECT edge_category,
               SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) as losses
        FROM completed_bets
        WHERE result IN ('win', 'loss')
        GROUP BY edge_category
    """).fetchall():
        edge, e_wins, e_losses = edge_row
        e_total = e_wins + e_losses
        by_primary_edge[edge] = {
            "wins": e_wins,
            "losses": e_losses,
            "win_rate": round(e_wins / e_total, 3) if e_total > 0 else 0.0,
        }

    # by_bet_type (wins/losses only)
    by_bet_type = {}
    for type_row in conn.execute("""
        SELECT bet_type,
               SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result = 'loss' THEN 1 ELSE 0 END) as losses
        FROM completed_bets
        WHERE result IN ('win', 'loss')
        GROUP BY bet_type
    """).fetchall():
        bt, t_wins, t_losses = type_row
        t_total = t_wins + t_losses
        by_bet_type[bt] = {
            "wins": t_wins,
            "losses": t_losses,
            "win_rate": round(t_wins / t_total, 3) if t_total > 0 else 0.0,
        }

    # current_streak from last 10 win/loss results
    recent_results = conn.execute("""
        SELECT result FROM completed_bets
        WHERE result IN ('win', 'loss')
        ORDER BY date DESC, created_at DESC
        LIMIT 10
    """).fetchall()

    current_streak = ""
    if recent_results:
        latest = recent_results[0][0]
        count = 1
        for r in recent_results[1:]:
            if r[0] == latest:
                count += 1
            else:
                break
        prefix = "W" if latest == "win" else "L"
        current_streak = f"{prefix}{count}"

    return {
        "total_bets": total_bets,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": win_rate,
        "total_units_wagered": total_units_wagered,
        "net_units": net_units,
        "roi": roi,
        "by_confidence": by_confidence,
        "by_primary_edge": by_primary_edge,
        "by_bet_type": by_bet_type,
        "current_streak": current_streak,
        "net_dollar_pnl": net_dollar_pnl,
    }


def get_summary(db_path: Optional[Path] = None) -> BetHistorySummary:
    """Compute summary from SQL aggregation."""
    conn = _get_conn(db_path)
    try:
        return _get_summary_from_conn(conn)
    finally:
        conn.close()


def get_history(db_path: Optional[Path] = None) -> BetHistory:
    """Backward-compatible history dict with bets list and computed summary."""
    conn = _get_conn(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM completed_bets ORDER BY date, created_at"
        ).fetchall()
        bets = [_row_to_bet(row) for row in rows]
        summary = _get_summary_from_conn(conn)
        return {"bets": bets, "summary": summary}
    finally:
        conn.close()


# --- Active bets ---


def _insert_active_row(conn: sqlite3.Connection, bet: ActiveBet) -> None:
    """Insert a single active bet row."""
    conn.execute(
        """INSERT OR REPLACE INTO active_bets
        (id, game_id, matchup, bet_type, pick, line, confidence, units,
         reasoning, primary_edge, date, created_at,
         amount, odds_price, poly_price, placed_polymarket)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            bet["id"],
            bet["game_id"],
            bet["matchup"],
            bet.get("bet_type", "moneyline"),
            bet["pick"],
            bet.get("line"),
            bet["confidence"],
            bet["units"],
            bet["reasoning"],
            bet["primary_edge"],
            bet["date"],
            bet["created_at"],
            bet.get("amount"),
            bet.get("odds_price"),
            bet.get("poly_price"),
            1 if bet.get("placed_polymarket") else 0,
        ),
    )


def _row_to_active_bet(row: sqlite3.Row) -> ActiveBet:
    """Convert a database row to ActiveBet dict."""
    bet: ActiveBet = {
        "id": row["id"],
        "game_id": row["game_id"],
        "matchup": row["matchup"],
        "bet_type": row["bet_type"],
        "pick": row["pick"],
        "line": row["line"],
        "confidence": row["confidence"],
        "units": row["units"],
        "reasoning": row["reasoning"],
        "primary_edge": row["primary_edge"],
        "date": row["date"],
        "created_at": row["created_at"],
    }
    if row["amount"] is not None:
        bet["amount"] = row["amount"]
    if row["odds_price"] is not None:
        bet["odds_price"] = row["odds_price"]
    if row["poly_price"] is not None:
        bet["poly_price"] = row["poly_price"]
    if row["placed_polymarket"]:
        bet["placed_polymarket"] = True
    return bet


def get_active_bets_db(db_path: Optional[Path] = None) -> List[ActiveBet]:
    """Get all active bets ordered by date, created_at."""
    conn = _get_conn(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM active_bets ORDER BY date, created_at"
        ).fetchall()
        return [_row_to_active_bet(row) for row in rows]
    finally:
        conn.close()


def save_active_bets_db(bets: List[ActiveBet], db_path: Optional[Path] = None) -> None:
    """Replace all active bets atomically."""
    conn = _get_conn(db_path)
    try:
        conn.execute("DELETE FROM active_bets")
        for bet in bets:
            _insert_active_row(conn, bet)
        conn.commit()
    finally:
        conn.close()
