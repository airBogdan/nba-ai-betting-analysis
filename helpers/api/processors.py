"""Data processing functions and hybrid fetch+process functions."""

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..utils import get_current_nba_season_year
from .types import (
    TeamPlayerStatistics,
    ProcessedPlayerStats,
    RawTeamStats,
    ProcessedTeamStats,
    RecentGame,
    ScheduledGame,
)
from .client import fetch_nba_api, get_team_statistics, get_games_by_date

_ET = ZoneInfo("America/New_York")

RECENT_GAMES_LIMIT = 10
TOP_PLAYERS = 10
MIN_PLAYER_GAMES = 3

_FALLBACK_EFFICIENCY = 113.5  # avoid circular import with matchup.py
LEAGUE_EFFICIENCY_CACHE = Path(__file__).parent.parent.parent / "bets" / "cache" / "league_avg_efficiency.json"
LEAGUE_EFFICIENCY_MAX_AGE_DAYS = 30


def parse_minutes(min_str: str) -> float:
    """Parse minutes string (e.g., '32:45') to float."""
    if not min_str or min_str == '--':
        return 0.0
    parts = min_str.split(":")
    # Handle '--' or non-numeric values in parts
    try:
        minutes = int(parts[0]) if parts[0] and parts[0] != '--' else 0
        seconds = int(parts[1]) if len(parts) > 1 and parts[1] and parts[1] != '--' else 0
    except ValueError:
        return 0.0
    return minutes + seconds / 60


def process_player_statistics(
    raw_stats: List[TeamPlayerStatistics],
    top_n: int = TOP_PLAYERS,
    min_games: int = MIN_PLAYER_GAMES
) -> List[ProcessedPlayerStats]:
    """
    Process raw player statistics into aggregated per-game stats.

    Args:
        raw_stats: Raw player game logs from API
        top_n: Number of top players to return (by minutes)
        min_games: Minimum games played to be included

    Returns:
        List of processed player stats, sorted by minutes per game
    """
    if not raw_stats:
        return []

    # Group stats by player id
    by_player: Dict[int, Dict[str, Any]] = {}

    for stat in raw_stats:
        player = stat.get("player")
        if not player or "id" not in player:
            continue
        pid = player["id"]
        if pid not in by_player:
            by_player[pid] = {
                "name": f"{player.get('firstname', '')} {player.get('lastname', '')}".strip(),
                "games": []
            }
        by_player[pid]["games"].append(stat)

    # Aggregate each player's stats
    aggregated: List[ProcessedPlayerStats] = []

    for player_id, data in by_player.items():
        games = data["games"]
        game_count = len(games)

        # Skip players with too few games
        if game_count < min_games:
            continue

        # Sum up all stats
        total_min = 0.0
        total_pts = 0
        total_reb = 0
        total_ast = 0
        total_stl = 0
        total_blk = 0
        total_tov = 0
        total_fgm = 0
        total_fga = 0
        total_tpm = 0
        total_tpa = 0
        total_ftm = 0
        total_fta = 0
        total_pm = 0

        for g in games:
            total_min += parse_minutes(g.get("min", ""))
            total_pts += g.get("points", 0) or 0
            total_reb += g.get("totReb", 0) or 0
            total_ast += g.get("assists", 0) or 0
            total_stl += g.get("steals", 0) or 0
            total_blk += g.get("blocks", 0) or 0
            total_tov += g.get("turnovers", 0) or 0
            total_fgm += g.get("fgm", 0) or 0
            total_fga += g.get("fga", 0) or 0
            total_tpm += g.get("tpm", 0) or 0
            total_tpa += g.get("tpa", 0) or 0
            total_ftm += g.get("ftm", 0) or 0
            total_fta += g.get("fta", 0) or 0
            pm_str = g.get("plusMinus", "0")
            try:
                total_pm += int(pm_str) if pm_str and pm_str != '--' else 0
            except ValueError:
                pass  # Skip invalid plus/minus values

        aggregated.append({
            "id": player_id,
            "name": data["name"],
            "games": game_count,
            "mpg": round(total_min / game_count, 1),
            "ppg": round(total_pts / game_count, 1),
            "rpg": round(total_reb / game_count, 1),
            "apg": round(total_ast / game_count, 1),
            "disruption": round((total_stl + total_blk) / game_count, 1),
            "fgp": round((total_fgm / total_fga) * 100, 1) if total_fga > 0 else 0.0,
            "tpp": round((total_tpm / total_tpa) * 100, 1) if total_tpa > 0 else 0.0,
            "plus_minus": round(total_pm / game_count, 1),
        })

    # Sort by minutes per game and return top N
    aggregated.sort(key=lambda x: x["mpg"], reverse=True)
    return aggregated[:top_n]


def process_team_stats(raw: RawTeamStats) -> ProcessedTeamStats:
    """Process raw team statistics into derived metrics."""
    games = raw.get("games", 1) or 1
    points = raw.get("points", 0) or 0
    ppg = round(points / games, 1)

    # Pace estimate: possessions ≈ FGA + 0.44*FTA + TOV - OREB
    fga = raw.get("fga", 0) or 0
    fta = raw.get("fta", 0) or 0
    turnovers = raw.get("turnovers", 0) or 0
    off_reb = raw.get("offReb", 0) or 0
    tot_reb = raw.get("totReb", 0) or 0

    possessions = fga + 0.44 * fta + turnovers - off_reb
    pace = round(possessions / games, 1)

    assists = raw.get("assists", 0) or 0
    steals = raw.get("steals", 0) or 0
    blocks = raw.get("blocks", 0) or 0
    plus_minus = raw.get("plusMinus", 0) or 0

    return {
        "games": raw.get("games", 0),
        "ppg": ppg,
        "apg": round(assists / games, 1),
        "rpg": round(tot_reb / games, 1),
        "topg": round(turnovers / games, 1),
        "disruption": round((steals + blocks) / games, 1),
        "net_rating": round(plus_minus / games, 2),
        "tpp": float(raw.get("tpp", "0") or "0"),
        "fgp": float(raw.get("fgp", "0") or "0"),
        "pace": pace,
    }


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


