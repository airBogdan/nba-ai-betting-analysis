"""Utility functions for NBA analytics."""

from datetime import datetime
from typing import Optional


def get_current_nba_season_year() -> Optional[int]:
    """
    Get the current NBA season year.

    NBA season runs from September to May.
    - If current month is between September and December, season started this year
    - If current month is between January and May, season started previous year
    - If current month is between June and August, we're outside the season

    Returns:
        The season start year, or None if outside season months.
    """
    current_date = datetime.now()
    current_month = current_date.month
    current_year = current_date.year

    if 9 <= current_month <= 12:
        return current_year
    elif 1 <= current_month <= 5:
        return current_year - 1
    else:
        return None  # Outside of season months
