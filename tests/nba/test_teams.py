"""Tests for helpers/teams.py."""

import pytest

from sports.nba.teams import process_standing


class TestProcessStanding:
    """Tests for process_standing function."""

    @pytest.fixture
    def sample_raw_standing(self):
        """Sample raw standing data from API."""
        return {
            "conference": {"name": "east", "rank": 3},
            "win": {
                "home": 15,
                "away": 10,
                "total": 25,
                "percentage": ".625",
                "lastTen": 7,
            },
            "loss": {
                "home": 5,
                "away": 10,
                "total": 15,
                "lastTen": 3,
            },
        }

    def test_preserves_season(self, sample_raw_standing):
        """Season year is preserved in output."""
        result = process_standing(2024, sample_raw_standing)
        assert result["season"] == 2024

    def test_extracts_conference_rank(self, sample_raw_standing):
        """Conference rank extracted correctly."""
        result = process_standing(2024, sample_raw_standing)
        assert result["conference_rank"] == 3

    def test_extracts_win_loss_totals(self, sample_raw_standing):
        """Wins and losses extracted correctly."""
        result = process_standing(2024, sample_raw_standing)
        assert result["wins"] == 25
        assert result["losses"] == 15
        assert result["win_pct"] == ".625"

    def test_extracts_home_away_splits(self, sample_raw_standing):
        """Home and away records extracted correctly."""
        result = process_standing(2024, sample_raw_standing)
        assert result["home_wins"] == 15
        assert result["home_losses"] == 5
        assert result["away_wins"] == 10
        assert result["away_losses"] == 10

    def test_extracts_last_ten(self, sample_raw_standing):
        """Last 10 games record extracted correctly."""
        result = process_standing(2024, sample_raw_standing)
        assert result["last_ten_wins"] == 7
        assert result["last_ten_losses"] == 3

    def test_computes_home_win_pct(self, sample_raw_standing):
        """Home win percentage computed correctly."""
        result = process_standing(2024, sample_raw_standing)
        # 15 wins / 20 home games = 0.75
        assert result["home_win_pct"] == 0.75

    def test_computes_away_win_pct(self, sample_raw_standing):
        """Away win percentage computed correctly."""
        result = process_standing(2024, sample_raw_standing)
        # 10 wins / 20 away games = 0.5
        assert result["away_win_pct"] == 0.5

    def test_computes_last_ten_pct(self, sample_raw_standing):
        """Last 10 percentage computed correctly."""
        result = process_standing(2024, sample_raw_standing)
        # 7 / 10 = 0.7
        assert result["last_ten_pct"] == 0.7

    def test_computes_home_court_advantage(self, sample_raw_standing):
        """Home court advantage computed as home_pct - away_pct."""
        result = process_standing(2024, sample_raw_standing)
        # 0.75 - 0.5 = 0.25
        assert result["home_court_advantage"] == 0.25

    def test_handles_zero_home_games(self):
        """Handles zero home games without division error."""
        raw = {
            "conference": {"rank": 1},
            "win": {"home": 0, "away": 5, "total": 5, "lastTen": 3},
            "loss": {"home": 0, "away": 5, "total": 5, "lastTen": 7},
        }
        result = process_standing(2024, raw)
        assert result["home_win_pct"] == 0.0

    def test_handles_zero_away_games(self):
        """Handles zero away games without division error."""
        raw = {
            "conference": {"rank": 1},
            "win": {"home": 5, "away": 0, "total": 5, "lastTen": 5},
            "loss": {"home": 5, "away": 0, "total": 5, "lastTen": 5},
        }
        result = process_standing(2024, raw)
        assert result["away_win_pct"] == 0.0

    def test_handles_missing_data(self):
        """Handles missing data with defaults."""
        raw = {}
        result = process_standing(2024, raw)
        assert result["season"] == 2024
        assert result["conference_rank"] == 0
        assert result["wins"] == 0
        assert result["losses"] == 0
        assert result["home_win_pct"] == 0.0
        assert result["away_win_pct"] == 0.0

    def test_handles_none_win_percentage(self):
        """Handles None win percentage string."""
        raw = {
            "conference": {"rank": 5},
            "win": {"home": 10, "away": 8, "total": 18, "percentage": None, "lastTen": 6},
            "loss": {"home": 5, "away": 7, "total": 12, "lastTen": 4},
        }
        result = process_standing(2024, raw)
        # Should handle None gracefully
        assert result["wins"] == 18
        assert result["losses"] == 12

    def test_perfect_home_record(self):
        """Handles perfect home record."""
        raw = {
            "conference": {"rank": 1},
            "win": {"home": 20, "away": 15, "total": 35, "percentage": ".875", "lastTen": 8},
            "loss": {"home": 0, "away": 5, "total": 5, "lastTen": 2},
        }
        result = process_standing(2024, raw)
        assert result["home_win_pct"] == 1.0
        assert result["away_win_pct"] == 0.75

    def test_negative_home_court_advantage(self):
        """Team can have negative home court advantage (worse at home)."""
        raw = {
            "conference": {"rank": 10},
            "win": {"home": 5, "away": 15, "total": 20, "percentage": ".500", "lastTen": 5},
            "loss": {"home": 15, "away": 5, "total": 20, "lastTen": 5},
        }
        result = process_standing(2024, raw)
        # 0.25 - 0.75 = -0.5
        assert result["home_court_advantage"] == -0.5
