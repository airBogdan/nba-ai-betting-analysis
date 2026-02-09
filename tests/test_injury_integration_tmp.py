"""Temp integration tests: injuries linked to rotation stats end-to-end."""

import copy
from unittest.mock import AsyncMock, patch

import pytest

from workflow.analyze import (
    INJURY_REPLACEMENT_FACTOR,
    _extract_and_compute_injuries,
    compute_injury_impact,
    _normalize_name,
)


def _make_game(
    team1="Boston Celtics",
    team2="Memphis Grizzlies",
    t1_rotation=None,
    t2_rotation=None,
    t1_api_injuries=None,
    t2_api_injuries=None,
    search_context=None,
    expected_total=224.5,
):
    """Build a realistic game dict matching the output/*.json structure."""
    return {
        "_file": "test_game_2026-02-09.json",
        "matchup": {"team1": team1, "team2": team2, "home_team": team1},
        "players": {
            "team1": {
                "rotation": t1_rotation or [],
                "injuries": t1_api_injuries or [],
            },
            "team2": {
                "rotation": t2_rotation or [],
                "injuries": t2_api_injuries or [],
            },
        },
        "totals_analysis": {"expected_total": expected_total},
        "search_context": search_context,
    }


def _rot(name, ppg):
    return {"name": name, "ppg": ppg, "plus_minus": 1.0, "games": 50}


# ---------------------------------------------------------------------------
# 1) compute_injury_impact links injury names to rotation stats
# ---------------------------------------------------------------------------

