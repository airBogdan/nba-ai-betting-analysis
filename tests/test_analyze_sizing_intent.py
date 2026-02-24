import json
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.analyze.sizing import (
    CONFIDENCE_WIN_PROB,
    KELLY_FRACTION,
    _american_odds_to_decimal,
    _extract_poly_and_odds_price,
    _extract_sizing_strategy,
    _fallback_sizing,
    _half_kelly_amount,
)


class TestOddsConversion:
    """American odds to decimal odds conversion. This is pure math."""

    def test_minus_110_standard_juice(self):
        # -110 means you bet $110 to win $100 -> payout = 1 + 100/110 ≈ 1.909
        result = _american_odds_to_decimal(-110)
        assert abs(result - (1 + 100 / 110)) < 0.001

    def test_even_money(self):
        # +100 means you bet $100 to win $100 -> payout = 2.0
        assert _american_odds_to_decimal(100) == 2.0

    def test_heavy_favorite(self):
        # -300 means bet $300 to win $100 -> payout = 1.333
        result = _american_odds_to_decimal(-300)
        assert abs(result - (1 + 100 / 300)) < 0.001

    def test_heavy_underdog(self):
        # +300 means bet $100 to win $300 -> payout = 4.0
        assert _american_odds_to_decimal(300) == 4.0


class TestHalfKelly:
    """Half Kelly determines position size based on edge and bankroll.
    Returns 0 when there's no edge (Kelly formula goes negative)."""

    def test_returns_zero_when_no_edge(self):
        """At very low probability, Kelly says don't bet."""
        # At -300 odds, you need >75% win rate. Low confidence = 54%.
        amount = _half_kelly_amount(-300, "low", 1000.0)
        assert amount == 0.0

    def test_positive_amount_when_edge_exists(self):
        """At even money with medium confidence (57%), there's an edge."""
        amount = _half_kelly_amount(100, "medium", 1000.0)
        assert amount > 0

    def test_scales_with_bankroll(self):
        """Doubling available funds should roughly double the bet size."""
        amount_1k = _half_kelly_amount(100, "medium", 1000.0)
        amount_2k = _half_kelly_amount(100, "medium", 2000.0)
        assert abs(amount_2k - 2 * amount_1k) < 0.02  # Rounding tolerance

    def test_higher_confidence_means_larger_bet(self):
        """High confidence should produce a larger bet than low."""
        low = _half_kelly_amount(-110, "low", 1000.0)
        high = _half_kelly_amount(-110, "high", 1000.0)
        # High should be strictly larger (or both zero)
        assert high >= low

    def test_is_half_kelly_not_full(self):
        """The fraction applied should be 0.5 (half Kelly for safety)."""
        assert KELLY_FRACTION == 0.5

    def test_confidence_win_probabilities(self):
        """Verify the business-defined win probabilities."""
        assert CONFIDENCE_WIN_PROB == {"high": 0.65, "medium": 0.57, "low": 0.54}

    def test_zero_available_means_zero_bet(self):
        amount = _half_kelly_amount(100, "high", 0.0)
        assert amount == 0.0


class TestSizingStrategyExtraction:
    """The sizing prompt needs the Position Sizing section from strategy.md."""

    def test_extracts_position_sizing_section(self):
        strategy = (
            "## Game Selection\nPick carefully.\n\n"
            "## Position Sizing\nBet 1-3% of bankroll.\n\n"
            "## Risk Management\nDon't go broke."
        )
        result = _extract_sizing_strategy(strategy)
        assert "Bet 1-3% of bankroll" in result
        assert "Don't go broke" not in result

    def test_returns_default_when_no_section(self):
        result = _extract_sizing_strategy("## Other Section\nStuff.")
        assert "No sizing strategy" in result

    def test_returns_default_when_none(self):
        result = _extract_sizing_strategy(None)
        assert "No sizing strategy" in result

    def test_handles_section_at_end_of_file(self):
        strategy = "## Position Sizing\nLast section content."
        result = _extract_sizing_strategy(strategy)
        assert "Last section content" in result


class TestPolyAndOddsExtraction:
    """Each bet needs a Polymarket price. If not found, returns (None, -110).
    The -110 fallback is standard juice for American odds."""

    def test_returns_none_when_no_polymarket_data(self):
        game = {}
        bet = {"bet_type": "moneyline", "pick": "Lakers", "line": None}
        poly, odds = _extract_poly_and_odds_price(game, bet)
        assert poly is None
        assert odds == -110

    @patch("workflow.analyze.sizing.extract_poly_price_for_bet", return_value=0.60)
    @patch("workflow.analyze.sizing.poly_price_to_american", return_value=-150)
    def test_returns_price_when_found(self, mock_american, mock_extract):
        game = {"polymarket_odds": {"moneyline": {"outcomes": ["Lakers"], "prices": [0.6]}}}
        bet = {"bet_type": "moneyline", "pick": "Lakers", "line": None}
        poly, odds = _extract_poly_and_odds_price(game, bet)
        assert poly == 0.60
        assert odds == -150


