"""Temporary tests to verify analyze.py refactor preserves functionality.

Delete after confirming refactor is solid.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# --- gamedata.py ---

from workflow.analyze.gamedata import (
    OUTPUT_DIR,
    MAX_CONCURRENT_LLM_CALLS,
    HAIKU_MODEL,
    load_games_for_date,
    load_props_for_date,
    extract_game_id,
    format_matchup_string,
    _save_game_file,
)


class TestGamedataFunctions:
    def test_output_dir_points_to_output(self):
        assert OUTPUT_DIR.name == "output"

    def test_constants(self):
        assert MAX_CONCURRENT_LLM_CALLS == 4
        assert HAIKU_MODEL == "anthropic/claude-haiku-4.5"

    def test_extract_game_id(self):
        assert extract_game_id("celtics_vs_lakers_2026-02-20.json") == "celtics_vs_lakers_2026-02-20"

    def test_format_matchup_string_away_at_home(self):
        matchup = {"home_team": "Boston Celtics", "team1": "Boston Celtics", "team2": "LA Lakers"}
        assert format_matchup_string(matchup) == "LA Lakers @ Boston Celtics"

    def test_format_matchup_string_reversed(self):
        matchup = {"home_team": "LA Lakers", "team1": "Boston Celtics", "team2": "LA Lakers"}
        assert format_matchup_string(matchup) == "Boston Celtics @ LA Lakers"

    def test_load_games_for_date(self, tmp_path):
        game_data = {"matchup": {"team1": "A", "team2": "B"}, "api_game_id": 1}
        (tmp_path / "a_vs_b_2026-02-20.json").write_text(json.dumps(game_data))
        # Props file should be excluded
        (tmp_path / "props_a_vs_b_2026-02-20.json").write_text(json.dumps({"props": True}))

        with patch("workflow.analyze.gamedata.OUTPUT_DIR", tmp_path):
            games = load_games_for_date("2026-02-20")

        assert len(games) == 1
        assert games[0]["matchup"]["team1"] == "A"
        assert games[0]["_file"] == "a_vs_b_2026-02-20.json"

    def test_load_props_for_date(self, tmp_path):
        props_data = {"team1": "A", "api_game_id": 42}
        (tmp_path / "props_a_vs_b_2026-02-20.json").write_text(json.dumps(props_data))
        (tmp_path / "a_vs_b_2026-02-20.json").write_text(json.dumps({"matchup": {}}))

        with patch("workflow.analyze.gamedata.OUTPUT_DIR", tmp_path):
            props = load_props_for_date("2026-02-20")

        assert len(props) == 1
        assert props[0]["api_game_id"] == 42

    def test_save_game_file(self, tmp_path):
        game = {"_file": "test.json", "matchup": {"team1": "A"}, "search_context": "ctx"}
        with patch("workflow.analyze.gamedata.OUTPUT_DIR", tmp_path):
            _save_game_file(game)

        saved = json.loads((tmp_path / "test.json").read_text())
        assert "matchup" in saved
        assert "search_context" in saved
        assert "_file" not in saved  # internal key stripped


# --- injuries.py ---

from workflow.analyze.injuries import (
    INJURY_REPLACEMENT_FACTOR,
    _extract_injuries_from_search,
    compute_injury_impact,
)


class TestInjuriesFunctions:
    def test_injury_replacement_factor(self):
        assert INJURY_REPLACEMENT_FACTOR == 0.55

    def test_compute_injury_impact_basic(self):
        injuries = [
            {"team": "Celtics", "player": "Jayson Tatum", "status": "Out"},
        ]
        t1_rotation = [{"name": "Jayson Tatum", "ppg": 27.0}]
        t2_rotation = []

        impact = compute_injury_impact(injuries, "Celtics", "Lakers", t1_rotation, t2_rotation)

        assert impact is not None
        assert len(impact["team1"]["out_players"]) == 1
        assert impact["team1"]["missing_ppg"] == 27.0
        expected_loss = round(27.0 * (1 - 0.55), 1)
        assert impact["team1"]["adjusted_ppg_loss"] == expected_loss
        assert impact["total_reduction"] == expected_loss

    def test_compute_injury_impact_no_matches(self):
        injuries = [{"team": "Celtics", "player": "Unknown Player", "status": "Out"}]
        t1_rotation = [{"name": "Jayson Tatum", "ppg": 27.0}]
        assert compute_injury_impact(injuries, "Celtics", "Lakers", t1_rotation, []) is None

    def test_compute_injury_impact_both_teams(self):
        injuries = [
            {"team": "Celtics", "player": "Star1", "status": "Out"},
            {"team": "Lakers", "player": "Star2", "status": "Out"},
        ]
        t1 = [{"name": "Star1", "ppg": 20.0}]
        t2 = [{"name": "Star2", "ppg": 25.0}]

        impact = compute_injury_impact(injuries, "Celtics", "Lakers", t1, t2)
        assert impact is not None
        assert len(impact["team1"]["out_players"]) == 1
        assert len(impact["team2"]["out_players"]) == 1
        assert impact["total_reduction"] == round(
            20.0 * 0.45 + 25.0 * 0.45, 1
        )

    @pytest.mark.asyncio
    async def test_extract_injuries_from_search_validates(self):
        mock_result = [
            {"team": "A", "player": "P1", "status": "Out"},
            {"team": "A", "player": "P2", "status": "Questionable"},  # filtered
            {"team": "B", "status": "Out"},  # missing player - filtered
        ]
        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value=mock_result):
            result = await _extract_injuries_from_search("ctx", "A", "B")
        assert len(result) == 1
        assert result[0]["player"] == "P1"


# --- sizing.py ---

from workflow.analyze.sizing import (
    CONFIDENCE_WIN_PROB,
    KELLY_FRACTION,
    _american_odds_to_decimal,
    _half_kelly_amount,
    _extract_sizing_strategy,
    _extract_poly_and_odds_price,
    _fallback_sizing,
)


class TestSizingFunctions:
    def test_confidence_win_prob(self):
        assert CONFIDENCE_WIN_PROB["high"] == 0.65
        assert CONFIDENCE_WIN_PROB["medium"] == 0.57
        assert CONFIDENCE_WIN_PROB["low"] == 0.54

    def test_kelly_fraction(self):
        assert KELLY_FRACTION == 0.5

    def test_american_odds_to_decimal_negative(self):
        assert _american_odds_to_decimal(-110) == pytest.approx(1.909, abs=0.001)

    def test_american_odds_to_decimal_positive(self):
        assert _american_odds_to_decimal(200) == pytest.approx(3.0)

    def test_half_kelly_basic(self):
        result = _half_kelly_amount(-110, "high", 1000.0)
        assert result > 0
        assert result < 1000.0

    def test_half_kelly_no_edge(self):
        # Very heavy favorite odds with low confidence = no edge
        result = _half_kelly_amount(-1000, "low", 1000.0)
        assert result == 0.0

    def test_extract_sizing_strategy_found(self):
        strategy = "# Strategy\n## Position Sizing\nBet 2% per play.\n## Other"
        result = _extract_sizing_strategy(strategy)
        assert "Position Sizing" in result
        assert "Bet 2%" in result
        assert "Other" not in result

    def test_extract_sizing_strategy_missing(self):
        assert _extract_sizing_strategy(None) == "No sizing strategy defined yet."
        assert _extract_sizing_strategy("# No sizing here") == "No sizing strategy defined yet."

    def test_extract_poly_and_odds_price_found(self):
        game = {"polymarket_odds": {"moneyline": {"home": {"price": 0.65}}}}
        bet = {"bet_type": "moneyline", "pick": "Home Team", "line": None}
        with patch("workflow.analyze.sizing.extract_poly_price_for_bet", return_value=0.65):
            poly, odds = _extract_poly_and_odds_price(game, bet)
        assert poly == 0.65
        assert odds != -110  # derived from poly price

    def test_extract_poly_and_odds_price_not_found(self):
        bet = {"bet_type": "moneyline", "pick": "X", "line": None}
        with patch("workflow.analyze.sizing.extract_poly_price_for_bet", return_value=None):
            poly, odds = _extract_poly_and_odds_price({}, bet)
        assert poly is None
        assert odds == -110

    def test_fallback_sizing(self):
        bets = [
            {"id": "1", "confidence": "high", "odds_price": -110, "game_id": "g1", "matchup": "A@B"},
            {"id": "2", "confidence": "low", "odds_price": -110, "game_id": "g2", "matchup": "C@D"},
        ]
        result = _fallback_sizing(bets, 1000.0)
        assert len(result) > 0
        for b in result:
            assert "amount" in b
            assert b["amount"] > 0


# --- bets.py ---

from workflow.analyze.bets import (
    VALID_CONFIDENCE,
    VALID_BET_TYPES,
    VALID_PROP_TYPES,
    _normalize_confidence,
    _normalize_bet_type,
    _normalize_units,
    _normalize_prop_pick,
    create_active_bet,
    create_prop_bet,
    write_journal_pre_game,
)


class TestBetsFunctions:
    def test_valid_sets(self):
        assert "high" in VALID_CONFIDENCE
        assert "moneyline" in VALID_BET_TYPES
        assert "points" in VALID_PROP_TYPES

    def test_normalize_confidence(self):
        assert _normalize_confidence("high") == "high"
        assert _normalize_confidence("STRONG edge") == "high"
        assert _normalize_confidence("moderate") == "medium"
        assert _normalize_confidence("garbage") == "low"

    def test_normalize_bet_type(self):
        assert _normalize_bet_type("moneyline") == "moneyline"
        assert _normalize_bet_type("spread_pick") == "spread"
        assert _normalize_bet_type("over/under total") == "total"
        assert _normalize_bet_type("garbage") == "moneyline"

    def test_normalize_units(self):
        assert _normalize_units(1.0, "medium") == 1.0
        assert _normalize_units(3.5, "high") == 2.0  # falls back to confidence

    def test_normalize_prop_pick(self):
        assert _normalize_prop_pick("over") == "over"
        assert _normalize_prop_pick("Under") == "under"
        assert _normalize_prop_pick("yes") == "over"
        assert _normalize_prop_pick("no") == "under"
        assert _normalize_prop_pick("maybe") is None

    def test_create_active_bet(self):
        selected = {
            "game_id": "123",
            "matchup": "A @ B",
            "bet_type": "moneyline",
            "pick": "A",
            "line": None,
            "confidence": "high",
            "units": 2.0,
            "reasoning": "Good form",
            "primary_edge": "momentum",
        }
        bet = create_active_bet(selected, "2026-02-20")
        assert bet["game_id"] == "123"
        assert bet["confidence"] == "high"
        assert bet["units"] == 2.0
        assert bet["date"] == "2026-02-20"
        assert "id" in bet  # UUID generated

    def test_create_prop_bet_valid(self):
        selected = {
            "game_id": "123",
            "matchup": "A @ B",
            "prop_type": "points",
            "pick": "over",
            "line": 25.5,
            "confidence": "medium",
            "units": 1.0,
            "reasoning": "Hot streak",
            "primary_edge": "form",
            "player_name": "LeBron James",
        }
        bet = create_prop_bet(selected, "2026-02-20")
        assert bet is not None
        assert bet["bet_type"] == "player_prop"
        assert bet["pick"] == "over"
        assert bet["player_name"] == "LeBron James"

    def test_create_prop_bet_bad_type(self):
        selected = {"prop_type": "steals", "pick": "over"}
        assert create_prop_bet(selected, "2026-02-20") is None

    def test_create_prop_bet_bad_pick(self):
        selected = {"prop_type": "points", "pick": "maybe"}
        assert create_prop_bet(selected, "2026-02-20") is None

    def test_write_journal_pre_game(self, tmp_path):
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        bets = [{
            "matchup": "A @ B", "bet_type": "moneyline", "pick": "A",
            "confidence": "high", "units": 2.0, "amount": 50.0,
            "primary_edge": "form", "reasoning": "Good",
        }]
        skipped = [{"matchup": "C @ D", "reason": "No edge"}]

        with patch("workflow.analyze.bets.JOURNAL_DIR", journal_dir):
            write_journal_pre_game("2026-02-20", bets, skipped, "Test summary")

        content = (journal_dir / "2026-02-20.md").read_text()
        assert "# NBA Betting Journal - 2026-02-20" in content
        assert "Test summary" in content
        assert "A @ B" in content
        assert "$50.00" in content
        assert "C @ D" in content
        assert "No edge" in content


# --- Cross-module integration ---

class TestCrossModuleIntegration:
    """Test that modules work together correctly."""

    def test_gamedata_used_by_injuries(self):
        """injuries.py imports from gamedata.py correctly."""
        from workflow.analyze.injuries import format_matchup_string, _save_game_file
        # These are re-imported from gamedata
        assert callable(format_matchup_string)
        assert callable(_save_game_file)

    def test_sizing_used_by_props(self):
        """props.py can access size_bets from sizing.py."""
        from workflow.analyze.props import size_bets
        assert callable(size_bets)

    def test_bets_used_by_props(self):
        """props.py can access create_prop_bet from bets.py."""
        from workflow.analyze.props import create_prop_bet
        assert callable(create_prop_bet)

    def test_pipeline_imports_all_submodules(self):
        """pipeline.py orchestrates all submodules."""
        from workflow.analyze.pipeline import (
            _enrich_games_with_search,
            analyze_game,
            synthesize_bets,
            run_analyze_workflow,
            _extract_and_compute_injuries,
            _run_props_pipeline,
            create_active_bet,
            write_journal_pre_game,
            _extract_poly_and_odds_price,
            size_bets,
        )
        assert all(callable(f) for f in [
            _enrich_games_with_search, analyze_game, synthesize_bets,
            run_analyze_workflow, _extract_and_compute_injuries,
            _run_props_pipeline, create_active_bet, write_journal_pre_game,
            _extract_poly_and_odds_price, size_bets,
        ])

    def test_init_exports_only_run_analyze_workflow(self):
        """__init__.py only re-exports run_analyze_workflow."""
        import workflow.analyze as pkg
        assert hasattr(pkg, "run_analyze_workflow")
        assert callable(pkg.run_analyze_workflow)

    def test_betting_py_import_still_works(self):
        """The main CLI entry point import is unchanged."""
        from workflow.analyze import run_analyze_workflow
        assert callable(run_analyze_workflow)

    @pytest.mark.asyncio
    async def test_injury_pipeline_end_to_end(self):
        """Full injury extraction → impact computation across modules."""
        mock_llm = [{"team": "Boston Celtics", "player": "Jayson Tatum", "status": "Out"}]
        game = {
            "_file": "test.json",
            "matchup": {"team1": "Boston Celtics", "team2": "LA Lakers", "home_team": "Boston Celtics"},
            "search_context": "Tatum is out tonight.",
            "players": {
                "team1": {"rotation": [{"name": "Jayson Tatum", "ppg": 27.0}], "injuries": []},
                "team2": {"rotation": [], "injuries": []},
            },
            "totals_analysis": {"expected_total": 220.0},
        }

        with patch("workflow.analyze.injuries.complete_json", new_callable=AsyncMock, return_value=mock_llm):
            with patch("workflow.analyze.injuries._save_game_file"):
                from workflow.analyze.injuries import _extract_and_compute_injuries
                await _extract_and_compute_injuries([game])

        assert "injury_impact" in game
        assert game["injury_impact"]["team1"]["out_players"][0]["name"] == "Jayson Tatum"
        assert game["totals_analysis"]["injury_adjusted_total"] < 220.0

    def test_sizing_and_bets_produce_valid_output(self):
        """create_active_bet + fallback_sizing work together."""
        selected = {
            "game_id": "123", "matchup": "A @ B", "bet_type": "moneyline",
            "pick": "A", "line": None, "confidence": "high", "units": 2.0,
            "reasoning": "test", "primary_edge": "test",
        }
        bet = create_active_bet(selected, "2026-02-20")
        bet["odds_price"] = -110

        sized = _fallback_sizing([bet], 1000.0)
        assert len(sized) == 1
        assert sized[0]["amount"] > 0
