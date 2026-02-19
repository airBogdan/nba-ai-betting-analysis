"""Integration tests — verify module composition, not individual functions."""

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


# === Module-level helpers ===


def _make_active_bet(**overrides):
    """Return a complete ActiveBet dict with sensible defaults."""
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
    """Return a complete CompletedBet dict."""
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
    """Return a GameResult dict."""
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


# === Class 1: TestBetEvaluationIntegration ===


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


# === Class 2: TestFileIORoundTrips ===


class TestFileIORoundTrips:
    """Tests write→read cycles preserve all data through JSON serialization."""

    @pytest.fixture
    def tmp_bets_dir(self, tmp_path):
        """Patch BETS_DIR to a temp directory."""
        with patch("workflow.io.BETS_DIR", tmp_path):
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


# === Class 3: TestHistoryAccumulationIntegration ===


class TestHistoryAccumulationIntegration:
    """Tests sequential update_history_with_bet() calls maintain correct running totals."""

    def test_sequential_accumulation(self):
        history = {"bets": [], "summary": _empty_summary()}

        outcomes = [
            ("win", 1.0, "high"),
            ("win", 1.0, "medium"),
            ("loss", -1.0, "high"),
            ("win", 0.5, "low"),
            ("loss", -1.0, "medium"),
        ]

        for i, (result, profit_loss, confidence) in enumerate(outcomes):
            bet = _make_completed_bet(
                id=f"seq-{i}",
                result=result,
                profit_loss=profit_loss,
                units=abs(profit_loss),
                confidence=confidence,
            )
            update_history_with_bet(history, bet)

        s = history["summary"]
        assert s["total_bets"] == 5
        assert s["wins"] == 3
        assert s["losses"] == 2
        assert s["net_units"] == pytest.approx(0.5)
        assert s["win_rate"] == pytest.approx(0.6)

    def test_by_confidence_breakdown(self):
        history = {"bets": [], "summary": _empty_summary()}

        bets = [
            _make_completed_bet(id="c1", result="win", profit_loss=1.0, confidence="high"),
            _make_completed_bet(id="c2", result="loss", profit_loss=-1.0, confidence="high"),
            _make_completed_bet(id="c3", result="win", profit_loss=1.0, confidence="medium"),
        ]

        for bet in bets:
            update_history_with_bet(history, bet)

        by_conf = history["summary"]["by_confidence"]
        assert by_conf["high"]["wins"] == 1
        assert by_conf["high"]["losses"] == 1
        assert by_conf["high"]["win_rate"] == 0.5
        assert by_conf["medium"]["wins"] == 1
        assert by_conf["medium"]["losses"] == 0

    def test_by_bet_type_breakdown(self):
        history = {"bets": [], "summary": _empty_summary()}

        bets = [
            _make_completed_bet(id="t1", result="win", profit_loss=1.0, bet_type="moneyline"),
            _make_completed_bet(id="t2", result="loss", profit_loss=-1.0, bet_type="spread"),
            _make_completed_bet(id="t3", result="win", profit_loss=1.0, bet_type="total"),
        ]

        for bet in bets:
            update_history_with_bet(history, bet)

        by_type = history["summary"]["by_bet_type"]
        assert by_type["moneyline"]["wins"] == 1
        assert by_type["spread"]["losses"] == 1
        assert by_type["total"]["wins"] == 1

    def test_streak_tracking(self):
        history = {"bets": [], "summary": _empty_summary()}

        # W, W, W, L, L
        sequence = ["win", "win", "win", "loss", "loss"]
        for i, result in enumerate(sequence):
            profit = 1.0 if result == "win" else -1.0
            bet = _make_completed_bet(id=f"s-{i}", result=result, profit_loss=profit)
            update_history_with_bet(history, bet)

        assert history["summary"]["current_streak"] == "L2"

        # Add a win → streak should change to W1
        bet = _make_completed_bet(id="s-5", result="win", profit_loss=1.0)
        update_history_with_bet(history, bet)
        assert history["summary"]["current_streak"] == "W1"