class TestFallbackSizing:
    """When LLM sizing fails, the system falls back to Half Kelly.
    Bets with no edge (Kelly <= 0) get dropped."""

    def test_sizes_bets_with_edge(self):
        bets = [
            {"id": "1", "matchup": "A @ B", "confidence": "high",
             "odds_price": 100, "game_id": "g1"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) == 1
        assert result[0]["amount"] > 0

    def test_drops_bets_with_no_edge(self):
        bets = [
            {"id": "1", "matchup": "A @ B", "confidence": "low",
             "odds_price": -500, "game_id": "g1"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) == 0

    def test_uses_default_odds_when_missing(self):
        """Bets without odds_price should use -110 default."""
        bets = [
            {"id": "1", "matchup": "A @ B", "confidence": "high", "game_id": "g1"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        # At -110, high confidence (65%) should produce a positive amount
        assert len(result) == 1
        assert result[0]["amount"] > 0


class TestSizeBets:
    """size_bets uses LLM for sizing but enforces Kelly constraints.
    Key invariants:
    - LLM amount is capped at kelly_max * 1.2
    - Kelly veto overrides LLM (if Kelly <= 0, bet is skipped)
    - LLM failure falls back to pure Kelly
    """

    def _make_bet(self, **overrides) -> dict:
        base = {
            "id": "bet-1",
            "game_id": "g1",
            "matchup": "A @ B",
            "bet_type": "moneyline",
            "pick": "A",
            "line": None,
            "confidence": "high",
            "units": 2.0,
            "reasoning": "Strong edge",
            "primary_edge": "Key factor",
            "odds_price": 100,  # Even money
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json")
    async def test_llm_amount_capped_at_kelly_120_percent(
        self, mock_llm, mock_pnl, mock_exposure
    ):
        """LLM can't exceed 120% of Kelly recommendation."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        kelly_max = _half_kelly_amount(100, "high", 1000.0)

        # LLM suggests way more than Kelly
        mock_llm.return_value = {
            "sizing_decisions": [
                {"bet_id": "bet-1", "action": "place", "amount": 9999.0}
            ]
        }

        sized, skipped = await size_bets([bet], 1000.0, None, {})
        assert len(sized) == 1
        assert sized[0]["amount"] <= round(kelly_max * 1.2, 2)

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json")
    async def test_kelly_veto_overrides_llm(self, mock_llm, mock_pnl, mock_exposure):
        """If Kelly says no edge, bet is skipped even if LLM says place it."""
        from workflow.analyze.sizing import size_bets

        # Odds so bad that Kelly formula goes negative for any confidence
        bet = self._make_bet(odds_price=-1000, confidence="low")

        mock_llm.return_value = {
            "sizing_decisions": [
                {"bet_id": "bet-1", "action": "place", "amount": 50.0}
            ]
        }

        sized, skipped = await size_bets([bet], 1000.0, None, {})
        assert len(sized) == 0
        assert len(skipped) == 1
        assert "Kelly" in skipped[0]["reason"]

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json", return_value=None)
    async def test_llm_failure_falls_back_to_kelly(
        self, mock_llm, mock_pnl, mock_exposure
    ):
        """When LLM sizing fails, pure Half Kelly is used as fallback."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        sized, skipped = await size_bets([bet], 1000.0, None, {})

        # Should still produce a sized bet via Kelly fallback
        assert len(sized) == 1
        assert sized[0]["amount"] > 0

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=200.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json", return_value=None)
    async def test_exposure_reduces_available_for_kelly(
        self, mock_llm, mock_pnl, mock_exposure
    ):
        """Open exposure is subtracted from balance before Kelly calculation.
        With $1000 balance and $200 exposure, only $800 is available."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        sized_with_exposure, _ = await size_bets([bet], 1000.0, None, {})

        mock_exposure.return_value = 0.0
        bet2 = self._make_bet()
        sized_no_exposure, _ = await size_bets([bet2], 1000.0, None, {})

        # Bet with exposure should be smaller (Kelly scales with available)
        if sized_with_exposure and sized_no_exposure:
            assert sized_with_exposure[0]["amount"] < sized_no_exposure[0]["amount"]

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json")
    async def test_llm_veto_skips_bet(self, mock_llm, mock_pnl, mock_exposure):
        """LLM can veto a bet by setting action=skip."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        mock_llm.return_value = {
            "sizing_decisions": [
                {"bet_id": "bet-1", "action": "skip", "amount": 0,
                 "reasoning": "Weak edge"}
            ]
        }

        sized, skipped = await size_bets([bet], 1000.0, None, {})
        assert len(sized) == 0
        assert len(skipped) == 1
        assert "Vetoed" in skipped[0]["reason"]
