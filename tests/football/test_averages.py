"""Tests for sports.football.averages."""

from datetime import datetime, timezone, timedelta

import pytest

from sports.football.averages import (
    compute_league_average,
    get_league_avg,
    is_stale,
)
from sports.football.stats import DEFAULT_LEAGUE_AVG


def _finished_match(h_score, a_score):
    return {
        "match_hometeam_score": str(h_score),
        "match_awayteam_score": str(a_score),
        "match_status": "Finished",
    }


class TestComputeLeagueAverage:
    def test_computes_goals_per_game(self):
        matches = [
            _finished_match(2, 1),  # 3 goals
            _finished_match(0, 0),  # 0 goals
            _finished_match(3, 2),  # 5 goals
        ]
        gpg, count = compute_league_average(matches)
        assert count == 3
        assert abs(gpg - 8 / 3) < 0.01

    def test_empty_matches(self):
        gpg, count = compute_league_average([])
        assert gpg == 0.0
        assert count == 0

    def test_skips_non_finished(self):
        matches = [
            _finished_match(2, 1),
            {"match_hometeam_score": "0", "match_awayteam_score": "0", "match_status": ""},
            {"match_hometeam_score": "1", "match_awayteam_score": "1", "match_status": "Postponed"},
        ]
        gpg, count = compute_league_average(matches)
        assert count == 1
        assert gpg == 3.0

    def test_skips_invalid_scores(self):
        matches = [
            {**_finished_match(2, 1)},
            {"match_hometeam_score": "?", "match_awayteam_score": "1", "match_status": "Finished"},
        ]
        gpg, count = compute_league_average(matches)
        assert count == 1
        assert gpg == 3.0


class TestIsStale:
    def test_fresh_data(self):
        data = {"updated": datetime.now(timezone.utc).isoformat()}
        assert not is_stale(data)

    def test_old_data(self):
        old = datetime.now(timezone.utc) - timedelta(days=31)
        data = {"updated": old.isoformat()}
        assert is_stale(data)

    def test_missing_timestamp(self):
        assert is_stale({})

    def test_invalid_timestamp(self):
        assert is_stale({"updated": "not-a-date"})

    def test_custom_max_age(self):
        recent = datetime.now(timezone.utc) - timedelta(days=5)
        data = {"updated": recent.isoformat()}
        assert not is_stale(data, max_age_days=7)
        assert is_stale(data, max_age_days=3)


class TestGetLeagueAvg:
    def _averages(self):
        return {
            "leagues": {
                "epl": {"goals_per_game": 2.75, "matches": 250},
                "la_liga": {"goals_per_game": 2.55, "matches": 240},
                "bundesliga": {"goals_per_game": 3.10, "matches": 200},
                "serie_a": {"goals_per_game": 2.60, "matches": 230},
                "ligue_1": {"goals_per_game": 2.50, "matches": 220},
            },
            "european_avg": 2.70,
        }

    def test_domestic_league(self):
        assert get_league_avg("epl", self._averages()) == 2.75
        assert get_league_avg("bundesliga", self._averages()) == 3.10

    def test_ucl_returns_european_avg(self):
        assert get_league_avg("ucl", self._averages()) == 2.70

    def test_uel_returns_european_avg(self):
        assert get_league_avg("uel", self._averages()) == 2.70

    def test_fallback_when_no_data(self):
        assert get_league_avg("epl", None) == DEFAULT_LEAGUE_AVG

    def test_fallback_when_league_missing(self):
        averages = {"leagues": {}, "european_avg": 2.70}
        assert get_league_avg("epl", averages) == DEFAULT_LEAGUE_AVG

    def test_fallback_when_zero_matches(self):
        averages = {
            "leagues": {"epl": {"goals_per_game": 0.0, "matches": 0}},
            "european_avg": 2.70,
        }
        assert get_league_avg("epl", averages) == DEFAULT_LEAGUE_AVG

    def test_unknown_league_returns_default(self):
        assert get_league_avg("mls", self._averages()) == DEFAULT_LEAGUE_AVG
