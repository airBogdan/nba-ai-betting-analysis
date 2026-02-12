"""Tests for workflow/db.py SQLite storage."""

import json
import sqlite3
from pathlib import Path

import pytest

from workflow.db import (
    _categorize_edge,
    _get_conn,
    get_all_bets,
    get_history,
    get_recent_bets,
    get_summary,
    insert_bet,
)


def _make_bet(**overrides):
    """Create a minimal CompletedBet dict with defaults."""
    base = {
        "id": "test-001",
        "game_id": "12345",
        "matchup": "Team A @ Team B",
        "bet_type": "moneyline",
        "pick": "Team B",
        "line": None,
        "confidence": "medium",
        "units": 1.0,
        "reasoning": "Strong edge",
        "primary_edge": "ratings_edge",
        "date": "2026-02-01",
        "created_at": "2026-02-01T10:00:00+00:00",
        "result": "win",
        "winner": "Team B",
        "final_score": "Team A 100 @ Team B 110",
        "actual_total": 210,
        "actual_margin": 10,
        "profit_loss": 1.0,
        "reflection": "Good bet.",
    }
    base.update(overrides)
    return base


@pytest.fixture
def db_path(tmp_path):
    """Provide a temporary DB path (no history.json to migrate)."""
    return tmp_path / "test.db"


@pytest.fixture
def db_path_with_json(tmp_path):
    """Provide a temporary DB path with a history.json to migrate."""
    bets = [
        _make_bet(id="bet-1", result="win", profit_loss=1.0, confidence="high", units=2.0,
                  primary_edge="ratings_edge", bet_type="moneyline", date="2026-02-01"),
        _make_bet(id="bet-2", result="loss", profit_loss=-1.0, confidence="medium", units=1.0,
                  primary_edge="injury_edge", bet_type="spread", date="2026-02-02"),
        _make_bet(id="bet-3", result="win", profit_loss=0.5, confidence="low", units=0.5,
                  primary_edge="home_court", bet_type="total", date="2026-02-03"),
    ]
    history = {"bets": bets, "summary": {}}
    json_path = tmp_path / "history.json"
    json_path.write_text(json.dumps(history))
    return tmp_path / "history.db"


