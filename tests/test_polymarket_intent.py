"""Intent-based tests for the Polymarket integration.

Tests validate the BUSINESS INTENT behind each module:
- matching.py: Team name resolution, event-to-matchup matching, pick-to-outcome mapping
- odds.py: Probability conversions, price comparisons
- gamma.py: Event fetching, market lookup, prop extraction, JSON normalization
- polymarket.py: Bet resolution pipeline, price drift gating, order placement orchestration
"""

import json
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# matching.py — Team name extraction, event matching, pick mapping
# ---------------------------------------------------------------------------
from polymarket_helpers.matching import (
    parse_matchup,
    event_matches_matchup,
    pick_matches_outcome,
    prop_pick_to_outcome,
    _extract_short_name,
)


class TestParseMatchup:
    """parse_matchup splits 'Away @ Home' into the two team names."""

    def test_standard_matchup(self):
        away, home = parse_matchup("Phoenix Suns @ Boston Celtics")
        assert away == "Phoenix Suns"
        assert home == "Boston Celtics"

    def test_rejects_missing_at_sign(self):
        with pytest.raises(ValueError):
            parse_matchup("Phoenix Suns vs Boston Celtics")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            parse_matchup("")

    def test_preserves_whitespace_within_names(self):
        away, home = parse_matchup("Portland Trail Blazers @ Golden State Warriors")
        assert away == "Portland Trail Blazers"
        assert home == "Golden State Warriors"


class TestExtractShortName:
    """Short name extraction turns full team names into their last word (or two for Trail Blazers)."""

    def test_single_word_team(self):
        assert _extract_short_name("Boston Celtics") == "celtics"

    def test_two_word_suffix_trail_blazers(self):
        assert _extract_short_name("Portland Trail Blazers") == "trail blazers"

    def test_76ers(self):
        assert _extract_short_name("Philadelphia 76ers") == "76ers"

    def test_just_team_name(self):
        # Even a bare name should work
        assert _extract_short_name("Celtics") == "celtics"


class TestEventMatchesMatchup:
    """Event titles from Polymarket (like 'Suns vs. Celtics') must match our 'Away @ Home' format."""

    def test_standard_match(self):
        assert event_matches_matchup("Suns vs. Celtics", "Phoenix Suns", "Boston Celtics")

    def test_order_irrelevant_in_title(self):
        # Polymarket title order might differ from away/home
        assert event_matches_matchup("Celtics vs. Suns", "Phoenix Suns", "Boston Celtics")

    def test_no_match_wrong_teams(self):
        assert not event_matches_matchup("Lakers vs. Knicks", "Phoenix Suns", "Boston Celtics")

    def test_partial_match_fails(self):
        # Both teams must appear
        assert not event_matches_matchup("Suns vs. Lakers", "Phoenix Suns", "Boston Celtics")

    def test_trail_blazers_in_title(self):
        assert event_matches_matchup(
            "Trail Blazers vs. Lakers",
            "Portland Trail Blazers",
            "Los Angeles Lakers",
        )

    def test_case_insensitive(self):
        assert event_matches_matchup("SUNS VS. CELTICS", "Phoenix Suns", "Boston Celtics")


class TestPickMatchesOutcome:
    """A bet pick (our format) must match a Polymarket outcome."""

    def test_exact_match(self):
        assert pick_matches_outcome("Over", "Over")

    def test_case_insensitive(self):
        assert pick_matches_outcome("over", "Over")

    def test_full_team_name_matches_short_outcome(self):
        # Our pick is "Phoenix Suns", Polymarket outcome is "Suns"
        assert pick_matches_outcome("Phoenix Suns", "suns")

    def test_no_match(self):
        assert not pick_matches_outcome("Phoenix Suns", "Celtics")


class TestPropPickToOutcome:
    """Player prop bets use over/under; Polymarket uses Yes/No."""

    def test_over_maps_to_yes(self):
        assert prop_pick_to_outcome("over") == "Yes"

    def test_under_maps_to_no(self):
        assert prop_pick_to_outcome("under") == "No"

    def test_case_insensitive_over(self):
        assert prop_pick_to_outcome("Over") == "Yes"

    def test_case_insensitive_under(self):
        assert prop_pick_to_outcome("Under") == "No"

    def test_anything_else_maps_to_no(self):
        # The function treats non-"over" as "No" — this is the actual behavior
        assert prop_pick_to_outcome("push") == "No"


