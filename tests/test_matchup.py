"""Tests for helpers/matchup.py."""

from unittest.mock import patch

import pytest

from helpers.matchup import (
    _exponential_decay_weights,
    build_team_snapshot,
    compute_edges,
    compute_days_rest,
    compute_streak,
    compute_games_last_n_days,
    compute_schedule_context,
    generate_signals,
    compute_h2h_patterns,
    compute_h2h_matchup_stats,
    compute_recent_h2h,
    compute_totals_analysis,
    build_team_players,
    DEFAULT_LEAGUE_AVG_EFFICIENCY,
    SCORING_REGRESSION_THRESHOLD,
)


class TestBuildTeamSnapshot:
    """Tests for build_team_snapshot function."""

    @pytest.fixture
    def sample_standing(self):
        """Sample team standing."""
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
        """Sample team stats."""
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
        """Builds complete snapshot with standing and stats."""
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)

        assert result["name"] == "Hawks"
        assert result["record"] == "25-15"
        assert result["conf_rank"] == 3
        assert result["games"] == 40
        assert result["ppg"] == 112.5

    def test_computes_ortg_drtg(self, sample_standing, sample_stats):
        """ORTG and DRTG estimated from net rating."""
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)

        # ORTG = 113.5 + net_rating/2 = 113.5 + 2.5 = 116.0
        assert result["ortg"] == 116.0
        # DRTG = 113.5 - net_rating/2 = 113.5 - 2.5 = 111.0
        assert result["drtg"] == 111.0

    def test_computes_opp_ppg(self, sample_standing, sample_stats):
        """Opponent PPG estimated from DRTG and pace."""
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)
        # opp_ppg = DRTG * pace / 100 = 111.0 * 100 / 100 = 111.0
        assert result["opp_ppg"] == 111.0

    def test_handles_none_standing(self, sample_stats):
        """Handles None standing gracefully."""
        result = build_team_snapshot("Hawks", None, sample_stats)

        assert result["record"] == "N/A"
        assert result["conf_rank"] == 0
        assert result["last_ten"] == "N/A"
        assert result["home_record"] == "N/A"
        assert result["away_record"] == "N/A"

    def test_handles_none_stats(self, sample_standing):
        """Handles None stats gracefully."""
        result = build_team_snapshot("Hawks", sample_standing, None)

        assert result["games"] == 0
        assert result["ppg"] == 0.0
        assert result["pace"] == 100.0  # Default pace

    def test_handles_both_none(self):
        """Handles both None inputs."""
        result = build_team_snapshot("Hawks", None, None)

        assert result["name"] == "Hawks"
        assert result["record"] == "N/A"
        assert result["games"] == 0


class TestComputeEdges:
    """Tests for compute_edges function."""

    @pytest.fixture
    def team1_snapshot(self):
        """Team 1 snapshot."""
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
        """Team 2 snapshot."""
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
        """PPG edge computed correctly."""
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["ppg"] == 5.0  # 115 - 110

    def test_computes_net_rating_edge(self, team1_snapshot, team2_snapshot):
        """Net rating edge computed correctly."""
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["net_rating"] == 3.0  # 5 - 2

    def test_computes_form_edge(self, team1_snapshot, team2_snapshot):
        """Form edge (last 10 pct difference) computed correctly."""
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["form"] == 0.2  # 0.7 - 0.5

    def test_computes_turnover_edge(self, team1_snapshot, team2_snapshot):
        """Turnover edge (positive = team1 turns over less)."""
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["turnovers"] == 2.0  # 14 - 12 (team2 - team1)

    def test_computes_rebound_edge(self, team1_snapshot, team2_snapshot):
        """Rebound edge computed correctly."""
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["rebounds"] == 3.0  # 45 - 42

    def test_computes_shooting_edges(self, team1_snapshot, team2_snapshot):
        """FG% and 3P% edges computed correctly."""
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["fgp"] == 2.0  # 48 - 46
        assert result["three_pt_pct"] == 3.0  # 38 - 35

    def test_computes_pace_metrics(self, team1_snapshot, team2_snapshot):
        """Pace difference and combined pace computed correctly."""
        result = compute_edges(team1_snapshot, team2_snapshot)
        assert result["pace"] == 4.0  # 102 - 98
        assert result["combined_pace"] == 100.0  # (102 + 98) / 2


