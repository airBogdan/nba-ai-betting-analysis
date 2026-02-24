import asyncio
from unittest.mock import AsyncMock, patch

import pytest


def _make_bet(**overrides):
    base = {
        "id": "bet-001",
        "game_id": "12345",
        "matchup": "Celtics @ Lakers",
        "bet_type": "moneyline",
        "pick": "Lakers",
        "line": None,
        "confidence": "high",
        "units": 2.0,
        "reasoning": "Lakers strong at home",
        "primary_edge": "home_court",
        "date": "2026-02-20",
        "created_at": "2026-02-20T10:00:00",
    }
    base.update(overrides)
    return base


def _make_game_result(**overrides):
    base = {
        "game_id": "12345",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "home_score": 115,
        "away_score": 108,
        "winner": "Los Angeles Lakers",
        "status": "finished",
    }
    base.update(overrides)
    return base


def _make_prop_bet(**overrides):
    base = _make_bet(
        bet_type="player_prop",
        pick="over",
        line=25.5,
        prop_type="points",
        player_name="LeBron James",
    )
    base.update(overrides)
    return base


class TestGameResultMatching:
    """Bets must be matched to the correct game before evaluation."""

    def test_match_by_exact_game_id(self):
        """Primary matching path: match bet to result by game_id."""
        from workflow.game_results import match_bet_to_result

        bet = _make_bet(game_id="12345")
        results = [_make_game_result(game_id="12345")]
        matched = match_bet_to_result(bet, results)
        assert matched is not None
        assert matched["game_id"] == "12345"

    def test_fallback_to_team_name_matching(self):
        """When game_id doesn't match, fall back to team name matching from matchup string."""
        from workflow.game_results import match_bet_to_result

        bet = _make_bet(game_id="legacy-id", matchup="Celtics @ Lakers")
        results = [
            _make_game_result(
                game_id="99999",
                home_team="Los Angeles Lakers",
                away_team="Boston Celtics",
            )
        ]
        matched = match_bet_to_result(bet, results)
        assert matched is not None

    def test_no_match_returns_none(self):
        """If no game matches, the bet stays unresolved."""
        from workflow.game_results import match_bet_to_result

        bet = _make_bet(game_id="99999", matchup="Warriors @ Heat")
        results = [_make_game_result()]
        matched = match_bet_to_result(bet, results)
        assert matched is None


class TestTeamNameMatching:
    """Team names come from different sources and need fuzzy matching."""

    def test_exact_match(self):
        from workflow.game_results import _teams_match

        assert _teams_match("Lakers", "Lakers")

    def test_partial_match_short_in_long(self):
        from workflow.game_results import _teams_match

        assert _teams_match("Lakers", "Los Angeles Lakers")

    def test_la_abbreviation_variations(self):
        """'LA Lakers' should match 'Los Angeles Lakers'."""
        from workflow.game_results import _teams_match

        assert _teams_match("LA Lakers", "Los Angeles Lakers")

    def test_case_insensitive(self):
        from workflow.game_results import _teams_match

        assert _teams_match("lakers", "LAKERS")

    def test_non_matching_teams(self):
        from workflow.game_results import _teams_match

        assert not _teams_match("Lakers", "Celtics")


