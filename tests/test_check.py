"""Tests for workflow/check.py — position re-evaluation workflow."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from workflow.check import (
    ADVERSE_THRESHOLD,
    compute_position_pnl,
    is_adverse,
    execute_close,
    run_check_workflow,
)


def _make_bet(**overrides):
    """Create a minimal active bet dict for testing."""
    base = {
        "id": "test-bet-1",
        "game_id": "12345",
        "matchup": "Celtics @ Lakers",
        "bet_type": "total",
        "pick": "under",
        "line": 224.5,
        "confidence": "high",
        "units": 2.0,
        "reasoning": "Injury edge",
        "primary_edge": "injury_edge",
        "date": "2026-02-12",
        "created_at": "2026-02-12T12:00:00+00:00",
        "amount": 20.0,
        "odds_price": 113,
        "poly_price": 0.47,
        "placed_polymarket": True,
    }
    base.update(overrides)
    return base


class TestComputePositionPnl:
    def test_break_even(self):
        """Same entry and live price = zero P&L."""
        pnl = compute_position_pnl(0.50, 0.50, 20.0)
        assert pnl["unrealized_pnl"] == 0.0
        assert pnl["pnl_pct"] == 0.0
        assert pnl["shares"] == 40.0
        assert pnl["current_value"] == 20.0
        assert pnl["price_move"] == 0.0

    def test_favorable_move(self):
        """Price moved in our favor."""
        pnl = compute_position_pnl(0.47, 0.55, 20.0)
        # shares = 20 / 0.47 = 42.5532
        assert pnl["shares"] == pytest.approx(42.5532, abs=0.001)
        # current_value = 42.5532 * 0.55 = 23.4043
        assert pnl["current_value"] == pytest.approx(23.40, abs=0.01)
        assert pnl["unrealized_pnl"] > 0
        assert pnl["pnl_pct"] > 0
        assert pnl["price_move"] == pytest.approx(0.08, abs=0.001)

    def test_adverse_move(self):
        """Price moved against us."""
        pnl = compute_position_pnl(0.47, 0.35, 20.0)
        assert pnl["unrealized_pnl"] < 0
        assert pnl["pnl_pct"] < 0
        assert pnl["price_move"] == pytest.approx(-0.12, abs=0.001)

    def test_small_amount(self):
        """Works with small dollar amounts."""
        pnl = compute_position_pnl(0.60, 0.50, 5.0)
        shares = 5.0 / 0.60
        assert pnl["shares"] == pytest.approx(round(shares, 4), abs=0.001)
        assert pnl["current_value"] == pytest.approx(round(shares * 0.50, 2), abs=0.01)

    def test_price_move_calculation(self):
        """Price move is live - entry."""
        pnl = compute_position_pnl(0.40, 0.55, 10.0)
        assert pnl["price_move"] == pytest.approx(0.15, abs=0.001)


class TestIsAdverse:
    def test_not_adverse_small_drop(self):
        """Small price drop below threshold is not adverse."""
        pnl = compute_position_pnl(0.50, 0.45, 20.0)
        assert not is_adverse(pnl)

    def test_adverse_large_drop(self):
        """Large price drop beyond threshold is adverse."""
        pnl = compute_position_pnl(0.50, 0.35, 20.0)
        assert is_adverse(pnl)

    def test_exactly_at_threshold(self):
        """Exactly at threshold boundary is NOT adverse (needs to exceed)."""
        pnl = compute_position_pnl(0.50, 0.40, 20.0)
        # price_move = -0.10, threshold = 0.10 → not strictly less than -0.10
        assert not is_adverse(pnl)

    def test_favorable_not_adverse(self):
        """Price moving up is never adverse."""
        pnl = compute_position_pnl(0.50, 0.70, 20.0)
        assert not is_adverse(pnl)

    def test_custom_threshold(self):
        """Custom threshold works."""
        pnl = compute_position_pnl(0.50, 0.44, 20.0)
        # price_move = -0.06
        assert not is_adverse(pnl, threshold=0.10)
        assert is_adverse(pnl, threshold=0.05)


class TestExecuteClose:
    def test_successful_close(self):
        """Sell succeeds — records to DB, removes from active."""
        bet = _make_bet()
        pnl = compute_position_pnl(0.47, 0.35, 20.0)
        recommendation = {"action": "CLOSE", "reasoning": "Edge gone"}
        events = [{"title": "Celtics vs Lakers", "markets": []}]

        mock_client = MagicMock()
        mock_client.create_market_order.return_value = "signed"
        mock_client.post_order.return_value = {"status": "ok"}

        active_bets = [bet, _make_bet(id="other-bet")]

        with patch("workflow.check.resolve_token_id", return_value=("token123", 0.35)), \
             patch("workflow.check.sell_position", return_value={"status": "ok"}), \
             patch("workflow.check.db_insert_bet") as mock_db:

            result = execute_close(
                bet, pnl, recommendation,
                mock_client, events, active_bets,
            )

        assert result is True
        # Bet removed from active
        assert len(active_bets) == 1
        assert active_bets[0]["id"] == "other-bet"
        # DB insert called with dollar_pnl
        mock_db.assert_called_once()
        completed = mock_db.call_args[0][0]
        assert completed["result"] == "early_exit"
        assert completed["dollar_pnl"] == round(pnl["current_value"] - bet["amount"], 2)

    def test_sell_fails(self):
        """Sell failure — position stays open."""
        bet = _make_bet()
        pnl = compute_position_pnl(0.47, 0.35, 20.0)
        recommendation = {"action": "CLOSE", "reasoning": "Edge gone"}
        events = []
        active_bets = [bet]

        with patch("workflow.check.resolve_token_id", return_value=None):
            result = execute_close(
                bet, pnl, recommendation,
                MagicMock(), events, active_bets,
            )

        assert result is False
        assert len(active_bets) == 1

    def test_sell_exception(self):
        """Sell throws — position stays open."""
        bet = _make_bet()
        pnl = compute_position_pnl(0.47, 0.35, 20.0)
        recommendation = {"action": "CLOSE", "reasoning": "Edge gone"}
        events = []
        active_bets = [bet]

        with patch("workflow.check.resolve_token_id", return_value=("token123", 0.35)), \
             patch("workflow.check.sell_position", side_effect=Exception("Network error")):
            result = execute_close(
                bet, pnl, recommendation,
                MagicMock(), events, active_bets,
            )

        assert result is False
        assert len(active_bets) == 1


@pytest.mark.asyncio
class TestRunCheckWorkflow:
    @patch("workflow.check.get_active_bets", return_value=[])
    async def test_no_active_bets(self, mock_active, capsys):
        """No active bets — exits cleanly."""
        await run_check_workflow()
        captured = capsys.readouterr()
        assert "No placed positions" in captured.out

    @patch("workflow.check.get_active_bets")
    async def test_no_poly_price_skipped(self, mock_active, capsys):
        """Bets without poly_price are skipped."""
        bet = _make_bet()
        del bet["poly_price"]
        mock_active.return_value = [bet]
        await run_check_workflow()
        captured = capsys.readouterr()
        assert "No placed positions" in captured.out

    @patch("workflow.check.append_journal_check")
    @patch("workflow.check.fetch_nba_events", return_value=[])
    @patch("workflow.check.get_active_bets")
    async def test_no_events(self, mock_active, mock_events, mock_journal, capsys):
        """No events found — logs and exits."""
        mock_active.return_value = [_make_bet()]
        await run_check_workflow()
        captured = capsys.readouterr()
        assert "no Polymarket events" in captured.out

    @patch("workflow.check.append_journal_check")
    @patch("workflow.check._get_live_price", return_value=0.50)
    @patch("workflow.check.fetch_nba_events", return_value=[{"title": "test"}])
    @patch("workflow.check.get_active_bets")
    async def test_no_adverse_positions(self, mock_active, mock_events, mock_price, mock_journal, capsys):
        """Positions within threshold — no re-evaluation."""
        mock_active.return_value = [_make_bet(poly_price=0.47)]
        await run_check_workflow()
        captured = capsys.readouterr()
        assert "No action needed" in captured.out
        mock_journal.assert_called_once()

    @patch("workflow.check.append_journal_check")
    @patch("workflow.check.save_active_bets")
    @patch("workflow.check.get_dollar_pnl", return_value=-40.0)
    @patch("workflow.check.create_clob_client")
    @patch("workflow.check.execute_close", return_value=True)
    @patch("workflow.check.reevaluate_position")
    @patch("workflow.check.search_position_context")
    @patch("workflow.check._get_live_price", return_value=0.30)
    @patch("workflow.check.fetch_nba_events", return_value=[{"title": "test"}])
    @patch("workflow.check.get_active_bets")
    async def test_adverse_triggers_reeval_and_close(
        self, mock_active, mock_events, mock_price,
        mock_search, mock_reeval, mock_exec,
        mock_clob, mock_dollar_pnl,
        mock_save_active, mock_journal, capsys,
        monkeypatch,
    ):
        """Adverse position triggers search + LLM + auto-close."""
        monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xtest")
        monkeypatch.setenv("POLYMARKET_FUNDER", "0xfunder")

        bet = _make_bet(poly_price=0.47)  # live=0.30, move=-0.17 > threshold
        mock_active.return_value = [bet]
        mock_search.return_value = "SGA now confirmed OUT"
        mock_reeval.return_value = {
            "action": "CLOSE",
            "edge_still_valid": False,
            "reasoning": "Key player status changed",
            "revised_confidence": "low",
            "new_factors": ["SGA out"],
        }

        await run_check_workflow()

        # Search was called
        mock_search.assert_called_once()
        # LLM re-evaluation was called
        mock_reeval.assert_called_once()
        # Execute close was called
        mock_exec.assert_called_once()

    @patch("workflow.check.append_journal_check")
    @patch("workflow.check.reevaluate_position")
    @patch("workflow.check.search_position_context")
    @patch("workflow.check._get_live_price", return_value=0.30)
    @patch("workflow.check.fetch_nba_events", return_value=[{"title": "test"}])
    @patch("workflow.check.get_active_bets")
    async def test_adverse_hold_no_sell(
        self, mock_active, mock_events, mock_price,
        mock_search, mock_reeval, mock_journal, capsys,
    ):
        """Adverse position with HOLD recommendation — no sell."""
        bet = _make_bet(poly_price=0.47)
        mock_active.return_value = [bet]
        mock_search.return_value = "No changes"
        mock_reeval.return_value = {
            "action": "HOLD",
            "edge_still_valid": True,
            "reasoning": "Original thesis intact",
            "revised_confidence": "high",
            "new_factors": [],
        }

        await run_check_workflow()
        captured = capsys.readouterr()
        assert "HOLD" in captured.out
        assert "No sells executed" in captured.out

    @patch("workflow.check.append_journal_check")
    @patch("workflow.check.reevaluate_position", return_value=None)
    @patch("workflow.check.search_position_context", return_value=None)
    @patch("workflow.check._get_live_price", return_value=0.30)
    @patch("workflow.check.fetch_nba_events", return_value=[{"title": "test"}])
    @patch("workflow.check.get_active_bets")
    async def test_llm_failure_defaults_hold(
        self, mock_active, mock_events, mock_price,
        mock_search, mock_reeval, mock_journal, capsys,
    ):
        """LLM failure defaults to HOLD."""
        bet = _make_bet(poly_price=0.47)
        mock_active.return_value = [bet]

        await run_check_workflow()
        captured = capsys.readouterr()
        assert "defaulting to HOLD" in captured.out
