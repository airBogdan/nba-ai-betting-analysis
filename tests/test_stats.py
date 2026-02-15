"""Tests for workflow.stats module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow.stats import (
    _pick_side,
    compute_all_breakdowns,
    compute_breakdown_table,
    compute_cumulative_pnl,
    compute_overview,
    compute_paper_breakdowns,
    compute_paper_overview,
    compute_rolling_win_rate,
    compute_skip_stats,
    generate_dashboard,
)


def _make_bet(**overrides) -> dict:
    """Factory for CompletedBet dicts with sensible defaults."""
    base = {
        "id": "test-1",
        "game_id": "123",
        "matchup": "Celtics @ Lakers",
        "bet_type": "moneyline",
        "pick": "Lakers",
        "line": None,
        "confidence": "medium",
        "units": 1.0,
        "reasoning": "Test reasoning",
        "primary_edge": "ratings_edge",
        "date": "2026-02-10",
        "created_at": "2026-02-10T12:00:00Z",
        "result": "win",
        "winner": "Lakers",
        "final_score": "Celtics 100 @ Lakers 110",
        "actual_total": 210,
        "actual_margin": 10,
        "profit_loss": 1.0,
        "reflection": "Good pick.",
        "dollar_pnl": 5.0,
    }
    base.update(overrides)
    return base


def _make_history(bets: list) -> dict:
    """Build a history dict from a list of bets."""
    wins = sum(1 for b in bets if b["result"] == "win")
    losses = sum(1 for b in bets if b["result"] == "loss")
    pushes = sum(1 for b in bets if b["result"] == "push")
    total = wins + losses + pushes
    net_units = sum(b["profit_loss"] for b in bets)
    wagered = sum(b["units"] for b in bets if b["result"] in ("win", "loss"))
    return {
        "bets": bets,
        "summary": {
            "total_bets": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": round(wins / total, 3) if total > 0 else 0.0,
            "total_units_wagered": wagered,
            "net_units": net_units,
            "roi": round(net_units / wagered, 3) if wagered > 0 else 0.0,
            "by_confidence": {},
            "by_primary_edge": {},
            "by_bet_type": {},
            "current_streak": f"W{wins}" if wins > 0 and losses == 0 else "",
            "net_dollar_pnl": sum(b.get("dollar_pnl", 0) for b in bets),
        },
    }


# --- TestComputeOverview ---

class TestComputeOverview:
    def test_standard_history(self):
        bets = [
            _make_bet(result="win", profit_loss=1.0),
            _make_bet(result="loss", profit_loss=-1.0),
            _make_bet(result="win", profit_loss=2.0),
        ]
        history = _make_history(bets)
        overview = compute_overview(history)
        assert overview["wins"] == 2
        assert overview["losses"] == 1
        assert overview["total_bets"] == 3
        assert overview["net_units"] == 2.0

    def test_empty_history(self):
        history = _make_history([])
        overview = compute_overview(history)
        assert overview["total_bets"] == 0
        assert overview["win_rate"] == 0.0
        assert overview["avg_units"] == 0.0

    def test_with_pushes(self):
        bets = [
            _make_bet(result="win", profit_loss=1.0),
            _make_bet(result="push", profit_loss=0.0),
        ]
        history = _make_history(bets)
        overview = compute_overview(history)
        assert overview["pushes"] == 1
        assert overview["wins"] == 1


# --- TestComputeCumulativePnl ---

class TestComputeCumulativePnl:
    def test_single_bet(self):
        bets = [_make_bet(profit_loss=2.0, dollar_pnl=10.0)]
        result = compute_cumulative_pnl(bets)
        assert len(result) == 1
        assert result[0]["cumulative_units"] == 2.0
        assert result[0]["cumulative_dollars"] == 10.0

    def test_multiple_bets_same_date(self):
        bets = [
            _make_bet(date="2026-02-10", profit_loss=1.0, dollar_pnl=5.0),
            _make_bet(date="2026-02-10", profit_loss=-0.5, dollar_pnl=-2.5),
        ]
        result = compute_cumulative_pnl(bets)
        # Aggregated by date, last value wins
        assert len(result) == 1
        assert result[0]["cumulative_units"] == 0.5

    def test_multiple_dates(self):
        bets = [
            _make_bet(date="2026-02-10", profit_loss=1.0, dollar_pnl=5.0),
            _make_bet(date="2026-02-11", profit_loss=2.0, dollar_pnl=10.0),
        ]
        result = compute_cumulative_pnl(bets)
        assert len(result) == 2
        assert result[0]["date"] == "2026-02-10"
        assert result[1]["cumulative_units"] == 3.0

    def test_empty(self):
        assert compute_cumulative_pnl([]) == []


# --- TestComputeRollingWinRate ---

class TestComputeRollingWinRate:
    def test_all_wins(self):
        bets = [_make_bet(result="win") for _ in range(5)]
        result = compute_rolling_win_rate(bets, window=3)
        assert all(r["rolling_win_rate"] == 1.0 for r in result)

    def test_alternating(self):
        bets = [_make_bet(result="win" if i % 2 == 0 else "loss") for i in range(6)]
        result = compute_rolling_win_rate(bets, window=4)
        assert len(result) == 6
        # Last 4: L, W, L, W → 50%
        assert result[-1]["rolling_win_rate"] == 0.5

    def test_partial_window(self):
        bets = [_make_bet(result="win"), _make_bet(result="loss")]
        result = compute_rolling_win_rate(bets, window=10)
        assert len(result) == 2
        assert result[0]["rolling_win_rate"] == 1.0
        assert result[1]["rolling_win_rate"] == 0.5

    def test_pushes_excluded(self):
        bets = [
            _make_bet(result="win"),
            _make_bet(result="push"),
            _make_bet(result="loss"),
        ]
        result = compute_rolling_win_rate(bets, window=10)
        # Only win and loss count
        assert len(result) == 2
        assert result[0]["rolling_win_rate"] == 1.0
        assert result[1]["rolling_win_rate"] == 0.5


# --- TestBreakdownTable ---

class TestBreakdownTable:
    def test_grouping(self):
        bets = [
            _make_bet(confidence="high", result="win", profit_loss=2.0),
            _make_bet(confidence="high", result="loss", profit_loss=-1.0),
            _make_bet(confidence="low", result="win", profit_loss=0.5),
        ]
        rows = compute_breakdown_table(bets, lambda b: b.get("confidence"))
        assert len(rows) == 2
        high = next(r for r in rows if r["category"] == "high")
        assert high["wins"] == 1
        assert high["losses"] == 1
        assert high["win_rate"] == 0.5

    def test_roi_calc(self):
        bets = [
            _make_bet(units=2.0, result="win", profit_loss=2.0),
            _make_bet(units=1.0, result="loss", profit_loss=-1.0),
        ]
        rows = compute_breakdown_table(bets, lambda b: "all")
        assert len(rows) == 1
        assert rows[0]["net_units"] == 1.0
        # ROI = 1.0 / 3.0 = 0.333
        assert rows[0]["roi"] == 0.333

    def test_push_handling(self):
        bets = [_make_bet(result="push", profit_loss=0.0)]
        rows = compute_breakdown_table(bets, lambda b: "all")
        assert rows[0]["pushes"] == 1
        assert rows[0]["win_rate"] == 0.0

    def test_empty(self):
        rows = compute_breakdown_table([], lambda b: b.get("confidence"))
        assert rows == []

    def test_none_key_skipped(self):
        bets = [_make_bet(bet_type="total", pick="over")]
        rows = compute_breakdown_table(bets, _pick_side)
        assert rows == []


# --- TestPickSide ---

class TestPickSide:
    def test_home_pick(self):
        bet = _make_bet(matchup="Celtics @ Lakers", pick="Lakers")
        assert _pick_side(bet) == "home"

    def test_away_pick(self):
        bet = _make_bet(matchup="Celtics @ Lakers", pick="Celtics")
        assert _pick_side(bet) == "away"

    def test_totals_returns_none(self):
        bet = _make_bet(bet_type="total", pick="over")
        assert _pick_side(bet) is None

    def test_malformed_matchup(self):
        bet = _make_bet(matchup="invalid", pick="Lakers")
        assert _pick_side(bet) is None


# --- TestComputeSkipStats ---

class TestComputeSkipStats:
    def test_counts(self):
        skips = [
            {"matchup": "A @ B", "reason": "No edge", "date": "2026-02-10", "outcome_resolved": True},
            {"matchup": "C @ D", "reason": "No edge", "date": "2026-02-10"},
        ]
        result = compute_skip_stats(skips)
        assert result["total_skipped"] == 2
        assert result["resolved"] == 1
        assert len(result["skips"]) == 2

    def test_empty(self):
        result = compute_skip_stats([])
        assert result["total_skipped"] == 0
        assert result["resolved"] == 0


# --- TestGenerateDashboard ---

class TestGenerateDashboard:
    def test_generates_html_file(self, tmp_path):
        bets = [
            _make_bet(result="win", profit_loss=1.0, dollar_pnl=5.0),
            _make_bet(result="loss", profit_loss=-1.0, dollar_pnl=-5.0, date="2026-02-11"),
        ]
        history = _make_history(bets)

        output = tmp_path / "dashboard.html"

        with (
            patch("workflow.stats.get_history", return_value=history),
            patch("workflow.stats.get_skips", return_value=[]),
            patch("workflow.stats.webbrowser"),
        ):
            generate_dashboard(str(output))

        assert output.exists()
        content = output.read_text()
        assert "chart.js" in content.lower()
        assert "1-1-0" in content  # record
        assert "NBA Betting Dashboard" in content

    def test_empty_history_prints_message(self, capsys):
        empty = {"bets": [], "summary": {"total_bets": 0, "wins": 0, "losses": 0, "pushes": 0, "win_rate": 0.0, "total_units_wagered": 0.0, "net_units": 0.0, "roi": 0.0, "by_confidence": {}, "by_primary_edge": {}, "by_bet_type": {}, "current_streak": "", "net_dollar_pnl": 0.0}}

        with (
            patch("workflow.stats.get_history", return_value=empty),
            patch("workflow.stats.get_skips", return_value=[]),
        ):
            generate_dashboard()

        captured = capsys.readouterr()
        assert "No bet history" in captured.out

    def test_with_skips(self, tmp_path):
        bets = [_make_bet(result="win", profit_loss=1.0)]
        history = _make_history(bets)
        skips = [
            {"matchup": "A @ B", "reason": "No edge", "date": "2026-02-10", "source": "synthesis", "outcome_resolved": True, "final_score": "A 100 @ B 105", "winner": "B"},
        ]

        output = tmp_path / "dashboard.html"

        with (
            patch("workflow.stats.get_history", return_value=history),
            patch("workflow.stats.get_skips", return_value=skips),
            patch("workflow.stats.webbrowser"),
        ):
            generate_dashboard(str(output))

        content = output.read_text()
        assert "A @ B" in content
        assert "No edge" in content
        assert "1 resolved" in content


# --- TestComputeAllBreakdowns ---

class TestComputeAllBreakdowns:
    def test_returns_all_keys(self):
        bets = [_make_bet()]
        result = compute_all_breakdowns(bets)
        assert "by_confidence" in result
        assert "by_edge_type" in result
        assert "by_bet_type" in result
        assert "by_pick_side" in result


# --- Paper Trading Helpers ---

def _make_paper_trade(**overrides) -> dict:
    """Factory for paper trade dicts with sensible defaults."""
    base = {
        "matchup": "Celtics @ Lakers",
        "date": "2026-02-10",
        "bet_type": "moneyline",
        "pick": "Lakers",
        "confidence": "medium",
        "skip_reason": "No clear edge",
        "units": 1.0,
        "result": "win",
        "profit_loss": 1.0,
    }
    base.update(overrides)
    return base


def _make_paper_history(trades: list) -> dict:
    """Build a paper history dict from a list of trades."""
    resolved = [t for t in trades if "result" in t]
    wins = sum(1 for t in resolved if t["result"] == "win")
    losses = sum(1 for t in resolved if t["result"] == "loss")
    pushes = sum(1 for t in resolved if t["result"] == "push")
    total = wins + losses + pushes
    net_units = sum(t.get("profit_loss", 0.0) for t in resolved)
    return {
        "trades": trades,
        "summary": {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": round(wins / total, 3) if total > 0 else 0.0,
            "net_units": round(net_units, 2),
        },
    }


# --- TestComputePaperOverview ---

class TestComputePaperOverview:
    def test_standard_summary(self):
        trades = [
            _make_paper_trade(result="win", profit_loss=1.0),
            _make_paper_trade(result="loss", profit_loss=-1.0),
            _make_paper_trade(result="win", profit_loss=0.5),
        ]
        history = _make_paper_history(trades)
        overview = compute_paper_overview(history)
        assert overview["wins"] == 2
        assert overview["losses"] == 1
        assert overview["pushes"] == 0
        assert overview["total_trades"] == 3
        assert overview["net_units"] == 0.5

    def test_empty_history(self):
        history = _make_paper_history([])
        overview = compute_paper_overview(history)
        assert overview["total_trades"] == 0
        assert overview["win_rate"] == 0.0
        assert overview["net_units"] == 0.0


# --- TestComputePaperBreakdowns ---

class TestComputePaperBreakdowns:
    def test_returns_all_keys(self):
        trades = [_make_paper_trade()]
        result = compute_paper_breakdowns(trades)
        assert "by_confidence" in result
        assert "by_bet_type" in result
        assert "by_skip_reason" in result

    def test_skip_reason_categorized(self):
        trades = [
            _make_paper_trade(skip_reason="No clear edge", result="win", profit_loss=1.0),
            _make_paper_trade(skip_reason="Injury concerns for star player", result="loss", profit_loss=-1.0),
            _make_paper_trade(skip_reason="Too uncertain and unpredictable", result="win", profit_loss=0.5),
        ]
        result = compute_paper_breakdowns(trades)
        reasons = {r["category"] for r in result["by_skip_reason"]}
        assert "no_edge" in reasons
        assert "injury_uncertainty" in reasons
        assert "high_variance" in reasons
        # Raw strings should NOT appear
        assert "No clear edge" not in reasons

    def test_empty(self):
        result = compute_paper_breakdowns([])
        assert result["by_confidence"] == []
        assert result["by_bet_type"] == []
        assert result["by_skip_reason"] == []


# --- TestGenerateDashboard (Paper Trading) ---

class TestGenerateDashboardPaper:
    def test_with_paper_trades(self, tmp_path):
        bets = [_make_bet(result="win", profit_loss=1.0)]
        history = _make_history(bets)
        paper_trades = [
            _make_paper_trade(result="win", profit_loss=1.0, date="2026-02-10"),
            _make_paper_trade(result="loss", profit_loss=-0.5, date="2026-02-11"),
        ]
        paper_history = _make_paper_history(paper_trades)

        output = tmp_path / "dashboard.html"

        with (
            patch("workflow.stats.get_history", return_value=history),
            patch("workflow.stats.get_skips", return_value=[]),
            patch("workflow.stats.get_paper_history", return_value=paper_history),
            patch("workflow.stats.webbrowser"),
        ):
            generate_dashboard(str(output))

        content = output.read_text()
        assert "Paper Trading" in content
        assert "paperPnlChart" in content
        assert "1-1-0" in content  # paper record

    def test_no_paper_trades(self, tmp_path):
        bets = [_make_bet(result="win", profit_loss=1.0)]
        history = _make_history(bets)
        paper_history = _make_paper_history([])

        output = tmp_path / "dashboard.html"

        with (
            patch("workflow.stats.get_history", return_value=history),
            patch("workflow.stats.get_skips", return_value=[]),
            patch("workflow.stats.get_paper_history", return_value=paper_history),
            patch("workflow.stats.webbrowser"),
        ):
            generate_dashboard(str(output))

        content = output.read_text()
        assert "Paper Trading" not in content
        assert "NBA Betting Dashboard" in content
