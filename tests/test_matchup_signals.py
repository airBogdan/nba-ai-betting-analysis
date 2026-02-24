import pytest

from helpers.matchup import (
    _exponential_decay_weights,
    build_team_snapshot,
    generate_signals,
    compute_totals_analysis,
    DEFAULT_LEAGUE_AVG_EFFICIENCY,
    SCORING_REGRESSION_THRESHOLD,
)


class TestExponentialDecayWeights:

    def test_weights_sum_to_one(self):
        weights = _exponential_decay_weights(10)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_weights_are_decreasing(self):
        weights = _exponential_decay_weights(5)
        for i in range(len(weights) - 1):
            assert weights[i] > weights[i + 1]

    def test_empty_returns_empty(self):
        assert _exponential_decay_weights(0) == []

    def test_single_element(self):
        weights = _exponential_decay_weights(1)
        assert len(weights) == 1
        assert abs(weights[0] - 1.0) < 1e-9


class TestRecentFormInSnapshot:

    @pytest.fixture
    def sample_standing(self):
        return {
            "season": 2024, "conference_rank": 3, "wins": 25, "losses": 15,
            "home_wins": 15, "home_losses": 5, "away_wins": 10, "away_losses": 10,
            "last_ten_wins": 7, "last_ten_losses": 3,
            "home_win_pct": 0.75, "away_win_pct": 0.5, "last_ten_pct": 0.7,
        }

    @pytest.fixture
    def sample_stats(self):
        return {
            "games": 40, "ppg": 112.5, "apg": 26.0, "rpg": 44.0,
            "topg": 13.5, "net_rating": 5.0, "tpp": 36.5, "fgp": 47.2, "pace": 100.0,
        }

    def test_defaults_without_recent_games(self, sample_standing, sample_stats):
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)
        assert result["recent_ppg"] == 112.5
        assert result["recent_margin"] == 0.0
        assert result["sos"] == 0.5

    def test_computes_recent_form_with_games(self, sample_standing, sample_stats):
        recent = [
            {"score": "120-110", "margin": 10, "vs_win_pct": 0.6, "date": "2024-01-15", "result": "W"},
            {"score": "100-105", "margin": -5, "vs_win_pct": 0.55, "date": "2024-01-13", "result": "L"},
            {"score": "115-108", "margin": 7, "vs_win_pct": 0.45, "date": "2024-01-11", "result": "W"},
        ]
        result = build_team_snapshot("Hawks", sample_standing, sample_stats, recent_games=recent)
        # recent_ppg should be weighted average of 120, 100, 115
        assert result["recent_ppg"] > 0
        assert result["recent_margin"] != 0.0
        # SOS should be average of opponents' win pcts
        assert 0.4 < result["sos"] < 0.7


class TestSosComputation:

    def test_sos_adjusted_net_rating_positive(self):
        standing = {
            "season": 2024, "conference_rank": 1, "wins": 30, "losses": 10,
            "home_wins": 18, "home_losses": 2, "away_wins": 12, "away_losses": 8,
            "last_ten_wins": 8, "last_ten_losses": 2,
            "home_win_pct": 0.9, "away_win_pct": 0.6, "last_ten_pct": 0.8,
        }
        stats = {
            "games": 40, "ppg": 115.0, "apg": 28.0, "rpg": 45.0,
            "topg": 12.0, "net_rating": 8.0, "tpp": 38.0, "fgp": 49.0, "pace": 102.0,
        }
        recent = [
            {"score": "120-100", "margin": 20, "vs_win_pct": 0.7, "date": "2024-01-15", "result": "W"},
            {"score": "115-110", "margin": 5, "vs_win_pct": 0.65, "date": "2024-01-13", "result": "W"},
        ]
        result = build_team_snapshot("Team", standing, stats, recent_games=recent)
        # SOS > 0.5 should boost net rating
        assert result["sos_adjusted_net_rating"] > result["net_rating"]

    def test_sos_adjusted_net_rating_negative(self):
        standing = {
            "season": 2024, "conference_rank": 12, "wins": 15, "losses": 25,
            "home_wins": 10, "home_losses": 10, "away_wins": 5, "away_losses": 15,
            "last_ten_wins": 3, "last_ten_losses": 7,
            "home_win_pct": 0.5, "away_win_pct": 0.25, "last_ten_pct": 0.3,
        }
        stats = {
            "games": 40, "ppg": 105.0, "apg": 22.0, "rpg": 42.0,
            "topg": 15.0, "net_rating": -5.0, "tpp": 33.0, "fgp": 44.0, "pace": 98.0,
        }
        recent = [
            {"score": "100-110", "margin": -10, "vs_win_pct": 0.35, "date": "2024-01-15", "result": "L"},
            {"score": "98-105", "margin": -7, "vs_win_pct": 0.40, "date": "2024-01-13", "result": "L"},
        ]
        result = build_team_snapshot("Team", standing, stats, recent_games=recent)
        # SOS < 0.5 should decrease net rating further
        assert result["sos_adjusted_net_rating"] < result["net_rating"]

    def test_custom_league_avg_efficiency(self):
        standing = {
            "season": 2024, "conference_rank": 5, "wins": 20, "losses": 20,
            "home_wins": 12, "home_losses": 8, "away_wins": 8, "away_losses": 12,
            "last_ten_wins": 5, "last_ten_losses": 5,
            "home_win_pct": 0.6, "away_win_pct": 0.4, "last_ten_pct": 0.5,
        }
        stats = {
            "games": 40, "ppg": 110.0, "apg": 25.0, "rpg": 43.0,
            "topg": 14.0, "net_rating": 0.0, "tpp": 35.0, "fgp": 46.0, "pace": 100.0,
        }
        # Default efficiency
        default = build_team_snapshot("Team", standing, stats)
        # Custom higher efficiency
        custom = build_team_snapshot("Team", standing, stats, league_avg_efficiency=115.0)

        assert custom["ortg"] == 115.0  # 115 + 0/2
        assert custom["drtg"] == 115.0  # 115 - 0/2
        assert default["ortg"] == DEFAULT_LEAGUE_AVG_EFFICIENCY  # 112 + 0/2


