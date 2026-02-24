from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from betting.check import (
    run_check_workflow,
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


class TestRunCheckWorkflow:
    """The orchestrator should filter, compute, evaluate, and execute correctly."""

    @pytest.mark.asyncio
    async def test_no_placed_bets_exits_early(self):
        """If no bets are placed on Polymarket, exit immediately."""
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events:
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

        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.append_journal_check"):
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve:
            mock_active.return_value = [bet]
            mock_events.return_value = [_make_event()]
            mock_resolve.return_value = None  # market not found

            # Should not crash, just print and exit
            await run_check_workflow()

    @pytest.mark.asyncio
    async def test_no_adverse_positions_skips_evaluation(self):
        """When all positions are within threshold, no LLM evaluation should happen."""
        bet = _make_bet(poly_price=0.60)
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("betting.check.append_journal_check"):
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("betting.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("betting.check.append_journal_check"):
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("betting.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("betting.check.save_active_bets") as mock_save, \
             patch("betting.check.append_journal_check"):
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("betting.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("betting.check.sell_position") as mock_sell, \
             patch("betting.check.create_clob_client") as mock_client, \
             patch("betting.check.get_history") as mock_hist, \
             patch("betting.check.save_history"), \
             patch("betting.check.update_history_with_bet"), \
             patch("betting.check.save_active_bets"), \
             patch("betting.check.get_dollar_pnl") as mock_pnl, \
             patch("betting.check.append_journal_check"), \
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("betting.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("betting.check.save_active_bets") as mock_save, \
             patch("betting.check.append_journal_check"):
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("betting.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("betting.check.create_clob_client") as mock_client, \
             patch("betting.check.append_journal_check"), \
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.append_journal_check"):
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.append_journal_check") as mock_journal:
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
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events:
            mock_active.return_value = [bet_no_amount]
            await run_check_workflow()
            mock_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_adverse_positions_each_evaluated(self):
        """Each adverse position should get its own search + LLM evaluation."""
        bet1 = _make_bet(id="bet1", matchup="Celtics @ Lakers", poly_price=0.60)
        bet2 = _make_bet(id="bet2", matchup="Warriors @ Nuggets", poly_price=0.55)
        with patch("betting.check.load_dotenv"), \
             patch("betting.check.get_active_bets") as mock_active, \
             patch("betting.check.fetch_nba_events") as mock_events, \
             patch("betting.check.resolve_token_id") as mock_resolve, \
             patch("betting.check.search_position_context", new_callable=AsyncMock) as mock_search, \
             patch("betting.check.reevaluate_position", new_callable=AsyncMock) as mock_reeval, \
             patch("betting.check.append_journal_check"):
            mock_active.return_value = [bet1, bet2]
            mock_events.return_value = [_make_event()]
            # Both drop significantly → both adverse
            mock_resolve.return_value = ("token-abc", 0.40)
            mock_search.return_value = "context"
            mock_reeval.return_value = {"action": "HOLD", "reasoning": "ok"}

            await run_check_workflow()
            assert mock_search.call_count == 2
            assert mock_reeval.call_count == 2
