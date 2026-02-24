"""Tests for helpers/utils.py."""

from datetime import datetime
from unittest.mock import patch

import pytest

from sports.nba.utils import get_current_nba_season_year


class TestGetCurrentNbaSeasonYear:
    """Tests for get_current_nba_season_year function."""

    @pytest.mark.parametrize("month,expected_year", [
        (9, 2024),   # September - season starts
        (10, 2024),  # October
        (11, 2024),  # November
        (12, 2024),  # December
    ])
    def test_fall_months_return_current_year(self, month, expected_year):
        """Season year is current year for September-December."""
        with patch("sports.nba.utils.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, month, 15)
            result = get_current_nba_season_year()
            assert result == expected_year

    @pytest.mark.parametrize("month,expected_year", [
        (1, 2023),  # January
        (2, 2023),  # February
        (3, 2023),  # March
        (4, 2023),  # April
        (5, 2023),  # May
    ])
    def test_spring_months_return_previous_year(self, month, expected_year):
        """Season year is previous year for January-May."""
        with patch("sports.nba.utils.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, month, 15)
            result = get_current_nba_season_year()
            assert result == expected_year

    @pytest.mark.parametrize("month", [6, 7, 8])
    def test_summer_months_return_none(self, month):
        """Returns None for off-season months (June-August)."""
        with patch("sports.nba.utils.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, month, 15)
            result = get_current_nba_season_year()
            assert result is None

    def test_boundary_september_first(self):
        """September 1st should return current year."""
        with patch("sports.nba.utils.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 9, 1)
            result = get_current_nba_season_year()
            assert result == 2024

    def test_boundary_may_last_day(self):
        """May 31st should return previous year."""
        with patch("sports.nba.utils.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 5, 31)
            result = get_current_nba_season_year()
            assert result == 2023

    def test_boundary_june_first(self):
        """June 1st should return None (off-season starts)."""
        with patch("sports.nba.utils.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 6, 1)
            result = get_current_nba_season_year()
            assert result is None

    def test_boundary_august_last_day(self):
        """August 31st should return None (still off-season)."""
        with patch("sports.nba.utils.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 8, 31)
            result = get_current_nba_season_year()
            assert result is None
