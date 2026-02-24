import json
from unittest.mock import MagicMock, patch, call

import pytest

from polymarket_helpers.odds import (
    american_to_implied_probability,
    poly_price_to_american,
    format_price_comparison,
)

from polymarket_helpers.gamma import (
    _normalize_market,
    fetch_nba_events,
    find_market,
    find_prop_market,
    extract_polymarket_odds,
    extract_player_props,
)


class TestAmericanToImpliedProbability:
    """American odds encode implied probability differently for favorites and underdogs."""

    def test_heavy_favorite(self):
        # -200 means you risk $200 to win $100 → ~66.7% implied
        prob = american_to_implied_probability(-200)
        assert abs(prob - 2 / 3) < 0.001

    def test_even_money(self):
        # +100 means risk $100 to win $100 → 50%
        prob = american_to_implied_probability(100)
        assert prob == 0.5

    def test_underdog(self):
        # +200 means risk $100 to win $200 → ~33.3%
        prob = american_to_implied_probability(200)
        assert abs(prob - 1 / 3) < 0.001

    def test_extreme_favorite(self):
        # -1000 → ~90.9%
        prob = american_to_implied_probability(-1000)
        assert abs(prob - 10 / 11) < 0.001

    def test_standard_vig_line(self):
        # -110 is standard → ~52.4%
        prob = american_to_implied_probability(-110)
        assert abs(prob - 110 / 210) < 0.001


class TestPolyPriceToAmerican:
    """Convert Polymarket's decimal price (0-1) to American odds format."""

    def test_even_money(self):
        assert poly_price_to_american(0.5) == 100

    def test_favorite(self):
        # 0.6 → should be negative odds (favorite)
        result = poly_price_to_american(0.6)
        assert result < 0

    def test_underdog(self):
        # 0.3 → should be positive odds (underdog)
        result = poly_price_to_american(0.3)
        assert result > 0

    def test_heavy_favorite(self):
        # 0.8 → -400
        result = poly_price_to_american(0.8)
        assert result == -400

    def test_edge_case_zero(self):
        # Invalid price returns fallback
        result = poly_price_to_american(0)
        assert result == -110

    def test_edge_case_one(self):
        result = poly_price_to_american(1)
        assert result == -110

    def test_roundtrip_consistency(self):
        """Converting price→american→implied should approximate the original price."""
        for price in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
            american = poly_price_to_american(price)
            implied = american_to_implied_probability(american)
            assert abs(implied - price) < 0.02, f"Roundtrip failed for {price}: {implied}"


class TestFormatPriceComparison:
    """Format a human-readable comparison between our odds and Polymarket's price."""

    def test_positive_delta(self):
        result = format_price_comparison(-150, 0.55)
        assert "Our implied:" in result
        assert "Polymarket:" in result
        assert "delta:" in result
        assert "+" in result  # our implied > poly

    def test_negative_delta(self):
        result = format_price_comparison(200, 0.50)
        # +200 → 33.3% implied, poly at 50% → delta is negative
        assert "-" in result

    def test_equal_probabilities(self):
        result = format_price_comparison(-110, 0.524)
        # Should be approximately zero delta
        assert "delta:" in result


class TestNormalizeMarket:
    """Polymarket returns some fields as JSON strings; normalization parses them into lists."""

    def test_parses_json_strings(self):
        market = {
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.6", "0.4"]',
            "clobTokenIds": '["abc", "def"]',
        }
        _normalize_market(market)
        assert market["outcomes"] == ["Yes", "No"]
        assert market["outcomePrices"] == ["0.6", "0.4"]
        assert market["clobTokenIds"] == ["abc", "def"]

    def test_already_parsed_is_idempotent(self):
        market = {
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["0.6", "0.4"],
            "clobTokenIds": ["abc", "def"],
        }
        _normalize_market(market)
        assert market["outcomes"] == ["Yes", "No"]

    def test_missing_fields_are_safe(self):
        market = {"outcomes": '["Yes"]'}
        _normalize_market(market)
        assert market["outcomes"] == ["Yes"]
        # Other fields simply aren't present — no crash

    def test_mutates_in_place(self):
        market = {"outcomes": '["A", "B"]'}
        result = _normalize_market(market)
        assert result is market  # same object