class TestInjuryToRotationLinking:
    """Verify that injuries are matched against the rotation and stats are pulled."""

    def test_single_star_out_links_ppg(self):
        injuries = [{"team": "Boston Celtics", "player": "Jayson Tatum", "status": "Out"}]
        t1_rot = [_rot("Jayson Tatum", 27.3), _rot("Jaylen Brown", 24.1)]
        t2_rot = [_rot("Ja Morant", 25.0)]

        result = compute_injury_impact(injuries, "Boston Celtics", "Memphis Grizzlies", t1_rot, t2_rot)
        assert result is not None
        # Matched player carries rotation ppg
        out = result["team1"]["out_players"]
        assert len(out) == 1
        assert out[0]["name"] == "Jayson Tatum"
        assert out[0]["ppg"] == 27.3
        assert result["team1"]["missing_ppg"] == 27.3

    def test_multiple_players_out_sums_ppg(self):
        injuries = [
            {"team": "Boston Celtics", "player": "Jayson Tatum", "status": "Out"},
            {"team": "Boston Celtics", "player": "Jaylen Brown", "status": "Doubtful"},
        ]
        t1_rot = [_rot("Jayson Tatum", 27.3), _rot("Jaylen Brown", 24.1), _rot("Derrick White", 15.5)]

        result = compute_injury_impact(injuries, "Boston Celtics", "Memphis Grizzlies", t1_rot, [])
        assert result is not None
        assert result["team1"]["missing_ppg"] == round(27.3 + 24.1, 1)
        assert len(result["team1"]["out_players"]) == 2

    def test_suffix_mismatch_still_links(self):
        """Search says 'Gary Trent Jr.' but rotation has 'Gary Trent'."""
        injuries = [{"team": "Memphis Grizzlies", "player": "Gary Trent Jr.", "status": "Out"}]
        t2_rot = [_rot("Gary Trent", 14.8)]

        result = compute_injury_impact(injuries, "Boston Celtics", "Memphis Grizzlies", [], t2_rot)
        assert result is not None
        assert result["team2"]["out_players"][0]["ppg"] == 14.8

    def test_initial_name_links(self):
        """Search says 'K. Knueppel' but rotation has 'Kyle Knueppel'."""
        injuries = [{"team": "Boston Celtics", "player": "K. Knueppel", "status": "Out"}]
        t1_rot = [_rot("Kyle Knueppel", 8.2)]

        result = compute_injury_impact(injuries, "Boston Celtics", "Memphis Grizzlies", t1_rot, [])
        assert result is not None
        assert result["team1"]["out_players"][0]["ppg"] == 8.2

    def test_unmatched_injury_returns_none(self):
        """Injury for a player not in rotation → no impact."""
        injuries = [{"team": "Boston Celtics", "player": "Random Benchwarmer", "status": "Out"}]
        t1_rot = [_rot("Jayson Tatum", 27.3)]

        result = compute_injury_impact(injuries, "Boston Celtics", "Memphis Grizzlies", t1_rot, [])
        assert result is None

    def test_replacement_factor_applied(self):
        injuries = [{"team": "Boston Celtics", "player": "Jayson Tatum", "status": "Out"}]
        t1_rot = [_rot("Jayson Tatum", 20.0)]

        result = compute_injury_impact(injuries, "Boston Celtics", "Memphis Grizzlies", t1_rot, [])
        expected_loss = round(20.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        assert result["team1"]["adjusted_ppg_loss"] == expected_loss
        assert result["total_reduction"] == expected_loss

    def test_both_teams_ppg_diff_direction(self):
        """missing_ppg_diff positive means team2 loses more → favors team1."""
        injuries = [
            {"team": "Boston Celtics", "player": "JT", "status": "Out"},
            {"team": "Memphis Grizzlies", "player": "JM", "status": "Out"},
        ]
        t1_rot = [_rot("JT", 10.0)]
        t2_rot = [_rot("JM", 30.0)]

        result = compute_injury_impact(injuries, "Boston Celtics", "Memphis Grizzlies", t1_rot, t2_rot)
        t1_adj = round(10.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        t2_adj = round(30.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        assert result["missing_ppg_diff"] == round(t2_adj - t1_adj, 1)
        assert result["missing_ppg_diff"] > 0  # favors team1

    def test_partial_team_name_matching(self):
        """Search returns 'Trail Blazers', rotation team is 'Portland Trail Blazers'."""
        injuries = [{"team": "Trail Blazers", "player": "Star Guy", "status": "Out"}]
        t1_rot = [_rot("Star Guy", 22.0)]

        result = compute_injury_impact(
            injuries, "Portland Trail Blazers", "Memphis Grizzlies", t1_rot, []
        )
        assert result is not None
        assert result["team1"]["out_players"][0]["ppg"] == 22.0


# ---------------------------------------------------------------------------
# 2) _extract_and_compute_injuries end-to-end integration
# ---------------------------------------------------------------------------

class TestExtractAndComputeIntegration:
    """Test the full pipeline: search → extract → merge API → compute → attach to game."""

    @pytest.mark.asyncio
    async def test_search_injuries_attached_to_game(self):
        """Injuries from search context get extracted, matched, and attached."""
        game = _make_game(
            t1_rotation=[_rot("Jayson Tatum", 27.3), _rot("Jaylen Brown", 24.1)],
            t2_rotation=[_rot("Ja Morant", 25.0), _rot("Desmond Bane", 18.5)],
            search_context="Jayson Tatum is OUT tonight. Ja Morant is listed as Out.",
        )

        llm_extraction = [
            {"team": "Boston Celtics", "player": "Jayson Tatum", "status": "Out"},
            {"team": "Memphis Grizzlies", "player": "Ja Morant", "status": "Out"},
        ]

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, return_value=llm_extraction):
            with patch("workflow.analyze._save_game_file"):
                await _extract_and_compute_injuries([game])

        # injury_impact should be attached
        assert "injury_impact" in game
        impact = game["injury_impact"]

        # Team1 (Celtics) lost Tatum
        assert len(impact["team1"]["out_players"]) == 1
        assert impact["team1"]["out_players"][0]["name"] == "Jayson Tatum"
        assert impact["team1"]["out_players"][0]["ppg"] == 27.3

        # Team2 (Grizzlies) lost Morant
        assert len(impact["team2"]["out_players"]) == 1
        assert impact["team2"]["out_players"][0]["name"] == "Ja Morant"
        assert impact["team2"]["out_players"][0]["ppg"] == 25.0

        # Total reduction = both adjusted losses
        t1_loss = round(27.3 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        t2_loss = round(25.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        assert impact["total_reduction"] == round(t1_loss + t2_loss, 1)

    @pytest.mark.asyncio
    async def test_injury_adjusted_total_computed(self):
        """injury_adjusted_total = expected_total - total_reduction."""
        game = _make_game(
            expected_total=224.5,
            t1_rotation=[_rot("Star", 30.0)],
            search_context="Star is OUT.",
        )

        llm_extraction = [
            {"team": "Boston Celtics", "player": "Star", "status": "Out"},
        ]

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, return_value=llm_extraction):
            with patch("workflow.analyze._save_game_file"):
                await _extract_and_compute_injuries([game])

        reduction = round(30.0 * (1 - INJURY_REPLACEMENT_FACTOR), 1)
        assert game["totals_analysis"]["injury_adjusted_total"] == round(224.5 - reduction, 1)

    @pytest.mark.asyncio
    async def test_api_injuries_merged_with_search(self):
        """API injuries not in search results get merged in."""
        game = _make_game(
            t1_rotation=[_rot("Jayson Tatum", 27.3), _rot("Derrick White", 15.5)],
            t1_api_injuries=[
                {"player": "Derrick White", "status": "Out", "reason": "knee", "report_time": ""},
                {"player": "Al Horford", "status": "Questionable", "reason": "rest", "report_time": ""},
            ],
            search_context="Jayson Tatum ruled OUT tonight.",
        )

        # LLM only finds Tatum from search
        llm_extraction = [
            {"team": "Boston Celtics", "player": "Jayson Tatum", "status": "Out"},
        ]

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, return_value=llm_extraction):
            with patch("workflow.analyze._save_game_file"):
                await _extract_and_compute_injuries([game])

        impact = game["injury_impact"]
        # Tatum (from search) + White (from API, status=Out) should both be matched
        assert len(impact["team1"]["out_players"]) == 2
        names = {p["name"] for p in impact["team1"]["out_players"]}
        assert names == {"Jayson Tatum", "Derrick White"}
        # Horford is Questionable → excluded
        assert impact["team1"]["missing_ppg"] == round(27.3 + 15.5, 1)

    @pytest.mark.asyncio
    async def test_api_injuries_deduped_with_search(self):
        """Same player in both search and API → not double-counted."""
        game = _make_game(
            t1_rotation=[_rot("Jayson Tatum", 27.3)],
            t1_api_injuries=[
                {"player": "Jayson Tatum", "status": "Out", "reason": "ankle", "report_time": ""},
            ],
            search_context="Tatum is OUT.",
        )

        llm_extraction = [
            {"team": "Boston Celtics", "player": "Jayson Tatum", "status": "Out"},
        ]

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, return_value=llm_extraction):
            with patch("workflow.analyze._save_game_file"):
                await _extract_and_compute_injuries([game])

        impact = game["injury_impact"]
        # Should appear only once
        assert len(impact["team1"]["out_players"]) == 1
        assert impact["team1"]["missing_ppg"] == 27.3

    @pytest.mark.asyncio
    async def test_no_search_context_uses_api_only(self):
        """When no search_context, still picks up API injuries."""
        game = _make_game(
            t1_rotation=[_rot("Jayson Tatum", 27.3)],
            t1_api_injuries=[
                {"player": "Jayson Tatum", "status": "Out", "reason": "ankle", "report_time": ""},
            ],
            search_context=None,
        )

        # complete_json should NOT be called (no search context)
        with patch("workflow.analyze.complete_json", new_callable=AsyncMock) as mock_llm:
            with patch("workflow.analyze._save_game_file"):
                await _extract_and_compute_injuries([game])
            mock_llm.assert_not_called()

        impact = game["injury_impact"]
        assert len(impact["team1"]["out_players"]) == 1
        assert impact["team1"]["out_players"][0]["ppg"] == 27.3

    @pytest.mark.asyncio
    async def test_no_injuries_leaves_game_unchanged(self):
        """No injuries from search or API → game not modified."""
        game = _make_game(
            t1_rotation=[_rot("Jayson Tatum", 27.3)],
            search_context="Both teams fully healthy tonight.",
        )
        game_before = copy.deepcopy(game)

        llm_extraction = []  # No injuries found

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, return_value=llm_extraction):
            with patch("workflow.analyze._save_game_file") as mock_save:
                await _extract_and_compute_injuries([game])
                mock_save.assert_not_called()

        assert "injury_impact" not in game
        assert "injury_adjusted_total" not in game.get("totals_analysis", {})

    @pytest.mark.asyncio
    async def test_llm_returns_garbage_still_safe(self):
        """LLM returns non-list → gracefully handled, only API injuries used."""
        game = _make_game(
            t1_rotation=[_rot("Star", 20.0)],
            t1_api_injuries=[
                {"player": "Star", "status": "Out", "reason": "back", "report_time": ""},
            ],
            search_context="Star is out.",
        )

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, return_value={"error": "bad"}):
            with patch("workflow.analyze._save_game_file"):
                await _extract_and_compute_injuries([game])

        # Should still have impact from API injury
        assert "injury_impact" in game
        assert game["injury_impact"]["team1"]["out_players"][0]["ppg"] == 20.0

    @pytest.mark.asyncio
    async def test_multiple_games_processed(self):
        """Multiple games all get processed independently."""
        game1 = _make_game(
            team1="Boston Celtics", team2="Memphis Grizzlies",
            t1_rotation=[_rot("Star1", 25.0)],
            search_context="Star1 is OUT.",
        )
        game2 = _make_game(
            team1="LA Lakers", team2="Golden State Warriors",
            t1_rotation=[_rot("Star2", 30.0)],
            search_context="Star2 is OUT.",
        )

        async def fake_extract(prompt, **kwargs):
            if "Boston Celtics" in prompt:
                return [{"team": "Boston Celtics", "player": "Star1", "status": "Out"}]
            return [{"team": "LA Lakers", "player": "Star2", "status": "Out"}]

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, side_effect=fake_extract):
            with patch("workflow.analyze._save_game_file"):
                await _extract_and_compute_injuries([game1, game2])

        assert "injury_impact" in game1
        assert game1["injury_impact"]["team1"]["out_players"][0]["ppg"] == 25.0
        assert "injury_impact" in game2
        assert game2["injury_impact"]["team1"]["out_players"][0]["ppg"] == 30.0

    @pytest.mark.asyncio
    async def test_game_file_saved_when_impact_found(self):
        """_save_game_file called when impact is computed."""
        game = _make_game(
            t1_rotation=[_rot("Star", 20.0)],
            search_context="Star is OUT.",
        )
        llm_extraction = [{"team": "Boston Celtics", "player": "Star", "status": "Out"}]

        with patch("workflow.analyze.complete_json", new_callable=AsyncMock, return_value=llm_extraction):
            with patch("workflow.analyze._save_game_file") as mock_save:
                await _extract_and_compute_injuries([game])
                mock_save.assert_called_once_with(game)
