"""Tests for helpers/games.py."""

from unittest.mock import patch

import pytest

from helpers.games import (
    process_game_stats,
    process_h2h_results,
)
from helpers.h2h_stats import (
    compute_h2h_summary,
    compute_quarter_analysis,
    _weighted_h2h_games,
    H2H_SEASON_WEIGHTS,
)


class TestProcessGameStats:
    """Tests for process_game_stats function."""

    @pytest.fixture
    def sample_raw_game_stats(self):
        """Sample raw game statistics."""
        return {
            "points": 110,
            "fgp": "45.2",
            "ftp": "80.0",
            "tpm": 12,
            "tpp": "35.0",
            "totReb": 45,
            "assists": 25,
            "steals": 8,
            "turnovers": 12,
            "blocks": 5,
            "plusMinus": "15",
        }

    def test_preserves_basic_stats(self, sample_raw_game_stats):
        """Basic stats preserved correctly."""
        result = process_game_stats(sample_raw_game_stats)
        assert result["points"] == 110
        assert result["fgp"] == "45.2"
        assert result["ftp"] == "80.0"
        assert result["tpm"] == 12
        assert result["tpp"] == "35.0"
        assert result["totReb"] == 45
        assert result["assists"] == 25
        assert result["steals"] == 8
        assert result["turnovers"] == 12
        assert result["blocks"] == 5

    def test_converts_plus_minus_to_int(self, sample_raw_game_stats):
        """Plus/minus converted from string to int."""
        result = process_game_stats(sample_raw_game_stats)
        assert result["plusMinus"] == 15
        assert isinstance(result["plusMinus"], int)

    def test_computes_ast_to_tov(self, sample_raw_game_stats):
        """Assist to turnover ratio computed correctly."""
        result = process_game_stats(sample_raw_game_stats)
        # 25 assists / 12 turnovers = 2.08
        assert result["ast_to_tov"] == 2.08

    def test_computes_stocks(self, sample_raw_game_stats):
        """Stocks (steals + blocks) computed correctly."""
        result = process_game_stats(sample_raw_game_stats)
        # 8 steals + 5 blocks = 13
        assert result["stocks"] == 13

    def test_handles_zero_turnovers(self):
        """Handles zero turnovers (defaults to 1 to avoid division error)."""
        raw = {"turnovers": 0, "assists": 20}
        result = process_game_stats(raw)
        # Should use 1 as default denominator
        assert result["ast_to_tov"] == 20.0

    def test_handles_none_turnovers(self):
        """Handles None turnovers."""
        raw = {"turnovers": None, "assists": 15}
        result = process_game_stats(raw)
        assert result["ast_to_tov"] == 15.0

    def test_handles_missing_plus_minus(self):
        """Handles missing plusMinus field."""
        raw = {"points": 100}
        result = process_game_stats(raw)
        assert result["plusMinus"] == 0

    def test_handles_empty_plus_minus(self):
        """Handles empty plusMinus string."""
        raw = {"plusMinus": ""}
        result = process_game_stats(raw)
        assert result["plusMinus"] == 0

    def test_negative_plus_minus(self):
        """Handles negative plusMinus."""
        raw = {"plusMinus": "-10"}
        result = process_game_stats(raw)
        assert result["plusMinus"] == -10


