"""Tests for helpers/api.py."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from helpers.api import (
    parse_minutes,
    process_player_statistics,
    process_team_stats,
)
from helpers.api.league import (
    compute_league_avg_efficiency,
    _FALLBACK_EFFICIENCY,
    LEAGUE_EFFICIENCY_CACHE,
)
from helpers.api.games import (
    get_scheduled_games,
    _utc_to_et_date,
)


class TestParseMinutes:
    """Tests for parse_minutes function."""

    def test_standard_format(self):
        """Parse standard MM:SS format."""
        assert parse_minutes("32:45") == 32.75

    def test_zero_seconds(self):
        """Parse minutes with zero seconds."""
        assert parse_minutes("25:00") == 25.0

    def test_single_digit_minutes(self):
        """Parse single digit minutes."""
        assert parse_minutes("5:30") == 5.5

    def test_full_quarter(self):
        """Parse a full quarter (12 minutes)."""
        assert parse_minutes("12:00") == 12.0

    def test_empty_string(self):
        """Empty string returns 0."""
        assert parse_minutes("") == 0.0

    def test_none_string(self):
        """None/falsy value returns 0."""
        assert parse_minutes(None) == 0.0

    def test_minutes_only(self):
        """Handle minutes without seconds part."""
        assert parse_minutes("30:") == 30.0

    def test_just_minutes_no_colon(self):
        """Handle just minutes number."""
        assert parse_minutes("30") == 30.0


class TestProcessPlayerStatistics:
    """Tests for process_player_statistics function."""

    @pytest.fixture
    def sample_player_games(self):
        """Sample player game logs for testing."""
        return [
            # Player 1 - 6 games
            {"player": {"id": 1, "firstname": "LeBron", "lastname": "James"},
             "min": "35:00", "points": 25, "totReb": 8, "assists": 7, "steals": 1,
             "blocks": 1, "turnovers": 3, "fgm": 10, "fga": 20, "tpm": 2, "tpa": 5,
             "ftm": 3, "fta": 4, "plusMinus": "10"},
            {"player": {"id": 1, "firstname": "LeBron", "lastname": "James"},
             "min": "36:00", "points": 30, "totReb": 10, "assists": 8, "steals": 2,
             "blocks": 0, "turnovers": 4, "fgm": 12, "fga": 22, "tpm": 3, "tpa": 6,
             "ftm": 3, "fta": 3, "plusMinus": "15"},
            {"player": {"id": 1, "firstname": "LeBron", "lastname": "James"},
             "min": "34:00", "points": 22, "totReb": 7, "assists": 9, "steals": 1,
             "blocks": 2, "turnovers": 2, "fgm": 9, "fga": 18, "tpm": 2, "tpa": 5,
             "ftm": 2, "fta": 2, "plusMinus": "8"},
            {"player": {"id": 1, "firstname": "LeBron", "lastname": "James"},
             "min": "33:00", "points": 28, "totReb": 9, "assists": 6, "steals": 0,
             "blocks": 1, "turnovers": 3, "fgm": 11, "fga": 21, "tpm": 2, "tpa": 4,
             "ftm": 4, "fta": 5, "plusMinus": "12"},
            {"player": {"id": 1, "firstname": "LeBron", "lastname": "James"},
             "min": "37:00", "points": 27, "totReb": 8, "assists": 10, "steals": 2,
             "blocks": 1, "turnovers": 2, "fgm": 10, "fga": 19, "tpm": 3, "tpa": 7,
             "ftm": 4, "fta": 4, "plusMinus": "20"},
            {"player": {"id": 1, "firstname": "LeBron", "lastname": "James"},
             "min": "35:00", "points": 24, "totReb": 6, "assists": 8, "steals": 1,
             "blocks": 0, "turnovers": 4, "fgm": 9, "fga": 20, "tpm": 2, "tpa": 6,
             "ftm": 4, "fta": 5, "plusMinus": "5"},
            # Player 2 - 6 games (less minutes)
            {"player": {"id": 2, "firstname": "Anthony", "lastname": "Davis"},
             "min": "32:00", "points": 22, "totReb": 12, "assists": 3, "steals": 1,
             "blocks": 3, "turnovers": 2, "fgm": 9, "fga": 18, "tpm": 0, "tpa": 1,
             "ftm": 4, "fta": 5, "plusMinus": "8"},
            {"player": {"id": 2, "firstname": "Anthony", "lastname": "Davis"},
             "min": "30:00", "points": 20, "totReb": 10, "assists": 2, "steals": 2,
             "blocks": 2, "turnovers": 1, "fgm": 8, "fga": 16, "tpm": 1, "tpa": 2,
             "ftm": 3, "fta": 4, "plusMinus": "12"},
            {"player": {"id": 2, "firstname": "Anthony", "lastname": "Davis"},
             "min": "31:00", "points": 25, "totReb": 11, "assists": 4, "steals": 1,
             "blocks": 4, "turnovers": 2, "fgm": 10, "fga": 17, "tpm": 1, "tpa": 3,
             "ftm": 4, "fta": 5, "plusMinus": "15"},
            {"player": {"id": 2, "firstname": "Anthony", "lastname": "Davis"},
             "min": "29:00", "points": 18, "totReb": 9, "assists": 2, "steals": 0,
             "blocks": 2, "turnovers": 3, "fgm": 7, "fga": 15, "tpm": 0, "tpa": 1,
             "ftm": 4, "fta": 6, "plusMinus": "3"},
            {"player": {"id": 2, "firstname": "Anthony", "lastname": "Davis"},
             "min": "33:00", "points": 28, "totReb": 13, "assists": 3, "steals": 2,
             "blocks": 3, "turnovers": 2, "fgm": 11, "fga": 19, "tpm": 1, "tpa": 2,
             "ftm": 5, "fta": 6, "plusMinus": "18"},
            {"player": {"id": 2, "firstname": "Anthony", "lastname": "Davis"},
             "min": "28:00", "points": 21, "totReb": 10, "assists": 2, "steals": 1,
             "blocks": 2, "turnovers": 1, "fgm": 8, "fga": 16, "tpm": 0, "tpa": 1,
             "ftm": 5, "fta": 7, "plusMinus": "10"},
            # Player 3 - only 3 games (at default threshold, filtered when min_games=5)
            {"player": {"id": 3, "firstname": "Austin", "lastname": "Reaves"},
             "min": "25:00", "points": 15, "totReb": 3, "assists": 5, "steals": 1,
             "blocks": 0, "turnovers": 2, "fgm": 6, "fga": 12, "tpm": 2, "tpa": 5,
             "ftm": 1, "fta": 2, "plusMinus": "5"},
            {"player": {"id": 3, "firstname": "Austin", "lastname": "Reaves"},
             "min": "22:00", "points": 12, "totReb": 2, "assists": 4, "steals": 0,
             "blocks": 0, "turnovers": 1, "fgm": 5, "fga": 10, "tpm": 1, "tpa": 4,
             "ftm": 1, "fta": 1, "plusMinus": "2"},
            {"player": {"id": 3, "firstname": "Austin", "lastname": "Reaves"},
             "min": "24:00", "points": 18, "totReb": 4, "assists": 6, "steals": 2,
             "blocks": 0, "turnovers": 2, "fgm": 7, "fga": 14, "tpm": 2, "tpa": 6,
             "ftm": 2, "fta": 2, "plusMinus": "8"},
        ]

    def test_empty_list_returns_empty(self):
        """Empty input returns empty list."""
        result = process_player_statistics([])
        assert result == []

    def test_none_returns_empty(self):
        """None input returns empty list."""
        result = process_player_statistics(None)
        assert result == []

    def test_filters_by_min_games(self, sample_player_games):
        """Players below min_games threshold are filtered out."""
        result = process_player_statistics(sample_player_games, top_n=10, min_games=5)
        player_ids = [p["id"] for p in result]
        # Player 3 only has 3 games, should be filtered
        assert 3 not in player_ids
        assert 1 in player_ids
        assert 2 in player_ids

    def test_returns_top_n_by_minutes(self, sample_player_games):
        """Returns top N players sorted by minutes per game."""
        result = process_player_statistics(sample_player_games, top_n=1, min_games=5)
        assert len(result) == 1
        # LeBron plays more minutes than AD
        assert result[0]["name"] == "LeBron James"

    def test_computes_per_game_averages(self, sample_player_games):
        """Correctly computes per-game averages."""
        result = process_player_statistics(sample_player_games, top_n=2, min_games=5)
        lebron = next(p for p in result if p["name"] == "LeBron James")

        # LeBron: 6 games, 156 total points = 26 PPG
        assert lebron["games"] == 6
        assert lebron["ppg"] == 26.0
        # 48 total rebounds / 6 games = 8.0 RPG
        assert lebron["rpg"] == 8.0
        # 48 total assists / 6 games = 8.0 APG
        assert lebron["apg"] == 8.0

    def test_computes_disruption_stat(self, sample_player_games):
        """Disruption = steals + blocks per game."""
        result = process_player_statistics(sample_player_games, top_n=2, min_games=5)
        ad = next(p for p in result if p["name"] == "Anthony Davis")

        # AD: 7 steals + 16 blocks = 23 / 6 games = 3.8
        assert ad["disruption"] == 3.8

    def test_computes_shooting_percentages(self, sample_player_games):
        """FG% and 3P% are computed correctly."""
        result = process_player_statistics(sample_player_games, top_n=2, min_games=5)
        lebron = next(p for p in result if p["name"] == "LeBron James")

        # LeBron: 61 FGM / 120 FGA = 50.8%
        assert lebron["fgp"] == 50.8
        # 14 3PM / 33 3PA = 42.4%
        assert lebron["tpp"] == 42.4

    def test_handles_zero_attempts(self):
        """Handles zero FGA/3PA without division error."""
        player_games = [
            {"player": {"id": 1, "firstname": "Test", "lastname": "Player"},
             "min": "10:00", "points": 0, "totReb": 1, "assists": 0, "steals": 0,
             "blocks": 0, "turnovers": 0, "fgm": 0, "fga": 0, "tpm": 0, "tpa": 0,
             "ftm": 0, "fta": 0, "plusMinus": "0"}
            for _ in range(5)
        ]
        result = process_player_statistics(player_games, top_n=1, min_games=5)
        assert result[0]["fgp"] == 0.0
        assert result[0]["tpp"] == 0.0

    def test_handles_missing_stats(self):
        """Handles missing stat fields gracefully."""
        player_games = [
            {"player": {"id": 1, "firstname": "Test", "lastname": "Player"},
             "min": "20:00"}  # Minimal data
            for _ in range(5)
        ]
        result = process_player_statistics(player_games, top_n=1, min_games=5)
        assert len(result) == 1
        assert result[0]["ppg"] == 0.0


class TestProcessTeamStats:
    """Tests for process_team_stats function."""

    @pytest.fixture
    def sample_raw_stats(self):
        """Sample raw team statistics."""
        return {
            "games": 20,
            "points": 2200,  # 110 PPG
            "fgm": 800,
            "fga": 1800,  # 44.4 FG%
            "fgp": "44.4",
            "ftm": 350,
            "fta": 450,
            "ftp": "77.8",
            "tpm": 250,
            "tpa": 700,
            "tpp": "35.7",
            "offReb": 200,
            "defReb": 700,
            "totReb": 900,  # 45 RPG
            "assists": 500,  # 25 APG
            "steals": 150,
            "turnovers": 280,  # 14 TOPG
            "blocks": 100,  # steals + blocks = 250 / 20 = 12.5 disruption
            "plusMinus": 100,  # +5 net rating
        }

    def test_computes_ppg(self, sample_raw_stats):
        """Points per game computed correctly."""
        result = process_team_stats(sample_raw_stats)
        assert result["ppg"] == 110.0

    def test_computes_apg(self, sample_raw_stats):
        """Assists per game computed correctly."""
        result = process_team_stats(sample_raw_stats)
        assert result["apg"] == 25.0

    def test_computes_rpg(self, sample_raw_stats):
        """Rebounds per game computed correctly."""
        result = process_team_stats(sample_raw_stats)
        assert result["rpg"] == 45.0

    def test_computes_topg(self, sample_raw_stats):
        """Turnovers per game computed correctly."""
        result = process_team_stats(sample_raw_stats)
        assert result["topg"] == 14.0

    def test_computes_disruption(self, sample_raw_stats):
        """Disruption (steals + blocks) per game computed correctly."""
        result = process_team_stats(sample_raw_stats)
        assert result["disruption"] == 12.5

    def test_computes_net_rating(self, sample_raw_stats):
        """Net rating computed from plusMinus."""
        result = process_team_stats(sample_raw_stats)
        assert result["net_rating"] == 5.0

    def test_preserves_shooting_percentages(self, sample_raw_stats):
        """FG% and 3P% preserved from raw data."""
        result = process_team_stats(sample_raw_stats)
        assert result["fgp"] == 44.4
        assert result["tpp"] == 35.7

    def test_computes_pace(self, sample_raw_stats):
        """Pace estimate computed correctly."""
        result = process_team_stats(sample_raw_stats)
        # Pace = (FGA + 0.44*FTA + TOV - OREB) / games
        # = (1800 + 0.44*450 + 280 - 200) / 20
        # = (1800 + 198 + 280 - 200) / 20
        # = 2078 / 20 = 103.9
        assert result["pace"] == 103.9

    def test_handles_zero_games(self):
        """Handles zero games without division error."""
        raw = {"games": 0, "points": 0}
        result = process_team_stats(raw)
        # Should default games to 1 to avoid division by zero
        assert result["ppg"] == 0.0

    def test_handles_missing_fields(self):
        """Handles missing fields with defaults."""
        raw = {"games": 10}
        result = process_team_stats(raw)
        assert result["games"] == 10
        assert result["ppg"] == 0.0
        assert result["net_rating"] == 0.0

    def test_handles_none_values(self):
        """Handles None values in raw stats."""
        raw = {
            "games": 10,
            "points": None,
            "assists": None,
            "tpp": None,
            "fgp": None,
        }
        result = process_team_stats(raw)
        assert result["ppg"] == 0.0
        assert result["tpp"] == 0.0
        assert result["fgp"] == 0.0


class TestComputeLeagueAvgEfficiency:
    """Tests for compute_league_avg_efficiency."""

    def _make_raw_team_stats(self, points, games, fga, fta, turnovers, off_reb):
        """Build a raw stats list matching API shape."""
        return [{
            "games": games, "points": points,
            "fga": fga, "fta": fta, "turnovers": turnovers, "offReb": off_reb,
            "defReb": 500, "totReb": 700, "assists": 400,
            "steals": 100, "blocks": 80, "plusMinus": 50,
            "tpp": "36.0", "fgp": "46.0",
        }]

    @pytest.mark.asyncio
    async def test_computes_from_api(self, tmp_path, monkeypatch):
        """Computes average efficiency from all teams' stats."""
        monkeypatch.setattr(
            "helpers.api.league.LEAGUE_EFFICIENCY_CACHE",
            tmp_path / "cache" / "league_avg_efficiency.json",
        )
        teams = [
            {"id": 1, "name": "Team A", "nbaFranchise": True, "allStar": False},
            {"id": 2, "name": "Team B", "nbaFranchise": True, "allStar": False},
            {"id": 99, "name": "All Stars", "nbaFranchise": True, "allStar": True},
            {"id": 100, "name": "Shanghai Sharks", "nbaFranchise": False, "allStar": False},
        ]
        # Team A: 110 ppg, pace ~104 → ORTG ~105.8
        # Team B: 115 ppg, pace ~104 → ORTG ~110.6
        stats_a = self._make_raw_team_stats(2200, 20, 1800, 450, 280, 200)
        stats_b = self._make_raw_team_stats(2300, 20, 1800, 450, 280, 200)

        with patch("helpers.api.league.fetch_nba_api", new_callable=AsyncMock, return_value=teams) as mock_teams, \
             patch("helpers.api.league.get_team_statistics", new_callable=AsyncMock) as mock_stats:
            mock_stats.side_effect = [stats_a, stats_b]
            result = await compute_league_avg_efficiency(2025)

        assert 105 < result < 115  # reasonable NBA range
        # Only 2 real NBA teams should have stats fetched (not all-star or international)
        assert mock_stats.call_count == 2
        # Cache file should be written
        cache_file = tmp_path / "cache" / "league_avg_efficiency.json"
        assert cache_file.exists()

    @pytest.mark.asyncio
    async def test_reads_from_fresh_cache(self, tmp_path, monkeypatch):
        """Returns cached value without API calls when cache is fresh."""
        from datetime import date
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "league_avg_efficiency.json"
        cache_file.write_text(json.dumps({
            "date": str(date.today()), "season": 2025, "efficiency": 114.2, "teams": 30
        }))
        monkeypatch.setattr(
            "helpers.api.league.LEAGUE_EFFICIENCY_CACHE", cache_file,
        )

        with patch("helpers.api.league.fetch_nba_api", new_callable=AsyncMock) as mock_api:
            result = await compute_league_avg_efficiency(2025)

        assert result == 114.2
        mock_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_when_api_fails(self, tmp_path, monkeypatch):
        """Falls back to _FALLBACK_EFFICIENCY when API returns None."""
        monkeypatch.setattr(
            "helpers.api.league.LEAGUE_EFFICIENCY_CACHE",
            tmp_path / "no_cache.json",
        )

        with patch("helpers.api.league.fetch_nba_api", new_callable=AsyncMock, return_value=None):
            result = await compute_league_avg_efficiency(2025)

        assert result == _FALLBACK_EFFICIENCY

    @pytest.mark.asyncio
    async def test_handles_corrupt_cache(self, tmp_path, monkeypatch):
        """Recomputes when cache file is corrupt."""
        cache_file = tmp_path / "league_avg_efficiency.json"
        cache_file.write_text("not valid json{{{")
        monkeypatch.setattr(
            "helpers.api.league.LEAGUE_EFFICIENCY_CACHE", cache_file,
        )
        teams = [{"id": 1, "name": "Team A", "nbaFranchise": True, "allStar": False}]
        stats = self._make_raw_team_stats(2200, 20, 1800, 450, 280, 200)

        with patch("helpers.api.league.fetch_nba_api", new_callable=AsyncMock, return_value=teams), \
             patch("helpers.api.league.get_team_statistics", new_callable=AsyncMock, return_value=stats):
            result = await compute_league_avg_efficiency(2025)

        assert 100 < result < 120


