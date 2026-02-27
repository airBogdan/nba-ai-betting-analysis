"""Tests for sports.football.client."""

import pytest

from sports.football.client import extract_match_stats


SAMPLE_MATCH = {
    "match_id": "123",
    "match_hometeam_name": "Arsenal",
    "match_awayteam_name": "Chelsea",
    "match_hometeam_score": "2",
    "match_awayteam_score": "1",
    "match_hometeam_id": "10",
    "match_awayteam_id": "20",
    "statistics": [
        {"type": "Shots Total", "home": "15", "away": "8"},
        {"type": "Shots On Goal", "home": "7", "away": "3"},
        {"type": "Ball Possession", "home": "58%", "away": "42%"},
        {"type": "Corner Kicks", "home": "6", "away": "4"},
        {"type": "Fouls", "home": "12", "away": "10"},
    ],
}


class TestExtractMatchStats:
    def test_extracts_known_stats(self):
        result = extract_match_stats(SAMPLE_MATCH)
        assert result["home"]["shots_total"] == 15
        assert result["away"]["shots_total"] == 8
        assert result["home"]["shots_on_target"] == 7
        assert result["away"]["shots_on_target"] == 3
        assert result["home"]["possession"] == 58
        assert result["away"]["possession"] == 42
        assert result["home"]["corners"] == 6
        assert result["away"]["corners"] == 4

    def test_ignores_unknown_stats(self):
        result = extract_match_stats(SAMPLE_MATCH)
        assert "fouls" not in result["home"]

    def test_empty_statistics(self):
        result = extract_match_stats({"statistics": []})
        assert result == {"home": {}, "away": {}}

    def test_missing_statistics_key(self):
        result = extract_match_stats({})
        assert result == {"home": {}, "away": {}}

    def test_non_numeric_stat_values(self):
        match = {
            "statistics": [
                {"type": "Shots Total", "home": "abc", "away": "5"},
            ],
        }
        result = extract_match_stats(match)
        assert "shots_total" not in result["home"]
        assert result["away"]["shots_total"] == 5

    def test_empty_string_stat_values(self):
        match = {
            "statistics": [
                {"type": "Shots Total", "home": "", "away": "3"},
            ],
        }
        result = extract_match_stats(match)
        assert result["home"]["shots_total"] == 0
        assert result["away"]["shots_total"] == 3
