from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.check import (
    append_journal_check,
    execute_close,
)


def _make_bet(**overrides):
    base = {
        "id": "bet-001",
        "game_id": "game-123",
        "matchup": "Celtics @ Lakers",
        "bet_type": "moneyline",
        "pick": "Lakers",
        "line": None,
        "confidence": "medium",
        "units": 1.0,
        "reasoning": "Lakers strong at home with rest advantage",
        "primary_edge": "home_court",
        "date": "2026-02-21",
        "created_at": "2026-02-21T10:00:00Z",
        "amount": 25.00,
        "poly_price": 0.60,
        "placed_polymarket": True,
    }
    base.update(overrides)
    return base


def _make_event(title="Los Angeles Lakers vs Boston Celtics", markets=None):
    return {
        "title": title,
        "markets": markets or [],
    }


class TestExecuteClose:
    """Closing a position should sell on-chain, record as early_exit, and remove from active."""

    def test_successful_close_returns_true(self):
        """Successful sell should return True."""
        bet = _make_bet()
        pnl = {"shares": 50.0, "current_value": 27.50, "unrealized_pnl": -2.50, "pnl_pct": -10.0, "price_move": -0.05}
        recommendation = {"action": "CLOSE", "reasoning": "Key player now out"}
        active_bets = [bet]
        client = MagicMock()

        with patch("workflow.check.sell_position") as mock_sell, \
             patch("workflow.check.get_history") as mock_hist, \
             patch("workflow.check.save_history"):
            mock_sell.return_value = {"status": "matched"}
            mock_hist.return_value = {"bets": [], "summary": {}}

            result = execute_close(bet, pnl, recommendation, client, "token-abc", 0.55, active_bets)
            assert result is True

    def test_removes_bet_from_active_list(self):
        """After selling, the bet should be removed from the active bets list."""
        bet = _make_bet(id="bet-to-close")
        other_bet = _make_bet(id="bet-to-keep")
        pnl = {"shares": 50.0, "current_value": 27.50, "unrealized_pnl": -2.50, "pnl_pct": -10.0, "price_move": -0.05}
        recommendation = {"action": "CLOSE", "reasoning": "Edge gone"}
        active_bets = [bet, other_bet]
        client = MagicMock()

        with patch("workflow.check.sell_position") as mock_sell, \
             patch("workflow.check.get_history") as mock_hist, \
             patch("workflow.check.save_history"):
            mock_sell.return_value = {"status": "matched"}
            mock_hist.return_value = {"bets": [], "summary": {}}

            execute_close(bet, pnl, recommendation, client, "token-abc", 0.55, active_bets)
            remaining_ids = [b["id"] for b in active_bets]
            assert "bet-to-close" not in remaining_ids
            assert "bet-to-keep" in remaining_ids

    def test_records_early_exit_in_history(self):
        """Closed positions should be recorded with result='early_exit'."""
        bet = _make_bet()
        pnl = {"shares": 50.0, "current_value": 27.50, "unrealized_pnl": -2.50, "pnl_pct": -10.0, "price_move": -0.05}
        recommendation = {"action": "CLOSE", "reasoning": "Injury changed edge"}
        active_bets = [bet]
        client = MagicMock()

        with patch("workflow.check.sell_position") as mock_sell, \
             patch("workflow.check.get_history") as mock_hist, \
             patch("workflow.check.save_history"), \
             patch("workflow.check.update_history_with_bet") as mock_update:
            mock_sell.return_value = {"status": "matched"}
            mock_hist.return_value = {"bets": [], "summary": {}}

            execute_close(bet, pnl, recommendation, client, "token-abc", 0.55, active_bets)

            completed = mock_update.call_args[0][1]
            assert completed["result"] == "early_exit"

    def test_early_exit_includes_dollar_pnl(self):
        """The completed bet should have the dollar P&L from the sell."""
        bet = _make_bet(amount=30.0, units=1.0)
        # current_value (27.50) - amount (30.0) = -2.50
        pnl = {"shares": 50.0, "current_value": 27.50, "unrealized_pnl": -2.50, "pnl_pct": -8.3, "price_move": -0.05}
        recommendation = {"action": "CLOSE", "reasoning": "Edge gone"}
        active_bets = [bet]
        client = MagicMock()

        with patch("workflow.check.sell_position"), \
             patch("workflow.check.get_history") as mock_hist, \
             patch("workflow.check.save_history"), \
             patch("workflow.check.update_history_with_bet") as mock_update:
            mock_hist.return_value = {"bets": [], "summary": {}}

            execute_close(bet, pnl, recommendation, client, "token-abc", 0.55, active_bets)

            completed = mock_update.call_args[0][1]
            assert completed["dollar_pnl"] == -2.50

    def test_early_exit_reflection_contains_reasoning(self):
        """The reflection should explain why the position was closed."""
        bet = _make_bet()
        pnl = {"shares": 50.0, "current_value": 27.50, "unrealized_pnl": -2.50, "pnl_pct": -10.0, "price_move": -0.05}
        recommendation = {"action": "CLOSE", "reasoning": "Star player ruled out"}
        active_bets = [bet]
        client = MagicMock()

        with patch("workflow.check.sell_position"), \
             patch("workflow.check.get_history") as mock_hist, \
             patch("workflow.check.save_history"), \
             patch("workflow.check.update_history_with_bet") as mock_update:
            mock_hist.return_value = {"bets": [], "summary": {}}

            execute_close(bet, pnl, recommendation, client, "token-abc", 0.55, active_bets)

            completed = mock_update.call_args[0][1]
            assert "Star player ruled out" in completed["reflection"]

    def test_placed_polymarket_field_removed_from_completed(self):
        """placed_polymarket is an ActiveBet field — should not appear in CompletedBet."""
        bet = _make_bet(placed_polymarket=True)
        pnl = {"shares": 50.0, "current_value": 27.50, "unrealized_pnl": -2.50, "pnl_pct": -10.0, "price_move": -0.05}
        recommendation = {"action": "CLOSE", "reasoning": "Edge gone"}
        active_bets = [bet]
        client = MagicMock()

        with patch("workflow.check.sell_position"), \
             patch("workflow.check.get_history") as mock_hist, \
             patch("workflow.check.save_history"), \
             patch("workflow.check.update_history_with_bet") as mock_update:
            mock_hist.return_value = {"bets": [], "summary": {}}

            execute_close(bet, pnl, recommendation, client, "token-abc", 0.55, active_bets)

            completed = mock_update.call_args[0][1]
            assert "placed_polymarket" not in completed

    def test_sell_failure_returns_false(self):
        """If the sell order fails, return False and don't modify state."""
        bet = _make_bet()
        pnl = {"shares": 50.0, "current_value": 27.50, "unrealized_pnl": -2.50, "pnl_pct": -10.0, "price_move": -0.05}
        recommendation = {"action": "CLOSE", "reasoning": "Edge gone"}
        active_bets = [bet]
        client = MagicMock()

        with patch("workflow.check.sell_position") as mock_sell:
            mock_sell.side_effect = Exception("Insufficient liquidity")

            result = execute_close(bet, pnl, recommendation, client, "token-abc", 0.55, active_bets)
            assert result is False
            # Bet should still be in active list
            assert len(active_bets) == 1


