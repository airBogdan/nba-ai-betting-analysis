"""League-wide data: standings and efficiency computation."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .client import fetch_nba_api, get_team_statistics
from .transforms import process_team_stats

_FALLBACK_EFFICIENCY = 113.5  # avoid circular import with matchup.py
LEAGUE_EFFICIENCY_CACHE = Path(__file__).parent.parent.parent / "bets" / "cache" / "league_avg_efficiency.json"
LEAGUE_EFFICIENCY_MAX_AGE_DAYS = 30


async def get_all_standings(season: int) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Get standings for all teams in a season.

    Returns a dict keyed by team name with record info:
    {
        "Atlanta Hawks": {"wins": 11, "losses": 8, "win_pct": 0.579},
        ...
    }
    """
    raw = await fetch_nba_api(f"standings?league=standard&season={season}")
    if not raw:
        return None

    standings: Dict[str, Dict[str, Any]] = {}
    for entry in raw:
        team_name = entry.get("team", {}).get("name")
        if not team_name:
            continue

        win = entry.get("win", {})
        loss = entry.get("loss", {})
        wins = win.get("total", 0) or 0
        losses = loss.get("total", 0) or 0
        win_pct_str = win.get("percentage", "0")
        win_pct = float(win_pct_str) if win_pct_str else 0.0

        standings[team_name] = {
            "wins": wins,
            "losses": losses,
            "win_pct": win_pct,
        }

    return standings


async def compute_league_avg_efficiency(season: int) -> float:
    """Compute league-average offensive efficiency, cached to bets/cache/.

    Fetches all teams' season stats, computes avg (ppg/pace)*100.
    Cache is valid for 30 days. Falls back to _FALLBACK_EFFICIENCY on any failure.
    """
    # Try cache
    try:
        if LEAGUE_EFFICIENCY_CACHE.exists():
            with open(LEAGUE_EFFICIENCY_CACHE) as f:
                cached = json.load(f)
            cached_date = datetime.strptime(cached["date"], "%Y-%m-%d").date()
            if cached.get("season") == season and (date.today() - cached_date).days < LEAGUE_EFFICIENCY_MAX_AGE_DAYS:
                return cached["efficiency"]
    except (json.JSONDecodeError, KeyError, ValueError):
        pass  # stale/corrupt cache, recompute

    # Fetch all teams, filter to real NBA franchises (exclude international/all-star)
    all_teams = await fetch_nba_api("teams")
    if not all_teams:
        return _FALLBACK_EFFICIENCY

    teams = [t for t in all_teams if t.get("nbaFranchise") is True and t.get("allStar") is not True]

    # Fetch each team's stats, compute ORTG = (ppg / pace) * 100
    ortgs = []
    for team in teams:
        team_id = team.get("id")
        if not team_id:
            continue
        raw = await get_team_statistics(team_id, season)
        if raw and len(raw) > 0:
            stats = process_team_stats(raw[0])
            pace = stats["pace"]
            if pace > 0:
                ortgs.append(stats["ppg"] / pace * 100)

    if not ortgs:
        return _FALLBACK_EFFICIENCY

    efficiency = round(sum(ortgs) / len(ortgs), 1)

    # Write cache
    try:
        LEAGUE_EFFICIENCY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(LEAGUE_EFFICIENCY_CACHE, "w") as f:
            json.dump({"date": str(date.today()), "season": season, "efficiency": efficiency, "teams": len(ortgs)}, f)
    except OSError:
        pass  # non-fatal if cache write fails

    return efficiency
