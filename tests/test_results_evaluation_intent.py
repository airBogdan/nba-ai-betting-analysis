import asyncio
from unittest.mock import AsyncMock, patch

import pytest


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


class TestMoneylineBetEvaluation:
    """Moneyline bets should win when the picked team wins, lose otherwise."""

    def test_moneyline_win_when_picked_team_wins(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(pick="Lakers", units=2.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "win"
        assert pnl == 2.0

    def test_moneyline_loss_when_picked_team_loses(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(pick="Lakers", units=2.0)
        result = _make_game_result(winner="Boston Celtics")
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "loss"
        assert pnl == -2.0

    def test_moneyline_handles_partial_team_names(self):
        """Pick 'Celtics' should match 'Boston Celtics' in result."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(pick="Celtics", units=1.5)
        result = _make_game_result(winner="Boston Celtics")
        outcome, _ = _evaluate_bet(bet, result)
        assert outcome == "win"


class TestSpreadBetEvaluation:
    """Spread bets evaluate margin + line to determine cover."""

    def test_favorite_covers_spread(self):
        """Home team favored by 5 (-5) and wins by 10 -> covers."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-5.0, units=2.0)
        result = _make_game_result(home_score=115, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # margin=10, line=-5, adjusted=5 > 0 => win
        assert outcome == "win"
        assert pnl == 2.0

    def test_favorite_fails_to_cover(self):
        """Home team favored by 7 (-7) but only wins by 3 -> loss."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-7.0, units=1.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # margin=3, line=-7, adjusted=-4 < 0 => loss
        assert outcome == "loss"
        assert pnl == -1.0

    def test_spread_push_on_exact_margin(self):
        """Favorite wins by exactly the spread -> push, no profit/loss."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Lakers", line=-5.0, units=2.0)
        result = _make_game_result(home_score=110, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # margin=5, line=-5, adjusted=0 => push
        assert outcome == "push"
        assert pnl == 0.0

    def test_underdog_covers_spread(self):
        """Away team getting +6.5 and loses by only 3 -> covers."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Celtics", line=6.5, units=1.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, _ = _evaluate_bet(bet, result)
        # picked away: margin = 105-108 = -3, line=+6.5, adjusted=3.5 > 0 => win
        assert outcome == "win"

    def test_underdog_loses_by_more_than_spread(self):
        """Away team getting +4 but loses by 10 -> doesn't cover."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="spread", pick="Celtics", line=4.0, units=1.0)
        result = _make_game_result(home_score=115, away_score=105)
        outcome, _ = _evaluate_bet(bet, result)
        # margin = 105-115 = -10, line=+4, adjusted=-6 < 0 => loss
        assert outcome == "loss"


class TestTotalsBetEvaluation:
    """Over/under bets compare actual total against the line."""

    def test_over_wins_when_total_exceeds_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="over", line=220.5, units=1.5)
        result = _make_game_result(home_score=115, away_score=110)
        outcome, pnl = _evaluate_bet(bet, result)
        # total=225 > 220.5 => win
        assert outcome == "win"
        assert pnl == 1.5

    def test_over_loses_when_total_under_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="over", line=230.5, units=1.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        # total=213 < 230.5 => loss
        assert outcome == "loss"
        assert pnl == -1.0

    def test_under_wins_when_total_below_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="under", line=230.5, units=2.0)
        result = _make_game_result(home_score=108, away_score=105)
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "win"
        assert pnl == 2.0

    def test_under_loses_when_total_above_line(self):
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="under", line=210.5, units=1.0)
        result = _make_game_result(home_score=115, away_score=110)
        outcome, _ = _evaluate_bet(bet, result)
        assert outcome == "loss"

    def test_total_push_on_exact_line(self):
        """When total exactly hits the line, it's a push."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_bet(bet_type="total", pick="over", line=223.0, units=1.0)
        result = _make_game_result(home_score=115, away_score=108)
        outcome, pnl = _evaluate_bet(bet, result)
        assert outcome == "push"
        assert pnl == 0.0


class TestPlayerPropEvaluation:
    """Player prop bets compare actual stat against a line."""

    def test_over_wins_when_stat_exceeds_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="over", line=25.5, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 30.0)
        assert outcome == "win"
        assert pnl == 1.0

    def test_over_loses_when_stat_below_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="over", line=25.5, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 20.0)
        assert outcome == "loss"
        assert pnl == -1.0

    def test_under_wins_when_stat_below_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="under", line=25.5, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 20.0)
        assert outcome == "win"

    def test_prop_push_on_exact_line(self):
        from workflow.evaluation import _evaluate_prop_bet

        bet = _make_prop_bet(pick="over", line=25.0, units=1.0)
        outcome, pnl = _evaluate_prop_bet(bet, 25.0)
        assert outcome == "push"
        assert pnl == 0.0

    def test_player_prop_raises_if_evaluated_as_regular_bet(self):
        """_evaluate_bet must NOT handle player props — forces callers to use the right path."""
        from workflow.evaluation import _evaluate_bet

        bet = _make_prop_bet()
        result = _make_game_result()
        with pytest.raises(ValueError, match="player_prop"):
            _evaluate_bet(bet, result)


class TestDollarPnl:
    """Dollar P&L tracks real money returns alongside unit-based tracking."""

    def test_favorite_payout(self):
        """Betting $150 at -150: profit = $100 -> payout = $250."""
        from workflow.evaluation import calculate_payout

        payout = calculate_payout(150.0, -150, "win")
        assert payout == 250.0

    def test_underdog_payout(self):
        """Betting $100 at +130: profit = $130 -> payout = $230."""
        from workflow.evaluation import calculate_payout

        payout = calculate_payout(100.0, 130, "win")
        assert payout == 230.0

    def test_loss_returns_zero(self):
        """On a loss, payout is $0 (stake already deducted when placed)."""
        from workflow.evaluation import calculate_payout

        assert calculate_payout(100.0, -110, "loss") == 0.0

    def test_push_returns_stake(self):
        """Push returns exactly the staked amount."""
        from workflow.evaluation import calculate_payout

        assert calculate_payout(100.0, -110, "push") == 100.0

    def test_zero_odds_not_reached(self):
        """odds_price=0 is never passed to calculate_payout — the caller guards against it."""
        # The guard in results.py: `if amount and odds_price:` skips when odds_price=0
        # So calculate_payout is never called with odds_price=0 in practice.
        # This test documents that the caller is responsible for validation.
        from workflow.results import _build_completed_bets

        bet = _make_bet(amount=100.0, odds_price=0, units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert "dollar_pnl" not in completed[0]

    def test_dollar_pnl_computed_in_completed_bet(self):
        """When a bet has amount + odds_price, the completed bet should include dollar_pnl."""
        from workflow.results import _build_completed_bets

        bet = _make_bet(amount=100.0, odds_price=-110, units=1.0)
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert len(completed) == 1
        # Win at -110: payout = 100*(1 + 100/110) ≈ 190.91; pnl ≈ +90.91
        assert completed[0]["dollar_pnl"] == pytest.approx(90.91, abs=0.01)

    def test_no_dollar_pnl_without_amount_or_odds(self):
        """Bets without amount/odds_price should not have dollar_pnl field."""
        from workflow.results import _build_completed_bets

        bet = _make_bet(units=1.0)  # No amount or odds_price
        result = _make_game_result(winner="Los Angeles Lakers")
        matched = [(bet, result, "win", 1.0)]

        with patch("workflow.results.reflect_on_bet", new_callable=AsyncMock, return_value=None):
            completed = asyncio.get_event_loop().run_until_complete(
                _build_completed_bets(matched)
            )

        assert "dollar_pnl" not in completed[0]
