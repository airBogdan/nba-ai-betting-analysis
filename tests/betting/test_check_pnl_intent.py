from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from betting.check import (
    ADVERSE_THRESHOLD,
    compute_position_pnl,
    is_adverse,
)


class TestComputePositionPnl:
    """P&L computation must correctly reflect shares, value, and percentage."""

    def test_profitable_position(self):
        """When price goes up from entry, P&L should be positive."""
        result = compute_position_pnl(entry_price=0.60, live_price=0.70, amount=30.0)
        # 30 / 0.60 = 50 shares, 50 * 0.70 = 35.0 value, 35 - 30 = 5.0 profit
        assert result["shares"] == 50.0
        assert result["current_value"] == 35.0
        assert result["unrealized_pnl"] == 5.0
        assert result["pnl_pct"] > 0
        assert result["price_move"] == pytest.approx(0.10, abs=0.001)

    def test_losing_position(self):
        """When price drops from entry, P&L should be negative."""
        result = compute_position_pnl(entry_price=0.60, live_price=0.45, amount=30.0)
        assert result["unrealized_pnl"] < 0
        assert result["pnl_pct"] < 0
        assert result["price_move"] < 0

    def test_breakeven_position(self):
        """When price equals entry, P&L should be zero."""
        result = compute_position_pnl(entry_price=0.50, live_price=0.50, amount=20.0)
        assert result["unrealized_pnl"] == 0.0
        assert result["pnl_pct"] == 0.0
        assert result["price_move"] == 0.0

    def test_shares_calculation_is_amount_divided_by_entry(self):
        """Shares = amount / entry_price. This is how Polymarket works."""
        result = compute_position_pnl(entry_price=0.25, live_price=0.30, amount=50.0)
        assert result["shares"] == 200.0  # 50 / 0.25

    def test_pnl_percentage_is_relative_to_cost(self):
        """P&L percentage should be relative to the amount invested, not to share price."""
        result = compute_position_pnl(entry_price=0.50, live_price=0.60, amount=100.0)
        # 100/0.50 = 200 shares, 200*0.60 = 120, pnl = 20, pct = 20%
        assert result["pnl_pct"] == 20.0

    def test_zero_amount_returns_zero_pnl_pct(self):
        """Zero wager should not cause division by zero."""
        result = compute_position_pnl(entry_price=0.50, live_price=0.60, amount=0.0)
        assert result["pnl_pct"] == 0.0

    def test_values_are_rounded(self):
        """Results should be rounded to avoid floating point noise in output."""
        result = compute_position_pnl(entry_price=0.33, live_price=0.47, amount=10.0)
        # Shares, value, pnl should all be rounded (not raw float noise)
        assert isinstance(result["shares"], float)
        assert isinstance(result["current_value"], float)
        assert isinstance(result["unrealized_pnl"], float)
        # Check rounding precision
        assert str(result["pnl_pct"]).count(".") <= 1  # at most 1 decimal

    def test_high_entry_price_small_drop(self):
        """Expensive positions (near 1.0) with small drops have small P&L %."""
        result = compute_position_pnl(entry_price=0.90, live_price=0.88, amount=45.0)
        assert result["pnl_pct"] < 0
        assert abs(result["pnl_pct"]) < 5  # small percentage loss


class TestIsAdverse:
    """A position is adverse when price moved against us beyond the threshold."""

    def test_large_drop_is_adverse(self):
        """A 15pp price drop should be flagged as adverse."""
        pnl = {"price_move": -0.15}
        assert is_adverse(pnl) is True

    def test_small_drop_is_not_adverse(self):
        """A 5pp price drop is within normal fluctuation, not adverse."""
        pnl = {"price_move": -0.05}
        assert is_adverse(pnl) is False

    def test_price_increase_is_never_adverse(self):
        """If price went up, the position is profitable — never adverse."""
        pnl = {"price_move": 0.10}
        assert is_adverse(pnl) is False

    def test_zero_movement_is_not_adverse(self):
        """Flat price is not adverse."""
        pnl = {"price_move": 0.0}
        assert is_adverse(pnl) is False

    def test_exactly_at_threshold_is_not_adverse(self):
        """At exactly -0.10, it should NOT be adverse (strict inequality)."""
        pnl = {"price_move": -ADVERSE_THRESHOLD}
        assert is_adverse(pnl) is False

    def test_just_beyond_threshold_is_adverse(self):
        """Just past -0.10 triggers adverse."""
        pnl = {"price_move": -(ADVERSE_THRESHOLD + 0.001)}
        assert is_adverse(pnl) is True

    def test_custom_threshold(self):
        """Custom threshold should override the default."""
        pnl = {"price_move": -0.06}
        assert is_adverse(pnl, threshold=0.05) is True
        assert is_adverse(pnl, threshold=0.10) is False

    def test_default_threshold_is_ten_percent(self):
        """The default adverse threshold is 10 percentage points."""
        assert ADVERSE_THRESHOLD == 0.10