class TestComputeDaysRest:
    """Tests for compute_days_rest function."""

    def test_returns_none_for_empty_list(self):
        """Returns None for empty recent games list."""
        assert compute_days_rest([]) is None

    def test_computes_days_since_last_game(self):
        """Computes days since last game correctly."""
        recent = [{"date": "2024-01-13"}]
        result = compute_days_rest(recent, game_date="2024-01-15")
        assert result == 2

    def test_same_day_returns_zero(self):
        """Returns 0 for game on same day."""
        recent = [{"date": "2024-01-15"}]
        result = compute_days_rest(recent, game_date="2024-01-15")
        assert result == 0

    def test_defaults_to_today_when_no_game_date(self):
        """Verify backward compatibility - None game_date uses current date."""
        recent = [{"date": "2024-01-13"}]
        result = compute_days_rest(recent, game_date=None)
        assert result is not None  # Just verify it doesn't crash


class TestComputeStreak:
    """Tests for compute_streak function."""

    def test_returns_no_streak_for_empty(self):
        """Returns no streak for empty games list."""
        result = compute_streak([])
        assert result["type"] is None
        assert result["count"] == 0

    def test_win_streak(self):
        """Computes win streak correctly."""
        recent = [
            {"result": "W"},
            {"result": "W"},
            {"result": "W"},
            {"result": "L"},
        ]
        result = compute_streak(recent)
        assert result["type"] == "W"
        assert result["count"] == 3

    def test_loss_streak(self):
        """Computes loss streak correctly."""
        recent = [
            {"result": "L"},
            {"result": "L"},
            {"result": "W"},
        ]
        result = compute_streak(recent)
        assert result["type"] == "L"
        assert result["count"] == 2

    def test_single_game(self):
        """Single game streak."""
        recent = [{"result": "W"}]
        result = compute_streak(recent)
        assert result["type"] == "W"
        assert result["count"] == 1


class TestComputeGamesLastNDays:
    """Tests for compute_games_last_n_days function."""

    def test_returns_zero_for_empty(self):
        """Returns 0 for empty games list."""
        assert compute_games_last_n_days([]) == 0

    def test_counts_games_in_window(self):
        """Counts games within N day window."""
        recent = [
            {"date": "2024-01-14"},  # 1 day ago - in window
            {"date": "2024-01-12"},  # 3 days ago - in window
            {"date": "2024-01-10"},  # 5 days ago - in window
            {"date": "2024-01-05"},  # 10 days ago - outside 7 day window
        ]
        result = compute_games_last_n_days(recent, days=7, game_date="2024-01-15")
        assert result == 3


class TestComputeScheduleContext:
    """Tests for compute_schedule_context function."""

    def test_computes_full_context(self):
        """Computes complete schedule context."""
        recent = [
            {"date": "2024-01-14", "result": "W", "vs_win_pct": 0.6},
            {"date": "2024-01-12", "result": "W", "vs_win_pct": 0.55},
            {"date": "2024-01-10", "result": "L", "vs_win_pct": 0.7},
        ]
        result = compute_schedule_context(recent, game_date="2024-01-15")

        assert result["days_rest"] == 1
        assert result["streak"] == "W2"
        assert result["games_last_7_days"] == 3
        # Quality wins: 2 (both Ws were vs .500+ teams)
        assert result["quality_wins"] == 2
        # Quality losses: 1 (L was vs .500+ team)
        assert result["quality_losses"] == 1

    def test_handles_empty_games(self):
        """Handles empty recent games."""
        result = compute_schedule_context([])
        assert result["days_rest"] is None
        assert result["streak"] == "N/A"
        assert result["games_last_7_days"] == 0


