from unittest.mock import AsyncMock, patch

import pytest

from sports.football.live import (
    OddsCache,
    ScoreTracker,
    _event_matches_teams,
    _normalize_team_name,
    teams_match,
)


def _make_match(match_id, home, away, home_score, away_score, goalscorer=None):
    m = {
        "match_id": match_id,
        "match_hometeam_name": home,
        "match_awayteam_name": away,
        "match_hometeam_score": str(home_score),
        "match_awayteam_score": str(away_score),
    }
    if goalscorer is not None:
        m["goalscorer"] = goalscorer
    return m


class TestTeamMatching:
    def test_exact_match(self):
        assert teams_match("Arsenal", "Arsenal") is True

    def test_fc_suffix_stripped(self):
        assert teams_match("West Ham United", "West Ham United FC") is True

    def test_afc_suffix_stripped(self):
        assert teams_match("Bournemouth", "AFC Bournemouth") is True

    def test_no_match(self):
        assert teams_match("Arsenal", "Chelsea") is False

    def test_normalize_strips_suffix(self):
        assert _normalize_team_name("West Ham United FC") == "West Ham United"

    def test_event_matches_teams_vs_dot(self):
        assert _event_matches_teams(
            "Arsenal FC vs. Chelsea FC", "Arsenal", "Chelsea"
        ) is True

    def test_event_matches_teams_reversed(self):
        assert _event_matches_teams(
            "Chelsea FC vs. Arsenal FC", "Arsenal", "Chelsea"
        ) is True

    def test_event_no_match(self):
        assert _event_matches_teams(
            "Arsenal FC vs. Chelsea FC", "Liverpool", "Man City"
        ) is False


class TestScoreTracker:
    def test_first_update_no_goals_detected(self):
        tracker = ScoreTracker()
        match = _make_match("1", "Arsenal", "Chelsea", 1, 0, [
            {"time": "25", "scorer": "Saka", "score": "1 - 0"},
        ])
        goals = tracker.update([match])
        assert goals == []

    def test_detects_new_goal_tied_before(self):
        tracker = ScoreTracker()
        match_v1 = _make_match("1", "Arsenal", "Chelsea", 0, 0)
        tracker.update([match_v1])

        match_v2 = _make_match("1", "Arsenal", "Chelsea", 1, 0, [
            {"time": "25", "scorer": "Saka", "score": "1 - 0"},
        ])
        goals = tracker.update([match_v2])
        assert len(goals) == 1
        assert goals[0]["player"] == "Saka"
        assert goals[0]["was_tied"] is True

    def test_same_score_no_new_goal(self):
        tracker = ScoreTracker()
        match_v1 = _make_match("1", "Arsenal", "Chelsea", 1, 0, [
            {"time": "25", "scorer": "Saka", "score": "1 - 0"},
        ])
        tracker.update([match_v1])

        goals = tracker.update([match_v1])
        assert goals == []

    def test_non_tie_breaker_goal(self):
        tracker = ScoreTracker()
        match_v1 = _make_match("1", "Arsenal", "Chelsea", 1, 0, [
            {"time": "25", "scorer": "Saka", "score": "1 - 0"},
        ])
        tracker.update([match_v1])

        match_v2 = _make_match("1", "Arsenal", "Chelsea", 2, 0, [
            {"time": "25", "scorer": "Saka", "score": "1 - 0"},
            {"time": "50", "scorer": "Havertz", "score": "2 - 0"},
        ])
        goals = tracker.update([match_v2])
        assert len(goals) == 1
        assert goals[0]["player"] == "Havertz"
        assert goals[0]["was_tied"] is False

    def test_tracks_multiple_matches(self):
        tracker = ScoreTracker()
        m1 = _make_match("1", "Arsenal", "Chelsea", 0, 0)
        m2 = _make_match("2", "Liverpool", "Man City", 0, 0)
        tracker.update([m1, m2])

        m1_goal = _make_match("1", "Arsenal", "Chelsea", 1, 0, [
            {"time": "25", "scorer": "Saka", "score": "1 - 0"},
        ])
        m2_no_change = _make_match("2", "Liverpool", "Man City", 0, 0)
        goals = tracker.update([m1_goal, m2_no_change])

        assert len(goals) == 1
        assert goals[0]["match_id"] == "1"

    def test_multiple_new_goals_at_once(self):
        tracker = ScoreTracker()
        match_v1 = _make_match("1", "Arsenal", "Chelsea", 0, 0)
        tracker.update([match_v1])

        match_v2 = _make_match("1", "Arsenal", "Chelsea", 1, 1, [
            {"time": "25", "scorer": "Saka", "score": "1 - 0"},
            {"time": "30", "scorer": "Palmer", "score": "1 - 1"},
        ])
        goals = tracker.update([match_v2])
        assert len(goals) == 2
        assert goals[0]["was_tied"] is True
        assert goals[1]["was_tied"] is False


class TestOddsCache:
    def test_get_returns_none_when_empty(self):
        cache = OddsCache()
        assert cache.get("Arsenal", "Chelsea") is None

    def test_get_returns_cached_odds(self):
        cache = OddsCache()
        cache._cache["Arsenal FC vs. Chelsea FC"] = {"draw": 0.25}
        result = cache.get("Arsenal", "Chelsea")
        assert result == {"draw": 0.25}

    def test_get_matches_reversed_teams(self):
        cache = OddsCache()
        cache._cache["Chelsea FC vs. Arsenal FC"] = {"draw": 0.30}
        result = cache.get("Arsenal", "Chelsea")
        assert result == {"draw": 0.30}

    def test_get_no_match_for_different_teams(self):
        cache = OddsCache()
        cache._cache["Arsenal FC vs. Chelsea FC"] = {"draw": 0.25}
        assert cache.get("Liverpool", "Man City") is None


class TestFetchPolymarketOdds:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self):
        with patch("sports.football.live._fetch_series_events", new_callable=AsyncMock) as mock:
            mock.return_value = []
            from sports.football.live import fetch_polymarket_odds
            result = await fetch_polymarket_odds("Nonexistent FC", "Nobody United")
        assert result is None
