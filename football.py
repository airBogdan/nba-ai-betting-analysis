"""Football goal analysis CLI."""

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from dotenv import load_dotenv


def validate_date(date_str: str) -> str:
    """Validate date format is YYYY-MM-DD."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        print(f"Error: Invalid date '{date_str}'. Use YYYY-MM-DD format.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Football Goal Analysis")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze matches for goal probabilities")
    analyze.add_argument(
        "--league", "-l", required=True,
        help="League: epl, la_liga, bundesliga, serie_a, ligue_1, eredivisie, ucl, uel",
    )
    analyze.add_argument("--date", "-d", help="YYYY-MM-DD (default: today)")

    leagues_cmd = sub.add_parser("leagues", help="Show league shorthand mapping")
    leagues_cmd.add_argument(
        "--verify", action="store_true",
        help="Verify IDs against live API",
    )

    sub.add_parser("merge", help="Merge all league reports into all.html")

    sub.add_parser("live-update", help="Update all.html with live match probabilities")

    avg_cmd = sub.add_parser("league-averages", help="Compute league average goals/game")
    avg_cmd.add_argument(
        "--force", action="store_true",
        help="Force recompute even if cache is fresh",
    )

    args = parser.parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.command == "analyze":
        if args.date:
            validate_date(args.date)

        from sports.football.analysis import run_analysis

        asyncio.run(run_analysis(args.league, args.date))

    elif args.command == "leagues":
        from sports.football.client import LEAGUES

        print("League shorthand → API ID:")
        for shorthand, league_id in LEAGUES.items():
            print(f"  {shorthand:<12s} → {league_id}")

        if args.verify:
            from sports.football.client import close_session, fetch_leagues

            async def verify():
                try:
                    api_leagues = await fetch_leagues()
                    api_by_id = {str(l["league_id"]): l for l in api_leagues}
                    print("\nVerification against API:")
                    for shorthand, league_id in LEAGUES.items():
                        match = api_by_id.get(league_id)
                        if match:
                            print(f"  {shorthand:<12s} → {match['league_name']} ({match.get('country_name', '?')}) season {match.get('league_season', '?')}")
                        else:
                            print(f"  {shorthand:<12s} → NOT FOUND (ID {league_id})")
                finally:
                    await close_session()

            asyncio.run(verify())

    elif args.command == "merge":
        from sports.football.analysis import merge_reports

        merge_reports()

    elif args.command == "live-update":
        from sports.football.analysis import update_live

        asyncio.run(update_live())

    elif args.command == "league-averages":
        from sports.football.averages import ensure_averages
        from sports.football.client import close_session

        async def compute():
            try:
                data = await ensure_averages(force=args.force)
                if data:
                    print(f"Updated: {data.get('updated', '?')}")
                    for name, info in data.get("leagues", {}).items():
                        print(f"  {name:<12s}  {info['goals_per_game']:.2f} goals/game  ({info['matches']} matches)")
                    print(f"\n  European avg: {data['european_avg']:.3f}")
                else:
                    print("No averages available.")
            finally:
                await close_session()

        asyncio.run(compute())


if __name__ == "__main__":
    main()
