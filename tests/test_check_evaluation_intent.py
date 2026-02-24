from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.check import (
    reevaluate_position,
    search_position_context,
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