class TestUtcToEtDate:
    """Tests for _utc_to_et_date helper."""

    def test_evening_game_previous_day(self):
        """UTC midnight+ maps to previous ET day (7:30 PM ET game)."""
        assert _utc_to_et_date("2026-02-11T00:30:00.000Z") == "2026-02-10"

    def test_afternoon_game_same_day(self):
        """UTC afternoon maps to same ET day (1:00 PM ET game)."""
        assert _utc_to_et_date("2026-02-11T18:00:00.000Z") == "2026-02-11"

    def test_late_night_game(self):
        """UTC 3:30 AM maps to previous ET day (10:30 PM ET game)."""
        assert _utc_to_et_date("2026-02-11T03:30:00.000Z") == "2026-02-10"

    def test_5am_utc_midnight_et(self):
        """UTC 5:00 AM = midnight ET, start of new day."""
        assert _utc_to_et_date("2026-02-11T05:00:00.000Z") == "2026-02-11"

    def test_none_input(self):
        assert _utc_to_et_date(None) == None

    def test_empty_string(self):
        assert _utc_to_et_date("") == None

    def test_invalid_string(self):
        assert _utc_to_et_date("not-a-date") == None

    def test_dst_transition(self):
        """During EDT (UTC-4), 3:30 AM UTC = 11:30 PM ET prev day."""
        # March 8, 2026 is in EDT
        assert _utc_to_et_date("2026-03-15T03:30:00.000Z") == "2026-03-14"

    def test_dst_afternoon(self):
        """During EDT, 18:00 UTC = 2:00 PM ET same day."""
        assert _utc_to_et_date("2026-03-15T18:00:00.000Z") == "2026-03-15"


