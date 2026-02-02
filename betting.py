#!/usr/bin/env python
"""NBA Betting Analysis CLI."""

import argparse
import asyncio
import sys
from datetime import datetime


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
    analyze.add_argument("--date", "-d", required=True, help="YYYY-MM-DD")
    analyze.add_argument("--max-bets", "-m", type=int, default=3)
    analyze.add_argument("--force", "-f", action="store_true", help="Re-analyze even if bets exist")

    # results
    results = subparsers.add_parser("results", help="Post-game results")
    results.add_argument("--date", "-d", required=True, help="YYYY-MM-DD")

    # update-strategy
    subparsers.add_parser("update-strategy", help="Update strategy from history")

    args = parser.parse_args()

    if args.command == "init":
        from workflow.init import run_init

        run_init()
    elif args.command == "analyze":
        validate_date(args.date)
        from workflow.analyze import run_analyze_workflow

        asyncio.run(run_analyze_workflow(args.date, args.max_bets, args.force))
    elif args.command == "results":
        validate_date(args.date)
        from workflow.results import run_results_workflow

        asyncio.run(run_results_workflow(args.date))
    elif args.command == "update-strategy":
        from workflow.strategy import run_strategy_workflow

        asyncio.run(run_strategy_workflow())


if __name__ == "__main__":
    main()
