"""Intent-based tests for the post-game results workflow.

These tests verify the BEHAVIORAL INTENT of the results workflow,
not just that the current code works. Each test asks: "What should
this system do from a user/product perspective?"

The results workflow is the post-game settlement engine:
- After games finish, resolve all pending bets against actual outcomes
- Grade each bet as win/loss/push based on bet type rules
- Generate LLM reflections on reasoning quality
- Track running statistics in history
- Write journal entries for auditability
- Handle special cases: player props (box scores, DNP), skips, paper trades
- Calculate dollar P&L for real-money Polymarket bets
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: factory functions for test data
# ---------------------------------------------------------------------------


def _make_bet(**overrides):
    """Create a minimal ActiveBet dict with sensible defaults."""
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
    """Create a minimal GameResult dict with sensible defaults."""
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
    """Create a player prop ActiveBet."""
    base = _make_bet(
        bet_type="player_prop",
        pick="over",
        line=25.5,
        prop_type="points",
        player_name="LeBron James",
    )
    base.update(overrides)
    return base


def _make_skip(**overrides):
    """Create a skipped game entry."""
    base = {
        "matchup": "Celtics @ Lakers",
        "reason": "No clear edge",
        "date": "2026-02-20",
    }
    base.update(overrides)
    return base


def _make_paper_trade(**overrides):
    """Create a paper trade entry."""
    base = {
        "matchup": "Celtics @ Lakers",
        "date": "2026-02-20",
        "bet_type": "moneyline",
        "pick": "Lakers",
        "line": None,
        "confidence": "medium",
        "reasoning": "Contrarian paper pick",
        "primary_edge": "home_court",
        "skip_reason": "No clear edge",
        "units": 1.0,
    }
    base.update(overrides)
    return base


# ===================================================================
# 1. BET EVALUATION — Do we correctly grade bets against results?
# ===================================================================


class TestMoneylineBetEvaluation:
    """Moneyline bets should win when the picked team wins, lose otherwise."""

    def test_moneyline_win_when_picked_team_wins(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(pick="Lakers", units=2.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "win"
        assert pnl == 2.0

    def test_moneyline_loss_when_picked_team_loses(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(pick="Lakers", units=2.0)
        result = _make_game_result(winner="Boston Celtics")
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "loss"
        assert pnl == -2.0

    def test_moneyline_handles_partial_team_names(self):
        """Pick 'Celtics' should match 'Boston Celtics' in result."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(pick="Celtics", units=1.5)
        result = _make_game_result(winner="Boston Celtics")
        outcome, _ = _evaluate_bet(bet, result)
        assert outcome == "win"


class TestSpreadBetEvaluation:
    """Spread bets evaluate margin + line to determine cover."""

    def test_favorite_covers_spread(self):
        """Home team favored by 5 (-5) and wins by 10 -> covers."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-5.0, units=2.0)
        result = _make_game_result(home_score=115, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # margin=10, line=-5, adjusted=5 > 0 => win
        assert outcome == "win"
        assert pnl == 2.0

    def test_favorite_fails_to_cover(self):
        """Home team favored by 7 (-7) but only wins by 3 -> loss."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-7.0, units=1.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # margin=3, line=-7, adjusted=-4 < 0 => loss
        assert outcome == "loss"
        assert pnl == -1.0

    def test_spread_push_on_exact_margin(self):
        """Favorite wins by exactly the spread -> push, no profit/loss."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-5.0, units=2.0)
        result = _make_game_result(home_score=110, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # margin=5, line=-5, adjusted=0 => push
        assert outcome == "push"
        assert pnl == 0.0

    def test_underdog_covers_spread(self):
        """Away team getting +6.5 and loses by only 3 -> covers."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Celtics", line=6.5, units=1.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, _ = _evaluate_bet(bet, result)
        # picked away: margin = 105-108 = -3, line=+6.5, adjusted=3.5 > 0 => win
        assert outcome == "win"

    def test_underdog_loses_by_more_than_spread(self):
        """Away team getting +4 but loses by 10 -> doesn't cover."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Celtics", line=4.0, units=1.0)
        result = _make_game_result(home_score=115, away_score=105)
        outcome, _ = _evaluate_bet(bet, result)
        # margin = 105-115 = -10, line=+4, adjusted=-6 < 0 => loss
        assert outcome == "loss"


class TestTotalsBetEvaluation:
    """Over/under bets compare actual total against the line."""

    def test_over_wins_when_total_exceeds_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="over", line=220.5, units=1.5)
        result = _make_game_result(home_score=115, away_score=110)
        outcome, pnl = _evaluate_bet(bet, result)
        # total=225 > 220.5 => win
        assert outcome == "win"
        assert pnl == 1.5

    def test_over_loses_when_total_under_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="over", line=230.5, units=1.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # total=213 < 230.5 => loss
        assert outcome == "loss"
        assert pnl == -1.0

    def test_under_wins_when_total_below_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="under", line=230.5, units=2.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "win"
        assert pnl == 2.0

    def test_under_loses_when_total_above_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="under", line=210.5, units=1.0)
        result = _make_game_result(home_score=115, away_score=110)
        outcome, _ = _evaluate_bet(bet, result)
        assert outcome == "loss"

    def test_total_push_on_exact_line(self):
        """When total exactly hits the line, it's a push."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="over", line=223.0, units=1.0)
        result = _make_game_result(home_score=115, away_score=108)
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "push"
        assert pnl == 0.0


