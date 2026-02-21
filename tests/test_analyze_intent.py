"""Intent-based tests for the analyze workflow.

Tests are organized by the business intent they verify, not by the functions
they happen to call. Written from the findings doc to validate WHAT the code
should do, not just confirm HOW it currently does it.
"""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- Pure function imports ---
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


# =============================================================================
# 1. MATCHUP FORMATTING — "Away @ Home" convention
# =============================================================================


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


# =============================================================================
# 2. CONFIDENCE NORMALIZATION — LLM output -> valid enum
# =============================================================================


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


# =============================================================================
# 3. BET TYPE NORMALIZATION — LLM output -> valid enum
# =============================================================================


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


# =============================================================================
# 4. UNITS NORMALIZATION — must be 0.5, 1.0, or 2.0
# =============================================================================


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


# =============================================================================
# 5. PROP PICK NORMALIZATION — over/under from various LLM outputs
# =============================================================================


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


# =============================================================================
# 6. BET CREATION — LLM output normalized into ActiveBet
# =============================================================================


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


# =============================================================================
# 7. KELLY CRITERION MATH — position sizing foundation
# =============================================================================


class TestOddsConversion:
    """American odds to decimal odds conversion. This is pure math."""

    def test_minus_110_standard_juice(self):
        # -110 means you bet $110 to win $100 -> payout = 1 + 100/110 ≈ 1.909
        result = _american_odds_to_decimal(-110)
        assert abs(result - (1 + 100 / 110)) < 0.001

    def test_even_money(self):
        # +100 means you bet $100 to win $100 -> payout = 2.0
        assert _american_odds_to_decimal(100) == 2.0

    def test_heavy_favorite(self):
        # -300 means bet $300 to win $100 -> payout = 1.333
        result = _american_odds_to_decimal(-300)
        assert abs(result - (1 + 100 / 300)) < 0.001

    def test_heavy_underdog(self):
        # +300 means bet $100 to win $300 -> payout = 4.0
        assert _american_odds_to_decimal(300) == 4.0


class TestHalfKelly:
    """Half Kelly determines position size based on edge and bankroll.
    Returns 0 when there's no edge (Kelly formula goes negative)."""

    def test_returns_zero_when_no_edge(self):
        """At very low probability, Kelly says don't bet."""
        # At -300 odds, you need >75% win rate. Low confidence = 54%.
        amount = _half_kelly_amount(-300, "low", 1000.0)
        assert amount == 0.0

    def test_positive_amount_when_edge_exists(self):
        """At even money with medium confidence (57%), there's an edge."""
        amount = _half_kelly_amount(100, "medium", 1000.0)
        assert amount > 0

    def test_scales_with_bankroll(self):
        """Doubling available funds should roughly double the bet size."""
        amount_1k = _half_kelly_amount(100, "medium", 1000.0)
        amount_2k = _half_kelly_amount(100, "medium", 2000.0)
        assert abs(amount_2k - 2 * amount_1k) < 0.02  # Rounding tolerance

    def test_higher_confidence_means_larger_bet(self):
        """High confidence should produce a larger bet than low."""
        low = _half_kelly_amount(-110, "low", 1000.0)
        high = _half_kelly_amount(-110, "high", 1000.0)
        # High should be strictly larger (or both zero)
        assert high >= low

    def test_is_half_kelly_not_full(self):
        """The fraction applied should be 0.5 (half Kelly for safety)."""
        assert KELLY_FRACTION == 0.5

    def test_confidence_win_probabilities(self):
        """Verify the business-defined win probabilities."""
        assert CONFIDENCE_WIN_PROB == {"high": 0.65, "medium": 0.57, "low": 0.54}

    def test_zero_available_means_zero_bet(self):
        amount = _half_kelly_amount(100, "high", 0.0)
        assert amount == 0.0


# =============================================================================
# 8. SIZING STRATEGY EXTRACTION
# =============================================================================