class TestGetScheduledGamesETFilter:
    """Tests for get_scheduled_games with ET date filtering."""

    def _make_game(self, game_id, date_start, home_name, away_name):
        return {
            "id": game_id,
            "date": {"start": date_start},
            "status": {"clock": None, "halftime": False, "long": "Scheduled"},
            "teams": {
                "home": {"id": game_id * 10, "name": home_name},
                "visitors": {"id": game_id * 10 + 1, "name": away_name},
            },
        }

    @pytest.mark.asyncio
    async def test_filters_by_et_date(self):
        """Only games whose ET date matches the target are returned."""
        # Feb 10 evening games show up on UTC Feb 11
        evening_game = self._make_game(1, "2026-02-11T00:30:00.000Z", "Knicks", "Pacers")
        # Feb 11 afternoon game
        afternoon_game = self._make_game(2, "2026-02-11T18:00:00.000Z", "Lakers", "Celtics")
        # Feb 11 evening game shows up on UTC Feb 12
        next_evening = self._make_game(3, "2026-02-12T01:00:00.000Z", "Suns", "Mavs")

        async def mock_get_games(season, date_str):
            if date_str == "2026-02-11":
                return [evening_game, afternoon_game]
            elif date_str == "2026-02-12":
                return [next_evening]
            return None

        with patch("helpers.api.games.get_games_by_date", side_effect=mock_get_games):
            result = await get_scheduled_games(2025, "2026-02-11")

        # Should include afternoon_game (ET=Feb 11) and next_evening (ET=Feb 11)
        # Should exclude evening_game (ET=Feb 10)
        ids = [g["id"] for g in result]
        assert 2 in ids  # afternoon, same day
        assert 3 in ids  # evening, ET is Feb 11
        assert 1 not in ids  # evening from previous ET day

    @pytest.mark.asyncio
    async def test_both_api_calls_empty(self):
        """Returns empty list when both date queries return nothing."""
        async def mock_get_games(season, date_str):
            return None

        with patch("helpers.api.games.get_games_by_date", side_effect=mock_get_games):
            result = await get_scheduled_games(2025, "2026-02-11")

        assert result == []

    @pytest.mark.asyncio
    async def test_deduplicates_by_game_id(self):
        """Games appearing in both queries are deduplicated."""
        game = self._make_game(1, "2026-02-11T18:00:00.000Z", "Lakers", "Celtics")

        async def mock_get_games(season, date_str):
            # Same game returned by both date queries
            return [game]

        with patch("helpers.api.games.get_games_by_date", side_effect=mock_get_games):
            result = await get_scheduled_games(2025, "2026-02-11")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_queries_correct_dates(self):
        """Verifies both target date and next day are queried."""
        calls = []

        async def mock_get_games(season, date_str):
            calls.append(date_str)
            return None

        with patch("helpers.api.games.get_games_by_date", side_effect=mock_get_games):
            await get_scheduled_games(2025, "2026-02-11")

        assert "2026-02-11" in calls
        assert "2026-02-12" in calls
