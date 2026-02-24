import json
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.analyze.gamedata import extract_game_id, format_matchup_string
from workflow.analyze.bets import (
    CONFIDENCE_TO_UNITS,
    VALID_BET_TYPES,
    VALID_CONFIDENCE,
    VALID_PROP_TYPES,
    _normalize_bet_type,
    _normalize_confidence,
    _normalize_prop_pick,
    _normalize_units,
    create_active_bet,
    create_prop_bet,
    write_journal_pre_game,
)
from workflow.names import names_match, normalize_name
from workflow.prompts import compact_json
from workflow.llm import _strip_markdown_json


class TestNameNormalization:
    """Player names come from different sources (API, search, LLM) and need
    normalization for matching."""

    def test_strips_diacritics(self):
        assert normalize_name("Luka Dončić") == "luka doncic"

    def test_strips_suffixes(self):
        assert normalize_name("Jaren Jackson Jr.") == "jaren jackson"
        assert normalize_name("Robert Williams III") == "robert williams"

    def test_lowercases(self):
        assert normalize_name("LEBRON JAMES") == "lebron james"

    def test_strips_periods(self):
        assert normalize_name("P.J. Washington") == "pj washington"


class TestNameMatching:
    """Two names should match if they refer to the same person, even with
    different formatting, diacritics, suffixes, or initials."""

    def test_exact_match(self):
        assert names_match("LeBron James", "LeBron James")

    def test_case_insensitive(self):
        assert names_match("lebron james", "LEBRON JAMES")

    def test_diacritics_ignored(self):
        assert names_match("Luka Dončić", "Luka Doncic")

    def test_suffix_ignored(self):
        assert names_match("Jaren Jackson Jr.", "Jaren Jackson")

    def test_initial_matches_full_name(self):
        assert names_match("K Knueppel", "Kyle Knueppel")
        assert names_match("C. Coward", "Cedric Coward")

    def test_different_people_dont_match(self):
        assert not names_match("LeBron James", "Kevin Durant")

    def test_same_last_name_different_first(self):
        assert not names_match("Marcus Morris", "Markieff Morris")


