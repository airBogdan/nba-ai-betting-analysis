"""Integration tests — bet evaluation path."""

import json
from unittest.mock import patch

import pytest

from workflow.analyze.bets import create_active_bet
from workflow.analyze.gamedata import format_matchup_string
from workflow.analyze.injuries import compute_injury_impact
from workflow.io import (
    _empty_summary,
    get_active_bets,
    get_dollar_pnl,
    get_history,
    get_open_exposure,
    save_active_bets,
    save_history,
)
from workflow.prompts import compact_json
from workflow.evaluation import _evaluate_bet, calculate_payout
from workflow.game_results import match_bet_to_result
from workflow.history import update_history_with_bet


def _make_active_bet(**overrides):
    base = {
        "id": "test-001",
        "game_id": "12345",
        "matchup": "Celtics @ Lakers",
        "bet_type": "moneyline",
        "pick": "Celtics",
        "line": None,
        "confidence": "medium",
        "units": 1.0,
        "reasoning": "Test reasoning",
        "primary_edge": "form_momentum",
        "date": "2025-02-15",
        "created_at": "2025-02-15T12:00:00+00:00",
    }
    base.update(overrides)
    return base


def _make_completed_bet(**overrides):
    base = {
        **_make_active_bet(),
        "result": "win",
        "winner": "Celtics",
        "final_score": "Celtics 110 @ Lakers 105",
        "actual_total": 215,
        "actual_margin": -5,
        "profit_loss": 1.0,
        "reflection": "",
    }
    base.update(overrides)
    return base


def _make_game_result(**overrides):
    base = {
        "game_id": "12345",
        "home_team": "Lakers",
        "away_team": "Celtics",
        "home_score": 105,
        "away_score": 110,
        "winner": "Celtics",
        "status": "finished",
    }
    base.update(overrides)
    return base


class TestBetEvaluationIntegration:
    """Tests full evaluation path: ActiveBet + GameResult → _evaluate_bet → calculate_payout."""

    def test_moneyline_win_payout(self):
        bet = _make_active_bet(pick="Celtics", bet_type="moneyline", units=1.0)
        result = _make_game_result(winner="Celtics")

        outcome, profit_loss = _evaluate_bet(bet, result)
        assert outcome == "win"
        assert profit_loss == 1.0

        # Payout at -150 odds
        payout = calculate_payout(100.0, -150, outcome)
        assert payout == pytest.approx(166.67, abs=0.01)

    def test_moneyline_loss_payout(self):
        bet = _make_active_bet(pick="Celtics", bet_type="moneyline", units=1.0)
        result = _make_game_result(winner="Lakers")

        outcome, profit_loss = _evaluate_bet(bet, result)
        assert outcome == "loss"
        assert profit_loss == -1.0

        payout = calculate_payout(100.0, -150, outcome)
        assert payout == 0.0

    def test_spread_cover_and_miss(self):
        # Celtics -5.5: they won by 5 → didn't cover
        bet = _make_active_bet(
            pick="Celtics", bet_type="spread", line=-5.5, units=1.0
        )
        result = _make_game_result(
            home_team="Lakers", away_team="Celtics",
            home_score=105, away_score=110, winner="Celtics",
        )

        outcome, profit_loss = _evaluate_bet(bet, result)
        assert outcome == "loss"
        assert profit_loss == -1.0

        # Celtics -4.5: they won by 5 → covered
        bet2 = _make_active_bet(
            pick="Celtics", bet_type="spread", line=-4.5, units=1.0
        )
        outcome2, profit_loss2 = _evaluate_bet(bet2, result)
        assert outcome2 == "win"
        assert profit_loss2 == 1.0

    def test_spread_push(self):
        bet = _make_active_bet(
            pick="Celtics", bet_type="spread", line=-5.0, units=1.0
        )
        result = _make_game_result(
            home_team="Lakers", away_team="Celtics",
            home_score=105, away_score=110, winner="Celtics",
        )

        outcome, profit_loss = _evaluate_bet(bet, result)
        assert outcome == "push"
        assert profit_loss == 0.0

        payout = calculate_payout(100.0, -110, outcome)
        assert payout == 100.0  # Stake returned

    def test_total_over_under(self):
        # Over 214.5: actual total is 215 → win
        bet_over = _make_active_bet(
            pick="over", bet_type="total", line=214.5, units=1.0
        )
        result = _make_game_result(home_score=105, away_score=110)

        outcome, profit_loss = _evaluate_bet(bet_over, result)
        assert outcome == "win"
        assert profit_loss == 1.0

        # Under 214.5: actual total is 215 → loss
        bet_under = _make_active_bet(
            pick="under", bet_type="total", line=214.5, units=1.0
        )
        outcome2, profit_loss2 = _evaluate_bet(bet_under, result)
        assert outcome2 == "loss"
        assert profit_loss2 == -1.0

    def test_multi_bet_evaluation_pipeline(self):
        """3 bets (one per type) through match → evaluate → payout → build CompletedBet."""
        results = [
            _make_game_result(
                game_id="100", home_team="Lakers", away_team="Celtics",
                home_score=105, away_score=110, winner="Celtics",
            ),
        ]

        bets = [
            _make_active_bet(
                id="ml-1", game_id="100", pick="Celtics",
                bet_type="moneyline", units=1.0,
            ),
            _make_active_bet(
                id="sp-1", game_id="100", pick="Celtics",
                bet_type="spread", line=-4.5, units=1.0,
            ),
            _make_active_bet(
                id="tot-1", game_id="100", pick="over",
                bet_type="total", line=220.0, units=1.0,
            ),
        ]

        completed = []
        for bet in bets:
            matched = match_bet_to_result(bet, results)
            assert matched is not None

            outcome, profit_loss = _evaluate_bet(bet, matched)
            payout = calculate_payout(50.0, -110, outcome)

            completed.append({
                **bet,
                "result": outcome,
                "profit_loss": profit_loss,
                "payout": payout,
            })

        assert completed[0]["result"] == "win"   # Celtics won
        assert completed[1]["result"] == "win"   # Celtics won by 5 > 4.5
        assert completed[2]["result"] == "loss"  # 215 < 220
