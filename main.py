"""NBA Analytics main entry point."""

import asyncio
import json
import sys
from pathlib import Path

from helpers.api import (
    get_scheduled_games,
    get_team_statistics_for_seasons,
    get_team_players_statistics,
    get_team_recent_games,
    get_all_standings,
    process_player_statistics,
)
from helpers.teams import get_teams_standings
from helpers.games import h2h, compute_h2h_summary, add_game_statistics_to_h2h_results
from helpers.matchup import build_matchup_analysis


# Output directory (relative to this file)
OUTPUT_DIR = Path(__file__).parent / "output"


def write_json(filename: str, data: dict) -> None:
    """Write data to JSON file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Written: {filepath}")


async def analyze_game(
    home_id: int,
    home_name: str,
    away_id: int,
    away_name: str,
    game_date: str,
    season: int,
) -> dict:
    """Analyze a single matchup and return the analysis dict."""
    team1_id, team1_name = home_id, home_name
    team2_id, team2_name = away_id, away_name
    home_team = home_name

    # Pass season to all functions that need it
    teams_standings = await get_teams_standings(
        team1_id, team1_name, team2_id, team2_name, season=season
    )

    h2h_results = await h2h(team1_id, team2_id)
    h2h_results = await add_game_statistics_to_h2h_results(h2h_results)
    h2h_summary = compute_h2h_summary(h2h_results, team1_name, team2_name) if h2h_results else None

    team1_stats = await get_team_statistics_for_seasons(team1_id, season=season)
    team2_stats = await get_team_statistics_for_seasons(team2_id, season=season)

    team1_raw_stats = await get_team_players_statistics(team1_id, season)
    team1_players = process_player_statistics(team1_raw_stats or [])

    team2_raw_stats = await get_team_players_statistics(team2_id, season)
    team2_players = process_player_statistics(team2_raw_stats or [])

    all_standings = await get_all_standings(season)

    team1_recent_games = await get_team_recent_games(team1_id, season, 5, all_standings)
    team2_recent_games = await get_team_recent_games(team2_id, season, 5, all_standings)

    matchup_analysis = build_matchup_analysis({
        "team1_name": team1_name,
        "team2_name": team2_name,
        "home_team": home_team,
        "team1_standings": teams_standings.get(team1_name, []),
        "team2_standings": teams_standings.get(team2_name, []),
        "team1_stats": team1_stats,
        "team2_stats": team2_stats,
        "team1_players": team1_players,
        "team2_players": team2_players,
        "team1_recent_games": team1_recent_games,
        "team2_recent_games": team2_recent_games,
        "h2h_summary": h2h_summary,
        "h2h_results": h2h_results,
        "game_date": game_date,
    })

    return matchup_analysis


async def main() -> None:
    """Process all games for a given date."""
    if len(sys.argv) != 2:
        print("Usage: python main.py YYYY-MM-DD")
        sys.exit(1)

    game_date = sys.argv[1]  # e.g., "2026-01-31"
    season = 2025  # Hardcoded for now

    # Fetch all scheduled games for the date
    games = await get_scheduled_games(season, game_date)
    if not games:
        print(f"No games found for {game_date}")
        return

    print(f"Found {len(games)} games for {game_date}")

    for game in games:
        home = game["teams"]["home"]
        away = game["teams"]["visitors"]

        print(f"\nProcessing: {away['name']} @ {home['name']}")

        try:
            analysis = await analyze_game(
                home_id=home["id"],
                home_name=home["name"],
                away_id=away["id"],
                away_name=away["name"],
                game_date=game_date,
                season=season,
            )

            # Filename: away_vs_home_date.json (standard "@ notation")
            away_slug = away["name"].lower().replace(" ", "_")
            home_slug = home["name"].lower().replace(" ", "_")
            filename = f"{away_slug}_vs_{home_slug}_{game_date}.json"

            write_json(filename, analysis)

        except Exception as e:
            print(f"Error processing {away['name']} @ {home['name']}: {e}")
            continue

    print(f"\nDone. Processed {len(games)} games.")


def run() -> None:
    """Run the main function."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
