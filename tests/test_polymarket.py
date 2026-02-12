import pytest
from polymarket_helpers.odds import american_to_implied_probability, format_price_comparison, poly_price_to_american


class TestAmericanToImpliedProbability:
    def test_standard_negative(self):
        assert american_to_implied_probability(-110) == pytest.approx(0.5238, abs=0.001)

    def test_heavy_favorite(self):
        assert american_to_implied_probability(-200) == pytest.approx(0.6667, abs=0.001)

    def test_even_money(self):
        assert american_to_implied_probability(+100) == 0.5

    def test_underdog(self):
        assert american_to_implied_probability(+150) == pytest.approx(0.4, abs=0.001)


class TestFormatPriceComparison:
    def test_positive_delta(self):
        result = format_price_comparison(-110, 0.48)
        assert "52.4%" in result and "48.0%" in result and "+4.4pp" in result

    def test_negative_delta(self):
        result = format_price_comparison(+150, 0.55)
        assert "40.0%" in result and "-15.0pp" in result


class TestPolyPriceToAmerican:
    def test_favorite_60_pct(self):
        assert poly_price_to_american(0.60) == -150

    def test_even_money(self):
        assert poly_price_to_american(0.50) == 100

    def test_underdog_40_pct(self):
        assert poly_price_to_american(0.40) == 150

    def test_heavy_favorite(self):
        assert poly_price_to_american(0.80) == -400

    def test_heavy_underdog(self):
        assert poly_price_to_american(0.20) == 400

    def test_boundary_zero(self):
        assert poly_price_to_american(0.0) == -110  # fallback

    def test_boundary_one(self):
        assert poly_price_to_american(1.0) == -110  # fallback

    def test_roundtrip_favorite(self):
        """Converting to American and back should approximate the original."""
        original = 0.65
        american = poly_price_to_american(original)
        roundtrip = american_to_implied_probability(american)
        assert roundtrip == pytest.approx(original, abs=0.01)

    def test_roundtrip_underdog(self):
        original = 0.35
        american = poly_price_to_american(original)
        roundtrip = american_to_implied_probability(american)
        assert roundtrip == pytest.approx(original, abs=0.01)


from polymarket_helpers.matching import (
    _extract_short_name, parse_matchup, event_matches_matchup, pick_matches_outcome,
)


class TestExtractShortName:
    def test_standard(self):
        assert _extract_short_name("Phoenix Suns") == "suns"

    def test_two_word_city(self):
        assert _extract_short_name("San Antonio Spurs") == "spurs"

    def test_trail_blazers(self):
        assert _extract_short_name("Portland Trail Blazers") == "trail blazers"

    def test_76ers(self):
        assert _extract_short_name("Philadelphia 76ers") == "76ers"

    def test_already_short(self):
        assert _extract_short_name("Suns") == "suns"


class TestParseMatchup:
    def test_standard(self):
        away, home = parse_matchup("Dallas Mavericks @ Phoenix Suns")
        assert away == "Dallas Mavericks" and home == "Phoenix Suns"

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_matchup("Dallas vs Phoenix")


class TestEventMatchesMatchup:
    def test_match(self):
        assert event_matches_matchup("Mavericks vs. Suns", "Dallas Mavericks", "Phoenix Suns")

    def test_reversed(self):
        assert event_matches_matchup("Suns vs. Mavericks", "Dallas Mavericks", "Phoenix Suns")

    def test_no_match(self):
        assert not event_matches_matchup("Lakers vs. Celtics", "Dallas Mavericks", "Phoenix Suns")

    def test_partial_no_match(self):
        assert not event_matches_matchup("Suns vs. Lakers", "Dallas Mavericks", "Phoenix Suns")

    def test_nets_not_in_hornets(self):
        assert not event_matches_matchup("Hornets vs. Celtics", "Brooklyn Nets", "Charlotte Hornets")

    def test_nets_vs_hornets(self):
        assert event_matches_matchup("Nets vs. Hornets", "Brooklyn Nets", "Charlotte Hornets")

    def test_trail_blazers(self):
        assert event_matches_matchup("Trail Blazers vs. Timberwolves", "Portland Trail Blazers", "Minnesota Timberwolves")


class TestPickMatchesOutcome:
    def test_full_to_short(self):
        assert pick_matches_outcome("Phoenix Suns", "Suns")

    def test_over_under(self):
        assert pick_matches_outcome("over", "Over")
        assert pick_matches_outcome("under", "Under")

    def test_no_match(self):
        assert not pick_matches_outcome("Phoenix Suns", "Lakers")


