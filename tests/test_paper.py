"""Tests for paper trading workflow."""

import pytest
from unittest.mock import AsyncMock, patch

from workflow.types import PaperTrade
from workflow.io import (
    PAPER_DIR,
    get_paper_trades,
    save_paper_trades,
    get_paper_history,
    save_paper_history,
)
from workflow.prompts import (
    PAPER_TRADE_PROMPT,
    SYSTEM_PAPER_ANALYST,
    format_paper_trade_insights,
)
from workflow.paper import run_paper_trades, create_paper_trade, MIN_PAPER_TRADES_FOR_STRATEGY


class TestPaperTradeIO:
    def test_paper_dir_path(self):
        assert PAPER_DIR.name == "paper"
        assert PAPER_DIR.parent.name == "bets"

    def test_get_paper_trades_empty(self, tmp_path):
        with patch("workflow.io.PAPER_DIR", tmp_path):
            assert get_paper_trades() == []

    def test_save_and_get_paper_trades(self, tmp_path):
        with patch("workflow.io.PAPER_DIR", tmp_path):
            trades = [{"matchup": "A @ B", "date": "2026-02-15", "bet_type": "moneyline", "pick": "A", "confidence": "medium"}]
            save_paper_trades(trades)
            assert get_paper_trades() == trades

    def test_get_paper_history_empty(self, tmp_path):
        with patch("workflow.io.PAPER_DIR", tmp_path):
            history = get_paper_history()
            assert history["trades"] == []
            assert history["summary"]["total_trades"] == 0

    def test_save_and_get_paper_history(self, tmp_path):
        with patch("workflow.io.PAPER_DIR", tmp_path):
            history = {"trades": [{"matchup": "A @ B", "result": "win"}], "summary": {"total_trades": 1}}
            save_paper_history(history)
            assert get_paper_history() == history


class TestPaperTradePrompt:
    def test_prompt_has_required_placeholders(self):
        """Prompt must accept all required format keys."""
        formatted = PAPER_TRADE_PROMPT.format(
            skipped_games_json="[]",
            paper_strategy="No strategy yet.",
            paper_history_summary="No history.",
        )
        assert len(formatted) > 0

    def test_system_prompt_exists(self):
        assert len(SYSTEM_PAPER_ANALYST) > 0


class TestCreatePaperTrade:
    def test_creates_paper_trade_from_llm_output(self):
        llm_pick = {
            "matchup": "Team A @ Team B",
            "game_id": "12345",
            "bet_type": "total",
            "pick": "over",
            "line": 224.5,
            "confidence": "low",
            "reasoning": "Pace edge",
            "primary_edge": "pace_mismatch",
            "contrarian_argument": "Primary analyst underweighted pace",
        }
        skip_reason = "No clear edge"
        trade = create_paper_trade(llm_pick, "2026-02-15", skip_reason)

        assert trade["matchup"] == "Team A @ Team B"
        assert trade["date"] == "2026-02-15"
        assert trade["bet_type"] == "total"
        assert trade["pick"] == "over"
        assert trade["line"] == 224.5
        assert trade["confidence"] == "low"
        assert trade["skip_reason"] == "No clear edge"
        assert trade["units"] == 0.5  # low confidence = 0.5 units

    def test_confidence_to_units_mapping(self):
        base = {"matchup": "A @ B", "game_id": "1", "bet_type": "moneyline",
                "pick": "A", "line": None, "confidence": "high",
                "reasoning": "x", "primary_edge": "y", "contrarian_argument": "z"}
        assert create_paper_trade(base, "2026-02-15", "r")["units"] == 2.0
        base["confidence"] = "medium"
        assert create_paper_trade(base, "2026-02-15", "r")["units"] == 1.0
        base["confidence"] = "low"
        assert create_paper_trade(base, "2026-02-15", "r")["units"] == 0.5


class TestRunPaperTrades:
    @pytest.mark.asyncio
    async def test_no_skips_returns_early(self):
        """No skipped games -> no LLM call."""
        with patch("workflow.paper.complete_json", new_callable=AsyncMock) as mock_llm:
            await run_paper_trades([], "2026-02-15")
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_produces_paper_trades(self):
        skips = [
            {"matchup": "A @ B", "reason": "No edge", "date": "2026-02-15",
             "game_id": "123", "source": "synthesis"}
        ]
        llm_response = {
            "paper_trades": [{
                "matchup": "A @ B", "game_id": "123", "bet_type": "moneyline",
                "pick": "A", "line": None, "confidence": "medium",
                "reasoning": "underdog value", "primary_edge": "form",
                "contrarian_argument": "hot streak overlooked",
            }],
            "summary": "One paper trade",
        }
        with patch("workflow.paper.complete_json", new_callable=AsyncMock, return_value=llm_response), \
             patch("workflow.paper.save_paper_trades") as mock_save, \
             patch("workflow.paper.get_paper_trades", return_value=[]), \
             patch("workflow.paper.read_text", return_value=None), \
             patch("workflow.paper.get_paper_history", return_value={"trades": [], "summary": {"total_trades": 0}}), \
             patch("workflow.paper.write_paper_journal") as mock_journal:
            await run_paper_trades(skips, "2026-02-15")
            mock_save.assert_called_once()
            saved = mock_save.call_args[0][0]
            assert len(saved) == 1
            assert saved[0]["matchup"] == "A @ B"
            assert saved[0]["skip_reason"] == "No edge"
            mock_journal.assert_called_once()


