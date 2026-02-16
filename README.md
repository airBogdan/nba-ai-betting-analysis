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
python main.py
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

Creates the `bets/` directory with `active.json`, `history.json`, `strategy.md`, and the `paper/` subdirectory for paper trading.

### Analyze games and select bets

```bash
python betting.py analyze
```

Loads all matchup files from `output/`, condenses them, and sends them to an LLM along with the current strategy. The LLM evaluates each game and selects up to 3 bets with reasoning. Results are saved to `bets/active.json` and a daily journal entry in `bets/journal/`. Skipped games are automatically paper traded by a contrarian LLM analyst (see Paper Trading below).

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

Fetches final scores from the API, evaluates each active bet (win/loss/push), generates structured reflections on what went right or wrong, and moves everything to `bets/history.json`. Also resolves paper trade outcomes. Appends results to the daily journal. Clears `output/` after processing.

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Process results for a specific date (default: all active bets) |

### Check open positions

```bash
python betting.py check
```

Monitors placed Polymarket positions by fetching live prices and computing P&L. Positions that have moved adversely by more than 10pp trigger a re-evaluation — searches for fresh context (injuries, lineup changes) via Perplexity, then asks the LLM whether to HOLD or CLOSE. Positions recommended for close are auto-sold on Polymarket with bankroll and history updated. Results are appended to the daily journal.

### Stats dashboard

```bash
python betting.py stats
```

Generates a self-contained HTML dashboard at `bets/dashboard.html` and opens it in the browser. Includes:

- Overview cards (record, win rate, ROI, net units/dollars, streak)
- Cumulative P&L chart (dual y-axis: units + dollars) over time
- Rolling win rate chart (10-bet window)
- Breakdown tables by confidence level, edge type, bet type, and home/away pick side
- Skipped games table with reasons and resolved outcomes

The dashboard pulls from `bets/history.json` for bet performance and `bets/skips.json` for skip tracking data.

### Update strategy

```bash
python betting.py update-strategy
```

Requires 15+ completed bets. Aggregates performance patterns and reflections from history, then asks the LLM to produce 1-3 targeted adjustments to `bets/strategy.md`. Includes paper trade aggregate stats (when 15+ paper trades exist) and any actionable insights persisted by `update-paper-strategy`. Changes are appended to a change log for auditability. Previous strategy versions are archived (last 10 kept).

### Paper trading

The system automatically paper trades every skipped game using a contrarian LLM analyst that must find value in each one. Paper trades run after `analyze`, resolve during `results`, and track independently under `bets/paper/`.

```bash
python betting.py update-paper-strategy
```

Requires 15+ paper trades. Evolves the paper trading strategy and persists actionable insights to `bets/paper/insights.json`, which are automatically included in the next `update-strategy` run. This creates a feedback loop: profitable patterns discovered in skipped games flow back to the main strategy so those games stop being skipped. Paper trade performance is broken down by skip reason category (injury uncertainty, no edge, high variance, sizing veto) to identify which types of skipped games have the most missed value.

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
    check.py            # Position monitoring and auto-close workflow
    strategy.py         # Strategy evolution from performance patterns
    paper.py            # Contrarian paper trades on skipped games
    stats.py            # Analytics computation and HTML dashboard
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
    skips.json          # Skipped games with reasons and outcomes
    bankroll.json       # Bankroll tracking (auto-created at $1000)
    strategy.md         # Evolving betting strategy
    dashboard.html      # Generated stats dashboard
    journal/            # Daily analysis and results entries
    paper/              # Paper trading (contrarian bets on skipped games)
        trades.json     # Active paper trades
        history.json    # Resolved trades with summary stats
        strategy.md     # Paper-specific evolving strategy
        insights.json   # Actionable insights for main strategy
        journal/        # Daily paper trade entries
tests/                  # pytest test suite
```