class TestRecentScoringTrend:

    def test_correct_trend_calculation(self):
        team1 = {
            "name": "A", "ppg": 110.0, "opp_ppg": 108.0,
            "ortg": 112.0, "drtg": 110.0, "pace": 100.0,
        }
        team2 = {
            "name": "B", "ppg": 105.0, "opp_ppg": 107.0,
            "ortg": 111.0, "drtg": 109.0, "pace": 100.0,
        }
        # Recent: team1 scores 120 (vs season 110), team2 scores 100 (vs season 105)
        team1_recent = [
            {"score": "120-100", "date": "2024-01-15", "result": "W"},
        ]
        team2_recent = [
            {"score": "100-110", "date": "2024-01-15", "result": "L"},
        ]
        result = compute_totals_analysis(team1, team2, None, None, team1_recent, team2_recent)
        # recent_combined = 120 + 100 = 220, season_combined = 110 + 105 = 215
        # trend = 220 - 215 = 5.0
        assert result["recent_scoring_trend"] == 5.0


class TestScoringRegressionSignal:

    def _make_snapshot(self, name, ppg, recent_ppg):
        return {
            "name": name, "record": "20-10", "conference_rank": 3,
            "wins": 20, "losses": 10,
            "ppg": ppg, "opp_ppg": 108.0, "net_rating": 3.0,
            "ortg": 114.0, "drtg": 111.0,
            "fgp": 47.0, "tpp": 36.0, "rpg": 44.0, "apg": 25.0, "topg": 13.0,
            "last_ten": "7-3", "last_ten_pct": 0.7,
            "home_record": "12-3", "away_record": "8-7",
            "home_win_pct": 0.8, "away_win_pct": 0.53,
            "pace": 100.0, "recent_ppg": recent_ppg,
            "recent_margin": 5.0, "sos": 0.5, "sos_adjusted_net_rating": 3.0,
        }

    def _make_comparison(self):
        return {
            "ppg": 0.0, "net_rating": 0.0, "form": 0.0,
            "turnovers": 0.0, "rebounds": 0.0, "fgp": 0.0,
            "three_pt_pct": 0.0, "pace": 0.0, "combined_pace": 100.0,
            "weighted_form": 0.0, "adjusted_net_rating": 0.0,
        }

    def _make_totals(self):
        return {
            "expected_total": 220.0, "pace_adjusted_total": 220.0,
            "defense_factor": 110.0, "h2h_total_variance": 5.0,
            "recent_scoring_trend": 0.0, "margin_volatility": 5.0,
            "team1_h2h_scoring_diff": 0.0, "team2_h2h_scoring_diff": 0.0,
        }

    def test_hot_team_regression_signal(self):
        team1 = self._make_snapshot("Hawks", ppg=110.0, recent_ppg=118.0)
        team2 = self._make_snapshot("Celtics", ppg=112.0, recent_ppg=112.0)
        signals = generate_signals(
            team1, team2, "Hawks", self._make_comparison(),
            None, None, None, self._make_totals(), [], [],
        )
        regression = [s for s in signals if "regression likely" in s]
        assert len(regression) == 1
        assert "Hawks" in regression[0]
        assert "+8.0" in regression[0]

    def test_cold_team_bounceback_signal(self):
        team1 = self._make_snapshot("Hawks", ppg=110.0, recent_ppg=110.0)
        team2 = self._make_snapshot("Celtics", ppg=115.0, recent_ppg=108.0)
        signals = generate_signals(
            team1, team2, "Hawks", self._make_comparison(),
            None, None, None, self._make_totals(), [], [],
        )
        bounceback = [s for s in signals if "bounce-back" in s]
        assert len(bounceback) == 1
        assert "Celtics" in bounceback[0]

    def test_no_signal_within_threshold(self):
        team1 = self._make_snapshot("Hawks", ppg=110.0, recent_ppg=113.0)
        team2 = self._make_snapshot("Celtics", ppg=112.0, recent_ppg=110.0)
        signals = generate_signals(
            team1, team2, "Hawks", self._make_comparison(),
            None, None, None, self._make_totals(), [], [],
        )
        regression = [s for s in signals if "regression" in s or "bounce-back" in s]
        assert len(regression) == 0

    def test_both_teams_can_trigger(self):
        team1 = self._make_snapshot("Hawks", ppg=110.0, recent_ppg=120.0)
        team2 = self._make_snapshot("Celtics", ppg=115.0, recent_ppg=108.0)
        signals = generate_signals(
            team1, team2, "Hawks", self._make_comparison(),
            None, None, None, self._make_totals(), [], [],
        )
        regression = [s for s in signals if "regression" in s or "bounce-back" in s]
        assert len(regression) == 2