class TestProcessH2hResults:
    """Tests for process_h2h_results function."""

    @pytest.fixture
    def sample_raw_h2h_games(self):
        """Sample raw H2H games from API."""
        return [
            {
                "id": 1001,
                "season": 2024,
                "teams": {
                    "home": {"name": "Atlanta Hawks"},
                    "visitors": {"name": "Philadelphia 76ers"},
                },
                "scores": {
                    "home": {"points": 115, "linescore": ["28", "30", "25", "32"]},
                    "visitors": {"points": 108, "linescore": ["25", "28", "27", "28"]},
                },
            },
            {
                "id": 1002,
                "season": 2024,
                "teams": {
                    "home": {"name": "Philadelphia 76ers"},
                    "visitors": {"name": "Atlanta Hawks"},
                },
                "scores": {
                    "home": {"points": 120, "linescore": ["32", "28", "30", "30"]},
                    "visitors": {"points": 112, "linescore": ["28", "26", "28", "30"]},
                },
            },
            {
                "id": 1003,
                "season": 2023,
                "teams": {
                    "home": {"name": "Atlanta Hawks"},
                    "visitors": {"name": "Philadelphia 76ers"},
                },
                "scores": {
                    "home": {"points": 105, "linescore": ["24", "28", "26", "27"]},
                    "visitors": {"points": 105, "linescore": ["26", "28", "25", "26"]},  # Tie
                },
            },
            # Old game that should be filtered out
            {
                "id": 999,
                "season": 2020,
                "teams": {
                    "home": {"name": "Atlanta Hawks"},
                    "visitors": {"name": "Philadelphia 76ers"},
                },
                "scores": {
                    "home": {"points": 100},
                    "visitors": {"points": 95},
                },
            },
        ]

    def test_returns_none_for_empty_input(self):
        """Returns None for empty input."""
        assert process_h2h_results([]) is None
        assert process_h2h_results(None) is None

    @patch("helpers.games.get_current_nba_season_year")
    def test_returns_none_in_offseason(self, mock_season):
        """Returns None when in off-season."""
        mock_season.return_value = None
        result = process_h2h_results([{"season": 2024}])
        assert result is None

    @patch("helpers.games.get_current_nba_season_year")
    def test_filters_old_games(self, mock_season, sample_raw_h2h_games):
        """Filters out games older than cutoff (3 seasons)."""
        mock_season.return_value = 2024
        result = process_h2h_results(sample_raw_h2h_games)
        # 2024 - 2 = 2022 cutoff, so 2020 game should be excluded
        assert 2020 not in result

    @patch("helpers.games.get_current_nba_season_year")
    def test_groups_by_season(self, mock_season, sample_raw_h2h_games):
        """Games are grouped by season."""
        mock_season.return_value = 2024
        result = process_h2h_results(sample_raw_h2h_games)
        assert 2024 in result
        assert 2023 in result
        assert len(result[2024]) == 2
        assert len(result[2023]) == 1

    @patch("helpers.games.get_current_nba_season_year")
    def test_determines_winner(self, mock_season, sample_raw_h2h_games):
        """Winner determined correctly."""
        mock_season.return_value = 2024
        result = process_h2h_results(sample_raw_h2h_games)

        # Game 1001: Hawks 115, 76ers 108 -> Hawks win
        game1 = next(g for g in result[2024] if g["id"] == 1001)
        assert game1["winner"] == "Atlanta Hawks"

        # Game 1002: 76ers 120, Hawks 112 -> 76ers win
        game2 = next(g for g in result[2024] if g["id"] == 1002)
        assert game2["winner"] == "Philadelphia 76ers"

    @patch("helpers.games.get_current_nba_season_year")
    def test_handles_tie(self, mock_season, sample_raw_h2h_games):
        """Tie game handled correctly."""
        mock_season.return_value = 2024
        result = process_h2h_results(sample_raw_h2h_games)
        game3 = result[2023][0]
        assert game3["winner"] == "tie"

    @patch("helpers.games.get_current_nba_season_year")
    def test_computes_point_diff(self, mock_season, sample_raw_h2h_games):
        """Point differential computed as home - visitor."""
        mock_season.return_value = 2024
        result = process_h2h_results(sample_raw_h2h_games)
        game1 = next(g for g in result[2024] if g["id"] == 1001)
        # Home 115 - Visitor 108 = 7
        assert game1["point_diff"] == 7

    @patch("helpers.games.get_current_nba_season_year")
    def test_parses_linescore(self, mock_season, sample_raw_h2h_games):
        """Linescore parsed from strings to ints."""
        mock_season.return_value = 2024
        result = process_h2h_results(sample_raw_h2h_games)
        game1 = next(g for g in result[2024] if g["id"] == 1001)
        assert game1["home_linescore"] == [28, 30, 25, 32]
        assert game1["visitor_linescore"] == [25, 28, 27, 28]

    @patch("helpers.games.get_current_nba_season_year")
    def test_skips_games_with_null_scores(self, mock_season):
        """Games with null scores are skipped."""
        mock_season.return_value = 2024
        games = [
            {
                "id": 1,
                "season": 2024,
                "teams": {"home": {"name": "A"}, "visitors": {"name": "B"}},
                "scores": {"home": {"points": None}, "visitors": {"points": 100}},
            }
        ]
        result = process_h2h_results(games)
        assert result == {}