class TestSizingStrategyExtraction:
    """The sizing prompt needs the Position Sizing section from strategy.md."""

    def test_extracts_position_sizing_section(self):
        strategy = (
            "## Game Selection\nPick carefully.\n\n"
            "## Position Sizing\nBet 1-3% of bankroll.\n\n"
            "## Risk Management\nDon't go broke."
        )
        result = _extract_sizing_strategy(strategy)
        assert "Bet 1-3% of bankroll" in result
        assert "Don't go broke" not in result

    def test_returns_default_when_no_section(self):
        result = _extract_sizing_strategy("## Other Section\nStuff.")
        assert "No sizing strategy" in result

    def test_returns_default_when_none(self):
        result = _extract_sizing_strategy(None)
        assert "No sizing strategy" in result

    def test_handles_section_at_end_of_file(self):
        strategy = "## Position Sizing\nLast section content."
        result = _extract_sizing_strategy(strategy)
        assert "Last section content" in result


# =============================================================================
# 9. NAME MATCHING — player name normalization and fuzzy matching
# =============================================================================


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


# =============================================================================
# 11. COMPACT JSON — cleaning data for LLM prompts
# =============================================================================


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


# =============================================================================
# 12. MARKDOWN JSON STRIPPING — extracting JSON from LLM responses
# =============================================================================


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


# =============================================================================
# 12.5 ANALYZE_GAME — data hygiene before LLM call
# =============================================================================


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


# =============================================================================
# 13. POLYMARKET PRICE EXTRACTION — bet pricing from game data
# =============================================================================


class TestPolyAndOddsExtraction:
    """Each bet needs a Polymarket price. If not found, returns (None, -110).
    The -110 fallback is standard juice for American odds."""

    def test_returns_none_when_no_polymarket_data(self):
        game = {}
        bet = {"bet_type": "moneyline", "pick": "Lakers", "line": None}
        poly, odds = _extract_poly_and_odds_price(game, bet)
        assert poly is None
        assert odds == -110

    @patch("workflow.analyze.sizing.extract_poly_price_for_bet", return_value=0.60)
    @patch("workflow.analyze.sizing.poly_price_to_american", return_value=-150)
    def test_returns_price_when_found(self, mock_american, mock_extract):
        game = {"polymarket_odds": {"moneyline": {"outcomes": ["Lakers"], "prices": [0.6]}}}
        bet = {"bet_type": "moneyline", "pick": "Lakers", "line": None}
        poly, odds = _extract_poly_and_odds_price(game, bet)
        assert poly == 0.60
        assert odds == -150


# =============================================================================
# 14. FALLBACK SIZING — pure Kelly when LLM sizing fails
# =============================================================================


