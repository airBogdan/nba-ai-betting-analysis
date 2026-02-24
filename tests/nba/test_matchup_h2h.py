from unittest.mock import patch

from sports.nba.matchup import (
    compute_h2h_patterns,
    compute_h2h_matchup_stats,
    compute_recent_h2h,
)


class TestComputeH2hPatterns:

    def test_returns_none_for_no_results(self):
        assert compute_h2h_patterns(None) is None
        assert compute_h2h_patterns({}) is None

    @patch("sports.nba.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_avg_total(self, mock_season):
        h2h = {
            2024: [
                {"home_team": "A", "home_points": 110, "visitor_points": 105,
                 "winner": "A", "point_diff": 5},
                {"home_team": "B", "home_points": 120, "visitor_points": 115,
                 "winner": "B", "point_diff": 5},
            ]
        }
        result = compute_h2h_patterns(h2h)
        # (215 + 235) / 2 = 225
        assert result["avg_total"] == 225.0

    @patch("sports.nba.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_home_win_pct(self, mock_season):
        h2h = {
            2024: [
                {"home_team": "A", "home_points": 110, "visitor_points": 105,
                 "winner": "A", "point_diff": 5},
                {"home_team": "B", "home_points": 100, "visitor_points": 105,
                 "winner": "A", "point_diff": -5},  # Away team won
            ]
        }
        result = compute_h2h_patterns(h2h)
        assert result["home_win_pct"] == 0.5

    @patch("sports.nba.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_high_scoring_pct(self, mock_season):
        h2h = {
            2024: [
                {"home_team": "A", "home_points": 115, "visitor_points": 110,
                 "winner": "A", "point_diff": 5},  # 225 - high scoring
                {"home_team": "B", "home_points": 100, "visitor_points": 95,
                 "winner": "B", "point_diff": 5},  # 195 - not high scoring
            ]
        }
        result = compute_h2h_patterns(h2h)
        assert result["high_scoring_pct"] == 0.5

    @patch("sports.nba.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_computes_close_game_pct(self, mock_season):
        h2h = {
            2024: [
                {"home_team": "A", "home_points": 110, "visitor_points": 108,
                 "winner": "A", "point_diff": 2},  # Close
                {"home_team": "B", "home_points": 120, "visitor_points": 100,
                 "winner": "B", "point_diff": 20},  # Not close
            ]
        }
        result = compute_h2h_patterns(h2h)
        assert result["close_game_pct"] == 0.5


class TestComputeH2hMatchupStats:

    def test_returns_none_for_no_results(self):
        assert compute_h2h_matchup_stats(None, "A", "B") is None

    @patch("sports.nba.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_returns_none_for_no_box_scores(self, mock_season):
        h2h = {2024: [{"home_team": "A", "visitor_team": "B"}]}
        result = compute_h2h_matchup_stats(h2h, "A", "B")
        assert result is None

    @patch("sports.nba.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_aggregates_team_stats(self, mock_season):
        h2h = {
            2024: [
                {
                    "home_team": "Hawks", "visitor_team": "76ers",
                    "home_statistics": {
                        "fgp": "48.0", "tpp": "36.0", "totReb": 45,
                        "assists": 25, "turnovers": 12, "steals": 8, "blocks": 5
                    },
                    "visitor_statistics": {
                        "fgp": "45.0", "tpp": "34.0", "totReb": 42,
                        "assists": 22, "turnovers": 14, "steals": 6, "blocks": 4
                    },
                },
                {
                    "home_team": "76ers", "visitor_team": "Hawks",
                    "home_statistics": {
                        "fgp": "46.0", "tpp": "35.0", "totReb": 44,
                        "assists": 24, "turnovers": 13, "steals": 7, "blocks": 5
                    },
                    "visitor_statistics": {
                        "fgp": "50.0", "tpp": "38.0", "totReb": 46,
                        "assists": 26, "turnovers": 11, "steals": 9, "blocks": 6
                    },
                },
            ]
        }
        result = compute_h2h_matchup_stats(h2h, "Hawks", "76ers")

        # Hawks: game 1 home (48, 36), game 2 away (50, 38)
        assert result["team1"]["avg_fgp"] == 49.0  # (48 + 50) / 2
        # 76ers: game 1 away (45, 34), game 2 home (46, 35)
        assert result["team2"]["avg_fgp"] == 45.5  # (45 + 46) / 2


class TestComputeRecentH2h:

    @patch("sports.nba.matchup.h2h.get_current_nba_season_year")
    def test_returns_none_in_offseason(self, mock_season):
        mock_season.return_value = None
        result = compute_recent_h2h({2024: []}, "A", "A")
        assert result is None

    @patch("sports.nba.matchup.h2h.get_current_nba_season_year")
    def test_filters_to_last_2_seasons(self, mock_season):
        mock_season.return_value = 2024
        h2h = {
            2024: [{"winner": "A", "home_team": "A"}],
            2023: [{"winner": "B", "home_team": "B"}],
            2022: [{"winner": "A", "home_team": "A"}],  # Should be excluded
        }
        result = compute_recent_h2h(h2h, "A", "A")
        assert result["games_last_2_seasons"] == 2

    @patch("sports.nba.matchup.h2h.get_current_nba_season_year")
    def test_computes_recent_wins(self, mock_season):
        mock_season.return_value = 2024
        h2h = {
            2024: [
                {"winner": "Hawks", "home_team": "Hawks"},
                {"winner": "76ers", "home_team": "76ers"},
            ],
            2023: [
                {"winner": "Hawks", "home_team": "Hawks"},
            ],
        }
        result = compute_recent_h2h(h2h, "Hawks", "Hawks")
        assert result["team1_wins_last_2_seasons"] == 2
        assert result["team2_wins_last_2_seasons"] == 1


class TestComputeH2hPatternsMultiSeason:

    @patch("sports.nba.h2h_stats.get_current_nba_season_year", return_value=2024)
    def test_avg_total_skews_toward_recent(self, mock_season):
        h2h = {
            2024: [
                {"home_team": "A", "home_points": 120, "visitor_points": 115,
                 "winner": "A", "point_diff": 5},  # 235
            ],
            2023: [
                {"home_team": "B", "home_points": 95, "visitor_points": 90,
                 "winner": "B", "point_diff": 5},  # 185
            ],
        }
        result = compute_h2h_patterns(h2h)
        # Weights: 2024=1.0/1=1.0, 2023=0.6/1=0.6, total=1.6
        # Normalized: 2024=0.625, 2023=0.375
        # Weighted avg = 235*0.625 + 185*0.375 = 146.875 + 69.375 = 216.25
        assert result["avg_total"] == 216.2
        # Unweighted would be (235+185)/2 = 210 — verify it's different
        assert result["avg_total"] != 210.0
