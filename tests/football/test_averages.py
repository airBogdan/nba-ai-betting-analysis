"""Tests for sports.football.averages."""

from datetime import datetime, timezone, timedelta

import pytest

from sports.football.averages import (
    compute_league_average,
    get_league_avg,
    get_league_home_away_avg,
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
        gpg, count, home_gpg, away_gpg = compute_league_average(matches)
        assert count == 3
        assert abs(gpg - 8 / 3) < 0.01
        assert abs(home_gpg - 5 / 3) < 0.01
        assert abs(away_gpg - 3 / 3) < 0.01

    def test_empty_matches(self):
        gpg, count, home_gpg, away_gpg = compute_league_average([])
        assert gpg == 0.0
        assert count == 0
        assert home_gpg == 0.0
        assert away_gpg == 0.0

    def test_skips_non_finished(self):
        matches = [
            _finished_match(2, 1),
            {"match_hometeam_score": "0", "match_awayteam_score": "0", "match_status": ""},
            {"match_hometeam_score": "1", "match_awayteam_score": "1", "match_status": "Postponed"},
        ]
        gpg, count, home_gpg, away_gpg = compute_league_average(matches)
        assert count == 1
        assert gpg == 3.0
        assert home_gpg == 2.0
        assert away_gpg == 1.0

    def test_skips_invalid_scores(self):
        matches = [
            {**_finished_match(2, 1)},
            {"match_hometeam_score": "?", "match_awayteam_score": "1", "match_status": "Finished"},
        ]
        gpg, count, home_gpg, away_gpg = compute_league_average(matches)
        assert count == 1
        assert gpg == 3.0

    def test_home_away_split_reflects_advantage(self):
        matches = [
            _finished_match(3, 0),
            _finished_match(2, 1),
            _finished_match(1, 0),
        ]
        _, _, home_gpg, away_gpg = compute_league_average(matches)
        assert home_gpg > away_gpg


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
                "epl": {"goals_per_game": 2.75, "matches": 250, "home_goals_per_game": 1.55, "away_goals_per_game": 1.20},
                "la_liga": {"goals_per_game": 2.55, "matches": 240, "home_goals_per_game": 1.45, "away_goals_per_game": 1.10},
                "bundesliga": {"goals_per_game": 3.10, "matches": 200, "home_goals_per_game": 1.80, "away_goals_per_game": 1.30},
                "serie_a": {"goals_per_game": 2.60, "matches": 230, "home_goals_per_game": 1.50, "away_goals_per_game": 1.10},
                "ligue_1": {"goals_per_game": 2.50, "matches": 220, "home_goals_per_game": 1.40, "away_goals_per_game": 1.10},
            },
            "european_avg": 2.70,
            "european_home_avg": 1.54,
            "european_away_avg": 1.16,
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


class TestGetLeagueHomeAwayAvg:
    def _averages(self):
        return {
            "leagues": {
                "epl": {"goals_per_game": 2.75, "matches": 250, "home_goals_per_game": 1.55, "away_goals_per_game": 1.20},
                "serie_a": {"goals_per_game": 2.60, "matches": 230},
            },
            "european_avg": 2.70,
            "european_home_avg": 1.54,
            "european_away_avg": 1.16,
        }

    def test_domestic_league_with_splits(self):
        home, away = get_league_home_away_avg("epl", self._averages())
        assert home == 1.55
        assert away == 1.20

    def test_domestic_league_missing_splits_falls_back_to_half(self):
        home, away = get_league_home_away_avg("serie_a", self._averages())
        assert abs(home - 2.60 / 2) < 0.01
        assert abs(away - 2.60 / 2) < 0.01

    def test_ucl_returns_european_splits(self):
        home, away = get_league_home_away_avg("ucl", self._averages())
        assert home == 1.54
        assert away == 1.16

    def test_uel_returns_european_splits(self):
        home, away = get_league_home_away_avg("uel", self._averages())
        assert home == 1.54
        assert away == 1.16

    def test_none_averages_falls_back_to_half(self):
        home, away = get_league_home_away_avg("epl", None)
        half = DEFAULT_LEAGUE_AVG / 2
        assert home == half
        assert away == half

    def test_unknown_league_falls_back_to_half(self):
        home, away = get_league_home_away_avg("mls", self._averages())
        half = DEFAULT_LEAGUE_AVG / 2
        assert home == half
        assert away == half
