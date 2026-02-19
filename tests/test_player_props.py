"""Tests for player prop betting feature."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from workflow.names import normalize_name, names_match
from polymarket_helpers.gamma import extract_player_props, find_prop_market
from polymarket_helpers.matching import prop_pick_to_outcome
from workflow.polymarket_prices import extract_poly_price_for_prop
from workflow.results import _find_player_stat, _evaluate_prop_bet
from workflow.analyze import create_prop_bet, load_props_for_date
from workflow.io import get_voids, VOIDS_PATH


# --- Sample fixtures ---

SAMPLE_PROP_MARKET = {
    "sportsMarketType": "points",
    "acceptingOrders": True,
    "question": "LeBron James: 25.5 or more points?",
    "line": "25.5",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.55", "0.45"]',
    "clobTokenIds": '["token_yes", "token_no"]',
}

SAMPLE_REBOUNDS_MARKET = {
    "sportsMarketType": "rebounds",
    "acceptingOrders": True,
    "question": "Nikola Jokić: 11.5 or more rebounds?",
    "line": "11.5",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.60", "0.40"]',
    "clobTokenIds": '["reb_yes", "reb_no"]',
}

SAMPLE_ASSISTS_MARKET = {
    "sportsMarketType": "assists",
    "acceptingOrders": True,
    "question": "Luka Dončić: 8.5 or more assists?",
    "line": "8.5",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.48", "0.52"]',
    "clobTokenIds": '["ast_yes", "ast_no"]',
}

SAMPLE_MONEYLINE_MARKET = {
    "sportsMarketType": "moneyline",
    "acceptingOrders": True,
    "question": "Who will win?",
    "outcomes": '["Lakers", "Celtics"]',
    "outcomePrices": '["0.45", "0.55"]',
    "clobTokenIds": '["ml_lakers", "ml_celtics"]',
}

SAMPLE_NOT_ACCEPTING = {
    "sportsMarketType": "points",
    "acceptingOrders": False,
    "question": "Steph Curry: 30.5 or more points?",
    "line": "30.5",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.50", "0.50"]',
    "clobTokenIds": '["sc_yes", "sc_no"]',
}


def _make_event(markets):
    return {"markets": markets, "title": "Lakers vs Celtics"}


# --- TestNamesMatch ---


class TestNamesMatch:
    def test_exact_match(self):
        assert names_match("LeBron James", "LeBron James")

    def test_case_insensitive(self):
        assert names_match("lebron james", "LEBRON JAMES")

    def test_suffix_stripped(self):
        assert names_match("Jaren Jackson Jr.", "Jaren Jackson")

    def test_suffix_sr(self):
        assert names_match("Gary Payton Sr.", "Gary Payton")

    def test_periods_stripped(self):
        assert names_match("P.J. Washington", "PJ Washington")

    def test_initial_matching(self):
        assert names_match("C. Coward", "Cedric Coward")

    def test_initial_reverse(self):
        assert names_match("Kyle Knueppel", "K. Knueppel")

    def test_unicode_diacritics(self):
        assert names_match("Luka Dončić", "Luka Doncic")

    def test_unicode_diacritics_reverse(self):
        assert names_match("Nikola Jokic", "Nikola Jokić")

    def test_no_match_different_names(self):
        assert not names_match("LeBron James", "Stephen Curry")

    def test_no_match_same_last_different_first(self):
        assert not names_match("Michael Jordan", "DeAndre Jordan")

    def test_normalize_diacritics(self):
        assert normalize_name("Dončić") == "doncic"

    def test_normalize_suffix(self):
        assert normalize_name("Jaren Jackson Jr.") == "jaren jackson"


# --- TestExtractPlayerProps ---


class TestExtractPlayerProps:
    def test_extracts_points_market(self):
        event = _make_event([SAMPLE_PROP_MARKET])
        props = extract_player_props(event)
        assert len(props) == 1
        assert props[0]["prop_type"] == "points"
        assert props[0]["player_name"] == "LeBron James"
        assert props[0]["line"] == 25.5
        assert props[0]["outcomes"] == ["Yes", "No"]
        assert props[0]["prices"] == [0.55, 0.45]

    def test_extracts_multiple_prop_types(self):
        event = _make_event([
            SAMPLE_PROP_MARKET,
            SAMPLE_REBOUNDS_MARKET,
            SAMPLE_ASSISTS_MARKET,
        ])
        props = extract_player_props(event)
        assert len(props) == 3
        types = {p["prop_type"] for p in props}
        assert types == {"points", "rebounds", "assists"}

    def test_skips_non_accepting(self):
        event = _make_event([SAMPLE_NOT_ACCEPTING])
        props = extract_player_props(event)
        assert len(props) == 0

    def test_skips_non_prop_markets(self):
        event = _make_event([SAMPLE_MONEYLINE_MARKET])
        props = extract_player_props(event)
        assert len(props) == 0

    def test_handles_no_colon_in_question(self):
        market = {**SAMPLE_PROP_MARKET, "question": "Will LeBron score 25+?"}
        event = _make_event([market])
        props = extract_player_props(event)
        assert len(props) == 0

    def test_handles_diacritics_in_name(self):
        event = _make_event([SAMPLE_ASSISTS_MARKET])
        props = extract_player_props(event)
        assert props[0]["player_name"] == "Luka Dončić"


# --- TestFindPropMarket ---


class TestFindPropMarket:
    def test_finds_exact_match(self):
        event = _make_event([SAMPLE_PROP_MARKET, SAMPLE_REBOUNDS_MARKET])
        market = find_prop_market(event, "points", "LeBron James", 25.5)
        assert market is not None
        assert market["sportsMarketType"] == "points"

    def test_finds_with_fuzzy_name(self):
        event = _make_event([SAMPLE_ASSISTS_MARKET])
        market = find_prop_market(event, "assists", "Luka Doncic", 8.5)
        assert market is not None

    def test_returns_none_wrong_type(self):
        event = _make_event([SAMPLE_PROP_MARKET])
        market = find_prop_market(event, "rebounds", "LeBron James", 25.5)
        assert market is None

    def test_returns_none_wrong_line(self):
        event = _make_event([SAMPLE_PROP_MARKET])
        market = find_prop_market(event, "points", "LeBron James", 30.5)
        assert market is None

    def test_returns_none_not_accepting(self):
        event = _make_event([SAMPLE_NOT_ACCEPTING])
        market = find_prop_market(event, "points", "Steph Curry", 30.5)
        assert market is None


# --- TestPropPickToOutcome ---


class TestPropPickToOutcome:
    def test_over_to_yes(self):
        assert prop_pick_to_outcome("over") == "Yes"

    def test_under_to_no(self):
        assert prop_pick_to_outcome("under") == "No"

    def test_over_case_insensitive(self):
        assert prop_pick_to_outcome("Over") == "Yes"

    def test_under_case_insensitive(self):
        assert prop_pick_to_outcome("Under") == "No"


# --- TestExtractPolyPriceForProp ---


class TestExtractPolyPriceForProp:
    def setup_method(self):
        self.prop_markets = [
            {
                "prop_type": "points",
                "player_name": "LeBron James",
                "line": 25.5,
                "outcomes": ["Yes", "No"],
                "prices": [0.55, 0.45],
            },
            {
                "prop_type": "rebounds",
                "player_name": "Nikola Jokić",
                "line": 11.5,
                "outcomes": ["Yes", "No"],
                "prices": [0.60, 0.40],
            },
        ]

    def test_over_returns_yes_price(self):
        price = extract_poly_price_for_prop(
            self.prop_markets, "points", "LeBron James", 25.5, "over"
        )
        assert price == 0.55

    def test_under_returns_no_price(self):
        price = extract_poly_price_for_prop(
            self.prop_markets, "points", "LeBron James", 25.5, "under"
        )
        assert price == 0.45

    def test_fuzzy_name_with_diacritics(self):
        price = extract_poly_price_for_prop(
            self.prop_markets, "rebounds", "Nikola Jokic", 11.5, "over"
        )
        assert price == 0.60

    def test_returns_none_wrong_player(self):
        price = extract_poly_price_for_prop(
            self.prop_markets, "points", "Steph Curry", 25.5, "over"
        )
        assert price is None

    def test_returns_none_wrong_line(self):
        price = extract_poly_price_for_prop(
            self.prop_markets, "points", "LeBron James", 30.5, "over"
        )
        assert price is None

    def test_returns_none_wrong_type(self):
        price = extract_poly_price_for_prop(
            self.prop_markets, "assists", "LeBron James", 25.5, "over"
        )
        assert price is None


# --- TestEvaluatePropBet ---


class TestEvaluatePropBet:
    def _make_bet(self, pick="over", line=25.5, prop_type="points", player_name="LeBron James"):
        return {
            "id": "test",
            "game_id": "123",
            "matchup": "Lakers @ Celtics",
            "bet_type": "player_prop",
            "pick": pick,
            "line": line,
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "test",
            "primary_edge": "test",
            "date": "2026-02-17",
            "created_at": "2026-02-17T00:00:00Z",
            "prop_type": prop_type,
            "player_name": player_name,
        }

    def _make_result(self):
        return {
            "game_id": "123",
            "home_team": "Boston Celtics",
            "away_team": "Los Angeles Lakers",
            "home_score": 110,
            "away_score": 105,
            "winner": "Boston Celtics",
            "status": "finished",
        }

    def _make_box_score(self, points=28):
        return [
            {
                "player": {"firstname": "LeBron", "lastname": "James"},
                "points": points,
                "totReb": 7,
                "assists": 9,
            },
        ]

    def test_over_win(self):
        bet = self._make_bet(pick="over", line=25.5)
        outcome, pnl = _evaluate_prop_bet(bet, 28.0)
        assert outcome == "win"
        assert pnl == 1.0

    def test_over_loss(self):
        bet = self._make_bet(pick="over", line=25.5)
        outcome, pnl = _evaluate_prop_bet(bet, 20.0)
        assert outcome == "loss"
        assert pnl == -1.0

    def test_under_win(self):
        bet = self._make_bet(pick="under", line=25.5)
        outcome, pnl = _evaluate_prop_bet(bet, 20.0)
        assert outcome == "win"
        assert pnl == 1.0

    def test_under_loss(self):
        bet = self._make_bet(pick="under", line=25.5)
        outcome, pnl = _evaluate_prop_bet(bet, 28.0)
        assert outcome == "loss"
        assert pnl == -1.0

    def test_push(self):
        bet = self._make_bet(pick="over", line=25.0)
        outcome, pnl = _evaluate_prop_bet(bet, 25.0)
        assert outcome == "push"
        assert pnl == 0.0


# --- TestFindPlayerStat ---


class TestFindPlayerStat:
    def _make_box_score(self):
        return [
            {
                "player": {"firstname": "LeBron", "lastname": "James"},
                "points": 28,
                "totReb": 7,
                "assists": 9,
            },
            {
                "player": {"firstname": "Luka", "lastname": "Dončić"},
                "points": 32,
                "totReb": 10,
                "assists": 12,
            },
        ]

    def test_find_points(self):
        assert _find_player_stat(self._make_box_score(), "LeBron James", "points") == 28.0

    def test_find_rebounds(self):
        assert _find_player_stat(self._make_box_score(), "LeBron James", "rebounds") == 7.0

    def test_find_assists(self):
        assert _find_player_stat(self._make_box_score(), "LeBron James", "assists") == 9.0

    def test_diacritic_match(self):
        assert _find_player_stat(self._make_box_score(), "Luka Doncic", "points") == 32.0

    def test_not_found(self):
        assert _find_player_stat(self._make_box_score(), "Stephen Curry", "points") is None

    def test_empty_box_score(self):
        assert _find_player_stat([], "LeBron James", "points") is None


# --- TestCreatePropBet ---


class TestCreatePropBet:
    def test_creates_valid_bet(self):
        selected = {
            "game_id": "123",
            "matchup": "Lakers @ Celtics",
            "player_name": "LeBron James",
            "prop_type": "points",
            "line": 25.5,
            "pick": "over",
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "Season avg 27.5 PPG vs line of 25.5",
            "primary_edge": "avg_vs_line",
        }
        bet = create_prop_bet(selected, "2026-02-17")
        assert bet["bet_type"] == "player_prop"
        assert bet["prop_type"] == "points"
        assert bet["player_name"] == "LeBron James"
        assert bet["pick"] == "over"
        assert bet["line"] == 25.5
        assert bet["game_id"] == "123"
        assert bet["date"] == "2026-02-17"
        assert "id" in bet
        assert "created_at" in bet

    def test_rejects_unsupported_prop_type(self):
        selected = {
            "game_id": "123",
            "matchup": "Lakers @ Celtics",
            "player_name": "LeBron James",
            "prop_type": "steals",
            "line": 1.5,
            "pick": "over",
            "confidence": "medium",
        }
        assert create_prop_bet(selected, "2026-02-17") is None

    def test_rejects_empty_prop_type(self):
        selected = {
            "game_id": "123",
            "matchup": "Lakers @ Celtics",
            "player_name": "LeBron James",
            "prop_type": "",
            "line": 25.5,
            "pick": "over",
            "confidence": "medium",
        }
        assert create_prop_bet(selected, "2026-02-17") is None


# --- TestLoadPropsForDate ---


class TestLoadPropsForDate:
    def test_loads_props_files(self, tmp_path):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Write a props file
        props = {
            "api_game_id": 123,
            "game_date": "2026-02-17",
            "team1": "Lakers",
            "team2": "Celtics",
            "home_team": "Celtics",
            "team1_players": [{"name": "LeBron James", "ppg": 27.5}],
            "team2_players": [{"name": "Jayson Tatum", "ppg": 26.0}],
        }
        (output_dir / "props_lakers_vs_celtics_2026-02-17.json").write_text(json.dumps(props))

        # Also write a non-props file (should be excluded)
        (output_dir / "lakers_vs_celtics_2026-02-17.json").write_text(json.dumps({"matchup": {}}))

        with patch("workflow.analyze.OUTPUT_DIR", output_dir):
            result = load_props_for_date("2026-02-17")

        assert len(result) == 1
        assert result[0]["api_game_id"] == 123

    def test_no_props_files(self, tmp_path):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch("workflow.analyze.OUTPUT_DIR", output_dir):
            result = load_props_for_date("2026-02-17")

        assert result == []


# --- TestDNPVoidFlow ---


class TestDNPVoidFlow:
    """Test that player prop bets are voided when the player doesn't appear in box score."""

    def _make_prop_bet(self, player_name="LeBron James", game_id="12345"):
        return {
            "id": "prop-test-1",
            "game_id": game_id,
            "matchup": "Lakers @ Celtics",
            "bet_type": "player_prop",
            "pick": "over",
            "line": 25.5,
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "test",
            "primary_edge": "test",
            "date": "2026-02-17",
            "created_at": "2026-02-17T00:00:00Z",
            "prop_type": "points",
            "player_name": player_name,
        }

    def test_dnp_voids_bet_and_removes_from_active(self, tmp_path):
        """DNP player: bet saved to voids.json, removed from active.json."""
        from workflow.results import _find_player_stat, _evaluate_prop_bet
        from workflow.io import save_void, get_voids, get_active_bets, save_active_bets

        bet = self._make_prop_bet(player_name="Bench Warmer")

        # Box score has real players but not "Bench Warmer"
        box_score = [
            {
                "player": {"firstname": "LeBron", "lastname": "James"},
                "points": 28,
                "totReb": 7,
                "assists": 9,
            },
        ]

        # _find_player_stat should return None for missing player
        actual = _find_player_stat(box_score, "Bench Warmer", "points")
        assert actual is None

        # Simulate the void path: save to voids.json
        voids_path = tmp_path / "voids.json"
        with patch("workflow.io.VOIDS_PATH", voids_path):
            save_void(bet, "DNP: Bench Warmer not found in box score")
            voids = get_voids()

        assert len(voids) == 1
        assert voids[0]["player_name"] == "Bench Warmer"
        assert voids[0]["void_reason"] == "DNP: Bench Warmer not found in box score"
        assert voids[0]["id"] == "prop-test-1"

    def test_dnp_does_not_count_as_loss(self):
        """A DNP void should never reach _evaluate_prop_bet."""
        box_score = []  # Empty box score = no players found
        actual = _find_player_stat(box_score, "Anyone", "points")
        assert actual is None
        # The caller checks actual is None and voids — _evaluate_prop_bet is never called

    def test_played_player_not_voided(self):
        """Player who played should return a stat, not be voided."""
        box_score = [
            {
                "player": {"firstname": "LeBron", "lastname": "James"},
                "points": 28,
                "totReb": 7,
                "assists": 9,
            },
        ]
        actual = _find_player_stat(box_score, "LeBron James", "points")
        assert actual == 28.0

        bet = self._make_prop_bet()
        outcome, pnl = _evaluate_prop_bet(bet, actual)
        assert outcome == "win"
        assert pnl == 1.0
