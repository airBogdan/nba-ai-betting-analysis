"""Head-to-head games analysis."""

import asyncio
from typing import Any, Dict, List, Optional, Tuple
from typing_extensions import TypedDict

from .api import get_head_to_head_games, get_game_statistics
from .utils import get_current_nba_season_year
from .types import Game, GameStatistics, H2HResults, TeamGameStats


class RawGameStats(TypedDict, total=False):
    """Raw game statistics from API."""
    points: int
    fgm: int
    fga: int
    fgp: str
    ftp: str
    tpm: int
    tpa: int
    tpp: str
    offReb: int
    defReb: int
    totReb: int
    assists: int
    steals: int
    turnovers: int
    blocks: int
    plusMinus: str


class ProcessedGameStats(TypedDict):
    """Processed game statistics."""
    points: int
    fgp: str
    ftp: str
    tpm: int
    tpp: str
    totReb: int
    assists: int
    steals: int
    turnovers: int
    blocks: int
    plusMinus: int
    ast_to_tov: float
    stocks: int  # steals + blocks (defensive disruption)


def process_game_stats(raw: RawGameStats) -> ProcessedGameStats:
    """Process raw game stats into computed metrics."""
    turnovers = raw.get("turnovers", 1) or 1
    plus_minus_str = raw.get("plusMinus", "0")
    try:
        plus_minus = int(plus_minus_str) if plus_minus_str and plus_minus_str != '--' else 0
    except ValueError:
        plus_minus = 0
    assists = raw.get("assists", 0) or 0
    steals = raw.get("steals", 0) or 0
    blocks = raw.get("blocks", 0) or 0

    # Compute FG% from fgm/fga — the API's fgp field is unreliable for away teams
    fgm = raw.get("fgm", 0) or 0
    fga = raw.get("fga", 0) or 0
    fgp = str(round(fgm / fga * 100, 1)) if fga > 0 else raw.get("fgp", "0")

    return {
        "points": raw.get("points", 0),
        "fgp": fgp,
        "ftp": raw.get("ftp", "0"),
        "tpm": raw.get("tpm", 0),
        "tpp": raw.get("tpp", "0"),
        "totReb": raw.get("totReb", 0),
        "assists": assists,
        "steals": steals,
        "turnovers": raw.get("turnovers", 0),
        "blocks": blocks,
        "plusMinus": plus_minus,
        "ast_to_tov": round(assists / turnovers, 2),
        "stocks": steals + blocks,
    }


def process_h2h_results(games: Optional[List[Any]]) -> Optional[H2HResults]:
    """Process raw H2H games into organized results by season."""
    if not games:
        return None

    current_season_year = get_current_nba_season_year()
    if not current_season_year:
        return None

    cutoff_year = current_season_year - 2
    processed_results: H2HResults = {}

    for game in games:
        season_year = game.get("season")

        # Skip games that are older than the cutoff year
        if season_year < cutoff_year:
            continue

        teams = game.get("teams", {})
        scores = game.get("scores", {})
        home_team = teams.get("home", {})
        visitor_team = teams.get("visitors", {})

        home_points = scores.get("home", {}).get("points")
        visitor_points = scores.get("visitors", {}).get("points")

        # Skip games with null scores
        if home_points is None or visitor_points is None:
            continue

        # Initialize array for this season if it doesn't exist
        if season_year not in processed_results:
            processed_results[season_year] = []

        # Determine winner
        if home_points > visitor_points:
            winner = home_team.get("name")
        elif visitor_points > home_points:
            winner = visitor_team.get("name")
        else:
            winner = "tie"

        # Parse linescore (quarter scores as strings to numbers)
        home_linescore_raw = scores.get("home", {}).get("linescore") or []
        visitor_linescore_raw = scores.get("visitors", {}).get("linescore") or []

        def parse_quarter_score(q) -> int:
            """Parse quarter score, returning 0 for invalid values like '--'."""
            if not q:
                return 0
            if isinstance(q, int):
                return q
            if isinstance(q, str) and q.isdigit():
                return int(q)
            return 0

        home_linescore = [parse_quarter_score(q) for q in home_linescore_raw]
        visitor_linescore = [parse_quarter_score(q) for q in visitor_linescore_raw]

        processed_results[season_year].append({
            "id": game.get("id"),
            "home_team": home_team.get("name"),
            "visitor_team": visitor_team.get("name"),
            "home_points": home_points,
            "visitor_points": visitor_points,
            "winner": winner,
            "point_diff": home_points - visitor_points,
            "home_linescore": home_linescore,
            "visitor_linescore": visitor_linescore,
        })

    return processed_results


async def h2h(team1_id: int, team2_id: int) -> Optional[H2HResults]:
    """Get head-to-head results between two teams."""
    if not team1_id or not team2_id:
        print(f"Invalid team IDs: team1_id={team1_id}, team2_id={team2_id}")
        return None

    resp = await get_head_to_head_games(team1_id, team2_id)
    return process_h2h_results(resp)


async def add_game_statistics_to_h2h_results(
    h2h_results: Optional[H2HResults]
) -> H2HResults:
    """Add detailed game statistics to H2H results.

    Fetches all game statistics in parallel using asyncio.gather().
    """
    if not h2h_results:
        return {}

    # Collect all games with their location info for later matching
    games_to_fetch: List[Tuple[int, int, int]] = []  # (year, index, game_id)
    for year in h2h_results:
        for i, game in enumerate(h2h_results[year]):
            games_to_fetch.append((year, i, game["id"]))

    if not games_to_fetch:
        return h2h_results

    # Fetch all game statistics in parallel
    # Use return_exceptions=True to prevent one failure from breaking all fetches
    print(f"Fetching statistics for {len(games_to_fetch)} games in parallel...")
    tasks = [get_game_statistics(game_id) for _, _, game_id in games_to_fetch]
    all_statistics = await asyncio.gather(*tasks, return_exceptions=True)

    # Match results back to games
    for (year, i, _game_id), statistics in zip(games_to_fetch, all_statistics):
        # Skip if this fetch failed (returned an exception)
        if isinstance(statistics, Exception):
            continue
        game = h2h_results[year][i]

        if statistics and len(statistics) >= 2:
            # Process home team statistics
            home_team_stats = next(
                (s for s in statistics if s.get("team", {}).get("name") == game["home_team"]),
                None
            )
            if home_team_stats and home_team_stats.get("statistics"):
                stats_list = home_team_stats["statistics"]
                if stats_list and len(stats_list) > 0:
                    processed = process_game_stats(stats_list[0])
                    h2h_results[year][i]["home_statistics"] = processed

            # Process visitor team statistics
            visitor_team_stats = next(
                (s for s in statistics if s.get("team", {}).get("name") == game["visitor_team"]),
                None
            )
            if visitor_team_stats and visitor_team_stats.get("statistics"):
                stats_list = visitor_team_stats["statistics"]
                if stats_list and len(stats_list) > 0:
                    processed = process_game_stats(stats_list[0])
                    h2h_results[year][i]["visitor_statistics"] = processed

    return h2h_results