class TestFetchNbaEvents:
    """fetch_nba_events hits the Gamma API and filters events by date in the ticker field."""

    @patch("polymarket_helpers.gamma.requests.get")
    def test_filters_by_date_in_ticker(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"ticker": "NBA-2026-02-21-PHX-BOS", "title": "Suns vs. Celtics"},
            {"ticker": "NBA-2026-02-22-LAL-NYK", "title": "Lakers vs. Knicks"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_nba_events("2026-02-21")
        assert len(result) == 1
        assert result[0]["title"] == "Suns vs. Celtics"

    @patch("polymarket_helpers.gamma.requests.get")
    def test_returns_empty_on_api_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.RequestException("Network error")
        result = fetch_nba_events("2026-02-21")
        assert result == []

    @patch("polymarket_helpers.gamma.requests.get")
    def test_returns_empty_when_no_events_match_date(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"ticker": "NBA-2026-02-20-PHX-BOS"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_nba_events("2026-02-21")
        assert result == []


def _make_market(
    sport_type: str,
    outcomes: list[str],
    prices: list[str],
    token_ids: list[str] | None = None,
    line: float | None = None,
    accepting: bool = True,
    question: str = "",
):
    """Helper to build a Polymarket market dict."""
    m = {
        "sportsMarketType": sport_type,
        "outcomes": json.dumps(outcomes),
        "outcomePrices": json.dumps(prices),
        "clobTokenIds": json.dumps(token_ids or [f"tok_{i}" for i in range(len(outcomes))]),
        "acceptingOrders": accepting,
    }
    if line is not None:
        m["line"] = str(line)
    if question:
        m["question"] = question
    return m


class TestFindMarket:
    """find_market locates the right market in an event by bet type and line."""

    def test_finds_moneyline(self):
        event = {"markets": [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"])]}
        market = find_market(event, "moneyline", None)
        assert market is not None
        assert market["outcomes"] == ["Suns", "Celtics"]

    def test_moneyline_ignores_line(self):
        """Moneyline bets don't use a line — should match regardless."""
        event = {"markets": [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"])]}
        market = find_market(event, "moneyline", 5.5)
        assert market is not None

    def test_spread_requires_exact_line(self):
        event = {"markets": [
            _make_market("spread", ["Suns", "Celtics"], ["0.55", "0.45"], line=-4.5),
            _make_market("spread", ["Suns", "Celtics"], ["0.50", "0.50"], line=-6.5),
        ]}
        market = find_market(event, "spread", -4.5)
        assert market is not None
        assert float(market["outcomePrices"][0]) == 0.55

    def test_spread_no_match_wrong_line(self):
        event = {"markets": [
            _make_market("spread", ["Suns", "Celtics"], ["0.55", "0.45"], line=-4.5),
        ]}
        assert find_market(event, "spread", -7.5) is None

    def test_total_requires_exact_line(self):
        event = {"markets": [
            _make_market("total", ["Over", "Under"], ["0.52", "0.48"], line=224.5),
        ]}
        market = find_market(event, "total", 224.5)
        assert market is not None

    def test_skips_non_accepting_markets(self):
        event = {"markets": [
            _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"], accepting=False),
        ]}
        assert find_market(event, "moneyline", None) is None

    def test_skips_accepting_false_string(self):
        """acceptingOrders can be a string 'false' instead of a boolean."""
        market = _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"])
        market["acceptingOrders"] = "false"
        event = {"markets": [market]}
        assert find_market(event, "moneyline", None) is None

    def test_unknown_bet_type_returns_none(self):
        event = {"markets": [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"])]}
        assert find_market(event, "unknown_type", None) is None

    def test_spread_with_no_line_returns_none(self):
        """Spread bets MUST have a line to match."""
        event = {"markets": [
            _make_market("spread", ["Suns", "Celtics"], ["0.55", "0.45"], line=-4.5),
        ]}
        assert find_market(event, "spread", None) is None

    def test_totals_alias(self):
        """Both 'total' and 'totals' sportsMarketType should match."""
        event = {"markets": [
            _make_market("totals", ["Over", "Under"], ["0.52", "0.48"], line=224.5),
        ]}
        market = find_market(event, "total", 224.5)
        assert market is not None

    def test_spreads_alias(self):
        event = {"markets": [
            _make_market("spreads", ["Suns", "Celtics"], ["0.55", "0.45"], line=-4.5),
        ]}
        market = find_market(event, "spread", -4.5)
        assert market is not None


class TestFindPropMarket:
    """find_prop_market locates player prop markets using fuzzy name matching."""

    def test_finds_by_player_and_line(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        result = find_prop_market(event, "points", "LeBron James", 25.5)
        assert result is not None

    def test_no_match_wrong_player(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        result = find_prop_market(event, "points", "Stephen Curry", 25.5)
        assert result is None

    def test_no_match_wrong_line(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        result = find_prop_market(event, "points", "LeBron James", 30.5)
        assert result is None

    def test_no_match_wrong_prop_type(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        result = find_prop_market(event, "rebounds", "LeBron James", 25.5)
        assert result is None

    def test_skips_non_accepting(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5, accepting=False,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        result = find_prop_market(event, "points", "LeBron James", 25.5)
        assert result is None

    def test_none_line_matches_any(self):
        """When line is None, only player name and prop type must match."""
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        result = find_prop_market(event, "points", "LeBron James", None)
        assert result is not None

    def test_skips_market_without_colon_in_question(self):
        """Player name is extracted from question before the colon."""
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="Some market without player name format",
            ),
        ]}
        result = find_prop_market(event, "points", "LeBron James", 25.5)
        assert result is None


class TestExtractPolymarketOdds:
    """extract_polymarket_odds collects all accepting markets from an event into a structured dict."""

    def test_extracts_moneyline(self):
        event = {"markets": [
            _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"]),
        ]}
        result = extract_polymarket_odds(event)
        assert "moneyline" in result
        assert result["moneyline"]["prices"] == [0.55, 0.45]

    def test_extracts_multiple_spreads(self):
        event = {"markets": [
            _make_market("spread", ["Suns", "Celtics"], ["0.55", "0.45"], line=-4.5),
            _make_market("spread", ["Suns", "Celtics"], ["0.50", "0.50"], line=-6.5),
        ]}
        result = extract_polymarket_odds(event)
        assert len(result["available_spreads"]) == 2
        lines = {s["line"] for s in result["available_spreads"]}
        assert lines == {-4.5, -6.5}

    def test_extracts_totals(self):
        event = {"markets": [
            _make_market("total", ["Over", "Under"], ["0.52", "0.48"], line=224.5),
        ]}
        result = extract_polymarket_odds(event)
        assert len(result["available_totals"]) == 1
        assert result["available_totals"][0]["line"] == 224.5

    def test_skips_non_accepting_markets(self):
        event = {"markets": [
            _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"], accepting=False),
        ]}
        result = extract_polymarket_odds(event)
        assert "moneyline" not in result

    def test_empty_event(self):
        result = extract_polymarket_odds({"markets": []})
        assert result == {}

    def test_no_markets_key(self):
        result = extract_polymarket_odds({})
        assert result == {}


class TestExtractPlayerProps:
    """extract_player_props pulls out all player prop markets from an event."""

    def test_extracts_points_prop(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        props = extract_player_props(event)
        assert len(props) == 1
        assert props[0]["player_name"] == "LeBron James"
        assert props[0]["prop_type"] == "points"
        assert props[0]["line"] == 25.5

    def test_extracts_rebounds_and_assists(self):
        event = {"markets": [
            _make_market(
                "rebounds", ["Yes", "No"], ["0.50", "0.50"],
                line=10.5,
                question="Anthony Davis: 10.5 or more rebounds?",
            ),
            _make_market(
                "assists", ["Yes", "No"], ["0.45", "0.55"],
                line=7.5,
                question="LeBron James: 7.5 or more assists?",
            ),
        ]}
        props = extract_player_props(event)
        assert len(props) == 2
        types = {p["prop_type"] for p in props}
        assert types == {"rebounds", "assists"}

    def test_ignores_moneyline_markets(self):
        """Only prop types (points, rebounds, assists) should be extracted."""
        event = {"markets": [
            _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"]),
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        props = extract_player_props(event)
        assert len(props) == 1
        assert props[0]["prop_type"] == "points"

    def test_skips_non_accepting_props(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5, accepting=False,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        props = extract_player_props(event)
        assert props == []

    def test_skips_question_without_colon(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                line=25.5,
                question="Total points over 25.5",
            ),
        ]}
        props = extract_player_props(event)
        assert props == []

    def test_includes_clob_token_ids(self):
        event = {"markets": [
            _make_market(
                "points", ["Yes", "No"], ["0.55", "0.45"],
                token_ids=["tok_yes", "tok_no"],
                line=25.5,
                question="LeBron James: 25.5 or more points?",
            ),
        ]}
        props = extract_player_props(event)
        assert props[0]["clob_token_ids"] == ["tok_yes", "tok_no"]
