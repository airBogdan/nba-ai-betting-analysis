import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_bet(**overrides):
    base = {
        "id": "bet-001",
        "game_id": "12345",
        "matchup": "Celtics @ Lakers",
        "bet_type": "moneyline",
        "pick": "Lakers",
        "line": None,
        "confidence": "high",
        "units": 2.0,
        "reasoning": "Lakers strong at home",
        "primary_edge": "home_court",
        "date": "2026-02-20",
        "created_at": "2026-02-20T10:00:00",
    }
    base.update(overrides)
    return base


def _make_game_result(**overrides):
    base = {
        "game_id": "12345",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "home_score": 115,
        "away_score": 108,
        "winner": "Los Angeles Lakers",
        "status": "finished",
    }
    base.update(overrides)
    return base


def _make_prop_bet(**overrides):
    base = _make_bet(
        bet_type="player_prop",
        pick="over",
        line=25.5,
        prop_type="points",
        player_name="LeBron James",
    )
    base.update(overrides)
    return base


class TestWorkflowOrchestration:
    """The top-level workflow coordinates all sub-steps correctly."""

    def test_no_active_bets_exits_early(self):
        """If there are no active bets, the workflow should exit gracefully."""
        from betting.results.results import run_results_workflow

        with patch("betting.results.results.get_current_nba_season_year", return_value=2025), \
             patch("betting.results.results.get_skips", return_value=[]), \
             patch("betting.results.results.get_paper_trades", return_value=[]), \
             patch("betting.results.results.get_active_bets", return_value=[]), \
             patch("betting.results.results.clear_output_dir"):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )
        # Should not crash - just print "No active bets"

    def test_no_season_exits_early(self):
        """Off-season (no current season) should exit gracefully."""
        from betting.results.results import run_results_workflow

        with patch("betting.results.results.get_current_nba_season_year", return_value=None):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )

    def test_specific_date_processes_only_that_date(self):
        """When called with --date, only process bets for that date."""
        from betting.results.results import run_results_workflow

        bet_feb20 = _make_bet(date="2026-02-20")
        bet_feb21 = _make_bet(id="bet-002", date="2026-02-21")

        with patch("betting.results.results.get_current_nba_season_year", return_value=2025), \
             patch("betting.results.results.get_skips", return_value=[]), \
             patch("betting.results.results.get_paper_trades", return_value=[]), \
             patch("betting.results.results.get_active_bets", return_value=[bet_feb20, bet_feb21]), \
             patch("betting.results.results._process_results_for_date", new_callable=AsyncMock) as mock_process, \
             patch("betting.results.results.clear_output_dir"):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow("2026-02-20")
            )

        # Should only process the specified date
        mock_process.assert_called_once_with("2026-02-20", 2025)

    def test_no_date_processes_all_active_dates(self):
        """When called without --date, process all dates that have active bets."""
        from betting.results.results import run_results_workflow

        bet_feb20 = _make_bet(date="2026-02-20")
        bet_feb21 = _make_bet(id="bet-002", date="2026-02-21")

        with patch("betting.results.results.get_current_nba_season_year", return_value=2025), \
             patch("betting.results.results.get_skips", return_value=[]), \
             patch("betting.results.results.get_paper_trades", return_value=[]), \
             patch("betting.results.results.get_active_bets", return_value=[bet_feb20, bet_feb21]), \
             patch("betting.results.results._process_results_for_date", new_callable=AsyncMock) as mock_process, \
             patch("betting.results.results.clear_output_dir"):
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )

        assert mock_process.call_count == 2
        dates_processed = [call.args[0] for call in mock_process.call_args_list]
        assert "2026-02-20" in dates_processed
        assert "2026-02-21" in dates_processed

    def test_unresolved_bets_kept_active(self):
        """Bets whose games haven't finished should remain in active.json."""
        from betting.results.results import _process_results_for_date

        resolved_bet = _make_bet(id="bet-resolved", game_id="111")
        unresolved_bet = _make_bet(id="bet-unresolved", game_id="222", matchup="Warriors @ Heat")

        finished = [_make_game_result(game_id="111")]

        with patch("betting.results.results.get_active_bets", return_value=[resolved_bet, unresolved_bet]), \
             patch("betting.results.results._fetch_game_results", new_callable=AsyncMock, return_value=finished), \
             patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=None), \
             patch("betting.results.results.get_history", return_value={"bets": [], "summary": {
                 "total_bets": 0, "wins": 0, "losses": 0, "pushes": 0,
                 "win_rate": 0.0, "total_units_wagered": 0.0, "net_units": 0.0,
                 "roi": 0.0, "by_confidence": {}, "by_primary_edge": {},
                 "by_bet_type": {}, "current_streak": "", "net_dollar_pnl": 0.0,
             }}), \
             patch("betting.results.results.save_history"), \
             patch("betting.results.results.save_active_bets") as mock_save_active, \
             patch("betting.results.results.append_journal_post_game"), \
             patch("betting.results.results.get_dollar_pnl", return_value=0.0):
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        saved = mock_save_active.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["id"] == "bet-unresolved"

    def test_completed_bets_saved_to_history(self):
        """Settled bets should be added to history.json."""
        from betting.results.results import _process_results_for_date

        bet = _make_bet(game_id="111")
        finished = [_make_game_result(game_id="111", winner="Los Angeles Lakers")]
        history = {"bets": [], "summary": {
            "total_bets": 0, "wins": 0, "losses": 0, "pushes": 0,
            "win_rate": 0.0, "total_units_wagered": 0.0, "net_units": 0.0,
            "roi": 0.0, "by_confidence": {}, "by_primary_edge": {},
            "by_bet_type": {}, "current_streak": "", "net_dollar_pnl": 0.0,
        }}

        with patch("betting.results.results.get_active_bets", return_value=[bet]), \
             patch("betting.results.results._fetch_game_results", new_callable=AsyncMock, return_value=finished), \
             patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=None), \
             patch("betting.results.results.get_history", return_value=history), \
             patch("betting.results.results.save_history") as mock_save_hist, \
             patch("betting.results.results.save_active_bets"), \
             patch("betting.results.results.append_journal_post_game"), \
             patch("betting.results.results.get_dollar_pnl", return_value=0.0):
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        mock_save_hist.assert_called_once()
        assert len(history["bets"]) == 1
        assert history["bets"][0]["result"] == "win"

    def test_journal_entry_written_for_completed_bets(self):
        """A journal entry should be created for each date with completed bets."""
        from betting.results.results import _process_results_for_date

        bet = _make_bet(game_id="111")
        finished = [_make_game_result(game_id="111", winner="Los Angeles Lakers")]

        with patch("betting.results.results.get_active_bets", return_value=[bet]), \
             patch("betting.results.results._fetch_game_results", new_callable=AsyncMock, return_value=finished), \
             patch("betting.results.results.reflect_on_bet", new_callable=AsyncMock, return_value=None), \
             patch("betting.results.results.get_history", return_value={"bets": [], "summary": {
                 "total_bets": 0, "wins": 0, "losses": 0, "pushes": 0,
                 "win_rate": 0.0, "total_units_wagered": 0.0, "net_units": 0.0,
                 "roi": 0.0, "by_confidence": {}, "by_primary_edge": {},
                 "by_bet_type": {}, "current_streak": "", "net_dollar_pnl": 0.0,
             }}), \
             patch("betting.results.results.save_history"), \
             patch("betting.results.results.save_active_bets"), \
             patch("betting.results.results.append_journal_post_game") as mock_journal, \
             patch("betting.results.results.get_dollar_pnl", return_value=0.0):
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        mock_journal.assert_called_once()
        date_arg = mock_journal.call_args[0][0]
        completed_arg = mock_journal.call_args[0][1]
        assert date_arg == "2026-02-20"
        assert len(completed_arg) == 1

    def test_no_journal_when_no_bets_completed(self):
        """If all bets are unresolved (games not finished), skip journal."""
        from betting.results.results import _process_results_for_date

        with patch("betting.results.results.get_active_bets", return_value=[_make_bet()]), \
             patch("betting.results.results._fetch_game_results", new_callable=AsyncMock, return_value=None), \
             patch("betting.results.results.save_active_bets"), \
             patch("betting.results.results.append_journal_post_game") as mock_journal:
            asyncio.get_event_loop().run_until_complete(
                _process_results_for_date("2026-02-20", 2025)
            )

        mock_journal.assert_not_called()

    def test_paper_trade_failure_non_fatal(self):
        """Paper trade resolution failures should not block real bet processing."""
        from betting.results.results import run_results_workflow

        with patch("betting.results.results.get_current_nba_season_year", return_value=2025), \
             patch("betting.results.results.get_skips", return_value=[]), \
             patch("betting.results.results.get_paper_trades", side_effect=Exception("Paper file corrupt")), \
             patch("betting.results.results.get_active_bets", return_value=[]), \
             patch("betting.results.results.clear_output_dir"):
            # Should not raise, paper trade failure is caught
            asyncio.get_event_loop().run_until_complete(
                run_results_workflow()
            )