# === Class 4: TestBettingLifecycleIntegration ===


class TestBettingLifecycleIntegration:
    """Tests full bet lifecycle: create → persist → evaluate → history update."""

    @pytest.fixture
    def tmp_bets_dir(self, tmp_path):
        with patch("workflow.io.BETS_DIR", tmp_path):
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


# === Class 5: TestMatchupPipelineIntegration ===


def _make_standing(season=2025, **overrides):
    """Return a realistic SeasonStanding."""
    base = {
        "season": season,
        "conference_rank": 1,
        "wins": 40,
        "losses": 15,
        "win_pct": ".727",
        "home_wins": 22,
        "home_losses": 6,
        "away_wins": 18,
        "away_losses": 9,
        "last_ten_wins": 7,
        "last_ten_losses": 3,
        "home_win_pct": 0.786,
        "away_win_pct": 0.667,
        "last_ten_pct": 0.7,
        "home_court_advantage": 0.119,
    }
    base.update(overrides)
    return base


def _make_team_stats(season=2025, **overrides):
    """Return a realistic ProcessedTeamStats."""
    base = {
        "games": 55,
        "ppg": 115.0,
        "apg": 27.0,
        "rpg": 45.0,
        "topg": 13.0,
        "disruption": 8.0,
        "net_rating": 6.5,
        "tpp": 37.5,
        "fgp": 48.0,
        "pace": 101.0,
    }
    base.update(overrides)
    return base


def _make_recent_game(vs="Opponent", result="W", score="115-108", margin=7, date="2025-02-13", **overrides):
    """Return a RecentGame dict."""
    base = {
        "vs": vs,
        "vs_record": "25-20",
        "vs_win_pct": 0.556,
        "result": result,
        "score": score,
        "home": True,
        "margin": margin,
        "date": date,
    }
    base.update(overrides)
    return base


def _make_h2h_game(
    home_team="Lakers", visitor_team="Celtics",
    home_points=110, visitor_points=108,
    home_linescore=None, visitor_linescore=None,
    home_statistics=None, visitor_statistics=None,
    game_id=1,
):
    """Return an H2H game dict."""
    winner = home_team if home_points > visitor_points else visitor_team
    game = {
        "id": game_id,
        "home_team": home_team,
        "visitor_team": visitor_team,
        "home_points": home_points,
        "visitor_points": visitor_points,
        "winner": winner,
        "point_diff": home_points - visitor_points,
        "home_linescore": home_linescore or [28, 27, 28, 27],
        "visitor_linescore": visitor_linescore or [26, 28, 27, 27],
    }
    if home_statistics:
        game["home_statistics"] = home_statistics
    if visitor_statistics:
        game["visitor_statistics"] = visitor_statistics
    return game


def _make_box_stats(**overrides):
    """Return game statistics dict for H2H box scores."""
    base = {
        "fgp": 47.0,
        "tpp": 36.0,
        "totReb": 44,
        "assists": 25,
        "turnovers": 13,
        "steals": 7,
        "blocks": 5,
    }
    base.update(overrides)
    return base