class TestPlayerPropEvaluation:
    """Player prop bets compare actual stat against a line."""

    def test_over_wins_when_stat_exceeds_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="over", line=25.5, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 30.0)
        assert outcome == "win"
        assert pnl == 1.0

    def test_over_loses_when_stat_below_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="over", line=25.5, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 20.0)
        assert outcome == "loss"
        assert pnl == -1.0

    def test_under_wins_when_stat_below_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="under", line=25.5, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 20.0)
        assert outcome == "win"

    def test_prop_push_on_exact_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="over", line=25.0, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 25.0)
        assert outcome == "push"
        assert pnl == 0.0

    def test_player_prop_raises_if_evaluated_as_regular_bet(self):
        """_evaluate_bet must NOT handle player props — forces callers to use the right path."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_prop_bet()
        result = _make_game_result()
        with pytest.raises(ValueError, match="player_prop"):
            _evaluate_bet(bet, result)


# ===================================================================
# 2. DOLLAR P&L — American odds payout calculation
# ===================================================================


class TestDollarPnl:
    """Dollar P&L tracks real money returns alongside unit-based tracking."""

    def test_favorite_payout(self):
        """Betting $150 at -150: profit = $100 -> payout = $250."""
        from workflow.evaluation import calculate_payout

        payout = calculate_payout(150.0, -150, "win")
        assert payout == 250.0

    def test_underdog_payout(self):
        """Betting $100 at +130: profit = $130 -> payout = $230."""
        from workflow.evaluation import calculate_payout

        payout = calculate_payout(100.0, 130, "win")
        assert payout == 230.0

    def test_loss_returns_zero(self):
        """On a loss, payout is $0 (stake already deducted when placed)."""
        from workflow.evaluation import calculate_payout

        assert calculate_payout(100.0, -110, "loss") == 0.0

    def test_push_returns_stake(self):
        """Push returns exactly the staked amount."""
        from workflow.evaluation import calculate_payout

        assert calculate_payout(100.0, -110, "push") == 100.0

    def test_zero_odds_not_reached(self):
        """odds_price=0 is never passed to calculate_payout — the caller guards against it."""
        # The guard in results.py: `if amount and odds_price:` skips when odds_price=0
        # So calculate_payout is never called with odds_price=0 in practice.
        # This test documents that the caller is responsible for validation.
        from workflow.results import _build_completed_bets

        bet = _make_bet(amount=100.0, odds_price=0, units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert "dollar_pnl" not in completed[0]

    def test_dollar_pnl_computed_in_completed_bet(self):
        """When a bet has amount + odds_price, the completed bet should include dollar_pnl."""
        from workflow.results import _build_completed_bets

        bet = _make_bet(amount=100.0, odds_price=-110, units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert len(completed) == 1
        # Win at -110: payout = 100*(1 + 100/110) ≈ 190.91; pnl ≈ +90.91
        assert completed[0]["dollar_pnl"] == pytest.approx(90.91, abs=0.01)

    def test_no_dollar_pnl_without_amount_or_odds(self):
        """Bets without amount/odds_price should not have dollar_pnl field."""
        from workflow.results import _build_completed_bets

        bet = _make_bet(units=1.0)  # No amount or odds_price
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert "dollar_pnl" not in completed[0]


# ===================================================================
# 3. GAME RESULT MATCHING — Can we match bets to the right games?
# ===================================================================


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


# ===================================================================
# 4. PLAYER PROP RESOLUTION — Box score lookup and void handling
# ===================================================================


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
        """Unicode diacritics (e.g. Dončić) should match ASCII equivalent."""
        from workflow.evaluation import _find_player_stat

        box_score = [
            {"player": {"firstname": "Luka", "lastname": "Dončić"}, "points": "32"},
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


# ===================================================================
# 5. REFLECTION GENERATION — LLM reflects on each bet outcome
# ===================================================================


class TestReflectionGeneration:
    """Each completed bet gets an LLM reflection on reasoning quality."""

    def test_reflection_included_in_completed_bet(self):
        from workflow.results import _build_completed_bets

        bet = _make_bet(units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        mock_reflection = {
            "edge_valid": True,
            "missed_factors": [],
            "process_assessment": "sound",
            "key_lesson": "Home court edge was real",
            "summary": "Good bet, edge played out as expected.",
        }

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=mock_reflection):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert completed[0]["reflection"] == "Good bet, edge played out as expected."
        sr = completed[0]["structured_reflection"]
        assert sr["edge_valid"] is True
        assert sr["process_assessment"] == "sound"

    def test_reflection_failure_doesnt_block_settlement(self):
        """If LLM fails, the bet should still be settled — just without reflection text."""
        from workflow.results import _build_completed_bets

        bet = _make_bet(units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, side_effect=Exception("LLM timeout")):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert len(completed) == 1
        assert completed[0]["result"] == "win"
        assert completed[0]["reflection"] == ""
        assert "structured_reflection" not in completed[0]

    def test_reflection_none_handled_gracefully(self):
        """LLM returning None should not crash."""
        from workflow.results import _build_completed_bets

        bet = _make_bet(units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert completed[0]["reflection"] == ""

    def test_concurrent_reflections_are_bounded(self):
        """Reflections should be rate-limited to avoid overwhelming the LLM API."""
        from workflow.results import MAX_CONCURRENT_LLM_CALLS

        # The system limits concurrent LLM calls
        assert MAX_CONCURRENT_LLM_CALLS > 0
        assert MAX_CONCURRENT_LLM_CALLS <= 10  # Reasonable bound


# ===================================================================
# 6. COMPLETED BET CONSTRUCTION — Building the settlement record
# ===================================================================


class TestCompletedBetConstruction:
    """Completed bets must contain all fields needed for history and journal."""

    def test_completed_bet_has_required_fields(self):
        from workflow.results import _build_completed_bets

        bet = _make_bet(units=2.0)
        result = _make_game_result(
            home_score=115, away_score=108,
            winner="Los Angeles Lakers",
        )
        matched = [(bet, result, "win", 2.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        c = completed[0]
        assert c["result"] == "win"
        assert c["profit_loss"] == 2.0
        assert c["winner"] == "Los Angeles Lakers"
        assert c["final_score"] == "Boston Celtics 108 @ Los Angeles Lakers 115"
        assert c["actual_total"] == 223
        assert c["actual_margin"] == 7  # home_score - away_score

    def test_internal_fields_stripped_from_completed_bet(self):
        """Fields prefixed with _ (like _actual_stat) should not persist to history."""
        from workflow.results import _build_completed_bets

        bet = _make_prop_bet(units=1.0)
        bet["_actual_stat"] = 30.0  # Internal field
        result = _make_game_result()
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        # _actual_stat should be cleaned, but actual_stat (no underscore) should be set for props
        assert "_actual_stat" not in completed[0]
        assert completed[0]["actual_stat"] == 30.0

    def test_prop_actual_stat_included_when_available(self):
        """Player prop completed bets should include the actual stat value."""
        from workflow.results import _build_completed_bets

        bet = _make_prop_bet(units=1.0)
        bet["_actual_stat"] = 28.0
        result = _make_game_result()
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert completed[0]["actual_stat"] == 28.0


# ===================================================================
# 7. HISTORY TRACKING — Running statistics across all bets
# ===================================================================


class TestHistoryTracking:
    """History should maintain accurate running statistics."""

    def test_win_updates_history_correctly(self):
        from workflow.history import update_history_with_bet
        from workflow.io import _empty_summary

        history = {"bets": [], "summary": _empty_summary()}
        bet = {
            "result": "win", "units": 2.0, "profit_loss": 2.0,
            "confidence": "high", "primary_edge": "home_court",
            "bet_type": "moneyline",
        }
        update_history_with_bet(history, bet)

        s = history["summary"]
        assert s["total_bets"] == 1
        assert s["wins"] == 1
        assert s["losses"] == 0
        assert s["net_units"] == 2.0
        assert s["win_rate"] == 1.0

    def test_loss_updates_history_correctly(self):
        from workflow.history import update_history_with_bet
        from workflow.io import _empty_summary

        history = {"bets": [], "summary": _empty_summary()}
        bet = {
            "result": "loss", "units": 1.5, "profit_loss": -1.5,
            "confidence": "medium", "primary_edge": "form_momentum",
            "bet_type": "spread",
        }
        update_history_with_bet(history, bet)

        s = history["summary"]
        assert s["total_bets"] == 1
        assert s["losses"] == 1
        assert s["net_units"] == -1.5

    def test_push_doesnt_count_in_win_loss(self):
        from workflow.history import update_history_with_bet
        from workflow.io import _empty_summary

        history = {"bets": [], "summary": _empty_summary()}
        bet = {
            "result": "push", "units": 1.0, "profit_loss": 0.0,
            "confidence": "low", "primary_edge": "rest_advantage",
            "bet_type": "total",
        }
        update_history_with_bet(history, bet)

        s = history["summary"]
        assert s["total_bets"] == 1
        assert s["pushes"] == 1
        assert s["wins"] == 0
        assert s["losses"] == 0
        assert s["net_units"] == 0.0

    def test_roi_computed_from_wagered_units(self):
        """ROI = net_units / total_units_wagered (only wins and losses count)."""
        from workflow.history import update_history_with_bet
        from workflow.io import _empty_summary

        history = {"bets": [], "summary": _empty_summary()}

        # Win 2u, lose 1u, push 1u -> wagered = 2+1 = 3u, net = 2-1 = 1u, roi = 1/3
        update_history_with_bet(history, {
            "result": "win", "units": 2.0, "profit_loss": 2.0,
            "confidence": "high", "primary_edge": "edge", "bet_type": "moneyline",
        })
        update_history_with_bet(history, {
            "result": "loss", "units": 1.0, "profit_loss": -1.0,
            "confidence": "low", "primary_edge": "edge", "bet_type": "moneyline",
        })
        update_history_with_bet(history, {
            "result": "push", "units": 1.0, "profit_loss": 0.0,
            "confidence": "low", "primary_edge": "edge", "bet_type": "total",
        })

        s = history["summary"]
        assert s["total_units_wagered"] == 3.0  # push doesn't count
        assert s["net_units"] == 1.0
        assert s["roi"] == pytest.approx(0.333, abs=0.001)

    def test_early_exit_tracked_separately(self):
        """Early exit (from position check) updates P&L but not W/L/P counts."""
        from workflow.history import update_history_with_bet
        from workflow.io import _empty_summary

        history = {"bets": [], "summary": _empty_summary()}
        bet = {
            "result": "early_exit", "units": 1.0, "profit_loss": -0.5,
            "confidence": "high", "primary_edge": "edge", "bet_type": "moneyline",
            "dollar_pnl": -25.0,
        }
        update_history_with_bet(history, bet)

        s = history["summary"]
        assert s["total_bets"] == 0  # Not counted in W/L/P
        assert s["net_units"] == -0.5
        assert s["net_dollar_pnl"] == -25.0

    def test_streak_tracking(self):
        """Current streak should reflect the most recent consecutive same-result run."""
        from workflow.history import update_history_with_bet
        from workflow.io import _empty_summary

        history = {"bets": [], "summary": _empty_summary()}

        for _ in range(3):
            update_history_with_bet(history, {
                "result": "win", "units": 1.0, "profit_loss": 1.0,
                "confidence": "high", "primary_edge": "edge", "bet_type": "moneyline",
            })

        assert history["summary"]["current_streak"] == "W3"

        # One loss breaks the streak
        update_history_with_bet(history, {
            "result": "loss", "units": 1.0, "profit_loss": -1.0,
            "confidence": "low", "primary_edge": "edge", "bet_type": "moneyline",
        })
        assert history["summary"]["current_streak"] == "L1"

    def test_breakdown_by_confidence_and_bet_type(self):
        """History should track win rates sliced by confidence level and bet type."""
        from workflow.history import update_history_with_bet
        from workflow.io import _empty_summary

        history = {"bets": [], "summary": _empty_summary()}

        update_history_with_bet(history, {
            "result": "win", "units": 2.0, "profit_loss": 2.0,
            "confidence": "high", "primary_edge": "home_court", "bet_type": "moneyline",
        })
        update_history_with_bet(history, {
            "result": "loss", "units": 1.0, "profit_loss": -1.0,
            "confidence": "high", "primary_edge": "home_court", "bet_type": "spread",
        })

        s = history["summary"]
        assert s["by_confidence"]["high"]["wins"] == 1
        assert s["by_confidence"]["high"]["losses"] == 1
        assert s["by_confidence"]["high"]["win_rate"] == 0.5
        assert s["by_bet_type"]["moneyline"]["wins"] == 1
        assert s["by_bet_type"]["spread"]["losses"] == 1

    def test_edge_categorization(self):
        """Primary edges should be categorized into standard buckets."""
        from workflow.history import _categorize_edge

        assert _categorize_edge("Home court advantage") == "home_court"
        assert _categorize_edge("Rest advantage - opponent on B2B") == "rest_advantage"
        assert _categorize_edge("Key injury to starting PG") == "injury_edge"
        assert _categorize_edge("Hot streak, strong recent form") == "form_momentum"
        assert _categorize_edge("Net rating differential") == "ratings_edge"


# ===================================================================
# 8. SKIP RESOLUTION — Filling in outcomes for games we didn't bet on
# ===================================================================


class TestSkipResolution:
    """Skipped games should have their outcomes recorded for learning."""

    def test_skips_resolved_by_game_id(self):
        from workflow.results import _resolve_skips_for_date

        skips = [_make_skip(game_id="12345")]
        finished = [_make_game_result(game_id="12345")]

        with patch("workflow.results.get_skips", return_value=skips), \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock, return_value=["game"]), \
             patch("workflow.results.parse_game_results", return_value=finished), \
             patch("workflow.results.save_skips_all") as mock_save:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        mock_save.assert_called_once()
        saved_skips = mock_save.call_args[0][0]
        assert saved_skips[0]["outcome_resolved"] is True
        assert saved_skips[0]["winner"] == "Los Angeles Lakers"

    def test_skips_resolved_by_team_name_fallback(self):
        from workflow.results import _resolve_skips_for_date

        skips = [_make_skip(matchup="Celtics @ Lakers")]  # No game_id
        finished = [_make_game_result(
            game_id="99999",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            home_score=115, away_score=108,
        )]

        with patch("workflow.results.get_skips", return_value=skips), \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock, return_value=["game"]), \
             patch("workflow.results.parse_game_results", return_value=finished), \
             patch("workflow.results.save_skips_all") as mock_save:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        mock_save.assert_called_once()
        resolved = mock_save.call_args[0][0][0]
        assert resolved["outcome_resolved"] is True
        assert resolved["actual_total"] == 223

    def test_already_resolved_skips_ignored(self):
        """Skips that already have outcome_resolved=True should not be re-processed."""
        from workflow.results import _resolve_skips_for_date

        skips = [_make_skip(outcome_resolved=True, game_id="12345")]

        with patch("workflow.results.get_skips", return_value=skips), \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock) as mock_api:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        # Should not even call the API since no unresolved skips for this date
        mock_api.assert_not_called()

    def test_no_finished_games_means_no_resolution(self):
        from workflow.results import _resolve_skips_for_date

        skips = [_make_skip(game_id="12345")]

        with patch("workflow.results.get_skips", return_value=skips), \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock, return_value=["game"]), \
             patch("workflow.results.parse_game_results", return_value=[
                 _make_game_result(status="scheduled"),
             ]), \
             patch("workflow.results.save_skips_all") as mock_save:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        mock_save.assert_not_called()


# ===================================================================
# 9. PAPER TRADE RESOLUTION — Grading contrarian shadow bets
# ===================================================================


class TestPaperTradeResolution:
    """Paper trades on skipped games should be graded against actual results."""

    def test_paper_trade_resolved_with_outcome(self):
        from workflow.results import _resolve_paper_trades_for_date

        trades = [_make_paper_trade(game_id="12345")]
        finished = [_make_game_result(game_id="12345")]

        with patch("workflow.results.get_paper_trades", return_value=trades), \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock, return_value=["g"]), \
             patch("workflow.results.parse_game_results", return_value=finished), \
             patch("workflow.results.get_paper_history", return_value={"trades": [], "summary": {
                 "total_trades": 0, "wins": 0, "losses": 0, "pushes": 0,
                 "win_rate": 0.0, "net_units": 0.0,
                 "by_confidence": {}, "by_bet_type": {}, "by_skip_reason_category": {},
             }}), \
             patch("workflow.results.save_paper_trades") as mock_save_trades, \
             patch("workflow.results.save_paper_history") as mock_save_hist, \
             patch("workflow.results._append_paper_journal_results"):
            asyncio.get_event_loop().run_until_complete(
                _resolve_paper_trades_for_date("2026-02-20", 2025)
            )

        mock_save_trades.assert_called_once()
        mock_save_hist.assert_called_once()
        resolved_trade = trades[0]
        assert "result" in resolved_trade
        assert resolved_trade["winner"] == "Los Angeles Lakers"

    def test_already_resolved_paper_trades_skipped(self):
        from workflow.results import _resolve_paper_trades_for_date

        trades = [_make_paper_trade(game_id="12345", result="win")]

        with patch("workflow.results.get_paper_trades", return_value=trades), \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock) as mock_api:
            asyncio.get_event_loop().run_until_complete(
                _resolve_paper_trades_for_date("2026-02-20", 2025)
            )

        mock_api.assert_not_called()


# ===================================================================
# 10. WORKFLOW ORCHESTRATION — The full end-to-end pipeline
# ===================================================================


class TestWorkflowOrchestration:
    """The top-level workflow coordinates all sub-steps correctly."""

    def test_no_active_bets_exits_early(self):
        """If there are no active bets, the workflow should exit gracefully."""
        from workflow.results import run_results_workflow

        with patch("workflow.results.get_current_nba_season_year", return_value=2025), \
             patch("workflow.results.get_skips", return_value=[]), \
             patch("workflow.results.get_paper_trades", return_value=[]), \
             patch("workflow.results.get_active_bets", return_value=[]), \
             patch("workflow.results.clear_output_dir"):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )
        # Should not crash - just print "No active bets"

    def test_no_season_exits_early(self):
        """Off-season (no current season) should exit gracefully."""
        from workflow.results import run_results_workflow

        with patch("workflow.results.get_current_nba_season_year", return_value=None):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )

    def test_specific_date_processes_only_that_date(self):
        """When called with --date, only process bets for that date."""
        from workflow.results import run_results_workflow

        bet_feb20 = _make_bet(date="2026-02-20")
        bet_feb21 = _make_bet(id="bet-002", date="2026-02-21")

        with patch("workflow.results.get_current_nba_season_year", return_value=2025), \
             patch("workflow.results.get_skips", return_value=[]), \
             patch("workflow.results.get_paper_trades", return_value=[]), \
             patch("workflow.results.get_active_bets", return_value=[bet_feb20, bet_feb21]), \
             patch("workflow.results._process_results_for_date", new_callable=AsyncMock) as mock_process, \
             patch("workflow.results.clear_output_dir"):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow("2026-02-20")
            )

        # Should only process the specified date
        mock_process.assert_called_once_with("2026-02-20", 2025)

    def test_no_date_processes_all_active_dates(self):
        """When called without --date, process all dates that have active bets."""
        from workflow.results import run_results_workflow

        bet_feb20 = _make_bet(date="2026-02-20")
        bet_feb21 = _make_bet(id="bet-002", date="2026-02-21")

        with patch("workflow.results.get_current_nba_season_year", return_value=2025), \
             patch("workflow.results.get_skips", return_value=[]), \
             patch("workflow.results.get_paper_trades", return_value=[]), \
             patch("workflow.results.get_active_bets", return_value=[bet_feb20, bet_feb21]), \
             patch("workflow.results._process_results_for_date", new_callable=AsyncMock) as mock_process, \
             patch("workflow.results.clear_output_dir"):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )

        assert mock_process.call_count == 2
        dates_processed = [call.args[0] for call in mock_process.call_args_list]
        assert "2026-02-20" in dates_processed
        assert "2026-02-21" in dates_processed

    def test_unresolved_bets_kept_active(self):
        """Bets whose games haven't finished should remain in active.json."""
        from workflow.results import _process_results_for_date

        resolved_bet = _make_bet(id="bet-resolved", game_id="111")
        unresolved_bet = _make_bet(id="bet-unresolved", game_id="222", matchup="Warriors @ Heat")

        finished = [_make_game_result(game_id="111")]

        with patch("workflow.results.get_active_bets", return_value=[resolved_bet, unresolved_bet]), \
             patch("workflow.results._fetch_game_results", new_callable=AsyncMock, return_value=finished), \
             patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None), \
             patch("workflow.results.get_history", return_value={"bets": [], "summary": {
                 "total_bets": 0, "wins": 0, "losses": 0, "pushes": 0,
                 "win_rate": 0.0, "total_units_wagered": 0.0, "net_units": 0.0,
                 "roi": 0.0, "by_confidence": {}, "by_primary_edge": {},
                 "by_bet_type": {}, "current_streak": "", "net_dollar_pnl": 0.0,
             }}), \
             patch("workflow.results.save_history"), \
             patch("workflow.results.save_active_bets") as mock_save_active, \
             patch("workflow.results.append_journal_post_game"), \
             patch("workflow.results.get_dollar_pnl", return_value=0.0):
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        saved = mock_save_active.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["id"] == "bet-unresolved"

    def test_completed_bets_saved_to_history(self):
        """Settled bets should be added to history.json."""
        from workflow.results import _process_results_for_date

        bet = _make_bet(game_id="111")
        finished = [_make_game_result(game_id="111", winner="Los Angeles Lakers")]
        history = {"bets": [], "summary": {
            "total_bets": 0, "wins": 0, "losses": 0, "pushes": 0,
            "win_rate": 0.0, "total_units_wagered": 0.0, "net_units": 0.0,
            "roi": 0.0, "by_confidence": {}, "by_primary_edge": {},
            "by_bet_type": {}, "current_streak": "", "net_dollar_pnl": 0.0,
        }}

        with patch("workflow.results.get_active_bets", return_value=[bet]), \
             patch("workflow.results._fetch_game_results", new_callable=AsyncMock, return_value=finished), \
             patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None), \
             patch("workflow.results.get_history", return_value=history), \
             patch("workflow.results.save_history") as mock_save_hist, \
             patch("workflow.results.save_active_bets"), \
             patch("workflow.results.append_journal_post_game"), \
             patch("workflow.results.get_dollar_pnl", return_value=0.0):
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        mock_save_hist.assert_called_once()
        assert len(history["bets"]) == 1
        assert history["bets"][0]["result"] == "win"

    def test_journal_entry_written_for_completed_bets(self):
        """A journal entry should be created for each date with completed bets."""
        from workflow.results import _process_results_for_date

        bet = _make_bet(game_id="111")
        finished = [_make_game_result(game_id="111", winner="Los Angeles Lakers")]

        with patch("workflow.results.get_active_bets", return_value=[bet]), \
             patch("workflow.results._fetch_game_results", new_callable=AsyncMock, return_value=finished), \
             patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None), \
             patch("workflow.results.get_history", return_value={"bets": [], "summary": {
                 "total_bets": 0, "wins": 0, "losses": 0, "pushes": 0,
                 "win_rate": 0.0, "total_units_wagered": 0.0, "net_units": 0.0,
                 "roi": 0.0, "by_confidence": {}, "by_primary_edge": {},
                 "by_bet_type": {}, "current_streak": "", "net_dollar_pnl": 0.0,
             }}), \
             patch("workflow.results.save_history"), \
             patch("workflow.results.save_active_bets"), \
             patch("workflow.results.append_journal_post_game") as mock_journal, \
             patch("workflow.results.get_dollar_pnl", return_value=0.0):
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        mock_journal.assert_called_once()
        date_arg = mock_journal.call_args[0][0]
        completed_arg = mock_journal.call_args[0][1]
        assert date_arg == "2026-02-20"
        assert len(completed_arg) == 1

    def test_no_journal_when_no_bets_completed(self):
        """If all bets are unresolved (games not finished), skip journal."""
        from workflow.results import _process_results_for_date

        with patch("workflow.results.get_active_bets", return_value=[_make_bet()]), \
             patch("workflow.results._fetch_game_results", new_callable=AsyncMock, return_value=None), \
             patch("workflow.results.save_active_bets"), \
             patch("workflow.results.append_journal_post_game") as mock_journal:
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        mock_journal.assert_not_called()

    def test_paper_trade_failure_non_fatal(self):
        """Paper trade resolution failures should not block real bet processing."""
        from workflow.results import run_results_workflow

        with patch("workflow.results.get_current_nba_season_year", return_value=2025), \
             patch("workflow.results.get_skips", return_value=[]), \
             patch("workflow.results.get_paper_trades", side_effect=Exception("Paper file corrupt")), \
             patch("workflow.results.get_active_bets", return_value=[]), \
             patch("workflow.results.clear_output_dir"):
            # Should not raise, paper trade failure is caught
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )


# ===================================================================
# 11. GAME RESULT FETCHING — API interaction patterns
# ===================================================================


class TestGameResultFetching:
    """Game results should be fetched efficiently based on bet type."""

    def test_numeric_game_ids_fetched_individually(self):
        """Bets with numeric game_ids should fetch by individual game ID."""
        from workflow.results import _fetch_game_results

        bets = [_make_bet(game_id="12345")]
        game_data = {
            "id": 12345,
            "status": {"long": "Finished"},
            "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
            "scores": {"home": {"points": 115}, "visitors": {"points": 108}},
        }

        with patch("workflow.results.get_game_by_id", new_callable=AsyncMock, return_value=game_data) as mock_get:
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results(bets, "2026-02-20", 2025)
            )

        mock_get.assert_called_once_with(12345)
        assert result is not None
        assert len(result) == 1

    def test_legacy_bets_fetch_by_date(self):
        """Bets with non-numeric game_ids should fall back to date-based fetch."""
        from workflow.results import _fetch_game_results

        bets = [_make_bet(game_id="legacy-abc")]

        with patch("workflow.results.get_game_by_id", new_callable=AsyncMock) as mock_by_id, \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock, return_value=[{
                 "id": 99, "status": {"long": "Finished"},
                 "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
                 "scores": {"home": {"points": 115}, "visitors": {"points": 108}},
             }]) as mock_by_date:
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results(bets, "2026-02-20", 2025)
            )

        mock_by_id.assert_not_called()
        mock_by_date.assert_called_once()
        assert result is not None

    def test_returns_none_when_no_games_finished(self):
        """If all games are still in progress or scheduled, return None."""
        from workflow.results import _fetch_game_results

        bets = [_make_bet(game_id="12345")]
        game_data = {
            "id": 12345,
            "status": {"long": "Scheduled"},
            "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
            "scores": {"home": {"points": None}, "visitors": {"points": None}},
        }

        with patch("workflow.results.get_game_by_id", new_callable=AsyncMock, return_value=game_data):
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results(bets, "2026-02-20", 2025)
            )

        assert result is None

    def test_deduplicates_games_across_fetch_methods(self):
        """If both numeric and legacy bets reference the same game, don't duplicate results."""
        from workflow.results import _fetch_game_results

        # Same game fetched both ways — should only appear once
        numeric_bet = _make_bet(id="b1", game_id="12345")
        legacy_bet = _make_bet(id="b2", game_id="legacy-id")

        game_data = {
            "id": 12345,
            "status": {"long": "Finished"},
            "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
            "scores": {"home": {"points": 115}, "visitors": {"points": 108}},
        }

        with patch("workflow.results.get_game_by_id", new_callable=AsyncMock, return_value=game_data), \
             patch("workflow.results.get_games_by_date", new_callable=AsyncMock, return_value=[game_data]):
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results([numeric_bet, legacy_bet], "2026-02-20", 2025)
            )

        assert result is not None
        # Game 12345 fetched by ID first, then the same game from date fetch
        # is deduplicated by seen_game_ids
        assert len(result) == 1