class TestComputeH2hPatterns:
    """Tests for compute_h2h_patterns function."""

    def test_returns_none_for_no_results(self):
        """Returns None for empty results."""
        assert compute_h2h_patterns(None) is None
        assert compute_h2h_patterns({}) is None

    @patch("helpers.games.get_current_nba_season_year", return_value=2024)
    def test_computes_avg_total(self, mock_season):
        """Computes average combined score."""
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

    @patch("helpers.games.get_current_nba_season_year", return_value=2024)
    def test_computes_home_win_pct(self, mock_season):
        """Computes home team win percentage."""
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

    @patch("helpers.games.get_current_nba_season_year", return_value=2024)
    def test_computes_high_scoring_pct(self, mock_season):
        """Computes percentage of games over 220."""
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

    @patch("helpers.games.get_current_nba_season_year", return_value=2024)
    def test_computes_close_game_pct(self, mock_season):
        """Computes percentage of close games (margin <= 5)."""
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
    """Tests for compute_h2h_matchup_stats function."""

    def test_returns_none_for_no_results(self):
        """Returns None for empty results."""
        assert compute_h2h_matchup_stats(None, "A", "B") is None

    @patch("helpers.games.get_current_nba_season_year", return_value=2024)
    def test_returns_none_for_no_box_scores(self, mock_season):
        """Returns None when no games have box scores."""
        h2h = {2024: [{"home_team": "A", "visitor_team": "B"}]}
        result = compute_h2h_matchup_stats(h2h, "A", "B")
        assert result is None

    @patch("helpers.games.get_current_nba_season_year", return_value=2024)
    def test_aggregates_team_stats(self, mock_season):
        """Aggregates stats for each team from box scores."""
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
    """Tests for compute_recent_h2h function."""

    @patch("helpers.matchup_h2h.get_current_nba_season_year")
    def test_returns_none_in_offseason(self, mock_season):
        """Returns None when in off-season."""
        mock_season.return_value = None
        result = compute_recent_h2h({2024: []}, "A", "A")
        assert result is None

    @patch("helpers.matchup_h2h.get_current_nba_season_year")
    def test_filters_to_last_2_seasons(self, mock_season):
        """Only includes games from last 2 seasons."""
        mock_season.return_value = 2024
        h2h = {
            2024: [{"winner": "A", "home_team": "A"}],
            2023: [{"winner": "B", "home_team": "B"}],
            2022: [{"winner": "A", "home_team": "A"}],  # Should be excluded
        }
        result = compute_recent_h2h(h2h, "A", "A")
        assert result["games_last_2_seasons"] == 2

    @patch("helpers.matchup_h2h.get_current_nba_season_year")
    def test_computes_recent_wins(self, mock_season):
        """Computes wins for each team in recent games."""
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


class TestComputeTotalsAnalysis:
    """Tests for compute_totals_analysis function."""

    @pytest.fixture
    def team_snapshots(self):
        """Team snapshots for totals analysis."""
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
        """Expected total computed from current PPG when no H2H."""
        team1, team2 = team_snapshots
        result = compute_totals_analysis(team1, team2, None, None, [], [])

        # Current total = 115 + 112 = 227
        # Dynamic league_avg = (225 + 220) / 2 = 222.5
        # H2H weight = 0.2 (no H2H), baseline = 222.5
        # Expected = 227 * 0.8 + 222.5 * 0.2 = 226.1
        # Regression: 226.1 - (226.1 - 222.5) * 0.15 = 225.56 → 225.6
        assert result["expected_total"] == 225.6

    def test_computes_expected_total_with_h2h(self, team_snapshots):
        """Expected total weighted with H2H average."""
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
        """Pace-adjusted total computed from combined pace and ORTG."""
        team1, team2 = team_snapshots
        result = compute_totals_analysis(team1, team2, None, None, [], [])

        # Each team's expected scoring at combined pace, summed
        combined_pace = (team1["pace"] + team2["pace"]) / 2  # 101
        team1_expected = combined_pace * team1["ortg"] / 100
        team2_expected = combined_pace * team2["ortg"] / 100
        assert result["pace_adjusted_total"] == round(team1_expected + team2_expected, 1)

    def test_computes_defense_factor(self, team_snapshots):
        """Defense factor is average of both teams' DRTG."""
        team1, team2 = team_snapshots
        result = compute_totals_analysis(team1, team2, None, None, [], [])

        # (110 + 108) / 2 = 109
        assert result["defense_factor"] == 109.0


class TestBuildTeamPlayers:
    """Tests for build_team_players function."""

    @pytest.fixture
    def sample_players(self):
        """Sample processed player stats."""
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
        """Returns None for empty players list."""
        assert build_team_players([], 40, 110.0) is None

    def test_builds_rotation(self, sample_players):
        """Builds rotation with top N players by MPG."""
        result = build_team_players(sample_players, 40, 110.0, rotation_size=6)

        assert len(result["rotation"]) == 6
        assert result["rotation"][0]["name"] == "Trae Young"

    def test_identifies_availability_concerns(self, sample_players):
        """Identifies players with limited availability."""
        result = build_team_players(sample_players, 40, 110.0)

        # Bogdan: 25/40 = 62.5% < 70% threshold
        assert len(result["availability_concerns"]) > 0
        assert any("Bogdan" in c for c in result["availability_concerns"])

    def test_full_strength_when_no_concerns(self):
        """full_strength is True when no availability concerns."""
        players = [
            {"name": "Player 1", "ppg": 20.0, "apg": 5.0, "mpg": 30.0,
             "plus_minus": 2.0, "games": 40}
        ]
        result = build_team_players(players, 40, 100.0)
        assert result["full_strength"] is True

    def test_identifies_top_scorers(self, sample_players):
        """Identifies top 3 scorers."""
        result = build_team_players(sample_players, 40, 110.0)
        assert "Young 28.0" in result["top_scorers"]
        assert "Murray 22.0" in result["top_scorers"]

    def test_identifies_playmaker(self, sample_players):
        """Identifies top playmaker by APG."""
        result = build_team_players(sample_players, 40, 110.0)
        assert "Trae Young" in result["playmaker"]
        assert "10.5 APG" in result["playmaker"]

    def test_identifies_hot_hand(self, sample_players):
        """Identifies player with best plus/minus."""
        result = build_team_players(sample_players, 40, 110.0)
        # Trae Young has highest +/- at 5.0
        assert "Young" in result["hot_hand"]
        assert "+5.0" in result["hot_hand"]

    def test_computes_star_dependency(self, sample_players):
        """Computes star dependency as top scorer's share of team PPG."""
        result = build_team_players(sample_players, 40, 110.0)
        # Trae 28.0 / 110.0 = 25.45%
        assert result["star_dependency"] == 25.5

    def test_computes_bench_scoring(self, sample_players):
        """Computes bench scoring from non-starter players."""
        result = build_team_players(sample_players, 40, 110.0)
        # Bench (players 6+): Bogdan (12) + Onyeka (8) + Jalen (6) = 26
        assert result["bench_scoring"] == 26.0