class TestGameResultFetching:
    """Game results should be fetched efficiently based on bet type."""

    def test_numeric_game_ids_fetched_individually(self):
        """Bets with numeric game_ids should fetch by individual game ID."""
        from betting.results.results import _fetch_game_results

        bets = [_make_bet(game_id="12345")]
        game_data = {
            "id": 12345,
            "status": {"long": "Finished"},
            "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
            "scores": {"home": {"points": 115}, "visitors": {"points": 108}},
        }

        with patch("betting.results.results.get_game_by_id", new_callable=AsyncMock, return_value=game_data) as mock_get:
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results(bets, "2026-02-20", 2025)
            )

        mock_get.assert_called_once_with(12345)
        assert result is not None
        assert len(result) == 1

    def test_legacy_bets_fetch_by_date(self):
        """Bets with non-numeric game_ids should fall back to date-based fetch."""
        from betting.results.results import _fetch_game_results

        bets = [_make_bet(game_id="legacy-abc")]

        with patch("betting.results.results.get_game_by_id", new_callable=AsyncMock) as mock_by_id, \
             patch("betting.results.results.get_games_by_date", new_callable=AsyncMock, return_value=[{
                 "id": 99, "status": {"long": "Finished"},
                 "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
                 "scores": {"home": {"points": 115}, "visitors": {"points": 108}},
             }]) as mock_by_date:
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results(bets, "2026-02-20", 2025)
            )

        mock_by_id.assert_not_called()
        mock_by_date.assert_called_once()
        assert result is not None

    def test_returns_none_when_no_games_finished(self):
        """If all games are still in progress or scheduled, return None."""
        from betting.results.results import _fetch_game_results

        bets = [_make_bet(game_id="12345")]
        game_data = {
            "id": 12345,
            "status": {"long": "Scheduled"},
            "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
            "scores": {"home": {"points": None}, "visitors": {"points": None}},
        }

        with patch("betting.results.results.get_game_by_id", new_callable=AsyncMock, return_value=game_data):
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results(bets, "2026-02-20", 2025)
            )

        assert result is None

    def test_deduplicates_games_across_fetch_methods(self):
        """If both numeric and legacy bets reference the same game, don't duplicate results."""
        from betting.results.results import _fetch_game_results

        # Same game fetched both ways — should only appear once
        numeric_bet = _make_bet(id="b1", game_id="12345")
        legacy_bet = _make_bet(id="b2", game_id="legacy-id")

        game_data = {
            "id": 12345,
            "status": {"long": "Finished"},
            "teams": {"home": {"name": "Lakers"}, "visitors": {"name": "Celtics"}},
            "scores": {"home": {"points": 115}, "visitors": {"points": 108}},
        }

        with patch("betting.results.results.get_game_by_id", new_callable=AsyncMock, return_value=game_data), \
             patch("betting.results.results.get_games_by_date", new_callable=AsyncMock, return_value=[game_data]):
            result = asyncio.get_event_loop().run_until_complete(
                _fetch_game_results([numeric_bet, legacy_bet], "2026-02-20", 2025)
            )

        assert result is not None
        # Game 12345 fetched by ID first, then the same game from date fetch
        # is deduplicated by seen_game_ids
        assert len(result) == 1