class TestSchema:
    """Tests for schema creation and connection."""

    def test_creates_table(self, db_path):
        conn = _get_conn(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "completed_bets" in table_names

    def test_wal_mode(self, db_path):
        conn = _get_conn(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_indexes_created(self, db_path):
        conn = _get_conn(db_path)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        conn.close()
        idx_names = {i[0] for i in indexes}
        assert idx_names >= {"idx_date", "idx_result", "idx_edge_category", "idx_bet_type", "idx_confidence"}


class TestCategorizeEdge:
    """Tests for edge categorization."""

    def test_home_court(self):
        assert _categorize_edge("home court advantage") == "home_court"
        assert _categorize_edge("Strong home record") == "home_court"

    def test_rest_advantage(self):
        assert _categorize_edge("rest advantage after B2B") == "rest_advantage"
        assert _categorize_edge("opponent fatigue") == "rest_advantage"

    def test_injury_edge(self):
        assert _categorize_edge("injury_edge") == "injury_edge"
        assert _categorize_edge("Key players missing") == "injury_edge"

    def test_form_momentum(self):
        assert _categorize_edge("Hot streak momentum") == "form_momentum"

    def test_ratings_edge(self):
        assert _categorize_edge("ratings_edge") == "ratings_edge"
        assert _categorize_edge("+5 net rating differential") == "ratings_edge"

    def test_h2h(self):
        assert _categorize_edge("H2H dominance") == "h2h_history"

    def test_style_mismatch(self):
        assert _categorize_edge("pace mismatch") == "style_mismatch"

    def test_totals_edge(self):
        assert _categorize_edge("total scoring trend") == "totals_edge"

    def test_unknown_short(self):
        assert _categorize_edge("custom edge") == "custom edge"

    def test_unknown_long_truncated(self):
        long_edge = "a" * 30
        assert _categorize_edge(long_edge) == "a" * 25


class TestInsertAndRead:
    """Tests for insert_bet and get_all_bets."""

    def test_insert_and_retrieve(self, db_path):
        bet = _make_bet()
        insert_bet(bet, db_path)
        bets = get_all_bets(db_path)
        assert len(bets) == 1
        assert bets[0]["id"] == "test-001"
        assert bets[0]["result"] == "win"
        assert bets[0]["profit_loss"] == 1.0

    def test_insert_with_optional_fields(self, db_path):
        bet = _make_bet(
            amount=50.0,
            odds_price=-110,
            poly_price=0.65,
            structured_reflection={
                "edge_valid": True,
                "missed_factors": [],
                "process_assessment": "sound",
                "key_lesson": "Good",
                "summary": "Solid bet.",
            },
        )
        insert_bet(bet, db_path)
        bets = get_all_bets(db_path)
        assert bets[0]["amount"] == 50.0
        assert bets[0]["odds_price"] == -110
        assert bets[0]["poly_price"] == 0.65
        assert bets[0]["structured_reflection"]["edge_valid"] is True

    def test_optional_fields_absent(self, db_path):
        bet = _make_bet()
        insert_bet(bet, db_path)
        bets = get_all_bets(db_path)
        assert "amount" not in bets[0]
        assert "odds_price" not in bets[0]
        assert "structured_reflection" not in bets[0]

    def test_duplicate_insert_ignored(self, db_path):
        bet = _make_bet()
        insert_bet(bet, db_path)
        insert_bet(bet, db_path)  # Same ID
        bets = get_all_bets(db_path)
        assert len(bets) == 1

    def test_legacy_bet_defaults_moneyline(self, db_path):
        """Bets without bet_type default to moneyline."""
        bet = _make_bet()
        del bet["bet_type"]
        insert_bet(bet, db_path)
        bets = get_all_bets(db_path)
        assert bets[0]["bet_type"] == "moneyline"

    def test_ordering(self, db_path):
        insert_bet(_make_bet(id="b1", date="2026-02-02", created_at="2026-02-02T10:00:00+00:00"), db_path)
        insert_bet(_make_bet(id="b2", date="2026-02-01", created_at="2026-02-01T10:00:00+00:00"), db_path)
        insert_bet(_make_bet(id="b3", date="2026-02-01", created_at="2026-02-01T11:00:00+00:00"), db_path)
        bets = get_all_bets(db_path)
        assert [b["id"] for b in bets] == ["b2", "b3", "b1"]


class TestGetRecentBets:
    """Tests for get_recent_bets."""

    def test_returns_n_most_recent(self, db_path):
        for i in range(5):
            insert_bet(
                _make_bet(id=f"b{i}", date=f"2026-02-0{i+1}",
                          created_at=f"2026-02-0{i+1}T10:00:00+00:00"),
                db_path,
            )
        recent = get_recent_bets(3, db_path)
        assert len(recent) == 3
        # Should be in chronological order (oldest first of the recent 3)
        assert recent[0]["id"] == "b2"
        assert recent[-1]["id"] == "b4"

    def test_returns_all_if_fewer_than_n(self, db_path):
        insert_bet(_make_bet(), db_path)
        recent = get_recent_bets(20, db_path)
        assert len(recent) == 1


class TestGetSummary:
    """Tests for SQL-computed summary."""

    def test_empty_db(self, db_path):
        summary = get_summary(db_path)
        assert summary["total_bets"] == 0
        assert summary["wins"] == 0
        assert summary["win_rate"] == 0.0
        assert summary["by_confidence"] == {}
        assert summary["by_primary_edge"] == {}
        assert summary["by_bet_type"] == {}
        assert summary["current_streak"] == ""

    def test_basic_summary(self, db_path):
        insert_bet(_make_bet(id="b1", result="win", profit_loss=1.0, units=1.0), db_path)
        insert_bet(_make_bet(id="b2", result="loss", profit_loss=-1.0, units=1.0,
                             date="2026-02-02", created_at="2026-02-02T10:00:00+00:00"), db_path)
        insert_bet(_make_bet(id="b3", result="win", profit_loss=2.0, units=2.0, confidence="high",
                             date="2026-02-03", created_at="2026-02-03T10:00:00+00:00"), db_path)

        summary = get_summary(db_path)
        assert summary["total_bets"] == 3
        assert summary["wins"] == 2
        assert summary["losses"] == 1
        assert summary["pushes"] == 0
        assert summary["net_units"] == 2.0
        assert summary["total_units_wagered"] == 4.0
        assert summary["win_rate"] == round(2 / 3, 3)
        assert summary["roi"] == round(2.0 / 4.0, 3)

    def test_by_confidence(self, db_path):
        insert_bet(_make_bet(id="b1", result="win", confidence="high"), db_path)
        insert_bet(_make_bet(id="b2", result="loss", confidence="high",
                             date="2026-02-02", created_at="2026-02-02T10:00:00+00:00"), db_path)
        insert_bet(_make_bet(id="b3", result="win", confidence="medium",
                             date="2026-02-03", created_at="2026-02-03T10:00:00+00:00"), db_path)

        summary = get_summary(db_path)
        assert summary["by_confidence"]["high"]["wins"] == 1
        assert summary["by_confidence"]["high"]["losses"] == 1
        assert summary["by_confidence"]["high"]["win_rate"] == 0.5
        assert summary["by_confidence"]["medium"]["wins"] == 1
        assert summary["by_confidence"]["medium"]["losses"] == 0

    def test_by_primary_edge(self, db_path):
        insert_bet(_make_bet(id="b1", result="win", primary_edge="ratings_edge"), db_path)
        insert_bet(_make_bet(id="b2", result="win", primary_edge="injury_edge",
                             date="2026-02-02", created_at="2026-02-02T10:00:00+00:00"), db_path)

        summary = get_summary(db_path)
        assert "ratings_edge" in summary["by_primary_edge"]
        assert "injury_edge" in summary["by_primary_edge"]

    def test_by_bet_type(self, db_path):
        insert_bet(_make_bet(id="b1", result="win", bet_type="moneyline"), db_path)
        insert_bet(_make_bet(id="b2", result="loss", bet_type="spread",
                             date="2026-02-02", created_at="2026-02-02T10:00:00+00:00"), db_path)

        summary = get_summary(db_path)
        assert summary["by_bet_type"]["moneyline"]["wins"] == 1
        assert summary["by_bet_type"]["spread"]["losses"] == 1

    def test_pushes_excluded_from_wagered(self, db_path):
        insert_bet(_make_bet(id="b1", result="push", profit_loss=0.0, units=1.0), db_path)
        insert_bet(_make_bet(id="b2", result="win", profit_loss=1.0, units=1.0,
                             date="2026-02-02", created_at="2026-02-02T10:00:00+00:00"), db_path)

        summary = get_summary(db_path)
        assert summary["total_bets"] == 2
        assert summary["pushes"] == 1
        assert summary["total_units_wagered"] == 1.0  # Only the win counts

    def test_pushes_excluded_from_breakdowns(self, db_path):
        insert_bet(_make_bet(id="b1", result="push", profit_loss=0.0), db_path)

        summary = get_summary(db_path)
        assert summary["by_confidence"] == {}
        assert summary["by_primary_edge"] == {}
        assert summary["by_bet_type"] == {}

    def test_current_streak_win(self, db_path):
        insert_bet(_make_bet(id="b1", result="loss", date="2026-02-01",
                             created_at="2026-02-01T10:00:00+00:00"), db_path)
        insert_bet(_make_bet(id="b2", result="win", date="2026-02-02",
                             created_at="2026-02-02T10:00:00+00:00"), db_path)
        insert_bet(_make_bet(id="b3", result="win", date="2026-02-03",
                             created_at="2026-02-03T10:00:00+00:00"), db_path)

        summary = get_summary(db_path)
        assert summary["current_streak"] == "W2"

    def test_current_streak_loss(self, db_path):
        insert_bet(_make_bet(id="b1", result="win", date="2026-02-01",
                             created_at="2026-02-01T10:00:00+00:00"), db_path)
        insert_bet(_make_bet(id="b2", result="loss", date="2026-02-02",
                             created_at="2026-02-02T10:00:00+00:00"), db_path)

        summary = get_summary(db_path)
        assert summary["current_streak"] == "L1"


class TestMigration:
    """Tests for JSON → SQLite migration."""

    def test_migrates_from_json(self, db_path_with_json):
        bets = get_all_bets(db_path_with_json)
        assert len(bets) == 3
        assert bets[0]["id"] == "bet-1"
        assert bets[1]["id"] == "bet-2"
        assert bets[2]["id"] == "bet-3"

    def test_migration_computes_edge_category(self, db_path_with_json):
        conn = _get_conn(db_path_with_json)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT edge_category FROM completed_bets WHERE id = 'bet-1'"
        ).fetchone()
        conn.close()
        assert row["edge_category"] == "ratings_edge"

    def test_migration_runs_once(self, db_path_with_json):
        """Second connection should not re-import."""
        bets1 = get_all_bets(db_path_with_json)
        assert len(bets1) == 3
        # Re-open — should not duplicate
        bets2 = get_all_bets(db_path_with_json)
        assert len(bets2) == 3

    def test_no_json_no_error(self, db_path):
        """No history.json present — just empty DB."""
        bets = get_all_bets(db_path)
        assert bets == []

    def test_summary_after_migration(self, db_path_with_json):
        summary = get_summary(db_path_with_json)
        assert summary["total_bets"] == 3
        assert summary["wins"] == 2
        assert summary["losses"] == 1
        assert summary["net_units"] == 0.5


class TestGetHistory:
    """Tests for backward-compatible get_history."""

    def test_returns_bets_and_summary(self, db_path):
        insert_bet(_make_bet(), db_path)
        history = get_history(db_path)
        assert "bets" in history
        assert "summary" in history
        assert len(history["bets"]) == 1
        assert history["summary"]["total_bets"] == 1

    def test_empty_history(self, db_path):
        history = get_history(db_path)
        assert history["bets"] == []
        assert history["summary"]["total_bets"] == 0
