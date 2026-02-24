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
from workflow.analyze.sizing import (
    CONFIDENCE_WIN_PROB,
    KELLY_FRACTION,
    _american_odds_to_decimal,
    _extract_poly_and_odds_price,
    _extract_sizing_strategy,
    _fallback_sizing,
    _half_kelly_amount,
)
from workflow.names import names_match, normalize_name
from workflow.prompts import compact_json
from workflow.llm import _strip_markdown_json


class TestMatchupFormatting:
    """The system displays matchups as 'Away @ Home'. This is the universal
    convention in sports — the away team is listed first."""

    def test_away_at_home_when_team1_is_home(self):
        matchup = {"team1": "Lakers", "team2": "Celtics", "home_team": "Lakers"}
        assert format_matchup_string(matchup) == "Celtics @ Lakers"

    def test_away_at_home_when_team2_is_home(self):
        matchup = {"team1": "Celtics", "team2": "Lakers", "home_team": "Lakers"}
        assert format_matchup_string(matchup) == "Celtics @ Lakers"

    def test_fallback_when_home_team_missing(self):
        """When home_team doesn't match either team, defaults to 'team1 @ team2'."""
        matchup = {"team1": "Celtics", "team2": "Lakers", "home_team": ""}
        result = format_matchup_string(matchup)
        assert "Celtics" in result and "Lakers" in result

    def test_empty_matchup_doesnt_crash(self):
        """Gracefully handles missing fields."""
        result = format_matchup_string({})
        assert isinstance(result, str)


class TestGameIdExtraction:
    """Game IDs are derived from filenames by stripping .json."""

    def test_strips_json_extension(self):
        assert extract_game_id("12345_2026-02-21.json") == "12345_2026-02-21"

    def test_already_no_extension(self):
        assert extract_game_id("12345") == "12345"


class TestConfidenceNormalization:
    """The LLM might return any string for confidence. The system must normalize
    to one of: low, medium, high. Unknown values default to low (conservative)."""

    def test_valid_values_pass_through(self):
        for val in ("low", "medium", "high"):
            assert _normalize_confidence(val) == val

    def test_strong_maps_to_high(self):
        assert _normalize_confidence("strong") == "high"

    def test_moderate_maps_to_medium(self):
        assert _normalize_confidence("moderate") == "medium"

    def test_med_substring_maps_to_medium(self):
        assert _normalize_confidence("med confidence") == "medium"

    def test_unknown_defaults_to_low(self):
        assert _normalize_confidence("garbage") == "low"
        assert _normalize_confidence("") == "low"

    def test_case_insensitive(self):
        assert _normalize_confidence("HIGH") == "high"
        assert _normalize_confidence("Medium") == "medium"


class TestBetTypeNormalization:
    """Bet types must be one of: moneyline, spread, total, player_prop.
    Unknown types default to moneyline (safest default)."""

    def test_valid_types_pass_through(self):
        for bt in VALID_BET_TYPES:
            assert _normalize_bet_type(bt) == bt

    def test_spread_substring_recognized(self):
        assert _normalize_bet_type("point_spread") == "spread"

    def test_over_under_recognized_as_total(self):
        assert _normalize_bet_type("over/under") == "total"
        assert _normalize_bet_type("under 224.5") == "total"

    def test_unknown_defaults_to_moneyline(self):
        assert _normalize_bet_type("garbage") == "moneyline"
        assert _normalize_bet_type("") == "moneyline"


class TestUnitsNormalization:
    """Units represent position sizing tiers. Only 0.5, 1.0, 2.0 are valid.
    Invalid values fall back to confidence-based defaults."""

    def test_valid_units_pass_through(self):
        for u in (0.5, 1.0, 2.0):
            assert _normalize_units(u, "low") == u

    def test_invalid_units_use_confidence_mapping(self):
        assert _normalize_units(1.5, "high") == CONFIDENCE_TO_UNITS["high"]
        assert _normalize_units(0.0, "medium") == CONFIDENCE_TO_UNITS["medium"]
        assert _normalize_units(3.0, "low") == CONFIDENCE_TO_UNITS["low"]

    def test_confidence_to_units_mapping_is_correct(self):
        """Verify the business rule: high=2, medium=1, low=0.5."""
        assert CONFIDENCE_TO_UNITS == {"low": 0.5, "medium": 1.0, "high": 2.0}


class TestPropPickNormalization:
    """Player prop picks must be 'over' or 'under'. The LLM might say
    'yes', 'o', 'no', 'u', etc. Unrecognizable values return None."""

    def test_over_variants(self):
        for val in ("over", "yes", "o", "Over", "YES"):
            assert _normalize_prop_pick(val) == "over"

    def test_under_variants(self):
        for val in ("under", "no", "u", "Under", "NO"):
            assert _normalize_prop_pick(val) == "under"

    def test_unrecognizable_returns_none(self):
        assert _normalize_prop_pick("maybe") is None
        assert _normalize_prop_pick("") is None
        assert _normalize_prop_pick("higher") is None