class TestJournalWriting:
    """Journal entries should document bet outcomes for review."""

    def test_journal_contains_bet_details(self):
        from betting.journal import append_journal_post_game

        completed = [{
            "matchup": "Celtics @ Lakers",
            "bet_type": "moneyline",
            "pick": "Lakers",
            "line": None,
            "result": "win",
            "profit_loss": 2.0,
            "final_score": "Celtics 108 @ Lakers 115",
            "winner": "Lakers",
            "reflection": "Edge was valid.",
            "actual_total": 223,
            "actual_margin": 7,
        }]

        written_content = []
        mock_path = MagicMock()
        mock_path.exists.return_value = False  # Fresh journal, no existing file
        mock_journal_dir = MagicMock()
        mock_journal_dir.__truediv__ = MagicMock(return_value=mock_path)

        with patch("betting.journal.JOURNAL_DIR", mock_journal_dir), \
             patch("betting.journal.append_text", side_effect=lambda p, c: written_content.append(c)):
            append_journal_post_game("2026-02-20", completed)

        text = written_content[0]
        assert "NBA Betting Journal - 2026-02-20" in text  # Header for fresh journal
        assert "Post-Game Results" in text
        assert "WIN" in text
        assert "Lakers" in text
        assert "Celtics 108 @ Lakers 115" in text

    def test_journal_not_duplicated_on_rerun(self):
        """Re-running results should not append duplicate journal sections."""
        from betting.journal import append_journal_post_game

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "## Post-Game Results\nalready here"
        mock_journal_dir = MagicMock()
        mock_journal_dir.__truediv__ = MagicMock(return_value=mock_path)

        with patch("betting.journal.JOURNAL_DIR", mock_journal_dir), \
             patch("betting.journal.append_text") as mock_append:
            append_journal_post_game("2026-02-20", [])

        mock_append.assert_not_called()

    def test_journal_shows_push_record(self):
        """Record format should include pushes when there are any."""
        from betting.journal import append_journal_post_game

        completed = [
            {
                "matchup": "A @ B", "bet_type": "total", "pick": "over",
                "line": 220.0, "result": "push", "profit_loss": 0.0,
                "final_score": "A 110 @ B 110", "winner": "",
                "reflection": "", "actual_total": 220, "actual_margin": 0,
            },
        ]

        written = []
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_journal_dir = MagicMock()
        mock_journal_dir.__truediv__ = MagicMock(return_value=mock_path)

        with patch("betting.journal.JOURNAL_DIR", mock_journal_dir), \
             patch("betting.journal.append_text", side_effect=lambda p, c: written.append(c)):
            append_journal_post_game("2026-02-20", completed)

        text = written[0]
        assert "0-0-1" in text  # Record with push count