class TestResolvePaperTrades:
    def test_evaluate_moneyline_paper_trade(self):
        """Paper trades use same evaluation logic as real bets."""
        from workflow.results import _evaluate_bet
        trade = {"pick": "Boston Celtics", "bet_type": "moneyline", "units": 1.0}
        result = {"home_team": "Boston Celtics", "away_team": "New York Knicks",
                  "home_score": 110, "away_score": 105, "winner": "Boston Celtics", "status": "finished"}
        outcome, pnl = _evaluate_bet(trade, result)
        assert outcome == "win"
        assert pnl == 1.0

    def test_evaluate_total_paper_trade(self):
        from workflow.results import _evaluate_bet
        trade = {"pick": "under", "bet_type": "total", "line": 220.0, "units": 0.5}
        result = {"home_team": "A", "away_team": "B",
                  "home_score": 100, "away_score": 105, "winner": "B", "status": "finished"}
        outcome, pnl = _evaluate_bet(trade, result)
        assert outcome == "win"
        assert pnl == 0.5


class TestCategorizeSkipReason:
    def test_injury_category(self):
        from workflow.results import _categorize_skip_reason
        assert _categorize_skip_reason("Key player injured") == "injury_uncertainty"
        assert _categorize_skip_reason("Missing starters") == "injury_uncertainty"

    def test_no_edge_category(self):
        from workflow.results import _categorize_skip_reason
        assert _categorize_skip_reason("No clear edge") == "no_edge"
        assert _categorize_skip_reason("Coin flip game") == "no_edge"

    def test_high_variance_category(self):
        from workflow.results import _categorize_skip_reason
        assert _categorize_skip_reason("Too much variance") == "high_variance"
        assert _categorize_skip_reason("Unpredictable matchup") == "high_variance"

    def test_sizing_veto_category(self):
        from workflow.results import _categorize_skip_reason
        assert _categorize_skip_reason("Vetoed: Kelly sizing too small") == "sizing_veto"

    def test_other_category(self):
        from workflow.results import _categorize_skip_reason
        assert _categorize_skip_reason("Some random reason") == "other"


class TestPaperStrategyUpdate:
    @pytest.mark.asyncio
    async def test_needs_minimum_trades(self):
        """Should require MIN_PAPER_TRADES_FOR_STRATEGY trades before updating."""
        with patch("workflow.paper.get_paper_history", return_value={
            "trades": [], "summary": {"total_trades": 5}
        }):
            from workflow.paper import run_paper_strategy_workflow
            await run_paper_strategy_workflow()
            # No error = early return worked


class TestPaperInsightsInMainStrategy:
    def test_format_paper_insights_for_main_strategy(self):
        """Paper trade summary should appear in main strategy prompt when significant."""
        summary = {
            "total_trades": 20, "wins": 12, "losses": 8, "pushes": 0,
            "win_rate": 0.6, "net_units": 4.0,
            "by_skip_reason_category": {
                "no_edge": {"wins": 8, "losses": 3, "win_rate": 0.727},
                "injury_uncertainty": {"wins": 4, "losses": 5, "win_rate": 0.444},
            },
            "by_confidence": {}, "by_bet_type": {},
        }
        result = format_paper_trade_insights(summary)
        assert "12-8" in result
        assert "no_edge" in result

    def test_no_insights_when_insufficient_data(self):
        summary = {"total_trades": 5, "wins": 3, "losses": 2}
        result = format_paper_trade_insights(summary)
        assert "not enough" in result.lower()


class TestPaperTradeIntegration:
    @pytest.mark.asyncio
    async def test_analyze_imports_paper_trades(self):
        """run_analyze_workflow should import run_paper_trades."""
        from workflow.analyze import run_paper_trades as imported
        assert imported is not None


class TestPaperInit:
    def test_init_creates_paper_directory(self, tmp_path):
        """Init should create bets/paper/ with trades.json, strategy.md, and journal/."""
        paper_dir = tmp_path / "paper"
        paper_journal_dir = paper_dir / "journal"
        with patch("workflow.init.BETS_DIR", tmp_path), \
             patch("workflow.init.PAPER_DIR", paper_dir), \
             patch("workflow.init.PAPER_JOURNAL_DIR", paper_journal_dir):
            from workflow.init import run_init
            run_init()
            assert paper_dir.exists()
            assert paper_journal_dir.exists()
            assert (paper_dir / "trades.json").exists()
            assert (paper_dir / "history.json").exists()
            assert (paper_dir / "strategy.md").exists()
