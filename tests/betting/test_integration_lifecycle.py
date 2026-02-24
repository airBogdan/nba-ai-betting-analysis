"""Integration tests — file I/O round trips and betting lifecycle."""

import json
from unittest.mock import patch

import pytest

from betting.analyze.bets import create_active_bet
from betting.analyze.gamedata import format_matchup_string
from betting.analyze.injuries import compute_injury_impact
from betting.io import (
    _empty_summary,
    get_active_bets,
    get_dollar_pnl,
    get_history,
    get_open_exposure,
    save_active_bets,
    save_history,
)
from betting.prompts import compact_json
from betting.evaluation import _evaluate_bet, calculate_payout
from betting.results.game_results import match_bet_to_result
from betting.results.history import update_history_with_bet


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


class TestFileIORoundTrips:
    """Tests write→read cycles preserve all data through JSON serialization."""

    @pytest.fixture
    def tmp_bets_dir(self, tmp_path):
        """Patch BETS_DIR to a temp directory."""
        with patch("betting.io.BETS_DIR", tmp_path):
            yield tmp_path

    def test_active_bets_round_trip(self, tmp_bets_dir):
        bets = [
            _make_active_bet(id="a1", amount=50.0, odds_price=-110),
            _make_active_bet(id="a2", amount=75.0, odds_price=+130),
            _make_active_bet(id="a3", amount=25.0, odds_price=-150, poly_price=0.6),
        ]
        save_active_bets(bets)
        loaded = get_active_bets()

        assert len(loaded) == 3
        assert loaded[0]["id"] == "a1"
        assert loaded[1]["amount"] == 75.0
        assert loaded[2]["poly_price"] == 0.6

    def test_history_round_trip(self, tmp_bets_dir):
        history = {
            "bets": [
                _make_completed_bet(id="c1", result="win", profit_loss=1.0, dollar_pnl=50.0),
                _make_completed_bet(id="c2", result="loss", profit_loss=-1.0, dollar_pnl=-50.0),
            ],
            "summary": {
                **_empty_summary(),
                "total_bets": 2,
                "wins": 1,
                "losses": 1,
            },
        }
        save_history(history)
        loaded = get_history()

        assert len(loaded["bets"]) == 2
        assert loaded["bets"][0]["dollar_pnl"] == 50.0
        assert loaded["summary"]["total_bets"] == 2

    def test_empty_state_defaults(self, tmp_bets_dir):
        assert get_active_bets() == []
        history = get_history()
        assert history["bets"] == []
        assert history["summary"]["total_bets"] == 0
        assert get_dollar_pnl() == 0.0

    def test_dollar_pnl_sums_from_history(self, tmp_bets_dir):
        history = {
            "bets": [
                _make_completed_bet(dollar_pnl=50.0),
                _make_completed_bet(dollar_pnl=-30.0),
                _make_completed_bet(dollar_pnl=10.0),
            ],
            "summary": _empty_summary(),
        }
        save_history(history)
        assert get_dollar_pnl() == pytest.approx(30.0)

    def test_open_exposure_sums_from_active(self, tmp_bets_dir):
        bets = [
            _make_active_bet(id="e1", amount=50.0),
            _make_active_bet(id="e2", amount=75.0),
            _make_active_bet(id="e3", amount=25.0),
        ]
        save_active_bets(bets)
        assert get_open_exposure() == pytest.approx(150.0)


