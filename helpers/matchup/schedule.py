"""Schedule and situational context computations."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..api import RecentGame
from .types import TeamSchedule


def compute_days_rest(
    recent_games: List[RecentGame],
    game_date: Optional[str] = None
) -> Optional[int]:
    """Compute days of rest before a game.

    Args:
        recent_games: List of recent games (most recent first)
        game_date: Target game date (YYYY-MM-DD or ISO). Defaults to today.
    """
    if not recent_games:
        return None

    last_game_date = datetime.strptime(recent_games[0]["date"], "%Y-%m-%d")

    if game_date:
        # Handle both "YYYY-MM-DD" and "YYYY-MM-DDTHH:MM:SS" formats
        target = datetime.strptime(game_date.split("T")[0], "%Y-%m-%d")
    else:
        target = datetime.now()

    target = target.replace(hour=0, minute=0, second=0, microsecond=0)
    last_game_date = last_game_date.replace(hour=0, minute=0, second=0, microsecond=0)

    return (target - last_game_date).days


def compute_streak(recent_games: List[RecentGame]) -> Dict[str, Any]:
    """Compute current win/loss streak."""
    if not recent_games:
        return {"type": None, "count": 0}

    first_result = recent_games[0]["result"]
    count = 0

    for game in recent_games:
        if game["result"] == first_result:
            count += 1
        else:
            break

    return {"type": first_result, "count": count}


def compute_games_last_n_days(
    recent_games: List[RecentGame],
    days: int = 7,
    game_date: Optional[str] = None
) -> int:
    """Count games played in the last N days.

    Args:
        recent_games: List of recent games
        days: Number of days to look back
        game_date: Reference date (YYYY-MM-DD or ISO). Defaults to today.
    """
    if not recent_games:
        return 0

    if game_date:
        target = datetime.strptime(game_date.split("T")[0], "%Y-%m-%d")
    else:
        target = datetime.now()

    target = target.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = target - timedelta(days=days)
    count = 0

    for game in recent_games:
        gd = datetime.strptime(game["date"], "%Y-%m-%d")
        if gd >= cutoff:
            count += 1

    return count


def compute_schedule_context(
    recent_games: List[RecentGame],
    game_date: Optional[str] = None
) -> TeamSchedule:
    """Compute schedule/situational context for a team.

    Args:
        recent_games: List of recent games
        game_date: Target game date (YYYY-MM-DD or ISO). Defaults to today.
    """
    days_rest = compute_days_rest(recent_games, game_date)
    streak_data = compute_streak(recent_games)
    games_last_7 = compute_games_last_n_days(recent_games, 7, game_date)

    # Format streak as string (e.g., "W3", "L2")
    if streak_data["type"] and streak_data["count"] > 0:
        streak_str = f"{streak_data['type']}{streak_data['count']}"
    else:
        streak_str = "N/A"

    # Compute opponent strength metrics
    total_opp_win_pct = 0.0
    valid_opp_count = 0
    quality_wins = 0
    quality_losses = 0

    for game in recent_games:
        opp_win_pct = game.get("vs_win_pct", 0.0)
        if opp_win_pct > 0:  # Only count if we have valid data
            total_opp_win_pct += opp_win_pct
            valid_opp_count += 1

            # Quality game = opponent is .500 or better
            if opp_win_pct >= 0.5:
                if game["result"] == "W":
                    quality_wins += 1
                else:
                    quality_losses += 1

    recent_opponent_avg_win_pct = round(total_opp_win_pct / valid_opp_count, 3) if valid_opp_count > 0 else 0.0

    return {
        "days_rest": days_rest,
        "streak": streak_str,
        "games_last_7_days": games_last_7,
        "recent_opponent_avg_win_pct": recent_opponent_avg_win_pct,
        "quality_wins": quality_wins,
        "quality_losses": quality_losses,
    }
