import json
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from betting.analyze.bets import (
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


class TestCreateActiveBet:
    """create_active_bet converts raw LLM synthesis output into a clean ActiveBet.
    It must NEVER fail — all fields have defaults. It normalizes confidence,
    bet_type, and units."""

    def _make_selected(self, **overrides) -> dict:
        base = {
            "game_id": "12345",
            "matchup": "Celtics @ Lakers",
            "bet_type": "moneyline",
            "pick": "Lakers",
            "line": None,
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "Strong home team",
            "primary_edge": "Home court",
        }
        base.update(overrides)
        return base

    def test_produces_valid_active_bet(self):
        bet = create_active_bet(self._make_selected(), "2026-02-21")
        assert bet["date"] == "2026-02-21"
        assert bet["pick"] == "Lakers"
        assert bet["matchup"] == "Celtics @ Lakers"
        assert bet["confidence"] == "medium"
        assert bet["units"] == 1.0
        assert bet["bet_type"] == "moneyline"
        # Must have UUID
        uuid.UUID(bet["id"])  # Raises if invalid
        # Must have ISO timestamp
        assert "T" in bet["created_at"]

    def test_normalizes_bad_confidence(self):
        bet = create_active_bet(self._make_selected(confidence="very high"), "2026-02-21")
        assert bet["confidence"] in VALID_CONFIDENCE

    def test_normalizes_bad_bet_type(self):
        bet = create_active_bet(self._make_selected(bet_type="SPREAD_BET"), "2026-02-21")
        assert bet["bet_type"] in VALID_BET_TYPES

    def test_normalizes_bad_units(self):
        bet = create_active_bet(self._make_selected(units=99.0, confidence="high"), "2026-02-21")
        assert bet["units"] == CONFIDENCE_TO_UNITS["high"]

    def test_handles_completely_empty_input(self):
        """Even an empty dict should produce a valid bet, not crash."""
        bet = create_active_bet({}, "2026-02-21")
        assert bet["date"] == "2026-02-21"
        assert bet["pick"] == "Unknown"
        assert bet["confidence"] == "low"

    def test_each_bet_gets_unique_id(self):
        sel = self._make_selected()
        bet1 = create_active_bet(sel, "2026-02-21")
        bet2 = create_active_bet(sel, "2026-02-21")
        assert bet1["id"] != bet2["id"]


class TestCreatePropBet:
    """create_prop_bet can return None — it validates prop_type and pick.
    This is the safety gate for prop bets."""

    def _make_prop(self, **overrides) -> dict:
        base = {
            "game_id": "12345",
            "matchup": "Celtics @ Lakers",
            "prop_type": "points",
            "player_name": "LeBron James",
            "line": 25.5,
            "pick": "over",
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "High usage",
            "primary_edge": "Matchup advantage",
        }
        base.update(overrides)
        return base

    def test_valid_prop_creates_bet(self):
        bet = create_prop_bet(self._make_prop(), "2026-02-21")
        assert bet is not None
        assert bet["bet_type"] == "player_prop"
        assert bet["player_name"] == "LeBron James"
        assert bet["prop_type"] == "points"
        assert bet["pick"] == "over"

    def test_unsupported_prop_type_returns_none(self):
        bet = create_prop_bet(self._make_prop(prop_type="steals"), "2026-02-21")
        assert bet is None

    def test_unrecognizable_pick_returns_none(self):
        bet = create_prop_bet(self._make_prop(pick="maybe"), "2026-02-21")
        assert bet is None

    def test_valid_prop_types(self):
        """Only points, rebounds, assists are supported."""
        for pt in VALID_PROP_TYPES:
            bet = create_prop_bet(self._make_prop(prop_type=pt), "2026-02-21")
            assert bet is not None

    def test_normalizes_pick_variants(self):
        """'yes' should become 'over', 'no' should become 'under'."""
        bet = create_prop_bet(self._make_prop(pick="yes"), "2026-02-21")
        assert bet is not None
        assert bet["pick"] == "over"