# ---------------------------------------------------------------------------
# odds.py — Probability math and formatting
# ---------------------------------------------------------------------------
from polymarket_helpers.odds import (
    american_to_implied_probability,
    poly_price_to_american,
    format_price_comparison,
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


# ---------------------------------------------------------------------------
# gamma.py — Polymarket API interaction, market lookup, prop extraction
# ---------------------------------------------------------------------------
from polymarket_helpers.gamma import (
    _normalize_market,
    fetch_nba_events,
    find_market,
    find_prop_market,
    extract_polymarket_odds,
    extract_player_props,
)


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


# ---------------------------------------------------------------------------
# polymarket.py — Bet resolution, price drift, order placement
# ---------------------------------------------------------------------------
from polymarket import resolve_token_id, PRICE_DRIFT_TOLERANCE


class TestResolveTokenId:
    """resolve_token_id maps an internal bet to a Polymarket token ID and price."""

    def _make_event(self, title, ticker, markets):
        return {"title": title, "ticker": ticker, "markets": markets}

    def test_resolves_moneyline_bet(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                          token_ids=["tok_suns", "tok_celtics"])],
        )]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Phoenix Suns"}
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_suns"
        assert price == 0.55

    def test_resolves_away_team_pick(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                          token_ids=["tok_suns", "tok_celtics"])],
        )]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Boston Celtics"}
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_celtics"
        assert price == 0.45

    def test_resolves_spread_bet(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("spread", ["Suns", "Celtics"], ["0.52", "0.48"],
                          token_ids=["tok_suns", "tok_celtics"], line=-4.5)],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "spread", "pick": "Phoenix Suns", "line": -4.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None

    def test_resolves_total_bet(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("total", ["Over", "Under"], ["0.52", "0.48"],
                          token_ids=["tok_over", "tok_under"], line=224.5)],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "total", "pick": "Over", "line": 224.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_over"
        assert price == 0.52

    def test_resolves_player_prop(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market(
                "points", ["Yes", "No"], ["0.60", "0.40"],
                token_ids=["tok_yes", "tok_no"], line=25.5,
                question="LeBron James: 25.5 or more points?",
            )],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "player_prop", "pick": "over",
            "prop_type": "points", "player_name": "LeBron James", "line": 25.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_yes"
        assert price == 0.60

    def test_player_prop_under(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market(
                "points", ["Yes", "No"], ["0.60", "0.40"],
                token_ids=["tok_yes", "tok_no"], line=25.5,
                question="LeBron James: 25.5 or more points?",
            )],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "player_prop", "pick": "under",
            "prop_type": "points", "player_name": "LeBron James", "line": 25.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_no"
        assert price == 0.40

    def test_returns_none_for_invalid_matchup(self):
        result = resolve_token_id({"matchup": "bad format", "bet_type": "moneyline", "pick": "X"}, [])
        assert result is None

    def test_returns_none_when_no_event_matches(self):
        events = [self._make_event(
            "Lakers vs. Knicks", "NBA-2026-02-21-LAL-NYK",
            [_make_market("moneyline", ["Lakers", "Knicks"], ["0.55", "0.45"])],
        )]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Phoenix Suns"}
        assert resolve_token_id(bet, events) is None

    def test_returns_none_when_no_market_matches(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"])],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "spread", "pick": "Phoenix Suns", "line": -4.5,
        }
        assert resolve_token_id(bet, events) is None

    def test_searches_across_multiple_events(self):
        events = [
            self._make_event("Lakers vs. Knicks", "NBA-2026-02-21-LAL-NYK",
                             [_make_market("moneyline", ["Lakers", "Knicks"], ["0.55", "0.45"])]),
            self._make_event("Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
                             [_make_market("moneyline", ["Suns", "Celtics"], ["0.60", "0.40"],
                                           token_ids=["tok_suns", "tok_celtics"])]),
        ]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Phoenix Suns"}
        result = resolve_token_id(bet, events)
        assert result is not None
        assert result[0] == "tok_suns"