from unittest.mock import patch, MagicMock
from polymarket_helpers.gamma import fetch_nba_events, find_market

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
        {
            "id": "1004", "sportsMarketType": "totals", "line": 226.5,
            "outcomes": ["Over", "Under"],
            "outcomePrices": ["0.47", "0.53"],
            "clobTokenIds": ["token_i", "token_j"],
            "acceptingOrders": False,
        },
    ],
}


class TestFetchNbaEvents:
    @patch("polymarket_helpers.gamma.requests.get")
    def test_filters_by_date(self, mock_get):
        other_event = {
            "ticker": "nba-lal-bos-2026-02-12",
            "title": "Lakers vs. Celtics",
            "markets": [],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = [SAMPLE_EVENT, other_event]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = fetch_nba_events("2026-02-11")
        assert len(result) == 1
        assert result[0]["title"] == "Mavericks vs. Suns"

    @patch("polymarket_helpers.gamma.requests.get")
    def test_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        assert fetch_nba_events("2026-02-11") == []


class TestFindMarket:
    def test_moneyline(self):
        m = find_market(SAMPLE_EVENT, "moneyline", None)
        assert m["id"] == "1001"

    def test_spread_exact_line(self):
        m = find_market(SAMPLE_EVENT, "spread", -4.5)
        assert m["id"] == "1002"

    def test_spread_wrong_line(self):
        assert find_market(SAMPLE_EVENT, "spread", -3.5) is None

    def test_total_exact_line(self):
        m = find_market(SAMPLE_EVENT, "total", 224.5)
        assert m["id"] == "1003"

    def test_total_not_accepting(self):
        assert find_market(SAMPLE_EVENT, "total", 226.5) is None

    def test_unknown_type(self):
        assert find_market(SAMPLE_EVENT, "prop", None) is None


from polymarket import resolve_token_id


def _make_bet(**overrides) -> dict:
    base = {
        "id": "bet-001",
        "game_id": "12345",
        "matchup": "Dallas Mavericks @ Phoenix Suns",
        "bet_type": "moneyline",
        "pick": "Phoenix Suns",
        "line": None,
        "confidence": "high",
        "units": 2.0,
        "reasoning": "test",
        "primary_edge": "test",
        "date": "2026-02-11",
        "created_at": "2026-02-11T00:00:00",
        "amount": 22.0,
        "odds_price": -110,
    }
    base.update(overrides)
    return base


class TestResolveTokenId:
    def test_moneyline_home(self):
        bet = _make_bet(pick="Phoenix Suns")
        result = resolve_token_id(bet, [SAMPLE_EVENT])
        assert result == ("token_b", 0.60)

    def test_moneyline_away(self):
        bet = _make_bet(pick="Dallas Mavericks")
        result = resolve_token_id(bet, [SAMPLE_EVENT])
        assert result == ("token_a", 0.40)

    def test_spread(self):
        bet = _make_bet(bet_type="spread", pick="Phoenix Suns", line=-4.5)
        result = resolve_token_id(bet, [SAMPLE_EVENT])
        assert result == ("token_c", 0.52)

    def test_total_over(self):
        bet = _make_bet(bet_type="total", pick="over", line=224.5)
        result = resolve_token_id(bet, [SAMPLE_EVENT])
        assert result == ("token_g", 0.51)

    def test_total_under(self):
        bet = _make_bet(bet_type="total", pick="under", line=224.5)
        result = resolve_token_id(bet, [SAMPLE_EVENT])
        assert result == ("token_h", 0.49)

    def test_no_matching_event(self):
        bet = _make_bet(matchup="Chicago Bulls @ Boston Celtics")
        assert resolve_token_id(bet, [SAMPLE_EVENT]) is None

    def test_empty_events(self):
        bet = _make_bet()
        assert resolve_token_id(bet, []) is None


class TestRun:
    @patch("polymarket.save_active_bets")
    @patch("polymarket.place_bet")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.get_active_bets")
    def test_run_places_bets(self, mock_get_bets, mock_fetch, mock_place, mock_save):
        bet = _make_bet()
        mock_get_bets.return_value = [bet]
        mock_fetch.return_value = [SAMPLE_EVENT]
        mock_place.return_value = {"status": "matched"}

        from polymarket import run
        with patch.dict("os.environ", {
            "POLYMARKET_PRIVATE_KEY": "0x" + "ab" * 32,
            "POLYMARKET_FUNDER": "0x" + "cd" * 20,
        }):
            with patch("polymarket.create_clob_client") as mock_client:
                run()

        mock_place.assert_called_once()
        args = mock_place.call_args
        assert args[0][1] == "token_b"  # token_id
        assert args[0][2] == 22.0  # amount
        assert bet["placed_polymarket"] is True
        mock_save.assert_called_once()

    @patch("polymarket.save_active_bets")
    @patch("polymarket.place_bet")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.get_active_bets")
    def test_skips_already_placed(self, mock_get_bets, mock_fetch, mock_place, mock_save):
        """Bets with placed_polymarket=True are not placed again."""
        bet = _make_bet(placed_polymarket=True)
        mock_get_bets.return_value = [bet]

        from polymarket import run
        with patch.dict("os.environ", {
            "POLYMARKET_PRIVATE_KEY": "0x" + "ab" * 32,
            "POLYMARKET_FUNDER": "0x" + "cd" * 20,
        }):
            run()

        mock_place.assert_not_called()
        mock_fetch.assert_not_called()

    @patch("polymarket.save_active_bets")
    @patch("polymarket.place_bet")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.get_active_bets")
    def test_drift_gate_skips_drifted(self, mock_get_bets, mock_fetch, mock_place, mock_save):
        """Bets with price drift > 5pp are skipped."""
        bet = _make_bet(poly_price=0.60)  # analysis price was 60%
        # Live price is 0.60 but the Suns outcome is token_b at 0.60 → no drift
        # Let's make the live price differ by changing the event
        drifted_event = {
            "ticker": "nba-dal-phx-2026-02-11",
            "title": "Mavericks vs. Suns",
            "markets": [{
                "id": "1001", "sportsMarketType": "moneyline",
                "outcomes": ["Mavericks", "Suns"],
                "outcomePrices": ["0.34", "0.66"],  # drifted from 0.60 to 0.66 = 6pp
                "clobTokenIds": ["token_a", "token_b"],
                "acceptingOrders": True,
            }],
        }
        mock_get_bets.return_value = [bet]
        mock_fetch.return_value = [drifted_event]

        from polymarket import run
        with patch.dict("os.environ", {
            "POLYMARKET_PRIVATE_KEY": "0x" + "ab" * 32,
            "POLYMARKET_FUNDER": "0x" + "cd" * 20,
        }):
            with patch("polymarket.create_clob_client"):
                run()

        mock_place.assert_not_called()

    @patch("polymarket.save_active_bets")
    @patch("polymarket.place_bet")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.get_active_bets")
    def test_drift_gate_allows_small_drift(self, mock_get_bets, mock_fetch, mock_place, mock_save):
        """Bets with price drift <= 5pp are placed."""
        bet = _make_bet(poly_price=0.60)
        mock_get_bets.return_value = [bet]
        mock_fetch.return_value = [SAMPLE_EVENT]  # Suns at 0.60 → 0pp drift
        mock_place.return_value = {"status": "matched"}

        from polymarket import run
        with patch.dict("os.environ", {
            "POLYMARKET_PRIVATE_KEY": "0x" + "ab" * 32,
            "POLYMARKET_FUNDER": "0x" + "cd" * 20,
        }):
            with patch("polymarket.create_clob_client"):
                run()

        mock_place.assert_called_once()


from polymarket_helpers.gamma import extract_polymarket_odds


class TestExtractPolymarketOdds:
    def test_extracts_all_market_types(self):
        odds = extract_polymarket_odds(SAMPLE_EVENT)
        assert "moneyline" in odds
        assert odds["moneyline"]["outcomes"] == ["Mavericks", "Suns"]
        assert odds["moneyline"]["prices"] == [0.40, 0.60]

    def test_extracts_spreads(self):
        odds = extract_polymarket_odds(SAMPLE_EVENT)
        assert len(odds["available_spreads"]) == 1
        assert odds["available_spreads"][0]["line"] == -4.5

    def test_extracts_totals_skips_not_accepting(self):
        odds = extract_polymarket_odds(SAMPLE_EVENT)
        # Only line 224.5 is accepting orders, 226.5 is not
        assert len(odds["available_totals"]) == 1
        assert odds["available_totals"][0]["line"] == 224.5

    def test_empty_event(self):
        odds = extract_polymarket_odds({"markets": []})
        assert odds == {}