class TestComputeH2hSummary:
    """Tests for compute_h2h_summary function."""

    @pytest.fixture
    def sample_h2h_results(self):
        """Sample H2H results for summary computation."""
        return {
            2024: [
                {"home_team": "Hawks", "visitor_team": "76ers", "home_points": 115,
                 "visitor_points": 108, "winner": "Hawks", "point_diff": 7},
                {"home_team": "76ers", "visitor_team": "Hawks", "home_points": 120,
                 "visitor_points": 112, "winner": "76ers", "point_diff": 8},
            ],
            2023: [
                {"home_team": "Hawks", "visitor_team": "76ers", "home_points": 110,
                 "visitor_points": 105, "winner": "Hawks", "point_diff": 5},
                {"home_team": "76ers", "visitor_team": "Hawks", "home_points": 100,
                 "visitor_points": 118, "winner": "Hawks", "point_diff": -18},
                {"home_team": "Hawks", "visitor_team": "76ers", "home_points": 95,
                 "visitor_points": 102, "winner": "76ers", "point_diff": -7},
            ],
        }

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_total_games(self, mock_season, sample_h2h_results):
        """Total games counted correctly."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        assert result["total_games"] == 5

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_win_counts(self, mock_season, sample_h2h_results):
        """Win counts computed correctly."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        # Hawks: 3 wins, 76ers: 2 wins
        assert result["team1_wins_all_time"] == 3
        assert result["team2_wins_all_time"] == 2

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_win_pct(self, mock_season, sample_h2h_results):
        """Win percentage computed correctly."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        # 3/5 = 0.6
        assert result["team1_win_pct"] == 0.6

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_home_away_splits(self, mock_season, sample_h2h_results):
        """Home/away splits computed correctly."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        # Hawks at home: 2 wins (game 1 and 3), 1 loss (game 5)
        assert result["team1_home_wins"] == 2
        assert result["team1_home_losses"] == 1
        # Hawks away: 1 win (game 4), 1 loss (game 2)
        assert result["team1_away_wins"] == 1
        assert result["team1_away_losses"] == 1

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_avg_point_diff(self, mock_season, sample_h2h_results):
        """Average point differential weighted toward recent season."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        # Weights: 2024 games=0.3125 each, 2023 games=0.125 each
        # Diffs from Hawks: +7, -8, +5, +18, -7
        # = 7*0.3125 + (-8)*0.3125 + 5*0.125 + 18*0.125 + (-7)*0.125 = 1.6875
        assert result["avg_point_diff"] == 1.7

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_avg_points(self, mock_season, sample_h2h_results):
        """Average points per team weighted toward recent season."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        # Weights: 2024=0.3125 each, 2023=0.125 each
        # Hawks: 115*0.3125 + 112*0.3125 + 110*0.125 + 118*0.125 + 95*0.125 = 111.3125
        assert result["team1_avg_points"] == 111.3
        # 76ers: 108*0.3125 + 120*0.3125 + 105*0.125 + 100*0.125 + 102*0.125 = 109.625
        assert result["team2_avg_points"] == 109.6

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_last_5_games(self, mock_season, sample_h2h_results):
        """Last 5 game winners tracked correctly."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        assert len(result["last_5_games"]) == 5

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_close_games(self, mock_season, sample_h2h_results):
        """Close games (margin <= 5) counted correctly."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        # Games with margin <= 5: game 3 (5)
        assert result["close_games"] == 1

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_blowouts(self, mock_season, sample_h2h_results):
        """Blowouts (margin >= 15) counted correctly."""
        result = compute_h2h_summary(sample_h2h_results, "Hawks", "76ers")
        # Games with margin >= 15: game 4 (18)
        assert result["blowouts"] == 1

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_recent_trend_team1_hot(self, mock_season):
        """Recent trend is team1_hot when team1 won 4+ of last 5."""
        h2h = {
            2024: [
                {"home_team": "A", "visitor_team": "B", "home_points": 100,
                 "visitor_points": 90, "winner": "A", "point_diff": 10},
                {"home_team": "B", "visitor_team": "A", "home_points": 90,
                 "visitor_points": 100, "winner": "A", "point_diff": -10},
                {"home_team": "A", "visitor_team": "B", "home_points": 100,
                 "visitor_points": 95, "winner": "A", "point_diff": 5},
                {"home_team": "B", "visitor_team": "A", "home_points": 100,
                 "visitor_points": 105, "winner": "A", "point_diff": -5},
                {"home_team": "A", "visitor_team": "B", "home_points": 100,
                 "visitor_points": 90, "winner": "A", "point_diff": 10},
            ],
        }
        result = compute_h2h_summary(h2h, "A", "B")
        assert result["recent_trend"] == "team1_hot"

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_recent_trend_team2_hot(self, mock_season):
        """Recent trend is team2_hot when team1 won 1 or fewer of last 5."""
        h2h = {
            2024: [
                {"home_team": "A", "visitor_team": "B", "home_points": 90,
                 "visitor_points": 100, "winner": "B", "point_diff": -10},
                {"home_team": "B", "visitor_team": "A", "home_points": 100,
                 "visitor_points": 90, "winner": "B", "point_diff": 10},
                {"home_team": "A", "visitor_team": "B", "home_points": 90,
                 "visitor_points": 100, "winner": "B", "point_diff": -10},
                {"home_team": "B", "visitor_team": "A", "home_points": 100,
                 "visitor_points": 90, "winner": "B", "point_diff": 10},
                {"home_team": "A", "visitor_team": "B", "home_points": 90,
                 "visitor_points": 100, "winner": "B", "point_diff": -10},
            ],
        }
        result = compute_h2h_summary(h2h, "A", "B")
        assert result["recent_trend"] == "team2_hot"

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_recent_trend_balanced(self, mock_season):
        """Recent trend is balanced when split."""
        h2h = {
            2024: [
                {"home_team": "A", "visitor_team": "B", "home_points": 100,
                 "visitor_points": 90, "winner": "A", "point_diff": 10},
                {"home_team": "B", "visitor_team": "A", "home_points": 100,
                 "visitor_points": 90, "winner": "B", "point_diff": 10},
                {"home_team": "A", "visitor_team": "B", "home_points": 100,
                 "visitor_points": 90, "winner": "A", "point_diff": 10},
                {"home_team": "B", "visitor_team": "A", "home_points": 100,
                 "visitor_points": 90, "winner": "B", "point_diff": 10},
            ],
        }
        result = compute_h2h_summary(h2h, "A", "B")
        assert result["recent_trend"] == "balanced"


