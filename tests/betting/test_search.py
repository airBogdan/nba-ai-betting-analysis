"""Tests for web search enrichment and compact_json."""

from unittest.mock import AsyncMock, patch

import pytest

from betting.prompts import compact_json
from betting.search import (
    _build_search_summary,
    _get_available_players,
    sanitize_label,
    search_enrich,
    search_player_news,
)


SAMPLE_GAME_DATA = {
    "matchup": {"home_team": "Lakers", "team1": "Lakers", "team2": "Celtics"},
    "current_season": {
        "team1": {"name": "Lakers", "record": "30-20", "conf_rank": 5, "ppg": 115.2, "ortg": 112.0, "drtg": 108.5},
        "team2": {"name": "Celtics", "record": "35-15", "conf_rank": 2, "ppg": 118.1, "ortg": 115.3, "drtg": 106.2},
    },
    "schedule": {
        "team1": {"streak": "W3", "days_rest": 2, "games_last_7_days": 3},
        "team2": {"streak": "L1", "days_rest": 1, "games_last_7_days": 4},
    },
    "players": {
        "team1": {
            "availability_concerns": ["LeBron James (50/60 games)"],
            "rotation": [
                {"name": "LeBron James", "ppg": 25.5, "plus_minus": 3.1, "games": 50},
                {"name": "Anthony Davis", "ppg": 24.0, "plus_minus": 4.2, "games": 48},
                {"name": "Austin Reaves", "ppg": 18.3, "plus_minus": 1.5, "games": 52},
                {"name": "Rui Hachimura", "ppg": 12.8, "plus_minus": 0.8, "games": 50},
                {"name": "D'Angelo Russell", "ppg": 14.1, "plus_minus": -1.2, "games": 45},
                {"name": "Jaxson Hayes", "ppg": 6.5, "plus_minus": -0.3, "games": 40},
            ],
            "injuries": [
                {"player": "Anthony Davis", "status": "Out", "reason": "Knee"},
            ],
        },
        "team2": {
            "availability_concerns": [],
            "rotation": [
                {"name": "Jayson Tatum", "ppg": 27.2, "plus_minus": 5.0, "games": 50},
                {"name": "Jaylen Brown", "ppg": 23.1, "plus_minus": 3.8, "games": 52},
                {"name": "Derrick White", "ppg": 16.5, "plus_minus": 4.1, "games": 49},
                {"name": "Kristaps Porzingis", "ppg": 20.0, "plus_minus": 3.5, "games": 35},
                {"name": "Jrue Holiday", "ppg": 13.2, "plus_minus": 2.9, "games": 50},
                {"name": "Al Horford", "ppg": 8.5, "plus_minus": 1.0, "games": 42},
            ],
            "injuries": [
                {"player": "Kristaps Porzingis", "status": "Doubtful", "reason": "Ankle"},
                {"player": "Al Horford", "status": "Questionable", "reason": "Rest"},
            ],
        },
    },
}

MATCHUP_STR = "Celtics @ Lakers"


class TestCompactJson:
    def test_no_indent(self):
        result = compact_json({"key": "value", "num": 1})
        assert "\n" not in result

    def test_minimal_separators(self):
        result = compact_json({"a": 1})
        assert '{"a": 1}' == result

    def test_comma_space_separator(self):
        result = compact_json({"a": 1, "b": 2})
        assert ", " in result

    def test_nested_structures(self):
        data = {"outer": {"inner": [1, 2, 3]}}
        result = compact_json(data)
        assert result == '{"outer": {"inner": [1, 2, 3]}}'

    def test_preserves_all_data(self):
        import json
        data = {"name": "Lakers", "record": "30-20", "stats": [1.5, 2.0]}
        result = compact_json(data)
        assert json.loads(result) == data

    def test_handles_empty_dict(self):
        assert compact_json({}) == "{}"

    def test_handles_strings_with_spaces(self):
        result = compact_json({"name": "Los Angeles Lakers"})
        assert "Los Angeles Lakers" in result

    def test_strips_none_and_empty(self):
        data = {"name": "Lakers", "value": None, "empty": [], "nested": {}}
        result = compact_json(data)
        assert "value" not in result
        assert "empty" not in result
        assert "nested" not in result
        assert "Lakers" in result


