from helpers.matchup import (
    build_team_snapshot,
    compute_edges,
)

import pytest


class TestBuildTeamSnapshot:

    @pytest.fixture
    def sample_standing(self):
        return {
            "season": 2024,
            "conference_rank": 3,
            "wins": 25,
            "losses": 15,
            "win_pct": ".625",
            "home_wins": 15,
            "home_losses": 5,
            "away_wins": 10,
            "away_losses": 10,
            "last_ten_wins": 7,
            "last_ten_losses": 3,
            "home_win_pct": 0.75,
            "away_win_pct": 0.5,
            "last_ten_pct": 0.7,
            "home_court_advantage": 0.25,
        }

    @pytest.fixture
    def sample_stats(self):
        return {
            "games": 40,
            "ppg": 112.5,
            "apg": 26.0,
            "rpg": 44.0,
            "topg": 13.5,
            "disruption": 10.0,
            "net_rating": 5.0,
            "tpp": 36.5,
            "fgp": 47.2,
            "pace": 100.0,
        }

    def test_builds_snapshot_with_all_data(self, sample_standing, sample_stats):
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)

        assert result["name"] == "Hawks"
        assert result["record"] == "25-15"
        assert result["conf_rank"] == 3
        assert result["games"] == 40
        assert result["ppg"] == 112.5

    def test_computes_ortg_drtg(self, sample_standing, sample_stats):
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)

        # ORTG = 113.5 + net_rating/2 = 113.5 + 2.5 = 116.0
        assert result["ortg"] == 116.0
        # DRTG = 113.5 - net_rating/2 = 113.5 - 2.5 = 111.0
        assert result["drtg"] == 111.0

    def test_computes_opp_ppg(self, sample_standing, sample_stats):
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)
        # opp_ppg = DRTG * pace / 100 = 111.0 * 100 / 100 = 111.0
        assert result["opp_ppg"] == 111.0

    def test_handles_none_standing(self, sample_stats):
        result = build_team_snapshot("Hawks", None, sample_stats)

        assert result["record"] == "N/A"
        assert result["conf_rank"] == 0
        assert result["last_ten"] == "N/A"
        assert result["home_record"] == "N/A"
        assert result["away_record"] == "N/A"

    def test_handles_none_stats(self, sample_standing):
        result = build_team_snapshot("Hawks", sample_standing, None)

        assert result["games"] == 0
        assert result["ppg"] == 0.0
        assert result["pace"] == 100.0  # Default pace

    def test_handles_both_none(self):
        result = build_team_snapshot("Hawks", None, None)

        assert result["name"] == "Hawks"
        assert result["record"] == "N/A"
        assert result["games"] == 0


class TestComputeEdges:

    @pytest.fixture
    def team1_snapshot(self):
        return {
            "name": "Hawks",
            "ppg": 115.0,
            "net_rating": 5.0,
            "last_ten_pct": 0.7,
            "topg": 12.0,
            "rpg": 45.0,
            "fgp": 48.0,
            "tpp": 38.0,
            "pace": 102.0,
        }

    @pytest.fixture
    def team2_snapshot(self):
        return {
            "name": "76ers",
            "ppg": 110.0,
            "net_rating": 2.0,
            "last_ten_pct": 0.5,
            "topg": 14.0,
            "rpg": 42.0,
            "fgp": 46.0,
            "tpp": 35.0,
            "pace": 98.0,
        }

    def test_computes_ppg_edge(self, team1_snapshot, team2_snapshot):
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["ppg"] == 5.0  # 115 - 110

    def test_computes_net_rating_edge(self, team1_snapshot, team2_snapshot):
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["net_rating"] == 3.0  # 5 - 2

    def test_computes_form_edge(self, team1_snapshot, team2_snapshot):
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["form"] == 0.2  # 0.7 - 0.5

    def test_computes_turnover_edge(self, team1_snapshot, team2_snapshot):
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["turnovers"] == 2.0  # 14 - 12 (team2 - team1)

    def test_computes_rebound_edge(self, team1_snapshot, team2_snapshot):
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["rebounds"] == 3.0  # 45 - 42

    def test_computes_shooting_edges(self, team1_snapshot, team2_snapshot):
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["fgp"] == 2.0  # 48 - 46
        assert result["three_pt_pct"] == 3.0  # 38 - 35

    def test_computes_pace_metrics(self, team1_snapshot, team2_snapshot):
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["pace"] == 4.0  # 102 - 98
        assert result["combined_pace"] == 100.0  # (102 + 98) / 2