class TestComputeQuarterAnalysis:
    """Tests for compute_quarter_analysis function."""

    @pytest.fixture
    def sample_h2h_with_quarters(self):
        """H2H results with quarter data."""
        return {
            2024: [
                {"home_team": "Hawks", "visitor_team": "76ers", "winner": "Hawks",
                 "home_linescore": [28, 30, 25, 32], "visitor_linescore": [25, 28, 27, 28]},
                {"home_team": "76ers", "visitor_team": "Hawks", "winner": "76ers",
                 "home_linescore": [30, 28, 30, 32], "visitor_linescore": [26, 30, 28, 28]},
            ],
        }

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_returns_none_for_no_quarter_data(self, mock_season):
        """Returns None when no games have quarter data."""
        h2h = {2024: [{"home_team": "A", "winner": "A"}]}
        result = compute_quarter_analysis(h2h, "A", "B")
        assert result is None

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_avg_quarter_totals(self, mock_season, sample_h2h_with_quarters):
        """Average quarter totals computed correctly."""
        result = compute_quarter_analysis(sample_h2h_with_quarters, "Hawks", "76ers")
        # Q1: (28+25) + (30+26) = 109/2 = 54.5
        assert result["avg_q1_total"] == 54.5
        # Q2: (30+28) + (28+30) = 116/2 = 58.0
        assert result["avg_q2_total"] == 58.0

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_team_quarter_averages(self, mock_season, sample_h2h_with_quarters):
        """Per-team quarter averages computed correctly."""
        result = compute_quarter_analysis(sample_h2h_with_quarters, "Hawks", "76ers")
        # Hawks Q1: 28 (home game 1) + 26 (away game 2) = 54/2 = 27
        assert result["team1_q1_avg"] == 27.0
        # 76ers Q1: 25 (away game 1) + 30 (home game 2) = 55/2 = 27.5
        assert result["team2_q1_avg"] == 27.5

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_half_averages(self, mock_season, sample_h2h_with_quarters):
        """First and second half averages computed correctly."""
        result = compute_quarter_analysis(sample_h2h_with_quarters, "Hawks", "76ers")
        # First half: (Q1+Q2) for both games
        # Game 1: (28+30) + (25+28) = 111
        # Game 2: (30+28) + (26+30) = 114
        # Avg: 225/2 = 112.5
        assert result["avg_first_half"] == 112.5

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_halftime_leader_wins(self, mock_season, sample_h2h_with_quarters):
        """Halftime leader win percentage computed correctly."""
        result = compute_quarter_analysis(sample_h2h_with_quarters, "Hawks", "76ers")
        # Game 1: Hawks halftime 58, 76ers 53 -> Hawks lead, Hawks won (1)
        # Game 2: 76ers halftime 58, Hawks 56 -> 76ers lead, 76ers won (2)
        # Both halftime leaders won: 2/2 = 1.0
        assert result["halftime_leader_wins_pct"] == 1.0

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_handles_incomplete_quarter_data(self, mock_season):
        """Filters out games with incomplete quarter data."""
        h2h = {
            2024: [
                {"home_team": "A", "visitor_team": "B", "winner": "A",
                 "home_linescore": [25, 30, 25, 30], "visitor_linescore": [20, 25, 20, 25]},
                {"home_team": "B", "visitor_team": "A", "winner": "B",
                 "home_linescore": [25, 30], "visitor_linescore": [20, 25]},  # Incomplete
            ],
        }
        result = compute_quarter_analysis(h2h, "A", "B")
        # Should only use the complete game
        assert result is not None
        # Q1 total from single game: 25 + 20 = 45
        assert result["avg_q1_total"] == 45.0