class TestExponentialDecayWeights:
    """Tests for _exponential_decay_weights helper."""

    def test_weights_sum_to_one(self):
        """Weights should sum to 1.0."""
        weights = _exponential_decay_weights(10)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_weights_are_decreasing(self):
        """Weights should decrease (most recent first)."""
        weights = _exponential_decay_weights(5)
        for i in range(len(weights) - 1):
            assert weights[i] > weights[i + 1]

    def test_empty_returns_empty(self):
        """Empty input returns empty list."""
        assert _exponential_decay_weights(0) == []

    def test_single_element(self):
        """Single element gets weight 1.0."""
        weights = _exponential_decay_weights(1)
        assert len(weights) == 1
        assert abs(weights[0] - 1.0) < 1e-9


class TestRecentFormInSnapshot:
    """Tests for recent form fields in build_team_snapshot."""

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
        """Without recent games, recent_ppg defaults to season ppg."""
        result = build_team_snapshot("Hawks", sample_standing, sample_stats)
        assert result["recent_ppg"] == 112.5
        assert result["recent_margin"] == 0.0
        assert result["sos"] == 0.5

    def test_computes_recent_form_with_games(self, sample_standing, sample_stats):
        """Computes weighted recent form from recent games."""
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
    """Tests for SOS and SOS-adjusted net rating."""

    def test_sos_adjusted_net_rating_positive(self):
        """Positive net rating with strong schedule gets boost."""
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
        """Negative net rating with weak schedule stays negative (additive, not multiplicative)."""
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
        """Custom league_avg_efficiency changes ORTG/DRTG."""
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
    """Tests for the fixed recent_scoring_trend computation."""

    def test_correct_trend_calculation(self):
        """Recent scoring trend uses team PPG, not combined game totals."""
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


class TestComputeH2hPatternsMultiSeason:
    """Tests for compute_h2h_patterns with multi-season recency weighting."""

    @patch("helpers.games.get_current_nba_season_year", return_value=2024)
    def test_avg_total_skews_toward_recent(self, mock_season):
        """avg_total should weight recent season more heavily."""
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


class TestScoringRegressionSignal:
    """Tests for scoring regression detection in generate_signals."""

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
        """Team scoring well above season avg triggers regression warning."""
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
        """Team scoring well below season avg triggers bounce-back signal."""
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
        """No regression signal when recent PPG is close to season PPG."""
        team1 = self._make_snapshot("Hawks", ppg=110.0, recent_ppg=113.0)
        team2 = self._make_snapshot("Celtics", ppg=112.0, recent_ppg=110.0)
        signals = generate_signals(
            team1, team2, "Hawks", self._make_comparison(),
            None, None, None, self._make_totals(), [], [],
        )
        regression = [s for s in signals if "regression" in s or "bounce-back" in s]
        assert len(regression) == 0

    def test_both_teams_can_trigger(self):
        """Both teams can have regression signals simultaneously."""
        team1 = self._make_snapshot("Hawks", ppg=110.0, recent_ppg=120.0)
        team2 = self._make_snapshot("Celtics", ppg=115.0, recent_ppg=108.0)
        signals = generate_signals(
            team1, team2, "Hawks", self._make_comparison(),
            None, None, None, self._make_totals(), [], [],
        )
        regression = [s for s in signals if "regression" in s or "bounce-back" in s]
        assert len(regression) == 2
