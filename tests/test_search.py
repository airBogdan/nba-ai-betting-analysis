"""Tests for web search enrichment and compact_json."""

from unittest.mock import AsyncMock, patch

import pytest

from workflow.prompts import compact_json
from workflow.search import (
    _build_search_summary,
    sanitize_label,
    search_enrich,
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
        },
        "team2": {
            "availability_concerns": [],
        },
    },
}

MATCHUP_STR = "Celtics @ Lakers"


class TestCompactJson:
    def test_removes_whitespace(self):
        result = compact_json({"key": "value", "num": 1})
        assert " " not in result
        assert "\n" not in result

    def test_no_space_after_colon(self):
        result = compact_json({"a": 1})
        assert ": " not in result
        assert '{"a":1}' == result

    def test_no_space_after_comma(self):
        result = compact_json({"a": 1, "b": 2})
        assert ", " not in result

    def test_nested_structures(self):
        data = {"outer": {"inner": [1, 2, 3]}}
        result = compact_json(data)
        assert result == '{"outer":{"inner":[1,2,3]}}'

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
    @patch("workflow.search.complete", new_callable=AsyncMock)
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
    @patch("workflow.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_no_followup_needed(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline: complete info",  # template search
            "No follow-up needed",  # followup gen
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline: complete info"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("workflow.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_followup_gen_fails(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline: complete info",  # template search
            None,  # followup gen fails
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline: complete info"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("workflow.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_followup_short(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline info",  # template search
            "ok",  # short followup - skip
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline info"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("workflow.search.complete", new_callable=AsyncMock)
    async def test_returns_none_if_template_fails(self, mock_complete):
        mock_complete.return_value = None
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result is None
        assert mock_complete.call_count == 1

    @pytest.mark.asyncio
    @patch("workflow.search.complete", new_callable=AsyncMock)
    async def test_returns_baseline_when_followup_says_no_additional(self, mock_complete):
        mock_complete.side_effect = [
            "Baseline: all covered",  # template search
            "No additional search is necessary for this matchup",  # no additional
        ]
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result == "Baseline: all covered"
        assert mock_complete.call_count == 2

    @pytest.mark.asyncio
    @patch("workflow.search.complete", new_callable=AsyncMock)
    async def test_handles_exception_gracefully(self, mock_complete):
        mock_complete.side_effect = Exception("API down")
        result = await search_enrich(SAMPLE_GAME_DATA, MATCHUP_STR)
        assert result is None


class TestSanitizeLabel:
    def test_basic(self):
        assert sanitize_label("Celtics @ Lakers") == "celtics_at_lakers"

    def test_multi_word_teams(self):
        assert sanitize_label("Trail Blazers @ Thunder") == "trail_blazers_at_thunder"

    def test_already_lower(self):
        assert sanitize_label("nets @ heat") == "nets_at_heat"