class TestBuildSearchSummary:
    def test_includes_team_names(self):
        result = _build_search_summary(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert "Lakers" in result
        assert "Celtics" in result

    def test_includes_records(self):
        result = _build_search_summary(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert "30-20" in result
        assert "35-15" in result

    def test_includes_matchup_string(self):
        result = _build_search_summary(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert MATCHUP_STR in result

    def test_includes_availability_concerns(self):
        result = _build_search_summary(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert "LeBron James" in result

    def test_handles_dict_availability_concerns(self):
        """Availability concerns can be dicts (with 'name' key) or plain strings."""
        data = {**SAMPLE_GAME_DATA, "players": {
            "team1": {"availability_concerns": [{"name": "AD", "status": "questionable"}]},
            "team2": {"availability_concerns": []},
        }}
        result = _build_search_summary(data, MATCHUP_STR)
        assert "AD" in result

    def test_includes_streak(self):
        result = _build_search_summary(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert "W3" in result

    def test_reasonable_length(self):
        result = _build_search_summary(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert len(result) < 1000


class TestSearchEnrich:
    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_makes_three_calls_when_followup_needed(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline: injuries and odds info",  # template search
            "Investigate Lakers Celtics line movement last 24 hours and betting trends for this matchup",  # followup gen
            "Line moved from -3 to -4.5 due to...",  # followup search
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert mock_complete.call_count == 3
        assert "Baseline: injuries and odds info" in result
        assert "### Additional Context" in result
        assert "Line moved from -3 to -4.5" in result

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_no_followup_needed(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline: complete info",  # template search
            "No follow-up needed",  # followup gen
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline: complete info"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_followup_gen_fails(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline: complete info",  # template search
            None,  # followup gen fails
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline: complete info"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_followup_short(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline info",  # template search
            "ok",  # short followup - skip
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline info"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_none_if_template_fails(self, mock_complete):
        mock_complete.return_value = None
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result is None
        assert mock_complete.call_count == 1

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_followup_says_no_additional(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline: all covered",  # template search
            "No additional search is necessary for this matchup",  # no additional
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline: all covered"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_handles_exception_gracefully(self, mock_complete):
        mock_complete.side_effect = Exception("API down")
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result is None


class TestGetAvailablePlayers:
    def test_excludes_out_players(self):
        result = _get_available_players(SAMPLE_GAME_DATA, "team1")
        names = [p["name"] for p in result]
        assert "Anthony Davis" not in names
        assert "LeBron James" in names

    def test_excludes_doubtful_players(self):
        result = _get_available_players(SAMPLE_GAME_DATA, "team2")
        names = [p["name"] for p in result]
        assert "Kristaps Porzingis" not in names

    def test_keeps_questionable_players(self):
        result = _get_available_players(SAMPLE_GAME_DATA, "team2")
        names = [p["name"] for p in result]
        assert "Al Horford" in names

    def test_respects_max_players(self):
        result = _get_available_players(SAMPLE_GAME_DATA, "team2", max_players=2)
        assert len(result) == 2

    def test_default_max_is_five(self):
        result = _get_available_players(SAMPLE_GAME_DATA, "team2")
        assert len(result) == 5

    def test_handles_missing_players_section(self):
        data = {"matchup": {"team1": "A", "team2": "B"}}
        result = _get_available_players(data, "team1")
        assert result == []

    def test_handles_missing_rotation(self):
        data = {"players": {"team1": {"injuries": []}}}
        result = _get_available_players(data, "team1")
        assert result == []

    def test_handles_missing_injuries(self):
        data = {"players": {"team1": {"rotation": [
            {"name": "Player A", "ppg": 20.0},
        ]}}}
        result = _get_available_players(data, "team1")
        assert len(result) == 1
        assert result[0]["name"] == "Player A"


class TestSearchPlayerNews:
    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_success(self, mock_complete):
        mock_complete.return_value = "Tatum is on a 30+ point streak..."
        result = await search_player_news(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Tatum is on a 30+ point streak..."
        assert mock_complete.call_count == 1

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_none_on_failure(self, mock_complete):
        mock_complete.return_value = None
        result = await search_player_news(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result is None

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_none_on_exception(self, mock_complete):
        mock_complete.side_effect = Exception("API error")
        result = await search_player_news(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result is None

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_prompt_contains_player_names(self, mock_complete):
        mock_complete.return_value = "news"
        await search_player_news(SAMPLE_GAME_DATA, MATCHUP_STR)
        prompt = mock_complete.call_args[0][0]
        # Available team1 players (AD is Out, so excluded)
        assert "LeBron James" in prompt
        assert "Austin Reaves" in prompt
        # Available team2 players (Porzingis is Doubtful, so excluded)
        assert "Jayson Tatum" in prompt
        assert "Jaylen Brown" in prompt

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_prompt_excludes_injured_players(self, mock_complete):
        mock_complete.return_value = "news"
        await search_player_news(SAMPLE_GAME_DATA, MATCHUP_STR)
        prompt = mock_complete.call_args[0][0]
        assert "Anthony Davis" not in prompt
        assert "Kristaps Porzingis" not in prompt

    @pytest.mark.asyncio
    @patch("betting.search.complete", new_callable=AsyncMock)
    async def test_returns_none_when_no_players(self, mock_complete):
        data = {"players": {"team1": {}, "team2": {}}, "current_season": {}}
        result = await search_player_news(data, MATCHUP_STR)
        assert result is None
        mock_complete.assert_not_called()


class TestSanitizeLabel:
    def test_basic(self):
        assert sanitize_label("Celtics @ Lakers") == "celtics_at_lakers"

    def test_multi_word_teams(self):
        assert sanitize_label("Trail Blazers @ Thunder") == "trail_blazers_at_thunder"

    def test_already_lower(self):
        assert sanitize_label("nets @ heat") == "nets_at_heat"

