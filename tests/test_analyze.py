"""Tests for workflow/analyze.py Kelly Criterion sizing."""

import pytest

from workflow.analyze import (
    _american_odds_to_decimal,
    _extract_poly_and_odds_price,
    _half_kelly_amount,
    _fallback_sizing,
    CONFIDENCE_WIN_PROB,
    KELLY_FRACTION,
    KELLY_MAX_BET_FRACTION,
)


class TestAmericanOddsToDecimal:
    """Tests for American odds → decimal odds conversion."""

    def test_standard_vig(self):
        assert _american_odds_to_decimal(-110) == pytest.approx(1.909, abs=0.001)

    def test_negative_odds(self):
        assert _american_odds_to_decimal(-200) == 1.5
        assert _american_odds_to_decimal(-150) == pytest.approx(1.667, abs=0.001)
        assert _american_odds_to_decimal(-300) == pytest.approx(1.333, abs=0.001)

    def test_positive_odds(self):
        assert _american_odds_to_decimal(+150) == 2.5
        assert _american_odds_to_decimal(+100) == 2.0
        assert _american_odds_to_decimal(+200) == 3.0

    def test_even_money(self):
        assert _american_odds_to_decimal(+100) == 2.0


class TestHalfKellyAmount:
    """Tests for Half Kelly bet sizing."""

    def test_medium_conf_standard_odds_hits_cap(self):
        # -110, medium (57%): kelly=9.7%, half=4.8% → capped at 3%
        amount = _half_kelly_amount(-110, "medium", 1000.0)
        assert amount == 30.0

    def test_low_conf_standard_odds(self):
        # -110, low (54%): kelly=3.4%, half=1.7%
        amount = _half_kelly_amount(-110, "low", 1000.0)
        assert 15.0 < amount < 20.0

    def test_high_conf_standard_odds_hits_cap(self):
        # -110, high (65%): massive kelly → capped at 3%
        amount = _half_kelly_amount(-110, "high", 1000.0)
        assert amount == 30.0

    def test_no_edge_heavy_favorite(self):
        # -250, high: breakeven=71.4%, our 65% → no edge
        assert _half_kelly_amount(-250, "high", 1000.0) == 0.0

    def test_no_edge_medium_moderate_fav(self):
        # -150, medium: breakeven=60%, our 57% → no edge
        assert _half_kelly_amount(-150, "medium", 1000.0) == 0.0

    def test_positive_edge_high_moderate_fav(self):
        # -150, high: 65% vs 60% breakeven → edge exists
        amount = _half_kelly_amount(-150, "high", 1000.0)
        assert amount > 0

    def test_underdog_hits_cap(self):
        # +200, high: huge kelly → capped at 3%
        amount = _half_kelly_amount(+200, "high", 1000.0)
        assert amount == 30.0

    def test_zero_bankroll(self):
        assert _half_kelly_amount(-110, "high", 0.0) == 0.0

    def test_unknown_confidence_defaults_to_low(self):
        amount = _half_kelly_amount(-110, "unknown", 1000.0)
        assert amount == _half_kelly_amount(-110, "low", 1000.0)

    def test_scales_with_bankroll(self):
        small = _half_kelly_amount(-110, "low", 500.0)
        large = _half_kelly_amount(-110, "low", 2000.0)
        assert large == pytest.approx(small * 4, abs=0.02)


class TestFallbackSizing:
    """Tests for Kelly-based fallback sizing."""

    def test_sizes_bets_with_edge(self):
        bets = [
            {"id": "1", "matchup": "A @ B", "bet_type": "spread", "pick": "B",
             "confidence": "medium", "units": 1.0, "odds_price": -110,
             "reasoning": "test", "primary_edge": "test"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) == 1
        assert result[0]["amount"] > 0

    def test_drops_no_edge_bets(self):
        bets = [
            {"id": "1", "matchup": "A @ B", "bet_type": "moneyline", "pick": "B",
             "confidence": "medium", "units": 1.0, "odds_price": -250,
             "reasoning": "test", "primary_edge": "test"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) == 0

    def test_defaults_odds_when_missing(self):
        bets = [
            {"id": "1", "matchup": "A @ B", "bet_type": "spread", "pick": "B",
             "confidence": "high", "units": 2.0,
             "reasoning": "test", "primary_edge": "test"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) == 1
        assert result[0]["amount"] == 30.0  # 3% cap at -110 default


class TestExtractPolyAndOddsPrice:
    """Tests for _extract_poly_and_odds_price using Polymarket prices."""

    GAME_WITH_POLY = {
        "matchup": {"home_team": "Phoenix Suns", "team1": "Phoenix Suns", "team2": "Dallas Mavericks"},
        "polymarket_odds": {
            "moneyline": {"outcomes": ["Mavericks", "Suns"], "prices": [0.40, 0.60]},
            "available_spreads": [
                {"line": -4.5, "outcomes": ["Suns", "Mavericks"], "prices": [0.52, 0.48]},
            ],
            "available_totals": [
                {"line": 224.5, "outcomes": ["Over", "Under"], "prices": [0.51, 0.49]},
            ],
        },
    }

    def test_moneyline(self):
        bet = {"bet_type": "moneyline", "pick": "Phoenix Suns", "matchup": "Dallas Mavericks @ Phoenix Suns"}
        poly_price, odds_price = _extract_poly_and_odds_price(self.GAME_WITH_POLY, bet)
        assert poly_price == 0.60
        assert odds_price == -150  # derived from poly_price_to_american(0.60)

    def test_total(self):
        bet = {"bet_type": "total", "pick": "over", "line": 224.5, "matchup": "Dallas Mavericks @ Phoenix Suns"}
        poly_price, odds_price = _extract_poly_and_odds_price(self.GAME_WITH_POLY, bet)
        assert poly_price == 0.51
        assert odds_price < 0  # ~-104

    def test_no_poly_line_returns_none(self):
        bet = {"bet_type": "spread", "pick": "Phoenix Suns", "line": -6.5, "matchup": "Dallas Mavericks @ Phoenix Suns"}
        poly_price, odds_price = _extract_poly_and_odds_price(self.GAME_WITH_POLY, bet)
        assert poly_price is None
        assert odds_price == -110  # default

    def test_no_polymarket_odds_returns_none(self):
        game = {"matchup": {"home_team": "Phoenix Suns"}}
        bet = {"bet_type": "moneyline", "pick": "Phoenix Suns", "matchup": "Dallas Mavericks @ Phoenix Suns"}
        poly_price, odds_price = _extract_poly_and_odds_price(game, bet)
        assert poly_price is None
        assert odds_price == -110  # default
