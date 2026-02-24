import pytest

from helpers.matchup import (
    compute_totals_analysis,
    build_team_players,
)


class TestComputeTotalsAnalysis:

    @pytest.fixture
    def team_snapshots(self):
        team1 = {
            "name": "Hawks", "ppg": 115.0, "opp_ppg": 110.0,
            "ortg": 114.0, "drtg": 110.0, "pace": 102.0
        }
        team2 = {
            "name": "76ers", "ppg": 112.0, "opp_ppg": 108.0,
            "ortg": 113.0, "drtg": 108.0, "pace": 100.0
        }
        return team1, team2

    def test_computes_expected_total_without_h2h(self, team_snapshots):
        team1, team2 = team_snapshots
        result = compute_totals_analysis(team1, team2, None, None, [], [])

        # Current total = 115 + 112 = 227
        # Dynamic league_avg = (225 + 220) / 2 = 222.5
        # H2H weight = 0.2 (no H2H), baseline = 222.5
        # Expected = 227 * 0.8 + 222.5 * 0.2 = 226.1
        # Regression: 226.1 - (226.1 - 222.5) * 0.15 = 225.56 → 225.6
        assert result["expected_total"] == 225.6

    def test_computes_expected_total_with_h2h(self, team_snapshots):
        team1, team2 = team_snapshots
        h2h_summary = {
            "avg_total_points": 220.0,
            "team1_avg_points": 108.0,
            "team2_avg_points": 112.0,
        }
        result = compute_totals_analysis(team1, team2, h2h_summary, None, [], [])

        # Current total = 227
        # Dynamic league_avg = 222.5
        # H2H weight = 0.4
        # Expected = 227 * 0.6 + 220 * 0.4 = 224.2
        # Regression: 224.2 - (224.2 - 222.5) * 0.15 = 223.9
        assert result["expected_total"] == 223.9

    def test_computes_pace_adjusted_total(self, team_snapshots):
        team1, team2 = team_snapshots
        result = compute_totals_analysis(team1, team2, None, None, [], [])

        # Each team's expected scoring at combined pace, summed
        combined_pace = (team1["pace"] + team2["pace"]) / 2  # 101
        team1_expected = combined_pace * team1["ortg"] / 100
        team2_expected = combined_pace * team2["ortg"] / 100
        assert result["pace_adjusted_total"] == round(team1_expected + team2_expected, 1)

    def test_computes_defense_factor(self, team_snapshots):
        team1, team2 = team_snapshots
        result = compute_totals_analysis(team1, team2, None, None, [], [])

        # (110 + 108) / 2 = 109
        assert result["defense_factor"] == 109.0


class TestBuildTeamPlayers:

    @pytest.fixture
    def sample_players(self):
        return [
            {"name": "Trae Young", "ppg": 28.0, "apg": 10.5, "mpg": 35.0,
             "plus_minus": 5.0, "games": 40},
            {"name": "Dejounte Murray", "ppg": 22.0, "apg": 6.5, "mpg": 34.0,
             "plus_minus": 3.0, "games": 38},
            {"name": "De'Andre Hunter", "ppg": 15.0, "apg": 2.0, "mpg": 30.0,
             "plus_minus": 1.0, "games": 35},
            {"name": "John Collins", "ppg": 13.0, "apg": 1.5, "mpg": 28.0,
             "plus_minus": -1.0, "games": 40},
            {"name": "Clint Capela", "ppg": 10.0, "apg": 1.0, "mpg": 26.0,
             "plus_minus": 2.0, "games": 40},
            {"name": "Bogdan Bogdanovic", "ppg": 12.0, "apg": 3.0, "mpg": 24.0,
             "plus_minus": 0.0, "games": 25},  # Limited availability
            {"name": "Onyeka Okongwu", "ppg": 8.0, "apg": 1.0, "mpg": 20.0,
             "plus_minus": 4.0, "games": 40},
            {"name": "Jalen Johnson", "ppg": 6.0, "apg": 1.5, "mpg": 18.0,
             "plus_minus": -2.0, "games": 40},
        ]

    def test_returns_none_for_empty_players(self):
        assert build_team_players([], 40, 110.0) is None

    def test_builds_rotation(self, sample_players):
        result = build_team_players(sample_players, 40, 110.0, rotation_size=6)

        assert len(result["rotation"]) == 6
        assert result["rotation"][0]["name"] == "Trae Young"

    def test_identifies_availability_concerns(self, sample_players):
        result = build_team_players(sample_players, 40, 110.0)

        # Bogdan: 25/40 = 62.5% < 70% threshold
        assert len(result["availability_concerns"]) > 0
        assert any("Bogdan" in c for c in result["availability_concerns"])

    def test_full_strength_when_no_concerns(self):
        players = [
            {"name": "Player 1", "ppg": 20.0, "apg": 5.0, "mpg": 30.0,
             "plus_minus": 2.0, "games": 40}
        ]
        result = build_team_players(players, 40, 100.0)
        assert result["full_strength"] is True

    def test_identifies_top_scorers(self, sample_players):
        result = build_team_players(sample_players, 40, 110.0)
        assert "Young 28.0" in result["top_scorers"]
        assert "Murray 22.0" in result["top_scorers"]

    def test_identifies_playmaker(self, sample_players):
        result = build_team_players(sample_players, 40, 110.0)
        assert "Trae Young" in result["playmaker"]
        assert "10.5 APG" in result["playmaker"]

    def test_identifies_hot_hand(self, sample_players):
        result = build_team_players(sample_players, 40, 110.0)
        # Trae Young has highest +/- at 5.0
        assert "Young" in result["hot_hand"]
        assert "+5.0" in result["hot_hand"]

    def test_computes_star_dependency(self, sample_players):
        result = build_team_players(sample_players, 40, 110.0)
        # Trae 28.0 / 110.0 = 25.45%
        assert result["star_dependency"] == 25.5

    def test_computes_bench_scoring(self, sample_players):
        result = build_team_players(sample_players, 40, 110.0)
        # Bench (players 6+): Bogdan (12) + Onyeka (8) + Jalen (6) = 26
        assert result["bench_scoring"] == 26.0