class TestMatchupPipelineIntegration:
    """Tests build_matchup_analysis() chaining: snapshots → edges → H2H → totals → signals."""

    @pytest.fixture
    def matchup_input(self):
        """Build realistic Celtics @ Lakers matchup input."""
        team1_standings = [_make_standing(season=2025, wins=40, losses=15)]
        team2_standings = [_make_standing(
            season=2025, wins=30, losses=25, conference_rank=6,
            home_wins=18, home_losses=10, away_wins=12, away_losses=15,
            last_ten_wins=5, last_ten_losses=5, last_ten_pct=0.5,
            home_win_pct=0.643, away_win_pct=0.444,
        )]

        team1_stats = {2025: _make_team_stats(ppg=115.0, net_rating=6.5, pace=101.0)}
        team2_stats = {2025: _make_team_stats(ppg=110.0, net_rating=1.5, pace=99.0)}

        team1_players = [
            {"id": 1, "name": "Jayson Tatum", "games": 50, "mpg": 36.0,
             "ppg": 27.0, "rpg": 8.0, "apg": 5.0, "disruption": 1.5,
             "fgp": 47.0, "tpp": 37.0, "plus_minus": 8.5},
            {"id": 2, "name": "Jaylen Brown", "games": 48, "mpg": 34.0,
             "ppg": 23.0, "rpg": 5.5, "apg": 3.5, "disruption": 1.2,
             "fgp": 49.0, "tpp": 35.0, "plus_minus": 6.0},
            {"id": 3, "name": "Derrick White", "games": 52, "mpg": 32.0,
             "ppg": 16.0, "rpg": 4.0, "apg": 4.5, "disruption": 2.0,
             "fgp": 46.0, "tpp": 39.0, "plus_minus": 7.0},
        ]
        team2_players = [
            {"id": 10, "name": "Anthony Davis", "games": 45, "mpg": 35.0,
             "ppg": 25.5, "rpg": 12.0, "apg": 3.5, "disruption": 3.0,
             "fgp": 55.0, "tpp": 28.0, "plus_minus": 3.0},
            {"id": 11, "name": "LeBron James", "games": 50, "mpg": 33.0,
             "ppg": 24.0, "rpg": 7.0, "apg": 8.5, "disruption": 1.8,
             "fgp": 52.0, "tpp": 38.0, "plus_minus": 4.5},
            {"id": 12, "name": "Austin Reaves", "games": 53, "mpg": 30.0,
             "ppg": 17.0, "rpg": 4.5, "apg": 5.0, "disruption": 1.0,
             "fgp": 47.0, "tpp": 36.0, "plus_minus": 2.0},
        ]

        recent1 = [
            _make_recent_game(vs="Heat", result="W", score="118-105", margin=13, date="2025-02-13"),
            _make_recent_game(vs="Bucks", result="W", score="112-108", margin=4, date="2025-02-11"),
            _make_recent_game(vs="Knicks", result="W", score="110-102", margin=8, date="2025-02-09"),
        ]
        recent2 = [
            _make_recent_game(vs="Suns", result="L", score="105-112", margin=-7, date="2025-02-14"),
            _make_recent_game(vs="Kings", result="W", score="115-110", margin=5, date="2025-02-12"),
            _make_recent_game(vs="Clippers", result="L", score="100-108", margin=-8, date="2025-02-10"),
        ]

        # 3-season H2H data with linescores and box scores
        h2h_results = {
            2025: [
                _make_h2h_game(
                    home_team="Lakers", visitor_team="Celtics",
                    home_points=108, visitor_points=115,
                    home_linescore=[25, 28, 27, 28],
                    visitor_linescore=[30, 28, 29, 28],
                    home_statistics=_make_box_stats(fgp=45.0, tpp=33.0),
                    visitor_statistics=_make_box_stats(fgp=49.0, tpp=38.0),
                    game_id=1001,
                ),
                _make_h2h_game(
                    home_team="Celtics", visitor_team="Lakers",
                    home_points=120, visitor_points=105,
                    home_linescore=[32, 30, 28, 30],
                    visitor_linescore=[26, 27, 25, 27],
                    home_statistics=_make_box_stats(fgp=51.0, tpp=40.0),
                    visitor_statistics=_make_box_stats(fgp=43.0, tpp=30.0),
                    game_id=1002,
                ),
            ],
            2024: [
                _make_h2h_game(
                    home_team="Lakers", visitor_team="Celtics",
                    home_points=112, visitor_points=110,
                    home_linescore=[28, 30, 27, 27],
                    visitor_linescore=[27, 28, 28, 27],
                    home_statistics=_make_box_stats(fgp=47.0, tpp=35.0),
                    visitor_statistics=_make_box_stats(fgp=46.0, tpp=36.0),
                    game_id=1003,
                ),
            ],
            2023: [
                _make_h2h_game(
                    home_team="Celtics", visitor_team="Lakers",
                    home_points=125, visitor_points=100,
                    home_linescore=[33, 30, 32, 30],
                    visitor_linescore=[24, 26, 25, 25],
                    home_statistics=_make_box_stats(fgp=53.0, tpp=42.0),
                    visitor_statistics=_make_box_stats(fgp=40.0, tpp=28.0),
                    game_id=1004,
                ),
            ],
        }

        # Compute h2h_summary for real (tests H2H→matchup composition)
        from helpers.games import compute_h2h_summary
        with patch("helpers.games.get_current_nba_season_year", return_value=2025):
            h2h_summary = compute_h2h_summary(h2h_results, "Celtics", "Lakers")

        return {
            "team1_name": "Celtics",
            "team2_name": "Lakers",
            "home_team": "Lakers",
            "team1_standings": team1_standings,
            "team2_standings": team2_standings,
            "team1_stats": team1_stats,
            "team2_stats": team2_stats,
            "team1_players": team1_players,
            "team2_players": team2_players,
            "team1_recent_games": recent1,
            "team2_recent_games": recent2,
            "h2h_summary": h2h_summary,
            "h2h_results": h2h_results,
            "game_date": "2025-02-15",
        }

    def _run_with_mocks(self, matchup_input):
        """Run build_matchup_analysis with season mocks."""
        from helpers.matchup import build_matchup_analysis
        with patch("helpers.matchup.get_current_nba_season_year", return_value=2025), \
             patch("helpers.games.get_current_nba_season_year", return_value=2025):
            return build_matchup_analysis(matchup_input)

    def test_full_matchup_returns_all_keys(self, matchup_input):
        analysis = self._run_with_mocks(matchup_input)
        expected_keys = {
            "matchup", "current_season", "schedule", "recent_games",
            "players", "h2h", "totals_analysis", "comparison", "signals",
        }
        assert set(analysis.keys()) == expected_keys

    def test_snapshots_feed_into_edges(self, matchup_input):
        analysis = self._run_with_mocks(matchup_input)

        team1_ppg = analysis["current_season"]["team1"]["ppg"]
        team2_ppg = analysis["current_season"]["team2"]["ppg"]
        edge_ppg = analysis["comparison"]["ppg"]

        assert edge_ppg == pytest.approx(team1_ppg - team2_ppg, abs=0.01)

    def test_h2h_block_assembled(self, matchup_input):
        analysis = self._run_with_mocks(matchup_input)

        h2h = analysis["h2h"]
        assert h2h is not None
        assert "summary" in h2h
        assert "patterns" in h2h
        assert "recent" in h2h
        assert "quarters" in h2h
        assert "matchup_stats" in h2h

        # H2H should have data from our fixture
        assert h2h["summary"]["total_games"] == 4
        assert h2h["patterns"]["avg_total"] > 0
        assert h2h["matchup_stats"]["team1"]["avg_fgp"] > 0

    def test_totals_uses_snapshots_and_h2h(self, matchup_input):
        analysis = self._run_with_mocks(matchup_input)

        totals = analysis["totals_analysis"]
        assert 180 < totals["expected_total"] < 260
        assert totals["pace_adjusted_total"] > 0
        # Defense factor should be reasonable
        assert 100 < totals["defense_factor"] < 130

    def test_signals_from_composite_data(self, matchup_input):
        analysis = self._run_with_mocks(matchup_input)

        signals = analysis["signals"]
        signal_text = " ".join(signals)

        # Celtics have 7-3 last 10 (0.7 = hot threshold) → hot form signal
        assert "Celtics" in signal_text and "hot form" in signal_text
        # Lakers have strong home record (0.643 > 0.6)
        assert "strong at home" in signal_text
        # PPG edge: 115 - 110 = 5.0 > PPG_EDGE_THRESHOLD (3.0)
        assert "PPG edge" in signal_text

    def test_matchup_without_h2h(self, matchup_input):
        matchup_input["h2h_summary"] = None
        matchup_input["h2h_results"] = None

        analysis = self._run_with_mocks(matchup_input)

        assert analysis["h2h"] is None
        # Should still have all other keys
        assert analysis["comparison"] is not None
        assert analysis["totals_analysis"] is not None
        # Should have no-H2H signal
        signal_text = " ".join(analysis["signals"])
        assert "No recent H2H" in signal_text