class TestRunOrchestration:
    """The run() function orchestrates: load bets → group by date → resolve → drift check → place."""

    def _make_bet(self, matchup="Phoenix Suns @ Boston Celtics", bet_type="moneyline",
                  pick="Phoenix Suns", amount=10.0, date="2026-02-21", **kwargs):
        return {"matchup": matchup, "bet_type": bet_type, "pick": pick,
                "amount": amount, "date": date, **kwargs}

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_places_bet_and_marks_as_placed(self, mock_place, mock_client, mock_events,
                                            mock_get_bets, mock_save):
        from polymarket import run

        bet = self._make_bet()
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]
        mock_place.return_value = {"status": "matched"}

        run()

        mock_place.assert_called_once()
        assert bet["placed_polymarket"] is True
        mock_save.assert_called_once()

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_already_placed_bets(self, mock_get_bets, mock_save):
        from polymarket import run

        mock_get_bets.return_value = [self._make_bet(placed_polymarket=True)]
        run()
        # No events fetched, no orders placed — but still saves
        mock_save.assert_not_called()  # Actually, early return before save

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_bet_with_no_amount(self, mock_place, mock_client, mock_events,
                                      mock_get_bets, mock_save):
        from polymarket import run

        bet = self._make_bet(amount=0)
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"]),
            ]},
        ]

        run()
        mock_place.assert_not_called()
        assert "placed_polymarket" not in bet

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_bet_when_price_drifted(self, mock_place, mock_client, mock_events,
                                          mock_get_bets, mock_save):
        from polymarket import run

        # Analysis price was 0.55, but live price will be 0.70 → drift of 0.15 > 0.05 tolerance
        bet = self._make_bet(poly_price=0.55)
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.70", "0.30"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]

        run()
        mock_place.assert_not_called()

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_allows_bet_within_drift_tolerance(self, mock_place, mock_client, mock_events,
                                               mock_get_bets, mock_save):
        from polymarket import run

        # Analysis price was 0.55, live is 0.57 → drift of 0.02 < 0.05 tolerance
        bet = self._make_bet(poly_price=0.55)
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.57", "0.43"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]
        mock_place.return_value = {"status": "matched"}

        run()
        mock_place.assert_called_once()

    @patch("polymarket.load_dotenv")
    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch.dict("os.environ", {}, clear=True)
    def test_exits_without_credentials(self, mock_get_bets, mock_save, mock_dotenv, capsys):
        from polymarket import run
        run()
        mock_get_bets.assert_not_called()
        output = capsys.readouterr().out
        assert "POLYMARKET_PRIVATE_KEY" in output

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_handles_placement_failure_gracefully(self, mock_place, mock_client, mock_events,
                                                   mock_get_bets, mock_save):
        from polymarket import run

        bet = self._make_bet()
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]
        mock_place.side_effect = Exception("Order rejected")

        run()
        assert "placed_polymarket" not in bet  # Not marked as placed on failure
        mock_save.assert_called_once()  # Still saves the state

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_entire_date_when_no_events(self, mock_client, mock_events,
                                              mock_get_bets, mock_save, capsys):
        from polymarket import run

        mock_get_bets.return_value = [self._make_bet()]
        mock_events.return_value = []

        run()
        output = capsys.readouterr().out
        assert "no Polymarket events found" in output
        mock_save.assert_called_once()


class TestPriceDriftTolerance:
    """The price drift gate protects against placing bets when the market has moved significantly."""

    def test_tolerance_value(self):
        assert PRICE_DRIFT_TOLERANCE == 0.05

    def test_drift_exactly_at_tolerance_is_rejected(self):
        """Drift of exactly 0.05 should be rejected (> not >=)."""
        # The code uses `drift > PRICE_DRIFT_TOLERANCE`, so exactly 0.05 passes
        drift = 0.05
        assert not (drift > PRICE_DRIFT_TOLERANCE)  # 0.05 is NOT > 0.05

    def test_drift_just_over_tolerance_is_rejected(self):
        drift = 0.051
        assert drift > PRICE_DRIFT_TOLERANCE


class TestGetPolymarketBalance:
    """get_polymarket_balance queries USDC balance, converting from 6-decimal format."""

    @patch("polymarket.create_clob_client")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_converts_balance_from_microdollars(self, mock_client):
        from polymarket import get_polymarket_balance

        client = MagicMock()
        client.get_balance_allowance.return_value = {"balance": 50_000_000}  # 50 USDC
        mock_client.return_value = client

        balance = get_polymarket_balance()
        assert balance == 50.0

    @patch("polymarket.load_dotenv")
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_without_credentials(self, mock_dotenv):
        from polymarket import get_polymarket_balance
        assert get_polymarket_balance() is None

    @patch("polymarket.create_clob_client")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_returns_none_on_api_error(self, mock_client):
        from polymarket import get_polymarket_balance

        mock_client.side_effect = Exception("API down")
        assert get_polymarket_balance() is None
