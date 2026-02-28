"""Tests for sports.football.stats."""

import pytest

from sports.football.stats import (
    MIN_XG,
    compute_expected_goals,
    compute_goal_probabilities,
    compute_season_averages,
    poisson_pmf,
    DEFAULT_LEAGUE_AVG,
)


class TestPoissonPmf:
    def test_sum_to_one(self):
        lam = 2.5
        total = sum(poisson_pmf(k, lam) for k in range(21))
        assert abs(total - 1.0) < 1e-6

    def test_zero_goals(self):
        assert abs(poisson_pmf(0, 1.0) - 0.3679) < 0.001

    def test_zero_lambda(self):
        assert abs(poisson_pmf(0, 0.0) - 1.0) < 1e-10
        assert poisson_pmf(1, 0.0) == 0.0
        assert poisson_pmf(5, 0.0) == 0.0

    def test_large_lambda_no_overflow(self):
        result = poisson_pmf(100, 100.0)
        assert 0.0 < result < 1.0

    def test_negative_k_returns_zero(self):
        assert poisson_pmf(-1, 2.0) == 0.0
        assert poisson_pmf(-5, 1.0) == 0.0

    def test_mode_near_lambda(self):
        lam = 3.0
        probs = [poisson_pmf(k, lam) for k in range(10)]
        mode_k = probs.index(max(probs))
        assert mode_k in (2, 3)


class TestComputeSeasonAverages:
    def _make_match(self, home_id, away_id, h_score, a_score):
        return {
            "match_hometeam_id": str(home_id),
            "match_awayteam_id": str(away_id),
            "match_hometeam_score": str(h_score),
            "match_awayteam_score": str(a_score),
        }

    def test_basic_averages(self):
        matches = [
            self._make_match("10", "20", 2, 1),
            self._make_match("10", "30", 3, 0),
            self._make_match("40", "10", 1, 2),
        ]
        result = compute_season_averages(matches, "10")
        assert result["matches"] == 3
        assert abs(result["goals_for_avg"] - 7 / 3) < 0.01
        assert abs(result["goals_against_avg"] - 2 / 3) < 0.01

    def test_home_away_split(self):
        matches = [
            self._make_match("10", "20", 3, 1),  # home
            self._make_match("30", "10", 2, 0),  # away
        ]
        result = compute_season_averages(matches, "10")
        assert result["home_gf_avg"] == 3.0
        assert result["home_ga_avg"] == 1.0
        assert result["away_gf_avg"] == 0.0
        assert result["away_ga_avg"] == 2.0

    def test_empty_matches(self):
        result = compute_season_averages([], "10")
        assert result["matches"] == 0
        assert result["goals_for_avg"] == 0.0

    def test_invalid_scores_skipped(self):
        matches = [
            self._make_match("10", "20", "?", "1"),
            self._make_match("10", "30", 2, 1),
        ]
        result = compute_season_averages(matches, "10")
        assert result["matches"] == 1

    def test_no_matches_for_team_id(self):
        matches = [self._make_match("99", "88", 2, 1)]
        result = compute_season_averages(matches, "10")
        assert result["matches"] == 0
        assert result["goals_for_avg"] == 0.0


class TestComputeExpectedGoals:
    def test_symmetric_teams_equal_baselines(self):
        half = DEFAULT_LEAGUE_AVG / 2
        home_xg, away_xg = compute_expected_goals(half, half, half, half, half, half)
        assert abs(home_xg - half) < 0.01
        assert abs(away_xg - half) < 0.01

    def test_symmetric_teams_split_baselines(self):
        h_avg, a_avg = 1.5, 1.2
        home_xg, away_xg = compute_expected_goals(h_avg, a_avg, a_avg, h_avg, h_avg, a_avg)
        assert abs(home_xg - h_avg) < 0.01
        assert abs(away_xg - a_avg) < 0.01

    def test_strong_home_team(self):
        home_xg, away_xg = compute_expected_goals(
            2.5, 0.5, 1.0, 1.5, 1.5, 1.2,
        )
        assert home_xg > away_xg

    def test_zero_league_avg(self):
        home_xg, away_xg = compute_expected_goals(1.5, 1.0, 1.2, 1.3, 0.0, 0.0)
        assert home_xg == 0.0
        assert away_xg == 0.0

    def test_zero_one_baseline(self):
        home_xg, away_xg = compute_expected_goals(1.5, 1.0, 1.2, 1.3, 0.0, 1.2)
        assert home_xg == 0.0
        assert away_xg == 0.0

    def test_zero_input_gets_floored(self):
        home_xg, away_xg = compute_expected_goals(0.0, 0.0, 0.0, 0.0, 1.5, 1.2)
        assert home_xg == MIN_XG
        assert away_xg == MIN_XG

    def test_partial_zero_floors_only_affected(self):
        home_xg, away_xg = compute_expected_goals(0.0, 1.0, 1.2, 0.0, 1.5, 1.2)
        assert home_xg == MIN_XG
        assert away_xg > MIN_XG

    def test_home_advantage_in_baselines(self):
        """Higher home baseline should produce higher home xG for average teams."""
        h_avg, a_avg = 1.6, 1.1
        home_xg, away_xg = compute_expected_goals(h_avg, a_avg, a_avg, h_avg, h_avg, a_avg)
        assert home_xg > away_xg


class TestComputeGoalProbabilities:
    def test_has_required_keys(self):
        probs = compute_goal_probabilities(1.5, 1.2)
        assert "over_1_5" in probs
        assert "over_2_5" in probs
        assert "under_3_5" in probs
        assert "under_4_5" in probs

    def test_complementary_probabilities(self):
        probs = compute_goal_probabilities(1.5, 1.2)
        assert abs(probs["over_1_5"] + probs["under_1_5"] - 1.0) < 1e-6
        assert abs(probs["over_2_5"] + probs["under_2_5"] - 1.0) < 1e-6
        assert abs(probs["over_3_5"] + probs["under_3_5"] - 1.0) < 1e-6
        assert abs(probs["over_4_5"] + probs["under_4_5"] - 1.0) < 1e-6

    def test_high_xg_means_high_over(self):
        probs = compute_goal_probabilities(3.0, 2.5)
        assert probs["over_1_5"] > 0.9

    def test_low_xg_means_high_under(self):
        probs = compute_goal_probabilities(0.5, 0.3)
        assert probs["under_3_5"] > 0.95

    def test_probabilities_in_valid_range(self):
        probs = compute_goal_probabilities(1.5, 1.2)
        for key, val in probs.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} out of range"