class TestGameResultParsing:
    """API responses must be correctly parsed into our GameResult format."""

    def test_finished_game_parsing(self):
        from workflow.game_results import parse_single_game_result

        api_game = {
            "id": 42,
            "status": {"long": "Finished"},
            "teams": {
                "home": {"name": "Lakers"},
                "visitors": {"name": "Celtics"},
            },
            "scores": {
                "home": {"points": 115},
                "visitors": {"points": 108},
            },
        }
        result = parse_single_game_result(api_game)
        assert result["status"] == "finished"
        assert result["game_id"] == "42"
        assert result["winner"] == "Lakers"
        assert result["home_score"] == 115
        assert result["away_score"] == 108

    def test_scheduled_game_parsing(self):
        from workflow.game_results import parse_single_game_result

        api_game = {
            "id": 50,
            "status": {"long": "Scheduled"},
            "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Heat"}},
            "scores": {"home": {"points": None}, "visitors": {"points": None}},
        }
        result = parse_single_game_result(api_game)
        assert result["status"] == "scheduled"
        assert result["home_score"] == 0
        assert result["away_score"] == 0

    def test_tie_has_empty_winner(self):
        """NBA games can't really tie, but if scores are equal, winner should be empty."""
        from workflow.game_results import parse_single_game_result

        api_game = {
            "id": 99,
            "status": {"long": "Finished"},
            "teams": {"home": {"name": "A"}, "visitors": {"name": "B"}},
            "scores": {"home": {"points": 100}, "visitors": {"points": 100}},
        }
        result = parse_single_game_result(api_game)
        assert result["winner"] == ""

    def test_score_formatting(self):
        """Score should be formatted as 'Away X @ Home Y'."""
        from workflow.game_results import _format_score

        result = _make_game_result(
            away_team="Celtics", home_team="Lakers",
            away_score=108, home_score=115,
        )
        assert _format_score(result) == "Celtics 108 @ Lakers 115"

    def test_empty_api_response_returns_empty_list(self):
        from workflow.game_results import parse_game_results

        assert parse_game_results(None) == []
        assert parse_game_results([]) == []


class TestPlayerStatLookup:
    """Player props require finding the actual stat from box score data."""

    def test_finds_player_points(self):
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "LeBron", "lastname": "James"}, "points": "28"},
        ]
        result = _find_player_stat(box_score, "LeBron James", "points")
        assert result == 28.0

    def test_finds_player_rebounds(self):
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "LeBron", "lastname": "James"}, "totReb": "10"},
        ]
        result = _find_player_stat(box_score, "LeBron James", "rebounds")
        assert result == 10.0

    def test_finds_player_assists(self):
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "LeBron", "lastname": "James"}, "assists": "7"},
        ]
        result = _find_player_stat(box_score, "LeBron James", "assists")
        assert result == 7.0

    def test_returns_none_for_missing_player(self):
        """Player not in box score -> DNP -> should void the bet."""
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "Anthony", "lastname": "Davis"}, "points": "22"},
        ]
        result = _find_player_stat(box_score, "LeBron James", "points")
        assert result is None

    def test_name_matching_handles_initials(self):
        """'L James' should match 'LeBron James' via initial matching."""
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "LeBron", "lastname": "James"}, "points": "28"},
        ]
        result = _find_player_stat(box_score, "L James", "points")
        assert result == 28.0

    def test_unsupported_prop_type_returns_none(self):
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "LeBron", "lastname": "James"}, "points": "28"},
        ]
        result = _find_player_stat(box_score, "LeBron James", "steals")
        assert result is None

    def test_diacritic_name_matching(self):
        """Unicode diacritics (e.g. Doncic) should match ASCII equivalent."""
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "Luka", "lastname": "Doncic"}, "points": "32"},
        ]
        result = _find_player_stat(box_score, "Luka Doncic", "points")
        assert result == 32.0

    def test_empty_box_score_returns_none(self):
        from workflow.evaluation import _find_player_stat

        assert _find_player_stat([], "LeBron James", "points") is None