# ===================================================================
# 12. JOURNAL WRITING — Auditability of decisions
# ===================================================================


class TestJournalWriting:
    """Journal entries should document bet outcomes for review."""

    def test_journal_contains_bet_details(self):
        from workflow.journal import append_journal_post_game

        completed = [{
            "matchup": "Celtics @ Lakers",
            "bet_type": "moneyline",
            "pick": "Lakers",
            "line": None,
            "result": "win",
            "profit_loss": 2.0,
            "final_score": "Celtics 108 @ Lakers 115",
            "winner": "Lakers",
            "reflection": "Edge was valid.",
            "actual_total": 223,
            "actual_margin": 7,
        }]

        written_content = []
        mock_path = MagicMock()
        mock_path.exists.return_value = False  # Fresh journal, no existing file
        mock_journal_dir = MagicMock()
        mock_journal_dir.__truediv__ = MagicMock(return_value=mock_path)

        with patch("workflow.journal.JOURNAL_DIR", mock_journal_dir), \
             patch("workflow.journal.append_text", side_effect=lambda p, c: written_content.append(c)):
            append_journal_post_game("2026-02-20", completed)

        text = written_content[0]
        assert "NBA Betting Journal - 2026-02-20" in text  # Header for fresh journal
        assert "Post-Game Results" in text
        assert "WIN" in text
        assert "Lakers" in text
        assert "Celtics 108 @ Lakers 115" in text

    def test_journal_not_duplicated_on_rerun(self):
        """Re-running results should not append duplicate journal sections."""
        from workflow.journal import append_journal_post_game

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "## Post-Game Results\nalready here"
        mock_journal_dir = MagicMock()
        mock_journal_dir.__truediv__ = MagicMock(return_value=mock_path)

        with patch("workflow.journal.JOURNAL_DIR", mock_journal_dir), \
             patch("workflow.journal.append_text") as mock_append:
            append_journal_post_game("2026-02-20", [])

        mock_append.assert_not_called()

    def test_journal_shows_push_record(self):
        """Record format should include pushes when there are any."""
        from workflow.journal import append_journal_post_game

        completed = [
            {
                "matchup": "A @ B", "bet_type": "total", "pick": "over",
                "line": 220.0, "result": "push", "profit_loss": 0.0,
                "final_score": "A 110 @ B 110", "winner": "",
                "reflection": "", "actual_total": 220, "actual_margin": 0,
            },
        ]

        written = []
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_journal_dir = MagicMock()
        mock_journal_dir.__truediv__ = MagicMock(return_value=mock_path)

        with patch("workflow.journal.JOURNAL_DIR", mock_journal_dir), \
             patch("workflow.journal.append_text", side_effect=lambda p, c: written.append(c)):
            append_journal_post_game("2026-02-20", completed)

        text = written[0]
        assert "0-0-1" in text  # Record with push count


