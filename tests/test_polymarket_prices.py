"""Tests for workflow/polymarket_prices.py."""

import pytest
from unittest.mock import patch, MagicMock

from workflow.polymarket_prices import (
    extract_poly_price_for_bet,
    fetch_polymarket_prices,
)


SAMPLE_POLY_ODDS = {
    "moneyline": {"outcomes": ["Mavericks", "Suns"], "prices": [0.40, 0.60]},
    "available_spreads": [
        {"line": -4.5, "outcomes": ["Suns", "Mavericks"], "prices": [0.52, 0.48]},
    ],
    "available_totals": [
        {"line": 224.5, "outcomes": ["Over", "Under"], "prices": [0.51, 0.49]},
    ],
}

SAMPLE_EVENT = {
    "ticker": "nba-dal-phx-2026-02-11",
    "title": "Mavericks vs. Suns",
    "markets": [
        {
            "id": "1001", "sportsMarketType": "moneyline",
            "outcomes": ["Mavericks", "Suns"],
            "outcomePrices": ["0.40", "0.60"],
            "clobTokenIds": ["token_a", "token_b"],
            "acceptingOrders": True,
        },
        {
            "id": "1002", "sportsMarketType": "spreads", "line": -4.5,
            "outcomes": ["Suns", "Mavericks"],
            "outcomePrices": ["0.52", "0.48"],
            "clobTokenIds": ["token_c", "token_d"],
            "acceptingOrders": True,
        },
        {
            "id": "1003", "sportsMarketType": "totals", "line": 224.5,
            "outcomes": ["Over", "Under"],
            "outcomePrices": ["0.51", "0.49"],
            "clobTokenIds": ["token_g", "token_h"],
            "acceptingOrders": True,
        },
    ],
}


class TestExtractPolyPriceForBet:
    def _game(self):
        return {"polymarket_odds": SAMPLE_POLY_ODDS}

    def test_moneyline_home(self):
        price = extract_poly_price_for_bet(self._game(), "moneyline", "Phoenix Suns", None)
        assert price == 0.60

    def test_moneyline_away(self):
        price = extract_poly_price_for_bet(self._game(), "moneyline", "Dallas Mavericks", None)
        assert price == 0.40

    def test_spread(self):
        price = extract_poly_price_for_bet(self._game(), "spread", "Phoenix Suns", -4.5)
        assert price == 0.52

    def test_spread_wrong_line(self):
        price = extract_poly_price_for_bet(self._game(), "spread", "Phoenix Suns", -3.5)
        assert price is None

    def test_total_over(self):
        price = extract_poly_price_for_bet(self._game(), "total", "over", 224.5)
        assert price == 0.51

    def test_total_under(self):
        price = extract_poly_price_for_bet(self._game(), "total", "under", 224.5)
        assert price == 0.49

    def test_total_wrong_line(self):
        price = extract_poly_price_for_bet(self._game(), "total", "over", 230.5)
        assert price is None

    def test_no_polymarket_odds(self):
        price = extract_poly_price_for_bet({}, "moneyline", "Phoenix Suns", None)
        assert price is None

    def test_unknown_bet_type(self):
        price = extract_poly_price_for_bet(self._game(), "prop", "Phoenix Suns", None)
        assert price is None

    def test_moneyline_no_match(self):
        price = extract_poly_price_for_bet(self._game(), "moneyline", "Boston Celtics", None)
        assert price is None


class TestFetchPolymarketPrices:
    @patch("workflow.polymarket_prices.fetch_nba_events")
    def test_attaches_odds_to_matching_game(self, mock_fetch):
        mock_fetch.return_value = [SAMPLE_EVENT]
        games = [{
            "matchup": {
                "team1": "Phoenix Suns",
                "team2": "Dallas Mavericks",
                "home_team": "Phoenix Suns",
            },
        }]
        fetch_polymarket_prices(games, "2026-02-11")
        assert "polymarket_odds" in games[0]
        assert "moneyline" in games[0]["polymarket_odds"]

    @patch("workflow.polymarket_prices.fetch_nba_events")
    def test_no_match_no_odds(self, mock_fetch):
        mock_fetch.return_value = [SAMPLE_EVENT]
        games = [{
            "matchup": {
                "team1": "Boston Celtics",
                "team2": "Chicago Bulls",
                "home_team": "Boston Celtics",
            },
        }]
        fetch_polymarket_prices(games, "2026-02-11")
        assert "polymarket_odds" not in games[0]

    @patch("workflow.polymarket_prices.fetch_nba_events")
    def test_no_events(self, mock_fetch):
        mock_fetch.return_value = []
        games = [{
            "matchup": {
                "team1": "Phoenix Suns",
                "team2": "Dallas Mavericks",
                "home_team": "Phoenix Suns",
            },
        }]
        fetch_polymarket_prices(games, "2026-02-11")
        assert "polymarket_odds" not in games[0]

    @patch("workflow.polymarket_prices.fetch_nba_events")
    def test_missing_matchup_fields(self, mock_fetch):
        """Games with missing team info are skipped without error."""
        mock_fetch.return_value = [SAMPLE_EVENT]
        games = [{"matchup": {}}]
        fetch_polymarket_prices(games, "2026-02-11")
        assert "polymarket_odds" not in games[0]