# === Class 6: TestMatchupToWorkflowDataFlow ===


class TestMatchupToWorkflowDataFlow:
    """Tests that matchup output is compatible with workflow consumption."""

    def test_format_matchup_string(self):
        matchup = {
            "team1": "Celtics",
            "team2": "Lakers",
            "home_team": "Lakers",
        }
        result = format_matchup_string(matchup)
        assert result == "Celtics @ Lakers"

        # When team1 is home
        matchup2 = {
            "team1": "Lakers",
            "team2": "Celtics",
            "home_team": "Lakers",
        }
        result2 = format_matchup_string(matchup2)
        assert result2 == "Celtics @ Lakers"

    def test_compact_json_round_trip(self):
        """Full matchup-like dict → compact_json → json.loads succeeds, no None values."""
        data = {
            "matchup": {"team1": "Celtics", "team2": "Lakers", "home_team": "Lakers"},
            "current_season": {
                "team1": {"name": "Celtics", "ppg": 115.0, "net_rating": 6.5},
                "team2": {"name": "Lakers", "ppg": 110.0, "net_rating": 1.5},
            },
            "h2h": None,  # Should be stripped
            "signals": ["Signal 1", "Signal 2"],
            "empty_list": [],  # Should be stripped
            "empty_dict": {},  # Should be stripped
        }
        result = compact_json(data)
        parsed = json.loads(result)

        assert "matchup" in parsed
        assert "h2h" not in parsed
        assert "empty_list" not in parsed
        assert "empty_dict" not in parsed
        assert parsed["current_season"]["team1"]["ppg"] == 115.0

    def test_injury_impact_with_rotation(self):
        """Matchup rotation data + mock injuries → compute_injury_impact returns correct PPG loss."""
        team1_rotation = [
            {"name": "Jayson Tatum", "ppg": 27.0, "plus_minus": 8.5, "games": 50},
            {"name": "Jaylen Brown", "ppg": 23.0, "plus_minus": 6.0, "games": 48},
            {"name": "Derrick White", "ppg": 16.0, "plus_minus": 7.0, "games": 52},
        ]
        team2_rotation = [
            {"name": "Anthony Davis", "ppg": 25.5, "plus_minus": 3.0, "games": 45},
            {"name": "LeBron James", "ppg": 24.0, "plus_minus": 4.5, "games": 50},
        ]

        extracted_injuries = [
            {"team": "Celtics", "player": "Jayson Tatum", "status": "Out"},
            {"team": "Lakers", "player": "Anthony Davis", "status": "Doubtful"},
        ]

        impact = compute_injury_impact(
            extracted_injuries, "Celtics", "Lakers",
            team1_rotation, team2_rotation,
        )

        assert impact is not None
        # Tatum 27.0 * 0.45 = 12.15 → rounds to 12.1
        assert impact["team1"]["adjusted_ppg_loss"] == pytest.approx(12.1, abs=0.1)
        assert impact["team1"]["out_players"][0]["name"] == "Jayson Tatum"
        # Davis 25.5 * 0.45 = 11.475 → rounds to 11.5
        assert impact["team2"]["adjusted_ppg_loss"] == pytest.approx(11.5, abs=0.1)
        assert impact["total_reduction"] == pytest.approx(23.6, abs=0.1)
