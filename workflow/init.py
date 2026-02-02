"""Initialization command for betting workflow."""

from pathlib import Path

from .io import BETS_DIR, JOURNAL_DIR, ensure_dir, write_json, write_text

INITIAL_STRATEGY = """# NBA Betting Strategy

## Core Principles
- Only bet when there's a clear statistical or situational edge
- Prioritize moneyline bets with identifiable advantages
- Never chase losses or force bets on weak slates

## Confidence Guidelines
- **High confidence (2 units)**: Multiple strong edges align
- **Medium confidence (1 unit)**: Single strong edge with manageable risk
- **Low confidence (0.5 units)**: Slight edge, worth small position

## Key Factors to Weight
- Home/away performance differential
- Rest advantage (2+ days vs back-to-back)
- Recent form (last 10 games)
- Head-to-head patterns
- Key player availability

## What to Avoid
- Teams on long road trips
- Back-to-back situations against rested opponents
- Overvaluing streaks without underlying stats support

## Notes
- Strategy will be updated as betting history accumulates
"""


def run_init() -> None:
    """Initialize bets directory and files."""
    ensure_dir(BETS_DIR)
    ensure_dir(JOURNAL_DIR)

    # Initialize active.json
    active_path = BETS_DIR / "active.json"
    if not active_path.exists():
        write_json(active_path, [])
        print(f"Created {active_path}")
    else:
        print(f"Already exists: {active_path}")

    # Initialize history.json
    history_path = BETS_DIR / "history.json"
    if not history_path.exists():
        write_json(
            history_path,
            {
                "bets": [],
                "summary": {
                    "total_bets": 0,
                    "wins": 0,
                    "losses": 0,
                    "pushes": 0,
                    "win_rate": 0.0,
                    "total_units_wagered": 0.0,
                    "net_units": 0.0,
                    "roi": 0.0,
                    "by_confidence": {},
                    "by_primary_edge": {},
                    "by_bet_type": {},
                    "current_streak": "",
                },
            },
        )
        print(f"Created {history_path}")
    else:
        print(f"Already exists: {history_path}")

    # Initialize strategy.md
    strategy_path = BETS_DIR / "strategy.md"
    if not strategy_path.exists():
        write_text(strategy_path, INITIAL_STRATEGY)
        print(f"Created {strategy_path}")
    else:
        print(f"Already exists: {strategy_path}")

    print("\nInitialization complete.")