async def get_team_statistics_for_seasons(
    team_id: int,
    num_seasons: int = 2,
    season: Optional[int] = None,
) -> Optional[Dict[int, ProcessedTeamStats]]:
    """Get processed team statistics for multiple seasons.

    Args:
        team_id: Team ID to fetch stats for
        num_seasons: Number of seasons to fetch (default 2)
        season: Base season year. If None, uses current season.
    """
    current_season = season or get_current_nba_season_year()
    if not current_season:
        return None

    seasons_stats: Dict[int, ProcessedTeamStats] = {}

    for i in range(num_seasons):
        season_year = current_season - i
        stats = await get_team_statistics(team_id, season_year)

        if stats and len(stats) > 0:
            seasons_stats[season_year] = process_team_stats(stats[0])

    return seasons_stats


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


async def get_team_recent_games(
    team_id: int,
    season: int,
    all_standings: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[RecentGame]:
    """
    Get recent completed games for a team.

    Args:
        team_id: Team ID to fetch games for
        season: Season year
        all_standings: Optional dict of all team standings for opponent lookup
    """
    raw_games = await fetch_nba_api(f"games?team={team_id}&season={season}")
    if not raw_games:
        return []

    def is_valid_score(score) -> bool:
        """Check if score is a valid integer (not None, not '--')."""
        if score is None:
            return False
        if isinstance(score, int):
            return True
        if isinstance(score, str):
            return score.isdigit() or (score.startswith('-') and score[1:].isdigit())
        return False

    # Filter to completed games only (status.short === 3 means finished)
    completed = [
        g for g in raw_games
        if g.get("status", {}).get("short") == 3
        and is_valid_score(g.get("scores", {}).get("home", {}).get("points"))
        and is_valid_score(g.get("scores", {}).get("visitors", {}).get("points"))
    ]

    # Sort by date descending (most recent first)
    completed.sort(
        key=lambda g: g.get("date", {}).get("start", ""),
        reverse=True
    )

    # Take the last N games and process
    results: List[RecentGame] = []
    for game in completed[:RECENT_GAMES_LIMIT]:
        is_home = game["teams"]["home"]["id"] == team_id
        team_points = (
            game["scores"]["home"]["points"]
            if is_home
            else game["scores"]["visitors"]["points"]
        )
        opp_points = (
            game["scores"]["visitors"]["points"]
            if is_home
            else game["scores"]["home"]["points"]
        )
        opponent = (
            game["teams"]["visitors"]["name"]
            if is_home
            else game["teams"]["home"]["name"]
        )

        # Look up opponent's record
        vs_record = "N/A"
        vs_win_pct = 0.0
        if all_standings and opponent in all_standings:
            opp_data = all_standings[opponent]
            vs_record = f"{opp_data['wins']}-{opp_data['losses']}"
            vs_win_pct = opp_data["win_pct"]

        results.append({
            "vs": opponent,
            "vs_record": vs_record,
            "vs_win_pct": vs_win_pct,
            "result": "W" if team_points > opp_points else "L",
            "score": f"{team_points}-{opp_points}",
            "home": is_home,
            "margin": team_points - opp_points,
            "date": game["date"]["start"].split("T")[0],
        })

    return results


def _utc_to_et_date(date_start_str: Optional[str]) -> Optional[str]:
    """Convert a UTC ISO 8601 timestamp to a US Eastern date string (YYYY-MM-DD).

    Returns None if the input is missing or unparseable.
    """
    if not date_start_str:
        return None
    try:
        # Parse ISO 8601 UTC timestamp (e.g. "2026-02-11T00:30:00.000Z")
        utc_dt = datetime.fromisoformat(date_start_str.replace("Z", "+00:00"))
        et_dt = utc_dt.astimezone(_ET)
        return et_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


async def get_scheduled_games(season: int, target_date: str) -> List[ScheduledGame]:
    """
    Get scheduled games for a US Eastern date with filtered fields.

    Queries the API for both the target UTC date and the next day, then filters
    to games whose start time falls on the target date in US Eastern time.

    Args:
        season: NBA season year (e.g., 2025)
        target_date: Date in YYYY-MM-DD format (e.g., '2026-02-01')

    Returns:
        List of games with id, date_start, status, and teams (id/name only)
    """
    next_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    day1_games, day2_games = await asyncio.gather(
        get_games_by_date(season, target_date),
        get_games_by_date(season, next_date),
    )

    all_games = (day1_games or []) + (day2_games or [])

    # Deduplicate by game ID
    seen_ids: set[int] = set()
    unique_games = []
    for game in all_games:
        gid = game["id"]
        if gid not in seen_ids:
            seen_ids.add(gid)
            unique_games.append(game)

    results: List[ScheduledGame] = []
    for game in unique_games:
        et_date = _utc_to_et_date(game["date"]["start"])
        if et_date != target_date:
            continue
        results.append({
            "id": game["id"],
            "date_start": game["date"]["start"],
            "status": {
                "clock": game["status"]["clock"],
                "halftime": game["status"]["halftime"],
                "long": game["status"]["long"],
            },
            "teams": {
                "visitors": {
                    "id": game["teams"]["visitors"]["id"],
                    "name": game["teams"]["visitors"]["name"],
                },
                "home": {
                    "id": game["teams"]["home"]["id"],
                    "name": game["teams"]["home"]["name"],
                },
            },
        })

    return results