class TestWeightedH2hGames:
    """Tests for _weighted_h2h_games helper."""

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_weights_sum_to_one(self, mock_season):
        """Weights from 3 seasons sum to 1.0."""
        h2h = {
            2024: [{"id": 1}, {"id": 2}],
            2023: [{"id": 3}],
            2022: [{"id": 4}, {"id": 5}, {"id": 6}],
        }
        result = _weighted_h2h_games(h2h)
        total = sum(w for _, w in result)
        assert abs(total - 1.0) < 1e-9

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_recent_season_heavier(self, mock_season):
        """Current season games have higher per-game weight than older ones."""
        h2h = {
            2024: [{"id": 1}],
            2023: [{"id": 2}],
            2022: [{"id": 3}],
        }
        result = _weighted_h2h_games(h2h)
        # Should be sorted most recent first
        weights = [w for _, w in result]
        # 1 game per season, weights proportional to (1.0, 0.6, 0.3)
        assert weights[0] > weights[1] > weights[2]

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_single_season_uniform(self, mock_season):
        """Single season gives all games equal weight."""
        h2h = {2024: [{"id": 1}, {"id": 2}, {"id": 3}]}
        result = _weighted_h2h_games(h2h)
        weights = [w for _, w in result]
        assert all(abs(w - weights[0]) < 1e-9 for w in weights)
        assert abs(weights[0] - 1.0 / 3) < 1e-9

    def test_empty_input(self):
        """Empty input returns empty list."""
        assert _weighted_h2h_games({}) == []

    @patch("helpers.h2h_stats.get_current_nba_season_year", return_value=None)
    def test_offseason_uniform(self, mock_season):
        """Off-season returns uniform weights."""
        h2h = {
            2024: [{"id": 1}, {"id": 2}],
            2023: [{"id": 3}],
        }
        result = _weighted_h2h_games(h2h)
        weights = [w for _, w in result]
        expected = 1.0 / 3
        assert all(abs(w - expected) < 1e-9 for w in weights)