class TestBettingLifecycleIntegration:
    """Tests full bet lifecycle: create → persist → evaluate → history update."""

    @pytest.fixture
    def tmp_bets_dir(self, tmp_path):
        with patch("betting.io.BETS_DIR", tmp_path):
            yield tmp_path

    def test_lifecycle_moneyline_win(self, tmp_bets_dir):
        # Create from SelectedBet → ActiveBet
        selected = {
            "game_id": "200",
            "matchup": "Celtics @ Lakers",
            "bet_type": "moneyline",
            "pick": "Celtics",
            "line": None,
            "confidence": "high",
            "units": 2.0,
            "reasoning": "Strong form edge",
            "primary_edge": "form_momentum",
        }
        active = create_active_bet(selected, "2025-02-15")
        assert active["confidence"] == "high"
        assert active["units"] == 2.0

        # Persist and read back
        save_active_bets([active])
        loaded = get_active_bets()
        assert len(loaded) == 1
        assert loaded[0]["game_id"] == "200"

        # Evaluate as win
        result = _make_game_result(
            game_id="200", home_team="Lakers", away_team="Celtics",
            home_score=100, away_score=112, winner="Celtics",
        )
        outcome, profit_loss = _evaluate_bet(loaded[0], result)
        assert outcome == "win"
        assert profit_loss == 2.0

        # Update history
        completed = {
            **loaded[0],
            "result": outcome,
            "profit_loss": profit_loss,
            "winner": result["winner"],
            "final_score": "Celtics 112 @ Lakers 100",
            "actual_total": 212,
            "actual_margin": -12,
            "reflection": "",
        }
        history = get_history()
        update_history_with_bet(history, completed)
        save_history(history)

        # Verify
        loaded_history = get_history()
        assert loaded_history["summary"]["wins"] == 1
        assert loaded_history["summary"]["net_units"] == 2.0

    def test_lifecycle_spread_loss(self, tmp_bets_dir):
        selected = {
            "game_id": "201",
            "matchup": "Nets @ Knicks",
            "bet_type": "spread",
            "pick": "Knicks",
            "line": -7.5,
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "Home court edge",
            "primary_edge": "home_court",
        }
        active = create_active_bet(selected, "2025-02-15")
        save_active_bets([active])

        # Knicks win by 5, but don't cover -7.5
        result = _make_game_result(
            game_id="201", home_team="Knicks", away_team="Nets",
            home_score=110, away_score=105, winner="Knicks",
        )
        loaded = get_active_bets()
        outcome, profit_loss = _evaluate_bet(loaded[0], result)
        assert outcome == "loss"
        assert profit_loss == -1.0

        completed = {
            **loaded[0],
            "result": outcome,
            "profit_loss": profit_loss,
            "winner": result["winner"],
            "final_score": "Nets 105 @ Knicks 110",
            "actual_total": 215,
            "actual_margin": 5,
            "reflection": "",
            "dollar_pnl": -50.0,
        }
        history = get_history()
        update_history_with_bet(history, completed)
        save_history(history)

        h = get_history()
        assert h["summary"]["losses"] == 1
        assert h["summary"]["net_units"] == -1.0
        assert h["summary"]["net_dollar_pnl"] == -50.0

    def test_multi_bet_lifecycle(self, tmp_bets_dir):
        """3 bets (win, loss, push) through full lifecycle."""
        selecteds = [
            {
                "game_id": "300", "matchup": "Celtics @ Lakers",
                "bet_type": "moneyline", "pick": "Celtics", "line": None,
                "confidence": "high", "units": 2.0,
                "reasoning": "r1", "primary_edge": "form_momentum",
            },
            {
                "game_id": "301", "matchup": "Nets @ Knicks",
                "bet_type": "spread", "pick": "Knicks", "line": -7.5,
                "confidence": "medium", "units": 1.0,
                "reasoning": "r2", "primary_edge": "home_court",
            },
            {
                "game_id": "302", "matchup": "Bucks @ Heat",
                "bet_type": "total", "pick": "over", "line": 220.0,
                "confidence": "low", "units": 0.5,
                "reasoning": "r3", "primary_edge": "totals_edge",
            },
        ]
        actives = [create_active_bet(s, "2025-02-15") for s in selecteds]
        save_active_bets(actives)

        game_results = [
            _make_game_result(
                game_id="300", home_team="Lakers", away_team="Celtics",
                home_score=100, away_score=110, winner="Celtics",
            ),
            _make_game_result(
                game_id="301", home_team="Knicks", away_team="Nets",
                home_score=110, away_score=105, winner="Knicks",
            ),
            _make_game_result(
                game_id="302", home_team="Heat", away_team="Bucks",
                home_score=110, away_score=110, winner="",
            ),
        ]

        history = get_history()
        loaded = get_active_bets()
        remaining = []

        for bet in loaded:
            matched = match_bet_to_result(bet, game_results)
            if not matched:
                remaining.append(bet)
                continue
            outcome, profit_loss = _evaluate_bet(bet, matched)
            completed = {
                **bet,
                "result": outcome,
                "profit_loss": profit_loss,
                "winner": matched["winner"],
                "final_score": f"{matched['away_team']} {matched['away_score']} @ {matched['home_team']} {matched['home_score']}",
                "actual_total": matched["home_score"] + matched["away_score"],
                "actual_margin": matched["home_score"] - matched["away_score"],
                "reflection": "",
            }
            update_history_with_bet(history, completed)

        save_history(history)
        save_active_bets(remaining)

        s = history["summary"]
        # Moneyline win (+2.0), spread loss (-1.0), total push (220 == 220 → 0.0)
        assert s["wins"] == 1
        assert s["losses"] == 1
        assert s["pushes"] == 1
        assert s["net_units"] == pytest.approx(1.0)
        assert len(remaining) == 0
