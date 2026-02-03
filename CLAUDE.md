# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NBA Analytics tool with two main capabilities:
1. **Matchup Analysis**: Fetches data from API-Sports NBA API and generates comprehensive matchup analysis between two teams (team stats, H2H history, player data, contextual signals)
2. **Betting Workflow**: LLM-powered bet analysis and tracking system with strategy evolution

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Generate matchup data for a date (outputs to output/)
python main.py YYYY-MM-DD

# Run tests
pytest

# Run a single test
pytest tests/test_file.py::test_name -v

# Betting workflow (see bets/README.md for full workflow)
python betting.py init                          # Initialize betting directory
python betting.py analyze --date YYYY-MM-DD    # Analyze matchups, select bets
python betting.py results --date YYYY-MM-DD    # Process game results
python betting.py update-strategy              # Evolve strategy from history
```

## Environment Setup

- `NBA_RAPID_API_KEY` - Required for API-Sports NBA API access
- `OPENROUTER_API_KEY` - Required for betting workflow LLM analysis

Use a `.env` file or export directly.

## Architecture

Async Python using aiohttp for API calls.

### Matchup Analysis Pipeline (`main.py`)

```
main.py (orchestrator)
    ├── helpers/api/ (API client layer)
    │   ├── client.py - Low-level fetch_nba_api() and endpoint wrappers
    │   ├── processors.py - Data transformation (process_player_statistics, etc.)
    │   └── types.py - API response TypedDicts
    ├── helpers/teams.py - Team standings across seasons
    ├── helpers/games.py - H2H history, box score enrichment, quarter analysis
    └── helpers/matchup.py - Core analysis engine
        ├── build_team_snapshot() - Current season metrics with ORTG/DRTG
        ├── compute_edges() - Team comparison differentials
        ├── compute_totals_analysis() - O/U analysis with pace adjustments
        └── generate_signals() - Contextual betting signals
```

### Betting Workflow (`betting.py`)

```
betting.py (CLI)
    └── workflow/
        ├── analyze.py - Pre-game: load matchups → LLM analysis → bet selection
        ├── results.py - Post-game: fetch scores → evaluate bets → update history
        ├── strategy.py - Strategy evolution from performance patterns
        ├── llm.py - OpenRouter API client (complete_json)
        ├── prompts.py - LLM prompts and matchup condensing
        ├── io.py - File I/O for bets/, history, journal
        └── types.py - Bet-related TypedDicts
```

Output locations:
- `output/` - Matchup JSON files (away_vs_home_date.json)
- `bets/active.json` - Open bets awaiting results
- `bets/history.json` - Completed bets with outcomes
- `bets/strategy.md` - Evolving betting strategy
- `bets/journal/` - Daily analysis and results markdown

### Key Data Structures (TypedDict-based)

- `MatchupAnalysis` - Final output: snapshots, comparisons, totals_analysis, signals
- `TeamSnapshot` - Current season state with computed ORTG/DRTG estimates
- `H2HResults` - Dict mapping season year (int) to list of Game objects
- `ProcessedPlayerStats` / `ProcessedTeamStats` - Aggregated per-game stats
- `ActiveBet` / `SelectedBet` - Betting workflow structures

### Season Logic

`helpers/utils.py::get_current_nba_season_year()` determines season year:
- Sep-Dec → current year (season just started)
- Jan-May → previous year (mid-season)
- Jun-Aug → None (off-season)