class TestPlayerPropVoidHandling:
    """Player prop bets should be voided (not win/loss) for certain conditions."""

    def test_dnp_player_is_voided(self):
        """If a player didn't play (not in box score), the bet should be voided, not lost."""
        from workflow.results import _resolve_bet_outcomes

        bet = _make_prop_bet(game_id="12345", player_name="LeBron James")
        finished = [_make_game_result(game_id="12345")]

        # Empty box score -> player not found -> void
        with patch("workflow.results.get_game_player_stats", new_callable=AsyncMock, return_value=[]), \
             patch("workflow.results.save_void") as mock_void:
            matched, unresolved = asyncio.get_event_loop().run_until_complete(
                _resolve_bet_outcomes([bet], finished)
            )

        # Should not be counted as win or loss
        assert len(matched) == 0
        assert len(unresolved) == 0
        mock_void.assert_called_once()
        void_reason = mock_void.call_args[0][1]
        assert "DNP" in void_reason or "not in box score" in void_reason

    def test_unavailable_box_score_is_voided(self):
        """If box score API fails, the bet should be voided."""
        from workflow.results import _resolve_bet_outcomes

        bet = _make_prop_bet(game_id="12345")
        finished = [_make_game_result(game_id="12345")]

        with patch("workflow.results.get_game_player_stats", new_callable=AsyncMock, return_value=None), \
             patch("workflow.results.save_void") as mock_void:
            matched, _ = asyncio.get_event_loop().run_until_complete(
                _resolve_bet_outcomes([bet], finished)
            )

        assert len(matched) == 0
        mock_void.assert_called_once()

    def test_unsupported_prop_type_is_voided(self):
        """If the prop type isn't in our supported set, void it."""
        from workflow.results import _resolve_bet_outcomes

        bet = _make_prop_bet(game_id="12345", prop_type="steals")
        finished = [_make_game_result(game_id="12345")]

        # Box score available, but prop type unsupported
        with patch("workflow.results.get_game_player_stats", new_callable=AsyncMock, return_value=[{"player": {}}]), \
             patch("workflow.results.save_void") as mock_void:
            matched, _ = asyncio.get_event_loop().run_until_complete(
                _resolve_bet_outcomes([bet], finished)
            )

        assert len(matched) == 0
        mock_void.assert_called_once()
        assert "unsupported" in mock_void.call_args[0][1].lower() or "steals" in mock_void.call_args[0][1].lower()

    def test_invalid_game_id_is_voided(self):
        """Legacy non-numeric game IDs can't fetch box scores."""
        from workflow.results import _resolve_bet_outcomes

        bet = _make_prop_bet(game_id="legacy-abc")
        finished = [_make_game_result(game_id="legacy-abc")]

        with patch("workflow.results.save_void") as mock_void:
            matched, _ = asyncio.get_event_loop().run_until_complete(
                _resolve_bet_outcomes([bet], finished)
            )

        assert len(matched) == 0
        mock_void.assert_called_once()

    def test_successful_prop_bet_evaluation(self):
        """When everything resolves, prop bets should be graded like totals."""
        from workflow.results import _resolve_bet_outcomes

        bet = _make_prop_bet(
            game_id="12345", player_name="LeBron James",
            prop_type="points", pick="over", line=25.5, units=1.0,
        )
        finished = [_make_game_result(game_id="12345")]
        box_score = [
            {"player": {"firstname": "LeBron", "lastname": "James"}, "points": "30"},
        ]

        with patch("workflow.results.get_game_player_stats", new_callable=AsyncMock, return_value=box_score), \
             patch("workflow.results.save_void"):
            matched, _ = asyncio.get_event_loop().run_until_complete(
                _resolve_bet_outcomes([bet], finished)
            )

        assert len(matched) == 1
        _, _, outcome, pnl = matched[0]
        assert outcome == "win"
        assert pnl == 1.0

    def test_box_score_cached_across_same_game(self):
        """Multiple prop bets on the same game should only fetch box score once."""
        from workflow.results import _resolve_bet_outcomes

        bet1 = _make_prop_bet(
            id="p1", game_id="12345", player_name="LeBron James",
            prop_type="points", pick="over", line=25.5,
        )
        bet2 = _make_prop_bet(
            id="p2", game_id="12345", player_name="Anthony Davis",
            prop_type="rebounds", pick="over", line=10.5,
        )
        finished = [_make_game_result(game_id="12345")]
        box_score = [
            {"player": {"firstname": "LeBron", "lastname": "James"}, "points": "30", "totReb": "8"},
            {"player": {"firstname": "Anthony", "lastname": "Davis"}, "points": "22", "totReb": "12"},
        ]

        mock_stats = AsyncMock(return_value=box_score)
        with patch("workflow.results.get_game_player_stats", mock_stats), \
             patch("workflow.results.save_void"):
            matched, _ = asyncio.get_event_loop().run_until_complete(
                _resolve_bet_outcomes([bet1, bet2], finished)
            )

        # Both should resolve
        assert len(matched) == 2
        # Box score fetched only once despite two bets on same game
        mock_stats.assert_called_once()