class TestAppendJournalCheck:
    """Journal entries should record the position check with clear formatting."""

    def test_creates_journal_with_header_for_new_file(self, tmp_path):
        """New journal file should start with a date header."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()

        with patch("workflow.check.JOURNAL_DIR", journal_dir):
            positions = [{
                "bet": _make_bet(),
                "pnl": {"price_move": 0.05, "pnl_pct": 8.3, "unrealized_pnl": 2.50},
                "adverse": False,
            }]
            append_journal_check("2026-02-21", positions, [], [])

        content = (journal_dir / "2026-02-21.md").read_text()
        assert "# NBA Betting Journal - 2026-02-21" in content

    def test_appends_to_existing_journal(self, tmp_path):
        """Should append to an existing journal, not overwrite."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        journal_path = journal_dir / "2026-02-21.md"
        journal_path.write_text("# NBA Betting Journal - 2026-02-21\n\nExisting content.\n")

        with patch("workflow.check.JOURNAL_DIR", journal_dir):
            positions = [{
                "bet": _make_bet(),
                "pnl": {"price_move": 0.05, "pnl_pct": 8.3, "unrealized_pnl": 2.50},
                "adverse": False,
            }]
            append_journal_check("2026-02-21", positions, [], [])

        content = journal_path.read_text()
        assert "Existing content." in content
        assert "Position Check" in content

    def test_lists_all_positions_with_status(self, tmp_path):
        """Every position should appear with its P&L status."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()

        with patch("workflow.check.JOURNAL_DIR", journal_dir):
            positions = [
                {
                    "bet": _make_bet(matchup="Celtics @ Lakers"),
                    "pnl": {"price_move": 0.05, "pnl_pct": 8.3, "unrealized_pnl": 2.50},
                    "adverse": False,
                },
                {
                    "bet": _make_bet(matchup="Warriors @ Nuggets", poly_price=0.55),
                    "pnl": {"price_move": -0.15, "pnl_pct": -27.3, "unrealized_pnl": -6.80},
                    "adverse": True,
                },
            ]
            append_journal_check("2026-02-21", positions, [], [])

        content = (journal_dir / "2026-02-21.md").read_text()
        assert "Celtics @ Lakers" in content
        assert "Warriors @ Nuggets" in content
        assert "OK" in content
        assert "ADVERSE" in content

    def test_shows_healthy_message_when_no_adverse(self, tmp_path):
        """When all positions are healthy, a reassuring message should appear."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()

        with patch("workflow.check.JOURNAL_DIR", journal_dir):
            positions = [{
                "bet": _make_bet(),
                "pnl": {"price_move": 0.02, "pnl_pct": 3.3, "unrealized_pnl": 1.0},
                "adverse": False,
            }]
            append_journal_check("2026-02-21", positions, [], [])

        content = (journal_dir / "2026-02-21.md").read_text()
        assert "healthy" in content.lower() or "no adverse" in content.lower()

    def test_shows_recommendations_section(self, tmp_path):
        """Adverse positions with LLM recommendations should be shown."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()

        with patch("workflow.check.JOURNAL_DIR", journal_dir):
            bet = _make_bet(matchup="Heat @ Bucks")
            recommendations = [{
                "bet": bet,
                "pnl": {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0},
                "recommendation": {"action": "HOLD", "reasoning": "Edge still valid"},
            }]
            append_journal_check("2026-02-21", [], recommendations, [])

        content = (journal_dir / "2026-02-21.md").read_text()
        assert "Heat @ Bucks" in content
        assert "HOLD" in content

    def test_shows_executions_section(self, tmp_path):
        """Executed sells should be recorded in the journal."""
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()

        with patch("workflow.check.JOURNAL_DIR", journal_dir):
            bet = _make_bet(matchup="Suns @ Clippers")
            executions = [{
                "bet": bet,
                "pnl": {"unrealized_pnl": -3.50, "pnl_pct": -14.0},
            }]
            append_journal_check("2026-02-21", [], [], executions)

        content = (journal_dir / "2026-02-21.md").read_text()
        assert "SOLD" in content
        assert "Suns @ Clippers" in content
