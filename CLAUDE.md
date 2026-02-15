# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NBA Analytics tool with three main capabilities:
1. **Matchup Analysis**: Fetches data from API-Sports NBA API and generates comprehensive matchup analysis between two teams (team stats, H2H history, player data, contextual signals)
2. **Betting Workflow**: LLM-powered bet analysis, tracking, and strategy evolution with Polymarket integration
3. **Polymarket Execution**: Places and manages bets on Polymarket prediction markets

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

# Betting workflow
python betting.py init                          # Initialize bets/ directory
python betting.py analyze --date YYYY-MM-DD    # Analyze matchups, select bets
python betting.py analyze                       # Auto-detect dates from output/
python betting.py results --date YYYY-MM-DD    # Process game results
python betting.py results                       # Process all active bets
python betting.py update-strategy              # Evolve strategy from history
python betting.py check                        # Re-evaluate open positions, auto-close if edge lost
python betting.py stats                        # Generate HTML analytics dashboard

# Place bets on Polymarket
python polymarket.py
```

## Environment Setup

Required in `.env`:
- `NBA_RAPID_API_KEY` - API-Sports NBA API
- `OPENROUTER_API_KEY` - LLM analysis (OpenRouter)

Optional:
- `INJURIES_API_KEY` - Injury reports API
- `THE_ODDS_API` - Betting odds from the-odds-api
- `POLYMARKET_PRIVATE_KEY` / `POLYMARKET_FUNDER` - Polymarket trading
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` - Cron notifications
- `LLM_MODEL` - Override default LLM model
- `PERPLEXITY_MODEL` - Override Perplexity model for search enrichment

## Architecture

Async Python using aiohttp for API calls.

### Matchup Analysis Pipeline (`main.py`)

```
main.py (orchestrator)
    ├── helpers/api/ (API client layer)
    │   ├── client.py - Low-level fetch_nba_api() and endpoint wrappers
    │   ├── processors.py - Data transformation (process_player_statistics, etc.)
    │   ├── injuries.py - Injury reports from separate RapidAPI endpoint
    │   ├── odds.py - Betting lines from the-odds-api
    │   └── types.py - API response TypedDicts
    ├── helpers/teams.py - Team standings across seasons
    ├── helpers/games.py - H2H history, box score enrichment, quarter analysis
    └── helpers/matchup.py - Core analysis engine (~1100 lines)
        ├── build_team_snapshot() - Current season metrics with ORTG/DRTG
        ├── compute_edges() - Team comparison differentials
        ├── compute_totals_analysis() - O/U analysis with pace adjustments
        └── generate_signals() - Contextual betting signals
```

### Betting Workflow (`betting.py`)

```
betting.py (CLI, 6 subcommands)
    └── workflow/
        ├── analyze.py - Pre-game: load matchups → LLM analysis → bet selection → skip tracking
        ├── results.py - Post-game: fetch scores → evaluate bets → resolve skips → update history
        ├── strategy.py - Incremental strategy evolution via LLM (section-level adjustments)
        ├── check.py - Position re-evaluation: search + LLM → auto-close if edge lost
        ├── stats.py - HTML analytics dashboard generation from history/skips
        ├── llm.py - OpenRouter API client (complete, complete_json)
        ├── search.py - Perplexity-powered web search enrichment
        ├── polymarket_prices.py - Bridge to polymarket_helpers for price data
        ├── prompts.py - All LLM prompts and matchup condensing
        ├── io.py - File I/O for bets/ directory (history, active, skips, journal)
        └── types.py - Bet-related TypedDicts (ActiveBet, SelectedBet, SkipEntry, etc.)
```

### Polymarket Integration

```
polymarket.py - CLI for placing bets via Polymarket CLOB API
polymarket_helpers/
    ├── gamma.py - Gamma Markets API (fetch events, extract odds)
    ├── matching.py - Matchup/outcome string matching
    └── odds.py - Price formatting utilities
```

### Output Locations

- `output/` - Matchup JSON files (cleared after results processing)
- `bets/active.json` - Open bets awaiting results
- `bets/history.json` - Completed bets with outcomes and reflections
- `bets/skips.json` - Skipped games with reasons and resolved outcomes
- `bets/strategy.md` - Evolving betting strategy (LLM-maintained)
- `bets/journal/` - Daily markdown entries (analysis + results)
- `bets/dashboard.html` - Generated analytics dashboard

### Key Data Structures (TypedDict-based)

TypedDicts are not enforced at runtime — safe to add optional fields.

- `MatchupAnalysis` - Final output: snapshots, comparisons, totals_analysis, signals
- `TeamSnapshot` - Current season state with computed ORTG/DRTG estimates
- `H2HResults` - Dict mapping season year (int) to list of Game objects
- `ProcessedPlayerStats` / `ProcessedTeamStats` - Aggregated per-game stats
- `ActiveBet` / `SelectedBet` / `SkipEntry` - Betting workflow structures

### Season Logic

`helpers/utils.py::get_current_nba_season_year()` determines season year:
- Sep-Dec → current year (season just started)
- Jan-May → previous year (mid-season)
- Jun-Aug → None (off-season)

### Automation

`run.sh` wraps commands for cron: activates venv, loads `.env`, logs to `logs/`, sends Telegram notifications on completion. See `CRONS.md` for schedule.
