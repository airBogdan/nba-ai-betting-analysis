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


class TestReflectionGeneration:
    """Each completed bet gets an LLM reflection on reasoning quality."""

    def test_reflection_included_in_completed_bet(self):
        from betting.results.results import _build_completed_bets

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

        with patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=mock_reflection):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert completed[0]["reflection"] == "Good bet, edge played out as expected."
        sr = completed[0]["structured_reflection"]
        assert sr["edge_valid"] is True
        assert sr["process_assessment"] == "sound"

    def test_reflection_failure_doesnt_block_settlement(self):
        """If LLM fails, the bet should still be settled — just without reflection text."""
        from betting.results.results import _build_completed_bets

        bet = _make_bet(units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, side_effect=Exception("LLM timeout")):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert len(completed) == 1
        assert completed[0]["result"] == "win"
        assert completed[0]["reflection"] == ""
        assert "structured_reflection" not in completed[0]

    def test_reflection_none_handled_gracefully(self):
        """LLM returning None should not crash."""
        from betting.results.results import _build_completed_bets

        bet = _make_bet(units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert completed[0]["reflection"] == ""

    def test_concurrent_reflections_are_bounded(self):
        """Reflections should be rate-limited to avoid overwhelming the LLM API."""
        from betting.results.results import MAX_CONCURRENT_LLM_CALLS

        # The system limits concurrent LLM calls
        assert MAX_CONCURRENT_LLM_CALLS > 0
        assert MAX_CONCURRENT_LLM_CALLS <= 10  # Reasonable bound


class TestCompletedBetConstruction:
    """Completed bets must contain all fields needed for history and journal."""

    def test_completed_bet_has_required_fields(self):
        from betting.results.results import _build_completed_bets

        bet = _make_bet(units=2.0)
        result = _make_game_result(
            home_score=115, away_score=108,
            winner="Los Angeles Lakers",
        )
        matched = [(bet, result, "win", 2.0)]

        with patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
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
        from betting.results.results import _build_completed_bets

        bet = _make_prop_bet(units=1.0)
        bet["_actual_stat"] = 30.0  # Internal field
        result = _make_game_result()
        matched = [(bet, result, "win", 1.0)]

        with patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        # _actual_stat should be cleaned, but actual_stat (no underscore) should be set for props
        assert "_actual_stat" not in completed[0]
        assert completed[0]["actual_stat"] == 30.0

    def test_prop_actual_stat_included_when_available(self):
        """Player prop completed bets should include the actual stat value."""
        from betting.results.results import _build_completed_bets

        bet = _make_prop_bet(units=1.0)
        bet["_actual_stat"] = 28.0
        result = _make_game_result()
        matched = [(bet, result, "win", 1.0)]

        with patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert completed[0]["actual_stat"] == 28.0


class TestHistoryTracking:
    """History should maintain accurate running statistics."""

    def test_win_updates_history_correctly(self):
        from betting.results.history import update_history_with_bet
        from betting.io import _empty_summary

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
        from betting.results.history import update_history_with_bet
        from betting.io import _empty_summary

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
        from betting.results.history import update_history_with_bet
        from betting.io import _empty_summary

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
        from betting.results.history import update_history_with_bet
        from betting.io import _empty_summary

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
        from betting.results.history import update_history_with_bet
        from betting.io import _empty_summary

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
        from betting.results.history import update_history_with_bet
        from betting.io import _empty_summary

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
        from betting.results.history import update_history_with_bet
        from betting.io import _empty_summary

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
        from betting.results.history import _categorize_edge

        assert _categorize_edge("Home court advantage") == "home_court"
        assert _categorize_edge("Rest advantage - opponent on B2B") == "rest_advantage"
        assert _categorize_edge("Key injury to starting PG") == "injury_edge"
        assert _categorize_edge("Hot streak, strong recent form") == "form_momentum"
        assert _categorize_edge("Net rating differential") == "ratings_edge"