# ===================================================================
# 13. REFLECT_ON_BET — Prompt formatting for LLM reflection
# ===================================================================


class TestReflectOnBetPrompt:
    """The reflection prompt should be correctly formatted for the LLM."""

    def test_moneyline_reflection_prompt_formatted(self):
        from workflow.results import reflect_on_bet

        bet = _make_bet(pick="Lakers", line=None, units=2.0)
        result = _make_game_result(home_score=115, away_score=108)

        with patch("workflow.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "Lakers" in prompt
        assert "WIN" in prompt
        assert "N/A" in prompt  # line is None for moneyline

    def test_spread_reflection_shows_signed_line(self):
        from workflow.results import reflect_on_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-5.5, units=1.0)
        result = _make_game_result(home_score=115, away_score=108)

        with patch("workflow.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "-5.5" in prompt

    def test_total_reflection_shows_line_without_sign(self):
        from workflow.results import reflect_on_bet

        bet = _make_bet(bet_type="total", pick="over", line=224.5, units=1.0)
        result = _make_game_result(home_score=115, away_score=108)

        with patch("workflow.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "224.5" in prompt

    def test_player_prop_reflection_includes_stat_context(self):
        from workflow.results import reflect_on_bet

        bet = _make_prop_bet(player_name="LeBron James", prop_type="points", pick="over", line=25.5)
        bet["_actual_stat"] = 30
        result = _make_game_result()

        with patch("workflow.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "LeBron James" in prompt
        assert "points" in prompt
        assert "30" in prompt  # actual stat


# ===================================================================
# 14. OUTPUT CLEANUP — Matchup files removed after processing
# ===================================================================


class TestOutputCleanup:
    """After results processing, matchup JSON files should be removed."""

    def test_output_dir_cleared(self):
        from workflow.io import clear_output_dir

        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = [mock_file]

        with patch("workflow.io.OUTPUT_DIR", mock_dir):
            clear_output_dir()

        mock_file.unlink.assert_called_once()

    def test_output_cleanup_skipped_if_no_dir(self):
        from workflow.io import clear_output_dir

        mock_dir = MagicMock()
        mock_dir.exists.return_value = False

        with patch("workflow.io.OUTPUT_DIR", mock_dir):
            clear_output_dir()  # Should not crash