class TestCompactJson:
    """compact_json strips noise (None, empty collections, _-prefixed keys)
    to reduce token usage in LLM prompts."""

    def test_strips_none_values(self):
        result = compact_json({"a": 1, "b": None})
        parsed = json.loads(result)
        assert "b" not in parsed

    def test_strips_empty_lists(self):
        result = compact_json({"a": 1, "b": []})
        parsed = json.loads(result)
        assert "b" not in parsed

    def test_strips_empty_dicts(self):
        result = compact_json({"a": 1, "b": {}})
        parsed = json.loads(result)
        assert "b" not in parsed

    def test_strips_underscore_prefixed_keys(self):
        result = compact_json({"name": "test", "_internal": True})
        parsed = json.loads(result)
        assert "_internal" not in parsed

    def test_preserves_valid_data(self):
        data = {"name": "Lakers", "score": 110, "players": ["LeBron"]}
        result = compact_json(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_nested_cleaning(self):
        data = {"outer": {"inner": None, "keep": 1}}
        result = compact_json(data)
        parsed = json.loads(result)
        assert parsed == {"outer": {"keep": 1}}

    def test_uses_compact_separators(self):
        """Output uses (', ', ': ') separators for compactness."""
        result = compact_json({"a": 1, "b": 2})
        assert ", " in result
        assert ": " in result


class TestStripMarkdownJson:
    """LLMs often wrap JSON in ```json code blocks. The parser must handle this."""

    def test_strips_json_code_block(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _strip_markdown_json(raw)
        assert json.loads(result) == {"key": "value"}

    def test_strips_generic_code_block(self):
        raw = '```\n{"key": "value"}\n```'
        result = _strip_markdown_json(raw)
        assert json.loads(result) == {"key": "value"}

    def test_passes_through_raw_json(self):
        raw = '{"key": "value"}'
        result = _strip_markdown_json(raw)
        assert json.loads(result) == {"key": "value"}

    def test_handles_surrounding_text(self):
        raw = 'Here is the result:\n```json\n{"key": "value"}\n```\nDone!'
        result = _strip_markdown_json(raw)
        assert json.loads(result) == {"key": "value"}


class TestAnalyzeGameDataHygiene:
    """analyze_game strips internal/noisy keys before sending data to the LLM.
    The LLM should NOT see: _file, search_context, polymarket_odds, odds."""

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.complete_json")
    async def test_strips_internal_keys_from_llm_payload(self, mock_llm):
        from workflow.analyze.pipeline import analyze_game

        mock_llm.return_value = {
            "game_id": "123", "matchup": "A @ B",
            "expected_margin": 3.0, "expected_total": 220.0,
            "moneyline": {"pick": "A", "confidence": "medium", "edge": "x"},
            "spread": {"pick": "A", "line": -3, "confidence": "skip", "edge": ""},
            "total": {"pick": "over", "line": 220, "confidence": "skip", "edge": ""},
            "recommended_bets": [], "primary_edge": "x",
            "case_for": [], "case_against": [],
            "analysis_summary": "test",
        }

        game_data = {
            "_file": "test.json",
            "search_context": "Search results here",
            "polymarket_odds": {"moneyline": {"prices": [0.6, 0.4]}},
            "odds": {"spread": -4.5},
            "matchup": {"team1": "A", "team2": "B", "home_team": "A"},
            "important_stat": 42,
        }

        await analyze_game(game_data, "123", "B @ A", "## Strategy")

        # Check what was sent to the LLM
        prompt_sent = mock_llm.call_args[0][0]
        # Internal keys should NOT appear in the JSON blob
        assert "_file" not in prompt_sent
        # But search context should appear in its own section
        assert "Search results here" in prompt_sent
        # Real data should be in the prompt
        assert "important_stat" in prompt_sent

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.complete_json")
    async def test_sets_game_id_and_matchup_on_result(self, mock_llm):
        from workflow.analyze.pipeline import analyze_game

        mock_llm.return_value = {"some": "data"}

        game_data = {
            "matchup": {"team1": "A", "team2": "B", "home_team": "A"},
        }

        result = await analyze_game(game_data, "game-99", "B @ A", None)
        assert result["game_id"] == "game-99"
        assert result["matchup"] == "B @ A"

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.complete_json", return_value=None)
    async def test_returns_none_on_llm_failure(self, mock_llm):
        from workflow.analyze.pipeline import analyze_game

        game_data = {"matchup": {"team1": "A", "team2": "B", "home_team": "A"}}
        result = await analyze_game(game_data, "123", "B @ A", None)
        assert result is None


class TestJournalWriting:
    """The journal documents each day's analysis for review. It must include
    selected bets and skipped games."""

    def test_writes_journal_with_bets(self, tmp_path):
        with patch("workflow.analyze.bets.JOURNAL_DIR", tmp_path):
            bets = [{
                "matchup": "Celtics @ Lakers",
                "bet_type": "moneyline",
                "pick": "Lakers",
                "line": None,
                "confidence": "high",
                "units": 2.0,
                "primary_edge": "Home court",
                "reasoning": "Strong at home",
                "amount": 50.00,
            }]
            write_journal_pre_game("2026-02-21", bets, [], "Good slate today.")

            content = (tmp_path / "2026-02-21.md").read_text()
            assert "Celtics @ Lakers" in content
            assert "Lakers" in content
            assert "$50.00" in content
            assert "Good slate today" in content

    def test_writes_journal_with_no_bets(self, tmp_path):
        with patch("workflow.analyze.bets.JOURNAL_DIR", tmp_path):
            write_journal_pre_game("2026-02-21", [], [], "Quiet day.")
            content = (tmp_path / "2026-02-21.md").read_text()
            assert "No bets selected today" in content

    def test_includes_skipped_games(self, tmp_path):
        with patch("workflow.analyze.bets.JOURNAL_DIR", tmp_path):
            skipped = [{"matchup": "Nets @ Wizards", "reason": "No edge"}]
            write_journal_pre_game("2026-02-21", [], skipped, "")
            content = (tmp_path / "2026-02-21.md").read_text()
            assert "Nets @ Wizards" in content
            assert "No edge" in content

    def test_spread_bet_shows_line(self, tmp_path):
        with patch("workflow.analyze.bets.JOURNAL_DIR", tmp_path):
            bets = [{
                "matchup": "Celtics @ Lakers",
                "bet_type": "spread",
                "pick": "Lakers",
                "line": -4.5,
                "confidence": "medium",
                "units": 1.0,
                "primary_edge": "Spread value",
                "reasoning": "Cover easily",
            }]
            write_journal_pre_game("2026-02-21", bets, [], "")
            content = (tmp_path / "2026-02-21.md").read_text()
            assert "-4.5" in content

    def test_prop_bet_shows_player_info(self, tmp_path):
        with patch("workflow.analyze.bets.JOURNAL_DIR", tmp_path):
            bets = [{
                "matchup": "Celtics @ Lakers",
                "bet_type": "player_prop",
                "pick": "over",
                "line": 25.5,
                "confidence": "medium",
                "units": 1.0,
                "primary_edge": "Usage",
                "reasoning": "High volume",
                "player_name": "LeBron James",
                "prop_type": "points",
            }]
            write_journal_pre_game("2026-02-21", bets, [], "")
            content = (tmp_path / "2026-02-21.md").read_text()
            assert "LeBron James" in content
            assert "points" in content
