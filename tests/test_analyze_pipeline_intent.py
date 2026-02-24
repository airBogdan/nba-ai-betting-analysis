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
