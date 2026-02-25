from sports.football.api import parse_goal_event, was_tied


class TestWasTied:
    def test_zero_zero(self):
        assert was_tied(0, 0) is True

    def test_one_one(self):
        assert was_tied(1, 1) is True

    def test_one_zero(self):
        assert was_tied(1, 0) is False

    def test_two_one(self):
        assert was_tied(2, 1) is False


class TestParseGoalEvent:
    def test_parses_home_goal(self):
        match = {
            "match_id": "123",
            "match_hometeam_name": "Arsenal",
            "match_awayteam_name": "Chelsea",
            "match_hometeam_score": "1",
            "match_awayteam_score": "0",
            "goalscorer": [
                {"time": "25", "scorer": "Saka", "score": "1 - 0"},
            ],
        }
        result = parse_goal_event(match)
        assert result["match_id"] == "123"
        assert result["home_team"] == "Arsenal"
        assert result["away_team"] == "Chelsea"
        assert result["home_score"] == 1
        assert result["away_score"] == 0
        assert len(result["goals"]) == 1
        assert result["goals"][0]["player"] == "Saka"
        assert result["goals"][0]["home_score"] == 1
        assert result["goals"][0]["away_score"] == 0

    def test_parses_away_goal(self):
        match = {
            "match_id": "456",
            "match_hometeam_name": "Arsenal",
            "match_awayteam_name": "Chelsea",
            "match_hometeam_score": "0",
            "match_awayteam_score": "1",
            "goalscorer": [
                {"time": "30", "scorer": "Palmer", "score": "0 - 1"},
            ],
        }
        result = parse_goal_event(match)
        assert result["goals"][0]["home_score"] == 0
        assert result["goals"][0]["away_score"] == 1

    def test_parses_multiple_goals(self):
        match = {
            "match_id": "789",
            "match_hometeam_name": "Liverpool",
            "match_awayteam_name": "Man City",
            "match_hometeam_score": "2",
            "match_awayteam_score": "1",
            "goalscorer": [
                {"time": "10", "scorer": "Salah", "score": "1 - 0"},
                {"time": "35", "scorer": "Haaland", "score": "1 - 1"},
                {"time": "60", "scorer": "Salah", "score": "2 - 1"},
            ],
        }
        result = parse_goal_event(match)
        assert len(result["goals"]) == 3
        assert result["goals"][1]["home_score"] == 1
        assert result["goals"][1]["away_score"] == 1

    def test_returns_none_for_missing_goalscorer(self):
        match = {
            "match_id": "123",
            "match_hometeam_name": "Arsenal",
            "match_awayteam_name": "Chelsea",
            "match_hometeam_score": "0",
            "match_awayteam_score": "0",
        }
        assert parse_goal_event(match) is None

    def test_returns_none_for_empty_goalscorer(self):
        match = {
            "match_id": "123",
            "match_hometeam_name": "Arsenal",
            "match_awayteam_name": "Chelsea",
            "match_hometeam_score": "0",
            "match_awayteam_score": "0",
            "goalscorer": [],
        }
        assert parse_goal_event(match) is None

    def test_skips_goals_with_invalid_score_format(self):
        match = {
            "match_id": "123",
            "match_hometeam_name": "Arsenal",
            "match_awayteam_name": "Chelsea",
            "match_hometeam_score": "1",
            "match_awayteam_score": "0",
            "goalscorer": [
                {"time": "10", "scorer": "Saka", "score": "invalid"},
                {"time": "25", "scorer": "Saka", "score": "1 - 0"},
            ],
        }
        result = parse_goal_event(match)
        assert len(result["goals"]) == 1