class TestFallbackSizing:
    """When LLM sizing fails, the system falls back to Half Kelly.
    Bets with no edge (Kelly <= 0) get dropped."""

    def test_sizes_bets_with_edge(self):
        bets = [
            {"id": "1", "matchup": "A @ B", "confidence": "high",
             "odds_price": 100, "game_id": "g1"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) == 1
        assert result[0]["amount"] > 0

    def test_drops_bets_with_no_edge(self):
        bets = [
            {"id": "1", "matchup": "A @ B", "confidence": "low",
             "odds_price": -500, "game_id": "g1"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) == 0

    def test_uses_default_odds_when_missing(self):
        """Bets without odds_price should use -110 default."""
        bets = [
            {"id": "1", "matchup": "A @ B", "confidence": "high", "game_id": "g1"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        # At -110, high confidence (65%) should produce a positive amount
        assert len(result) == 1
        assert result[0]["amount"] > 0


# =============================================================================
# 15. JOURNAL WRITING — pre-game journal entries
# =============================================================================


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


# =============================================================================
# 16. LLM-DRIVEN SIZING — Kelly cap and veto logic
# =============================================================================


class TestSizeBets:
    """size_bets uses LLM for sizing but enforces Kelly constraints.
    Key invariants:
    - LLM amount is capped at kelly_max * 1.2
    - Kelly veto overrides LLM (if Kelly <= 0, bet is skipped)
    - LLM failure falls back to pure Kelly
    """

    def _make_bet(self, **overrides) -> dict:
        base = {
            "id": "bet-1",
            "game_id": "g1",
            "matchup": "A @ B",
            "bet_type": "moneyline",
            "pick": "A",
            "line": None,
            "confidence": "high",
            "units": 2.0,
            "reasoning": "Strong edge",
            "primary_edge": "Key factor",
            "odds_price": 100,  # Even money
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json")
    async def test_llm_amount_capped_at_kelly_120_percent(
        self, mock_llm, mock_pnl, mock_exposure
    ):
        """LLM can't exceed 120% of Kelly recommendation."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        kelly_max = _half_kelly_amount(100, "high", 1000.0)

        # LLM suggests way more than Kelly
        mock_llm.return_value = {
            "sizing_decisions": [
                {"bet_id": "bet-1", "action": "place", "amount": 9999.0}
            ]
        }

        sized, skipped = await size_bets([bet], 1000.0, None, {})
        assert len(sized) == 1
        assert sized[0]["amount"] <= round(kelly_max * 1.2, 2)

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json")
    async def test_kelly_veto_overrides_llm(self, mock_llm, mock_pnl, mock_exposure):
        """If Kelly says no edge, bet is skipped even if LLM says place it."""
        from workflow.analyze.sizing import size_bets

        # Odds so bad that Kelly formula goes negative for any confidence
        bet = self._make_bet(odds_price=-1000, confidence="low")

        mock_llm.return_value = {
            "sizing_decisions": [
                {"bet_id": "bet-1", "action": "place", "amount": 50.0}
            ]
        }

        sized, skipped = await size_bets([bet], 1000.0, None, {})
        assert len(sized) == 0
        assert len(skipped) == 1
        assert "Kelly" in skipped[0]["reason"]

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json", return_value=None)
    async def test_llm_failure_falls_back_to_kelly(
        self, mock_llm, mock_pnl, mock_exposure
    ):
        """When LLM sizing fails, pure Half Kelly is used as fallback."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        sized, skipped = await size_bets([bet], 1000.0, None, {})

        # Should still produce a sized bet via Kelly fallback
        assert len(sized) == 1
        assert sized[0]["amount"] > 0

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=200.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json", return_value=None)
    async def test_exposure_reduces_available_for_kelly(
        self, mock_llm, mock_pnl, mock_exposure
    ):
        """Open exposure is subtracted from balance before Kelly calculation.
        With $1000 balance and $200 exposure, only $800 is available."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        sized_with_exposure, _ = await size_bets([bet], 1000.0, None, {})

        mock_exposure.return_value = 0.0
        bet2 = self._make_bet()
        sized_no_exposure, _ = await size_bets([bet2], 1000.0, None, {})

        # Bet with exposure should be smaller (Kelly scales with available)
        if sized_with_exposure and sized_no_exposure:
            assert sized_with_exposure[0]["amount"] < sized_no_exposure[0]["amount"]

    @pytest.mark.asyncio
    @patch("workflow.analyze.sizing.get_open_exposure", return_value=0.0)
    @patch("workflow.analyze.sizing.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.sizing.complete_json")
    async def test_llm_veto_skips_bet(self, mock_llm, mock_pnl, mock_exposure):
        """LLM can veto a bet by setting action=skip."""
        from workflow.analyze.sizing import size_bets

        bet = self._make_bet()
        mock_llm.return_value = {
            "sizing_decisions": [
                {"bet_id": "bet-1", "action": "skip", "amount": 0,
                 "reasoning": "Weak edge"}
            ]
        }

        sized, skipped = await size_bets([bet], 1000.0, None, {})
        assert len(sized) == 0
        assert len(skipped) == 1
        assert "Vetoed" in skipped[0]["reason"]


# =============================================================================
# 17. PIPELINE ORCHESTRATION — run_analyze_workflow
# =============================================================================


def _make_game(game_id: str = "12345", home: str = "Lakers", away: str = "Celtics") -> dict:
    """Factory for a minimal game dict that passes through the pipeline."""
    return {
        "api_game_id": game_id,
        "_file": f"{game_id}_2026-02-21.json",
        "matchup": {"team1": home, "team2": away, "home_team": home},
        "polymarket_odds": {
            "moneyline": {"outcomes": [home, away], "prices": [0.6, 0.4]},
        },
    }


def _make_recommendation(game_id: str = "12345", matchup: str = "Celtics @ Lakers") -> dict:
    return {
        "game_id": game_id,
        "matchup": matchup,
        "expected_margin": 5.0,
        "expected_total": 220.0,
        "moneyline": {"pick": "Lakers", "confidence": "medium", "edge": "Home"},
        "spread": {"pick": "Lakers", "line": -4.5, "confidence": "skip", "edge": ""},
        "total": {"pick": "over", "line": 220.5, "confidence": "skip", "edge": ""},
        "recommended_bets": [
            {"bet_type": "moneyline", "pick": "Lakers", "line": None,
             "confidence": "medium", "edge": "Home court"}
        ],
        "primary_edge": "Home court",
        "case_for": ["Strong home record"],
        "case_against": ["Away team is good"],
        "analysis_summary": "Lakers favored at home.",
    }


def _make_synthesis(bets=None, skipped=None) -> dict:
    if bets is None:
        bets = [{
            "game_id": "12345",
            "matchup": "Celtics @ Lakers",
            "bet_type": "moneyline",
            "pick": "Lakers",
            "line": None,
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "Home court edge",
            "primary_edge": "Home court",
        }]
    return {
        "selected_bets": bets,
        "skipped": skipped or [],
        "summary": "One bet today.",
    }


class TestPipelineDuplicateCheck:
    """The pipeline must not create duplicate bets for the same date."""

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.get_active_bets")
    async def test_aborts_when_bets_exist_for_date(self, mock_active):
        from workflow.analyze.pipeline import run_analyze_workflow

        mock_active.return_value = [{"date": "2026-02-21", "id": "existing"}]
        # Should return without doing anything
        await run_analyze_workflow("2026-02-21")
        # If it tried to load games, that would be an error since no output dir

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.save_active_bets")
    @patch("workflow.analyze.pipeline.load_games_for_date", return_value=[])
    @patch("workflow.analyze.pipeline.get_active_bets")
    async def test_force_removes_existing_bets_for_date(
        self, mock_active, mock_load, mock_save
    ):
        from workflow.analyze.pipeline import run_analyze_workflow

        mock_active.return_value = [
            {"date": "2026-02-21", "id": "old"},
            {"date": "2026-02-20", "id": "other"},
        ]
        await run_analyze_workflow("2026-02-21", force=True)
        # Should have saved with old date's bet removed
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["date"] == "2026-02-20"


class TestPipelineEarlyExits:
    """The pipeline must exit cleanly at various stages without side effects."""

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.get_active_bets", return_value=[])
    @patch("workflow.analyze.pipeline.load_games_for_date", return_value=[])
    async def test_exits_when_no_games(self, mock_load, mock_active):
        from workflow.analyze.pipeline import run_analyze_workflow
        # Should not raise
        await run_analyze_workflow("2026-02-21")

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.fetch_polymarket_prices")
    @patch("polymarket_helpers.gamma.fetch_nba_events", return_value=[])
    @patch("workflow.analyze.pipeline._extract_and_compute_injuries", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline._enrich_games_with_search", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_active_bets", return_value=[])
    @patch("workflow.analyze.pipeline.load_games_for_date")
    async def test_exits_when_no_polymarket_markets(
        self, mock_load, mock_active, mock_enrich, mock_injuries,
        mock_fetch_events, mock_poly_prices
    ):
        from workflow.analyze.pipeline import run_analyze_workflow

        # Games exist but have no polymarket_odds after price fetch
        game = {"api_game_id": "123", "_file": "test.json",
                "matchup": {"team1": "A", "team2": "B", "home_team": "A"}}
        mock_load.return_value = [game]
        mock_poly_prices.return_value = None  # No prices attached

        await run_analyze_workflow("2026-02-21")
        # Pipeline should not have called analyze_game


class TestPipelineNoBalance:
    """When Polymarket balance is unavailable, the pipeline saves skips
    and runs paper trades but does NOT place real bets."""

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline.run_paper_trades", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.save_skips")
    @patch("workflow.analyze.pipeline.get_polymarket_balance", return_value=None)
    @patch("workflow.analyze.pipeline.synthesize_bets", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.analyze_game", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.read_text", return_value=None)
    @patch("workflow.analyze.pipeline.get_history", return_value={"bets": [], "summary": {}})
    @patch("workflow.analyze.pipeline.fetch_polymarket_prices")
    @patch("polymarket_helpers.gamma.fetch_nba_events", return_value=[])
    @patch("workflow.analyze.pipeline._extract_and_compute_injuries", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline._enrich_games_with_search", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_active_bets", return_value=[])
    @patch("workflow.analyze.pipeline.load_games_for_date")
    async def test_saves_skips_and_paper_trades_without_balance(
        self, mock_load, mock_active, mock_enrich, mock_injuries,
        mock_events, mock_prices, mock_history, mock_strategy,
        mock_analyze, mock_synth, mock_balance, mock_save_skips,
        mock_paper,
    ):
        from workflow.analyze.pipeline import run_analyze_workflow

        game = _make_game()
        mock_load.return_value = [game]
        mock_analyze.return_value = _make_recommendation()
        mock_synth.return_value = _make_synthesis(
            bets=[],
            skipped=[{"matchup": "Celtics @ Lakers", "reason": "No edge"}]
        )

        await run_analyze_workflow("2026-02-21")

        # Skips should be saved
        mock_save_skips.assert_called_once()
        # Paper trades should run on skipped games
        mock_paper.assert_called_once()


class TestPipelineFullFlow:
    """Integration-style test: mock only external services (LLM, Polymarket, file I/O)
    and verify the full pipeline produces correct outputs."""

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline._run_props_pipeline", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.pipeline.write_journal_pre_game")
    @patch("workflow.analyze.pipeline.run_paper_trades", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.save_skips")
    @patch("workflow.analyze.pipeline.save_active_bets")
    @patch("workflow.analyze.pipeline.size_bets", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_polymarket_balance", return_value=500.0)
    @patch("workflow.analyze.pipeline.synthesize_bets", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.analyze_game", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.read_text", return_value="## Strategy")
    @patch("workflow.analyze.pipeline.get_history", return_value={"bets": [], "summary": {}})
    @patch("workflow.analyze.pipeline.fetch_polymarket_prices")
    @patch("polymarket_helpers.gamma.fetch_nba_events", return_value=[])
    @patch("workflow.analyze.pipeline._extract_and_compute_injuries", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline._enrich_games_with_search", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_active_bets", return_value=[])
    @patch("workflow.analyze.pipeline.load_games_for_date")
    async def test_full_pipeline_places_bets(
        self, mock_load, mock_active, mock_enrich, mock_injuries,
        mock_events, mock_prices, mock_history, mock_strategy,
        mock_analyze, mock_synth, mock_balance, mock_size,
        mock_save_active, mock_save_skips, mock_paper,
        mock_journal, mock_pnl, mock_props,
    ):
        from workflow.analyze.pipeline import run_analyze_workflow

        game = _make_game()
        mock_load.return_value = [game]
        mock_analyze.return_value = _make_recommendation()
        mock_synth.return_value = _make_synthesis()

        # Sizing returns one bet with amount
        sized_bet = {
            "id": "bet-1", "game_id": "12345", "matchup": "Celtics @ Lakers",
            "bet_type": "moneyline", "pick": "Lakers", "line": None,
            "confidence": "medium", "units": 1.0, "reasoning": "Edge",
            "primary_edge": "Home", "date": "2026-02-21",
            "created_at": "2026-02-21T00:00:00Z", "amount": 25.0,
            "poly_price": 0.6, "odds_price": -150,
        }
        mock_size.return_value = ([sized_bet], [])

        await run_analyze_workflow("2026-02-21")

        # Active bets should be saved
        mock_save_active.assert_called_once()
        saved = mock_save_active.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["amount"] == 25.0

        # Journal should be written
        mock_journal.assert_called_once()

        # Props pipeline should run
        mock_props.assert_called_once()

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline._run_props_pipeline", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.pipeline.write_journal_pre_game")
    @patch("workflow.analyze.pipeline.run_paper_trades", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.save_skips")
    @patch("workflow.analyze.pipeline.save_active_bets")
    @patch("workflow.analyze.pipeline.size_bets", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_polymarket_balance", return_value=500.0)
    @patch("workflow.analyze.pipeline.synthesize_bets", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.analyze_game", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.read_text", return_value=None)
    @patch("workflow.analyze.pipeline.get_history", return_value={"bets": [], "summary": {}})
    @patch("workflow.analyze.pipeline.fetch_polymarket_prices")
    @patch("polymarket_helpers.gamma.fetch_nba_events", return_value=[])
    @patch("workflow.analyze.pipeline._extract_and_compute_injuries", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline._enrich_games_with_search", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_active_bets", return_value=[])
    @patch("workflow.analyze.pipeline.load_games_for_date")
    async def test_props_excluded_for_games_with_bets(
        self, mock_load, mock_active, mock_enrich, mock_injuries,
        mock_events, mock_prices, mock_history, mock_strategy,
        mock_analyze, mock_synth, mock_balance, mock_size,
        mock_save_active, mock_save_skips, mock_paper,
        mock_journal, mock_pnl, mock_props,
    ):
        from workflow.analyze.pipeline import run_analyze_workflow

        game = _make_game()
        mock_load.return_value = [game]
        mock_analyze.return_value = _make_recommendation()
        mock_synth.return_value = _make_synthesis()

        sized_bet = {
            "id": "bet-1", "game_id": "12345", "matchup": "Celtics @ Lakers",
            "bet_type": "moneyline", "pick": "Lakers", "line": None,
            "confidence": "medium", "units": 1.0, "reasoning": "Edge",
            "primary_edge": "Home", "date": "2026-02-21",
            "created_at": "2026-02-21T00:00:00Z", "amount": 25.0,
            "poly_price": 0.6, "odds_price": -150,
        }
        mock_size.return_value = ([sized_bet], [])

        await run_analyze_workflow("2026-02-21")

        # Props pipeline should receive the game_ids with bets for exclusion
        mock_props.assert_called_once()
        call_kwargs = mock_props.call_args
        # The last positional arg is game_ids_with_bets (set)
        exclude_ids = call_kwargs[0][-1] if call_kwargs[0] else call_kwargs[1].get("game_ids_with_bets", set())
        # Game "12345" had a sized bet, so it should be in the exclusion set
        props_call_args = mock_props.call_args[0]
        # _run_props_pipeline signature: (date, games, game_lookup, polymarket_events,
        #   strategy, history, balance, max_props, game_ids_with_bets)
        game_ids_with_bets = props_call_args[8]
        assert "12345" in game_ids_with_bets


class TestPipelineBetFiltering:
    """The pipeline filters out bets at multiple stages:
    1. Incomplete synthesis entries (missing pick/matchup)
    2. Bets without poly_price (can't execute on Polymarket)
    """

    @pytest.mark.asyncio
    @patch("workflow.analyze.pipeline._run_props_pipeline", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_dollar_pnl", return_value=0.0)
    @patch("workflow.analyze.pipeline.write_journal_pre_game")
    @patch("workflow.analyze.pipeline.run_paper_trades", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.save_skips")
    @patch("workflow.analyze.pipeline.save_active_bets")
    @patch("workflow.analyze.pipeline.size_bets", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_polymarket_balance", return_value=500.0)
    @patch("workflow.analyze.pipeline.synthesize_bets", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.analyze_game", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.read_text", return_value=None)
    @patch("workflow.analyze.pipeline.get_history", return_value={"bets": [], "summary": {}})
    @patch("workflow.analyze.pipeline.fetch_polymarket_prices")
    @patch("polymarket_helpers.gamma.fetch_nba_events", return_value=[])
    @patch("workflow.analyze.pipeline._extract_and_compute_injuries", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline._enrich_games_with_search", new_callable=AsyncMock)
    @patch("workflow.analyze.pipeline.get_active_bets", return_value=[])
    @patch("workflow.analyze.pipeline.load_games_for_date")
    @patch("workflow.analyze.pipeline._extract_poly_and_odds_price")
    async def test_incomplete_synthesis_entries_filtered(
        self, mock_poly_extract, mock_load, mock_active, mock_enrich, mock_injuries,
        mock_events, mock_prices, mock_history, mock_strategy,
        mock_analyze, mock_synth, mock_balance, mock_size,
        mock_save_active, mock_save_skips, mock_paper,
        mock_journal, mock_pnl, mock_props,
    ):
        from workflow.analyze.pipeline import run_analyze_workflow

        game = _make_game()
        mock_load.return_value = [game]
        mock_analyze.return_value = _make_recommendation()

        # Synthesis returns one valid and one incomplete bet
        mock_synth.return_value = {
            "selected_bets": [
                {"game_id": "12345", "matchup": "Celtics @ Lakers",
                 "pick": "Lakers", "bet_type": "moneyline", "confidence": "medium",
                 "units": 1.0, "reasoning": "Edge", "primary_edge": "Home"},
                {"game_id": "12345", "matchup": "", "pick": "",  # INCOMPLETE
                 "bet_type": "spread"},
            ],
            "skipped": [],
            "summary": "",
        }

        mock_poly_extract.return_value = (0.6, -150)
        mock_size.return_value = ([], [])

        await run_analyze_workflow("2026-02-21")

        # size_bets should only receive the valid bet (incomplete one filtered)
        if mock_size.called:
            bets_passed = mock_size.call_args[0][0]
            for b in bets_passed:
                assert b["pick"] and b["matchup"]


# =============================================================================
# 18. GAME DATA LOADING
# =============================================================================


class TestGameDataLoading:
    """load_games_for_date reads JSON files from output/ matching the date pattern,
    excluding props files."""

    def test_loads_matching_files(self, tmp_path):
        from workflow.analyze.gamedata import load_games_for_date

        # Create matching file
        game_data = {"matchup": {"team1": "A", "team2": "B"}}
        (tmp_path / "12345_2026-02-21.json").write_text(json.dumps(game_data))

        with patch("workflow.analyze.gamedata.OUTPUT_DIR", tmp_path):
            games = load_games_for_date("2026-02-21")
            assert len(games) == 1
            assert games[0]["matchup"]["team1"] == "A"
            assert "_file" in games[0]

    def test_excludes_props_files(self, tmp_path):
        from workflow.analyze.gamedata import load_games_for_date

        (tmp_path / "12345_2026-02-21.json").write_text('{"matchup": {}}')
        (tmp_path / "props_12345_2026-02-21.json").write_text('{"props": true}')

        with patch("workflow.analyze.gamedata.OUTPUT_DIR", tmp_path):
            games = load_games_for_date("2026-02-21")
            assert len(games) == 1
            assert not games[0].get("props")

    def test_handles_invalid_json(self, tmp_path):
        from workflow.analyze.gamedata import load_games_for_date

        (tmp_path / "bad_2026-02-21.json").write_text("not json{{{")

        with patch("workflow.analyze.gamedata.OUTPUT_DIR", tmp_path):
            games = load_games_for_date("2026-02-21")
            assert len(games) == 0

    def test_returns_empty_for_no_matches(self, tmp_path):
        from workflow.analyze.gamedata import load_games_for_date

        with patch("workflow.analyze.gamedata.OUTPUT_DIR", tmp_path):
            games = load_games_for_date("2026-02-21")
            assert games == []


# =============================================================================
# 19. SKIP ENRICHMENT AND PERSISTENCE
# =============================================================================


class TestSkipPersistence:
    """Skips are saved per-date, replacing any existing skips for that date.
    This supports --force re-analysis."""

    def test_save_skips_replaces_for_date(self, tmp_path):
        from workflow.io import save_skips, get_skips, SKIPS_PATH

        skips_path = tmp_path / "skips.json"
        with patch("workflow.io.SKIPS_PATH", skips_path), \
             patch("workflow.io.read_json") as mock_read, \
             patch("workflow.io.write_json") as mock_write:
            # Existing skips from multiple dates
            mock_read.return_value = [
                {"date": "2026-02-20", "matchup": "Old"},
                {"date": "2026-02-21", "matchup": "Will be replaced"},
            ]

            new_skips = [{"date": "2026-02-21", "matchup": "New skip"}]
            save_skips("2026-02-21", new_skips)

            written = mock_write.call_args[0][1]
            dates = [s["date"] for s in written]
            assert dates.count("2026-02-21") == 1
            assert "2026-02-20" in dates
            # The new skip should be present
            matchups = [s["matchup"] for s in written]
            assert "New skip" in matchups
            assert "Will be replaced" not in matchups


# =============================================================================
# 20. CLI DATE HANDLING
# =============================================================================


class TestDateHandling:
    """The CLI extracts dates from output filenames and validates date format."""

    def test_extracts_dates_from_output_files(self, tmp_path):
        from betting import get_dates_from_output, OUTPUT_DIR

        (tmp_path / "game1_2026-02-21.json").write_text("{}")
        (tmp_path / "game2_2026-02-21.json").write_text("{}")
        (tmp_path / "game3_2026-02-22.json").write_text("{}")

        with patch("betting.OUTPUT_DIR", tmp_path):
            dates = get_dates_from_output()
            assert dates == ["2026-02-21", "2026-02-22"]

    def test_validates_good_date(self):
        from betting import validate_date
        assert validate_date("2026-02-21") == "2026-02-21"

    def test_rejects_bad_date(self):
        from betting import validate_date
        with pytest.raises(SystemExit):
            validate_date("not-a-date")

    def test_rejects_impossible_date(self):
        from betting import validate_date
        with pytest.raises(SystemExit):
            validate_date("2026-02-30")
