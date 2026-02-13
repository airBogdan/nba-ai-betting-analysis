# NBA Analytics & Betting System

Async Python toolkit for NBA matchup analysis and LLM-powered betting. Pulls data from API-Sports (team stats, standings, H2H history, player stats, injuries, odds) and generates structured matchup analyses. An optional betting workflow uses an LLM to select bets, track results, and evolve strategy over time.

## Setup

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

Create a `.env` file with:

```
NBA_RAPID_API_KEY=...       # API-Sports NBA API
OPENROUTER_API_KEY=...      # LLM access (betting workflow only)
INJURIES_API_KEY=...        # NBA injuries reports API
THE_ODDS_API=...            # The Odds API (spreads, totals, moneylines)
```

See `.env.sample` for links to each API.

## Matchup Analysis

Generate matchup data for all games on a given date:

```bash
python main.py 2026-02-10
```

For each game, this:

1. Fetches team stats, standings, and recent games for the current season
2. Pulls head-to-head history with box scores across multiple seasons
3. Gathers player statistics and current injuries
4. Fetches betting odds (spreads, totals, moneylines) with alternate lines
5. Runs everything through the analysis engine — computes team snapshots (ORTG/DRTG estimates, SOS-adjusted net rating, recent form), edges, totals projections, and contextual signals

Output goes to `output/` as JSON files named `away_vs_home_YYYY-MM-DD.json`.

## Betting Workflow

LLM-powered bet selection and tracking system built on top of the matchup analysis.

### Initialize

```bash
python betting.py init
```

Creates the `bets/` directory with `active.json`, `history.json`, and `strategy.md`.

### Analyze games and select bets

```bash
python betting.py analyze
```

Loads all matchup files from `output/`, condenses them, and sends them to an LLM along with the current strategy. The LLM evaluates each game and selects up to 3 bets with reasoning. Results are saved to `bets/active.json` and a daily journal entry in `bets/journal/`.

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Analyze matchups for a specific date (default: all dates in `output/`) |
| `--max-bets N` | Maximum bets to select (default: 3) |
| `--force` | Re-analyze even if bets already exist for the date |

### Place bets on Polymarket

```bash
python polymarket.py
```

Resolves active bets for the given date against live Polymarket markets and places market buy orders via the CLOB API. Includes a price drift gate — bets are skipped if the live price moved more than 5pp from the analysis price.

Requires additional `.env` variables:

```
POLYMARKET_PRIVATE_KEY=...  # Polygon wallet private key
POLYMARKET_FUNDER=...       # Funder address for CLOB client
```

### Process results

```bash
python betting.py results
```

Fetches final scores from the API, evaluates each active bet (win/loss/push), generates structured reflections on what went right or wrong, and moves everything to `bets/history.json`. Appends results to the daily journal. Clears `output/` after processing.

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Process results for a specific date (default: all active bets) |

### Update strategy

```bash
python betting.py update-strategy
```

Requires 15+ completed bets. Aggregates performance patterns and reflections from history, then asks the LLM to produce 1-3 targeted adjustments to `bets/strategy.md`. Changes are appended to a change log for auditability. Previous strategy versions are archived (last 10 kept).

## Running Tests

```bash
pytest

# Single test
pytest tests/test_matchup.py::test_name -v
```

## Project Structure

```
main.py                 # Matchup analysis CLI
betting.py              # Betting workflow CLI
helpers/
    api/                # API client, data processors, TypedDicts
    matchup.py          # Analysis engine (snapshots, edges, totals, signals)
    games.py            # H2H history, box scores, quarter analysis
    teams.py            # Team standings across seasons
    utils.py            # Season year logic
    types.py            # Shared TypedDicts
workflow/
    analyze.py          # Pre-game: matchups -> LLM -> bet selection
    results.py          # Post-game: scores -> evaluation -> history
    strategy.py         # Strategy evolution from performance patterns
    prompts.py          # LLM prompts and matchup condensing
    llm.py              # OpenRouter API client
    io.py               # File I/O for bets directory
    search.py           # Web search enrichment (Perplexity)
    types.py            # Bet-related TypedDicts
    init.py             # Bets directory initialization
output/                 # Generated matchup JSON files
bets/
    polymarket.py       # Place bets on Polymarket from active.json
    polymarket_helpers/  # Polymarket API client, matching, odds conversion
    active.json         # Open bets awaiting results
    history.json        # Completed bets with outcomes
    bankroll.json       # Bankroll tracking (auto-created at $1000)
    strategy.md         # Evolving betting strategy
    journal/            # Daily analysis and results entries
tests/                  # pytest test suite
```