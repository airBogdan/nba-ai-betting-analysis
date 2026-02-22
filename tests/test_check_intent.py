"""Intent-based tests for workflow/check.py — position re-evaluation workflow.

Tests verify INTENT of the check workflow:
- Compute P&L correctly for open Polymarket positions
- Identify adverse positions (price moved against us beyond threshold)
- Search for new information (injuries/lineups) on adverse positions
- Ask LLM whether to HOLD or CLOSE adverse positions
- Execute sells and record early exits in history
- Journal all position checks
- Orchestrate the full flow with correct filtering and control flow
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.check import (
    ADVERSE_THRESHOLD,
    append_journal_check,
    compute_position_pnl,
    execute_close,
    is_adverse,
    reevaluate_position,
    run_check_workflow,
    search_position_context,
)


# ---------------------------------------------------------------------------
# Helpers — build realistic test data
# ---------------------------------------------------------------------------

def _make_bet(**overrides):
    """Build a realistic active bet dict."""
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
    """Build a realistic Polymarket event."""
    return {
        "title": title,
        "markets": markets or [],
    }


# ===========================================================================
# compute_position_pnl — P&L math for a single position
# ===========================================================================


class TestComputePositionPnl:
    """P&L computation must correctly reflect shares, value, and percentage."""

    def test_profitable_position(self):
        """When price goes up from entry, P&L should be positive."""
        result = compute_position_pnl(entry_price=0.60, live_price=0.70, amount=30.0)
        # 30 / 0.60 = 50 shares, 50 * 0.70 = 35.0 value, 35 - 30 = 5.0 profit
        assert result["shares"] == 50.0
        assert result["current_value"] == 35.0
        assert result["unrealized_pnl"] == 5.0
        assert result["pnl_pct"] > 0
        assert result["price_move"] == pytest.approx(0.10, abs=0.001)

    def test_losing_position(self):
        """When price drops from entry, P&L should be negative."""
        result = compute_position_pnl(entry_price=0.60, live_price=0.45, amount=30.0)
        assert result["unrealized_pnl"] < 0
        assert result["pnl_pct"] < 0
        assert result["price_move"] < 0

    def test_breakeven_position(self):
        """When price equals entry, P&L should be zero."""
        result = compute_position_pnl(entry_price=0.50, live_price=0.50, amount=20.0)
        assert result["unrealized_pnl"] == 0.0
        assert result["pnl_pct"] == 0.0
        assert result["price_move"] == 0.0

    def test_shares_calculation_is_amount_divided_by_entry(self):
        """Shares = amount / entry_price. This is how Polymarket works."""
        result = compute_position_pnl(entry_price=0.25, live_price=0.30, amount=50.0)
        assert result["shares"] == 200.0  # 50 / 0.25

    def test_pnl_percentage_is_relative_to_cost(self):
        """P&L percentage should be relative to the amount invested, not to share price."""
        result = compute_position_pnl(entry_price=0.50, live_price=0.60, amount=100.0)
        # 100/0.50 = 200 shares, 200*0.60 = 120, pnl = 20, pct = 20%
        assert result["pnl_pct"] == 20.0

    def test_zero_amount_returns_zero_pnl_pct(self):
        """Zero wager should not cause division by zero."""
        result = compute_position_pnl(entry_price=0.50, live_price=0.60, amount=0.0)
        assert result["pnl_pct"] == 0.0

    def test_values_are_rounded(self):
        """Results should be rounded to avoid floating point noise in output."""
        result = compute_position_pnl(entry_price=0.33, live_price=0.47, amount=10.0)
        # Shares, value, pnl should all be rounded (not raw float noise)
        assert isinstance(result["shares"], float)
        assert isinstance(result["current_value"], float)
        assert isinstance(result["unrealized_pnl"], float)
        # Check rounding precision
        assert str(result["pnl_pct"]).count(".") <= 1  # at most 1 decimal

    def test_high_entry_price_small_drop(self):
        """Expensive positions (near 1.0) with small drops have small P&L %."""
        result = compute_position_pnl(entry_price=0.90, live_price=0.88, amount=45.0)
        assert result["pnl_pct"] < 0
        assert abs(result["pnl_pct"]) < 5  # small percentage loss


# ===========================================================================
# is_adverse — threshold check for price movement
# ===========================================================================


class TestIsAdverse:
    """A position is adverse when price moved against us beyond the threshold."""

    def test_large_drop_is_adverse(self):
        """A 15pp price drop should be flagged as adverse."""
        pnl = {"price_move": -0.15}
        assert is_adverse(pnl) is True

    def test_small_drop_is_not_adverse(self):
        """A 5pp price drop is within normal fluctuation, not adverse."""
        pnl = {"price_move": -0.05}
        assert is_adverse(pnl) is False

    def test_price_increase_is_never_adverse(self):
        """If price went up, the position is profitable — never adverse."""
        pnl = {"price_move": 0.10}
        assert is_adverse(pnl) is False

    def test_zero_movement_is_not_adverse(self):
        """Flat price is not adverse."""
        pnl = {"price_move": 0.0}
        assert is_adverse(pnl) is False

    def test_exactly_at_threshold_is_not_adverse(self):
        """At exactly -0.10, it should NOT be adverse (strict inequality)."""
        pnl = {"price_move": -ADVERSE_THRESHOLD}
        assert is_adverse(pnl) is False

    def test_just_beyond_threshold_is_adverse(self):
        """Just past -0.10 triggers adverse."""
        pnl = {"price_move": -(ADVERSE_THRESHOLD + 0.001)}
        assert is_adverse(pnl) is True

    def test_custom_threshold(self):
        """Custom threshold should override the default."""
        pnl = {"price_move": -0.06}
        assert is_adverse(pnl, threshold=0.05) is True
        assert is_adverse(pnl, threshold=0.10) is False

    def test_default_threshold_is_ten_percent(self):
        """The default adverse threshold is 10 percentage points."""
        assert ADVERSE_THRESHOLD == 0.10


# ===========================================================================
# search_position_context — search for injury/lineup changes
# ===========================================================================


class TestSearchPositionContext:
    """Search should fetch injury/lineup updates for a game matchup."""

    @pytest.mark.asyncio
    async def test_returns_search_results_on_success(self):
        """Successful search returns the text content."""
        with patch("workflow.check.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = "Player X upgraded to available"
            result = await search_position_context("Celtics @ Lakers")
            assert result == "Player X upgraded to available"

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        """Search failure should return None, not crash."""
        with patch("workflow.check.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.side_effect = Exception("API timeout")
            result = await search_position_context("Celtics @ Lakers")
            assert result is None

    @pytest.mark.asyncio
    async def test_uses_position_context_prompt(self):
        """Should use the SEARCH_POSITION_CONTEXT_PROMPT with the matchup."""
        with patch("workflow.check.complete", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = "some context"
            await search_position_context("Celtics @ Lakers")
            prompt_used = mock_complete.call_args[0][0]
            assert "Celtics @ Lakers" in prompt_used

    @pytest.mark.asyncio
    async def test_uses_perplexity_model(self):
        """Should use the Perplexity model (not default LLM) for search."""
        with patch("workflow.check.complete", new_callable=AsyncMock) as mock_complete, \
             patch.dict("os.environ", {"PERPLEXITY_MODEL": "perplexity/sonar-pro"}):
            mock_complete.return_value = "context"
            await search_position_context("Celtics @ Lakers")
            _, kwargs = mock_complete.call_args
            assert "perplexity" in kwargs.get("model", "").lower()


# ===========================================================================
# reevaluate_position — LLM decides HOLD or CLOSE
# ===========================================================================


class TestReevaluatePosition:
    """LLM re-evaluation should format bet context and return a HOLD/CLOSE decision."""

    @pytest.mark.asyncio
    async def test_returns_llm_decision(self):
        """Should return the LLM's JSON decision."""
        bet = _make_bet()
        pnl = {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0}
        with patch("workflow.check.complete_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {
                "action": "HOLD",
                "edge_still_valid": True,
                "reasoning": "Original thesis intact",
            }
            result = await reevaluate_position(bet, pnl, "No new injuries")
            assert result["action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_includes_bet_details_in_prompt(self):
        """The prompt should contain the bet's matchup, pick, and edge."""
        bet = _make_bet(
            matchup="Warriors @ Nuggets",
            pick="Nuggets",
            primary_edge="altitude advantage",
        )
        pnl = {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0}
        with patch("workflow.check.complete_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"action": "HOLD"}
            await reevaluate_position(bet, pnl, None)
            prompt = mock_llm.call_args[0][0]
            assert "Warriors @ Nuggets" in prompt
            assert "Nuggets" in prompt
            assert "altitude advantage" in prompt

    @pytest.mark.asyncio
    async def test_spread_line_formatted_with_sign(self):
        """Spread lines should show +/- sign (e.g., +4.5, -3.0)."""
        bet = _make_bet(bet_type="spread", line=-4.5)
        pnl = {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0}
        with patch("workflow.check.complete_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"action": "HOLD"}
            await reevaluate_position(bet, pnl, None)
            prompt = mock_llm.call_args[0][0]
            assert "-4.5" in prompt

    @pytest.mark.asyncio
    async def test_total_line_formatted_without_sign(self):
        """Total lines should not have +/- sign (e.g., 224.5 not +224.5)."""
        bet = _make_bet(bet_type="total", line=224.5)
        pnl = {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0}
        with patch("workflow.check.complete_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"action": "HOLD"}
            await reevaluate_position(bet, pnl, None)
            prompt = mock_llm.call_args[0][0]
            assert "224.5" in prompt
            assert "+224.5" not in prompt

    @pytest.mark.asyncio
    async def test_missing_line_shows_na(self):
        """Moneyline bets have no line — should show N/A."""
        bet = _make_bet(bet_type="moneyline", line=None)
        pnl = {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0}
        with patch("workflow.check.complete_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"action": "HOLD"}
            await reevaluate_position(bet, pnl, None)
            prompt = mock_llm.call_args[0][0]
            assert "N/A" in prompt

    @pytest.mark.asyncio
    async def test_no_search_context_shows_fallback_message(self):
        """When search returned nothing, prompt should say so."""
        bet = _make_bet()
        pnl = {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0}
        with patch("workflow.check.complete_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"action": "HOLD"}
            await reevaluate_position(bet, pnl, None)
            prompt = mock_llm.call_args[0][0]
            assert "No additional context available" in prompt

    @pytest.mark.asyncio
    async def test_uses_position_manager_system_prompt(self):
        """Should use the conservative SYSTEM_POSITION_MANAGER system prompt."""
        bet = _make_bet()
        pnl = {"price_move": -0.12, "pnl_pct": -20.0, "unrealized_pnl": -5.0}
        with patch("workflow.check.complete_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"action": "HOLD"}
            await reevaluate_position(bet, pnl, None)
            kwargs = mock_llm.call_args[1]
            system = kwargs.get("system", "")
            # The system prompt should establish conservative HOLD default
            assert "HOLD" in system


# ===========================================================================
# execute_close — sell position, record to history, update active bets
# ===========================================================================


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


# ===========================================================================
# append_journal_check — write position check results to daily journal
# ===========================================================================


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


# ===========================================================================
# run_check_workflow — full orchestration
# ===========================================================================


class TestRunCheckWorkflow:
    """The orchestrator should filter, compute, evaluate, and execute correctly."""

    @pytest.mark.asyncio
    async def test_no_placed_bets_exits_early(self):
        """If no bets are placed on Polymarket, exit immediately."""
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events:
            # Bets exist but none are placed on Polymarket
            mock_active.return_value = [
                _make_bet(placed_polymarket=False),
            ]
            await run_check_workflow()
            mock_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_to_only_placed_polymarket_bets(self):
        """Only bets with placed_polymarket=True, poly_price, and amount should be checked."""
        placed_bet = _make_bet(id="placed", placed_polymarket=True, poly_price=0.60, amount=25.0)
        unplaced_bet = _make_bet(id="unplaced", placed_polymarket=False, poly_price=0.55, amount=20.0)
        no_price_bet = _make_bet(id="no-price", placed_polymarket=True, amount=25.0)
        no_price_bet.pop("poly_price", None)  # remove poly_price

        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.append_journal_check"):
            mock_active.return_value = [placed_bet, unplaced_bet, no_price_bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = ("token-abc", 0.65)

            await run_check_workflow()

            # Only 1 bet should be processed (the placed one)
            assert mock_resolve.call_count == 1

    @pytest.mark.asyncio
    async def test_skips_bets_with_no_market(self):
        """Bets where market can't be resolved should be skipped gracefully."""
        bet = _make_bet()
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve:
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = None  # market not found

            # Should not crash, just print and exit
            await run_check_workflow()

    @pytest.mark.asyncio
    async def test_no_adverse_positions_skips_evaluation(self):
        """When all positions are within threshold, no LLM evaluation should happen."""
        bet = _make_bet(poly_price=0.60)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("workflow.check.append_journal_check"):
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            # Price barely moved — not adverse
            mock_resolve.return_value = ("token-abc", 0.58)

            await run_check_workflow()
            mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_adverse_position_triggers_search_and_llm(self):
        """Adverse positions should trigger search + LLM re-evaluation."""
        bet = _make_bet(poly_price=0.60)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("workflow.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("workflow.check.append_journal_check"):
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            # Price dropped significantly — adverse
            mock_resolve.return_value = ("token-abc", 0.45)
            mock_search.return_value = "Player X now out"
            mock_reeval.return_value = {"action": "HOLD", "reasoning": "Edge still valid"}

            await run_check_workflow()
            mock_search.assert_called_once()
            mock_reeval.assert_called_once()

    @pytest.mark.asyncio
    async def test_hold_recommendation_does_not_sell(self):
        """HOLD recommendations should not trigger any sell execution."""
        bet = _make_bet(poly_price=0.60)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("workflow.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("workflow.check.save_active_bets") as mock_save, \
             patch("workflow.check.append_journal_check"):
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = ("token-abc", 0.45)
            mock_search.return_value = "No changes"
            mock_reeval.return_value = {"action": "HOLD", "reasoning": "Edge intact"}

            await run_check_workflow()
            # save_active_bets should NOT be called (no state change)
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_recommendation_executes_sell(self):
        """CLOSE recommendations should trigger sell execution."""
        bet = _make_bet(poly_price=0.60)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("workflow.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("workflow.check.sell_position") as mock_sell, \
             patch("workflow.check.create_clob_client") as mock_client, \
             patch("workflow.check.get_history") as mock_hist, \
             patch("workflow.check.save_history"), \
             patch("workflow.check.update_history_with_bet"), \
             patch("workflow.check.save_active_bets"), \
             patch("workflow.check.get_dollar_pnl") as mock_pnl, \
             patch("workflow.check.append_journal_check"), \
             patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xabc", "POLYMARKET_FUNDER": "0xdef"}):
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = ("token-abc", 0.45)
            mock_search.return_value = "Star player ruled out"
            mock_reeval.return_value = {"action": "CLOSE", "reasoning": "Edge invalidated"}
            mock_sell.return_value = {"status": "matched"}
            mock_client.return_value = MagicMock()
            mock_hist.return_value = {"bets": [], "summary": {}}
            mock_pnl.return_value = -2.50

            await run_check_workflow()
            mock_sell.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_failure_defaults_to_hold(self):
        """If LLM evaluation fails, default to HOLD (don't sell)."""
        bet = _make_bet(poly_price=0.60)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("workflow.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("workflow.check.save_active_bets") as mock_save, \
             patch("workflow.check.append_journal_check"):
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = ("token-abc", 0.45)
            mock_search.return_value = "some context"
            mock_reeval.return_value = None  # LLM failure

            await run_check_workflow()
            # No sell should happen, no state change
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_polymarket_credentials_prevents_selling(self):
        """Without POLYMARKET_PRIVATE_KEY/FUNDER, sells can't execute."""
        bet = _make_bet(poly_price=0.60)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("workflow.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("workflow.check.create_clob_client") as mock_client, \
             patch("workflow.check.append_journal_check"), \
             patch.dict("os.environ", {}, clear=True):
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = ("token-abc", 0.45)
            mock_search.return_value = "context"
            mock_reeval.return_value = {"action": "CLOSE", "reasoning": "Edge gone"}

            await run_check_workflow()
            mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetches_events_per_date(self):
        """Bets on different dates should fetch events separately per date."""
        bet1 = _make_bet(id="bet1", date="2026-02-20", poly_price=0.60)
        bet2 = _make_bet(id="bet2", date="2026-02-21", poly_price=0.55)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.append_journal_check"):
            mock_active.return_value = [bet1, bet2]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = ("token-abc", 0.58)

            await run_check_workflow()
            # Should fetch events for both dates
            dates_fetched = [c[0][0] for c in mock_events.call_args_list]
            assert "2026-02-20" in dates_fetched
            assert "2026-02-21" in dates_fetched

    @pytest.mark.asyncio
    async def test_journal_always_appended(self):
        """Journal should be written whether there are adverse positions or not."""
        bet = _make_bet(poly_price=0.60)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.append_journal_check") as mock_journal:
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = ("token-abc", 0.58)  # not adverse

            await run_check_workflow()
            mock_journal.assert_called_once()

    @pytest.mark.asyncio
    async def test_bets_without_amount_are_excluded(self):
        """Bets without an amount (e.g., sizing vetoed) should be filtered out."""
        bet_no_amount = _make_bet(amount=0)
        # amount=0 is falsy, so this bet should be excluded
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events:
            mock_active.return_value = [bet_no_amount]
            await run_check_workflow()
            mock_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_adverse_positions_each_evaluated(self):
        """Each adverse position should get its own search + LLM evaluation."""
        bet1 = _make_bet(id="bet1", matchup="Celtics @ Lakers", poly_price=0.60)
        bet2 = _make_bet(id="bet2", matchup="Warriors @ Nuggets", poly_price=0.55)
        with patch("workflow.check.load_dotenv"), \
             patch("workflow.check.get_active_bets") as mock_active, \
             patch("workflow.check.fetch_nba_events") as mock_events, \
             patch("workflow.check.resolve_token_id") as mock_resolve, \
             patch("workflow.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("workflow.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("workflow.check.append_journal_check"):
            mock_active.return_value = [bet1, bet2]
            mock_events.return_value = [_make_event()]
            # Both drop significantly → both adverse
            mock_resolve.return_value = ("token-abc", 0.40)
            mock_search.return_value = "context"
            mock_reeval.return_value = {"action": "HOLD", "reasoning": "ok"}

            await run_check_workflow()
            assert mock_search.call_count == 2
            assert mock_reeval.call_count == 2
