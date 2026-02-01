"""Team standings processing."""

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

from .api import get_team_standings
from .utils import get_current_nba_season_year


class SeasonStanding(TypedDict):
    """Processed team standings for a season."""
    season: int
    conference_rank: int
    wins: int
    losses: int
    win_pct: str
    home_wins: int
    home_losses: int
    away_wins: int
    away_losses: int
    last_ten_wins: int
    last_ten_losses: int
    # Computed properties
    home_win_pct: float
    away_win_pct: float
    last_ten_pct: float
    home_court_advantage: float


class RawStanding(TypedDict, total=False):
    """Raw standing data from API."""
    conference: Dict[str, Any]  # { name: str, rank: int }
    win: Dict[str, Any]  # { home, away, total, percentage, lastTen }
    loss: Dict[str, Any]  # { home, away, total, lastTen }


def process_standing(season: int, raw: RawStanding) -> SeasonStanding:
    """Process raw standing data into computed metrics."""
    win = raw.get("win", {})
    loss = raw.get("loss", {})
    conf = raw.get("conference", {})

    home_wins = win.get("home", 0)
    home_losses = loss.get("home", 0)
    away_wins = win.get("away", 0)
    away_losses = loss.get("away", 0)

    home_games = home_wins + home_losses
    away_games = away_wins + away_losses

    home_win_pct = round(home_wins / home_games, 3) if home_games > 0 else 0.0
    away_win_pct = round(away_wins / away_games, 3) if away_games > 0 else 0.0
    last_ten_pct = round(win.get("lastTen", 0) / 10, 2)

    win_pct_str = win.get("percentage", "0")
    win_pct = float(win_pct_str) if win_pct_str else 0.0

    return {
        "season": season,
        "conference_rank": conf.get("rank", 0),
        "wins": win.get("total", 0),
        "losses": loss.get("total", 0),
        "win_pct": win_pct_str,
        "home_wins": home_wins,
        "home_losses": home_losses,
        "away_wins": away_wins,
        "away_losses": away_losses,
        "last_ten_wins": win.get("lastTen", 0),
        "last_ten_losses": loss.get("lastTen", 0),
        "home_win_pct": home_win_pct,
        "away_win_pct": away_win_pct,
        "last_ten_pct": last_ten_pct,
        "home_court_advantage": round(home_win_pct - away_win_pct, 3),
    }


async def get_team_standings_for_seasons(
    team_id: int,
    num_seasons: int = 2,
    season: Optional[int] = None,
) -> Optional[List[SeasonStanding]]:
    """Get standings for a team across multiple seasons.

    Args:
        team_id: Team ID to fetch standings for
        num_seasons: Number of seasons to fetch (default 2)
        season: Base season year. If None, uses current season.
    """
    current_season = season or get_current_nba_season_year()
    if not current_season:
        return None

    seasons: List[SeasonStanding] = []
    for i in range(num_seasons):
        season_year = current_season - i
        standings = await get_team_standings(team_id, season_year)

        if standings and len(standings) > 0:
            seasons.append(process_standing(season_year, standings[0]))

    return seasons


async def get_teams_standings(
    team1_id: int,
    team1_name: str,
    team2_id: int,
    team2_name: str,
    season: Optional[int] = None,
) -> Dict[str, List[SeasonStanding]]:
    """Get standings for two teams.

    Args:
        team1_id: First team ID
        team1_name: First team name
        team2_id: Second team ID
        team2_name: Second team name
        season: Base season year. If None, uses current season.
    """
    team1_standings = await get_team_standings_for_seasons(team1_id, season=season)
    team2_standings = await get_team_standings_for_seasons(team2_id, season=season)

    teams_standings: Dict[str, List[SeasonStanding]] = {}

    if team1_standings:
        teams_standings[team1_name] = team1_standings
    if team2_standings:
        teams_standings[team2_name] = team2_standings

    return teams_standings
