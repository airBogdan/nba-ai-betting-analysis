"""Integration tests — matchup pipeline and workflow data flow."""

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


def _make_standing(season=2025, **overrides):
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
        from helpers.h2h_stats import compute_h2h_summary
        with patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2025):
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
        with patch("helpers.matchup.core.get_current_nba_season_year", return_value=2025), \
             patch("helpers.matchup.h2h.get_current_nba_season_year", return_value=2025), \
             patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2025):
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
