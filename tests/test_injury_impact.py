"""Tests for injury impact extraction and computation."""

from unittest.mock import AsyncMock, patch

import pytest

from workflow.analyze.injuries import (
    INJURY_REPLACEMENT_FACTOR,
    _extract_injuries_from_search,
    compute_injury_impact,
)
from workflow.names import names_match as _names_match, normalize_name as _normalize_name


class TestNormalizeName:
    """Tests for _normalize_name."""

    def test_basic(self):
        assert _normalize_name("Ja Morant") == "ja morant"

    def test_strips_jr(self):
        assert _normalize_name("Gary Trent Jr.") == "gary trent"

    def test_strips_iii(self):
        assert _normalize_name("Robert Williams III") == "robert williams"

    def test_strips_sr(self):
        assert _normalize_name("Tim Hardaway Sr.") == "tim hardaway"

    def test_removes_periods(self):
        assert _normalize_name("P.J. Washington") == "pj washington"

    def test_strips_whitespace(self):
        assert _normalize_name("  Ja Morant  ") == "ja morant"


class TestNamesMatch:
    """Tests for _names_match."""

    def test_exact_match(self):
        assert _names_match("Ja Morant", "Ja Morant")

    def test_case_insensitive(self):
        assert _names_match("ja morant", "JA MORANT")

    def test_suffix_stripping(self):
        assert _names_match("Gary Trent Jr.", "Gary Trent")

    def test_initial_matching(self):
        assert _names_match("K. Knueppel", "Kyle Knueppel")

    def test_initial_reversed(self):
        assert _names_match("Cedric Coward", "C. Coward")

    def test_pj_matching(self):
        assert _names_match("P.J. Washington", "PJ Washington")

    def test_different_players(self):
        assert not _names_match("Ja Morant", "Trae Young")

    def test_same_last_name_different_first(self):
        assert not _names_match("Marcus Morris", "Markieff Morris")

    def test_initial_different_last_name(self):
        assert not _names_match("K. Durant", "K. Thompson")


class TestComputeInjuryImpact:
    """Tests for compute_injury_impact."""

    def _rotation(self, players):
        return [{"name": p[0], "ppg": p[1], "plus_minus": 0.0, "games": 50} for p in players]

    def test_basic_impact(self):
        injuries = [
            {"team": "Team A", "player": "Star Player", "status": "Out"},
        ]
        t1_rot = self._rotation([("Star Player", 25.0), ("Role Player", 10.0)])
        t2_rot = self._rotation([("Other Star", 20.0)])

        result = compute_injury_impact(injuries, "Team A", "Team B", t1_rot, t2_rot)
        assert result is not None
        assert len(result["team1"]["out_players"]) == 1
        assert result["team1"]["out_players"][0]["name"] == "Star Player"
        assert result["team1"]["missing_ppg"] == 25.0
        assert result["team1"]["adjusted_ppg_loss"] == round(25.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        assert result["team2"]["missing_ppg"] == 0.0
        assert result["total_reduction"] == result["team1"]["adjusted_ppg_loss"]

    def test_both_teams_injured(self):
        injuries = [
            {"team": "Team A", "player": "Player A", "status": "Out"},
            {"team": "Team B", "player": "Player B", "status": "Out"},
        ]
        t1_rot = self._rotation([("Player A", 20.0)])
        t2_rot = self._rotation([("Player B", 15.0)])

        result = compute_injury_impact(injuries, "Team A", "Team B", t1_rot, t2_rot)
        assert result is not None
        t1_loss = round(20.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        t2_loss = round(15.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        assert result["total_reduction"] == round(t1_loss + t2_loss, 1)
        # missing_ppg_diff = team2_loss - team1_loss (positive = favors team1)
        assert result["missing_ppg_diff"] == round(t2_loss - t1_loss, 1)

    def test_no_injuries(self):
        result = compute_injury_impact([], "Team A", "Team B", [], [])
        assert result is None

    def test_unmatched_player(self):
        injuries = [
            {"team": "Team A", "player": "Unknown Guy", "status": "Out"},
        ]
        t1_rot = self._rotation([("Star Player", 25.0)])
        t2_rot = self._rotation([("Other Star", 20.0)])

        result = compute_injury_impact(injuries, "Team A", "Team B", t1_rot, t2_rot)
        assert result is None  # No matched players → None

    def test_missing_ppg_diff_direction(self):
        """Positive missing_ppg_diff means team2 loses more → favors team1."""
        injuries = [
            {"team": "Team A", "player": "A1", "status": "Out"},
            {"team": "Team B", "player": "B1", "status": "Out"},
        ]
        t1_rot = self._rotation([("A1", 10.0)])
        t2_rot = self._rotation([("B1", 30.0)])

        result = compute_injury_impact(injuries, "Team A", "Team B", t1_rot, t2_rot)
        assert result["missing_ppg_diff"] > 0  # Team B loses more → positive

    def test_doubtful_status_included(self):
        injuries = [
            {"team": "Team A", "player": "Star", "status": "Doubtful"},
        ]
        t1_rot = self._rotation([("Star", 22.0)])
        result = compute_injury_impact(injuries, "Team A", "Team B", t1_rot, [])
        assert result is not None
        assert result["team1"]["out_players"][0]["status"] == "Doubtful"

    def test_name_matching_with_suffix(self):
        injuries = [
            {"team": "Team A", "player": "Gary Trent Jr.", "status": "Out"},
        ]
        t1_rot = self._rotation([("Gary Trent", 15.0)])
        result = compute_injury_impact(injuries, "Team A", "Team B", t1_rot, [])
        assert result is not None
        assert result["team1"]["missing_ppg"] == 15.0


class TestExtractInjuriesFromSearch:
    """Tests for _extract_injuries_from_search."""

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        mock_result = [
            {"team": "Portland Trail Blazers", "player": "Deni Avdija", "status": "Out"},
            {"team": "Memphis Grizzlies", "player": "Ja Morant", "status": "Out"},
        ]
        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value=mock_result):
            result = await _extract_injuries_from_search(
                "some search context", "Portland Trail Blazers", "Memphis Grizzlies"
            )
        assert len(result) == 2
        assert result[0]["player"] == "Deni Avdija"

    @pytest.mark.asyncio
    async def test_filters_invalid_status(self):
        mock_result = [
            {"team": "Team A", "player": "P1", "status": "Out"},
            {"team": "Team A", "player": "P2", "status": "Questionable"},  # Should be filtered
        ]
        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value=mock_result):
            result = await _extract_injuries_from_search("ctx", "Team A", "Team B")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_handles_none_response(self):
        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value=None):
            result = await _extract_injuries_from_search("ctx", "Team A", "Team B")
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_non_list_response(self):
        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value={"error": "bad"}):
            result = await _extract_injuries_from_search("ctx", "Team A", "Team B")
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_incomplete_entries(self):
        mock_result = [
            {"team": "Team A", "player": "P1", "status": "Out"},
            {"team": "Team A", "status": "Out"},  # missing player
            {"player": "P3", "status": "Out"},  # missing team
        ]
        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value=mock_result):
            result = await _extract_injuries_from_search("ctx", "Team A", "Team B")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_uses_haiku_model(self):
        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value=[]) as mock_llm:
            await _extract_injuries_from_search("ctx", "Team A", "Team B")
            _, kwargs = mock_llm.call_args
            assert kwargs["model"] == "anthropic/claude-haiku-4.5"
            assert kwargs["temperature"] == 0.0
