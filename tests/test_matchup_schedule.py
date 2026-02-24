from helpers.matchup import (
    compute_days_rest,
    compute_streak,
    compute_games_last_n_days,
    compute_schedule_context,
)


class TestComputeDaysRest:

    def test_returns_none_for_empty_list(self):
        assert compute_days_rest([]) is None

    def test_computes_days_since_last_game(self):
        recent = [{"date": "2024-01-13"}]
        result = compute_days_rest(recent, game_date="2024-01-15")
        assert result == 2

    def test_same_day_returns_zero(self):
        recent = [{"date": "2024-01-15"}]
        result = compute_days_rest(recent, game_date="2024-01-15")
        assert result == 0

    def test_defaults_to_today_when_no_game_date(self):
        recent = [{"date": "2024-01-13"}]
        result = compute_days_rest(recent, game_date=None)
        assert result is not None  # Just verify it doesn't crash


class TestComputeStreak:

    def test_returns_no_streak_for_empty(self):
        result = compute_streak([])
        assert result["type"] is None
        assert result["count"] == 0

    def test_win_streak(self):
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
        recent = [
            {"result": "L"},
            {"result": "L"},
            {"result": "W"},
        ]
        result = compute_streak(recent)
        assert result["type"] == "L"
        assert result["count"] == 2

    def test_single_game(self):
        recent = [{"result": "W"}]
        result = compute_streak(recent)
        assert result["type"] == "W"
        assert result["count"] == 1


class TestComputeGamesLastNDays:

    def test_returns_zero_for_empty(self):
        assert compute_games_last_n_days([]) == 0

    def test_counts_games_in_window(self):
        recent = [
            {"date": "2024-01-14"},  # 1 day ago - in window
            {"date": "2024-01-12"},  # 3 days ago - in window
            {"date": "2024-01-10"},  # 5 days ago - in window
            {"date": "2024-01-05"},  # 10 days ago - outside 7 day window
        ]
        result = compute_games_last_n_days(recent, days=7, game_date="2024-01-15")
        assert result == 3


class TestComputeScheduleContext:

    def test_computes_full_context(self):
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
        result = compute_schedule_context([])
        assert result["days_rest"] is None
        assert result["streak"] == "N/A"
        assert result["games_last_7_days"] == 0
