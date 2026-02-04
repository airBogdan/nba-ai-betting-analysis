#!/usr/bin/env python
"""NBA Betting Analysis CLI."""

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path


OUTPUT_DIR = Path(__file__).parent / "output"


def get_dates_from_output() -> list[str]:
    """Extract unique dates from matchup files in output folder."""
    if not OUTPUT_DIR.exists():
        return []

    dates = set()
    date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})\.json$")

    for f in OUTPUT_DIR.glob("*.json"):
        match = date_pattern.search(f.name)
        if match:
            dates.add(match.group(1))

    return sorted(dates)


def validate_date(date_str: str) -> str:
    """Validate date format is YYYY-MM-DD and is a real date."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        print(f"Error: Invalid date '{date_str}'. Use YYYY-MM-DD format.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="NBA Betting Workflow System")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    subparsers.add_parser("init", help="Initialize bets directory and files")

    # analyze
    analyze = subparsers.add_parser("analyze", help="Pre-game analysis")
    analyze.add_argument("--date", "-d", help="YYYY-MM-DD (optional, extracts from output folder)")
    analyze.add_argument("--max-bets", "-m", type=int, default=3)
    analyze.add_argument("--force", "-f", action="store_true", help="Re-analyze even if bets exist")

    # results
    results = subparsers.add_parser("results", help="Post-game results")
    results.add_argument("--date", "-d", help="YYYY-MM-DD (optional, defaults to all active bets)")

    # update-strategy
    subparsers.add_parser("update-strategy", help="Update strategy from history")

    args = parser.parse_args()

    if args.command == "init":
        from workflow.init import run_init

        run_init()
    elif args.command == "analyze":
        if args.date:
            validate_date(args.date)
            dates = [args.date]
        else:
            dates = get_dates_from_output()
            if not dates:
                print("Error: No matchup files found in output/. Run main.py first or specify --date.")
                sys.exit(1)
            print(f"Found matchups for: {', '.join(dates)}")

        from workflow.analyze import run_analyze_workflow

        for date in dates:
            asyncio.run(run_analyze_workflow(date, args.max_bets, args.force))
    elif args.command == "results":
        if args.date:
            validate_date(args.date)
        from workflow.results import run_results_workflow

        asyncio.run(run_results_workflow(args.date))
    elif args.command == "update-strategy":
        from workflow.strategy import run_strategy_workflow

        asyncio.run(run_strategy_workflow())


if __name__ == "__main__":
    main()
