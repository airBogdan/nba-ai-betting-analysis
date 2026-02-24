import asyncio
from unittest.mock import AsyncMock, patch


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


def _make_skip(**overrides):
    base = {
        "matchup": "Celtics @ Lakers",
        "reason": "No clear edge",
        "date": "2026-02-20",
    }
    base.update(overrides)
    return base


def _make_paper_trade(**overrides):
    base = {
        "matchup": "Celtics @ Lakers",
        "date": "2026-02-20",
        "bet_type": "moneyline",
        "pick": "Lakers",
        "line": None,
        "confidence": "medium",
        "reasoning": "Contrarian paper pick",
        "primary_edge": "home_court",
        "skip_reason": "No clear edge",
        "units": 1.0,
    }
    base.update(overrides)
    return base


class TestSkipResolution:
    """Skipped games should have their outcomes recorded for learning."""

    def test_skips_resolved_by_game_id(self):
        from betting.results.resolution import _resolve_skips_for_date

        skips = [_make_skip(game_id="12345")]
        finished = [_make_game_result(game_id="12345")]

        with patch("betting.results.resolution.get_skips", return_value=skips), \
             patch("betting.results.resolution.get_games_by_date", new_callable=AsyncMock, return_value=["game"]), \
             patch("betting.results.resolution.parse_game_results", return_value=finished), \
             patch("betting.results.resolution.save_skips_all") as mock_save:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        mock_save.assert_called_once()
        saved_skips = mock_save.call_args[0][0]
        assert saved_skips[0]["outcome_resolved"] is True
        assert saved_skips[0]["winner"] == "Los Angeles Lakers"

    def test_skips_resolved_by_team_name_fallback(self):
        from betting.results.resolution import _resolve_skips_for_date

        skips = [_make_skip(matchup="Celtics @ Lakers")]  # No game_id
        finished = [_make_game_result(
            game_id="99999",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            home_score=115, away_score=108,
        )]

        with patch("betting.results.resolution.get_skips", return_value=skips), \
             patch("betting.results.resolution.get_games_by_date", new_callable=AsyncMock, return_value=["game"]), \
             patch("betting.results.resolution.parse_game_results", return_value=finished), \
             patch("betting.results.resolution.save_skips_all") as mock_save:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        mock_save.assert_called_once()
        resolved = mock_save.call_args[0][0][0]
        assert resolved["outcome_resolved"] is True
        assert resolved["actual_total"] == 223

    def test_already_resolved_skips_ignored(self):
        """Skips that already have outcome_resolved=True should not be re-processed."""
        from betting.results.resolution import _resolve_skips_for_date

        skips = [_make_skip(outcome_resolved=True, game_id="12345")]

        with patch("betting.results.resolution.get_skips", return_value=skips), \
             patch("betting.results.resolution.get_games_by_date", new_callable=AsyncMock) as mock_api:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        # Should not even call the API since no unresolved skips for this date
        mock_api.assert_not_called()

    def test_no_finished_games_means_no_resolution(self):
        from betting.results.resolution import _resolve_skips_for_date

        skips = [_make_skip(game_id="12345")]

        with patch("betting.results.resolution.get_skips", return_value=skips), \
             patch("betting.results.resolution.get_games_by_date", new_callable=AsyncMock, return_value=["game"]), \
             patch("betting.results.resolution.parse_game_results", return_value=[
                 _make_game_result(status="scheduled"),
             ]), \
             patch("betting.results.resolution.save_skips_all") as mock_save:
            asyncio.get_event_loop().run_until_complete(
                _resolve_skips_for_date("2026-02-20", 2025)
            )

        mock_save.assert_not_called()


class TestPaperTradeResolution:
    """Paper trades on skipped games should be graded against actual results."""

    def test_paper_trade_resolved_with_outcome(self):
        from betting.results.resolution import _resolve_paper_trades_for_date

        trades = [_make_paper_trade(game_id="12345")]
        finished = [_make_game_result(game_id="12345")]

        with patch("betting.results.resolution.get_paper_trades", return_value=trades), \
             patch("betting.results.resolution.get_games_by_date", new_callable=AsyncMock, return_value=["g"]), \
             patch("betting.results.resolution.parse_game_results", return_value=finished), \
             patch("betting.results.resolution.get_paper_history", return_value={"trades": [], "summary": {
                 "total_trades": 0, "wins": 0, "losses": 0, "pushes": 0,
                 "win_rate": 0.0, "net_units": 0.0,
                 "by_confidence": {}, "by_bet_type": {}, "by_skip_reason_category": {},
             }}), \
             patch("betting.results.resolution.save_paper_trades") as mock_save_trades, \
             patch("betting.results.resolution.save_paper_history") as mock_save_hist, \
             patch("betting.results.resolution._append_paper_journal_results"):
            asyncio.get_event_loop().run_until_complete(
                _resolve_paper_trades_for_date("2026-02-20", 2025)
            )

        mock_save_trades.assert_called_once()
        mock_save_hist.assert_called_once()
        resolved_trade = trades[0]
        assert "result" in resolved_trade
        assert resolved_trade["winner"] == "Los Angeles Lakers"

    def test_already_resolved_paper_trades_skipped(self):
        from betting.results.resolution import _resolve_paper_trades_for_date

        trades = [_make_paper_trade(game_id="12345", result="win")]

        with patch("betting.results.resolution.get_paper_trades", return_value=trades), \
             patch("betting.results.resolution.get_games_by_date", new_callable=AsyncMock) as mock_api:
            asyncio.get_event_loop().run_until_complete(
                _resolve_paper_trades_for_date("2026-02-20", 2025)
            )

        mock_api.assert_not_called()