class TestReflectOnBetPrompt:
    """The reflection prompt should be correctly formatted for the LLM."""

    def test_moneyline_reflection_prompt_formatted(self):
        from betting.results.results import reflect_on_bet

        bet = _make_bet(pick="Lakers", line=None, units=2.0)
        result = _make_game_result(home_score=115, away_score=108)

        with patch("betting.results.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "Lakers" in prompt
        assert "WIN" in prompt
        assert "N/A" in prompt  # line is None for moneyline

    def test_spread_reflection_shows_signed_line(self):
        from betting.results.results import reflect_on_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-5.5, units=1.0)
        result = _make_game_result(home_score=115, away_score=108)

        with patch("betting.results.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "-5.5" in prompt

    def test_total_reflection_shows_line_without_sign(self):
        from betting.results.results import reflect_on_bet

        bet = _make_bet(bet_type="total", pick="over", line=224.5, units=1.0)
        result = _make_game_result(home_score=115, away_score=108)

        with patch("betting.results.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "224.5" in prompt

    def test_player_prop_reflection_includes_stat_context(self):
        from betting.results.results import reflect_on_bet

        bet = _make_prop_bet(player_name="LeBron James", prop_type="points", pick="over", line=25.5)
        bet["_actual_stat"] = 30
        result = _make_game_result()

        with patch("betting.results.results.complete_json", new_callable=AsyncMock, return_value={
            "summary": "test"
        }) as mock_llm:
            asyncio.get_event_loop().run_until_complete(
                reflect_on_bet(bet, result, "win")
            )

        prompt = mock_llm.call_args[0][0]
        assert "LeBron James" in prompt
        assert "points" in prompt
        assert "30" in prompt  # actual stat


class TestOutputCleanup:
    """After results processing, matchup JSON files should be removed."""

    def test_output_dir_cleared(self):
        from betting.io import clear_output_dir

        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = [mock_file]

        with patch("betting.io.OUTPUT_DIR", mock_dir):
            clear_output_dir()

        mock_file.unlink.assert_called_once()

    def test_output_cleanup_skipped_if_no_dir(self):
        from betting.io import clear_output_dir

        mock_dir = MagicMock()
        mock_dir.exists.return_value = False

        with patch("betting.io.OUTPUT_DIR", mock_dir):
            clear_output_dir()  # Should not crash
