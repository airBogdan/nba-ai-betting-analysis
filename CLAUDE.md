# CLAUDE.md

## Project Overview

NBA Analytics tool: matchup analysis (API-Sports NBA API), LLM-powered betting workflow (OpenRouter), and Polymarket execution. Async Python with aiohttp.

## Commands

```bash
pip install -r requirements.txt
python main.py YYYY-MM-DD                      # Generate matchup data → output/
pytest                                          # Run tests
pytest tests/test_file.py::test_name -v        # Single test

# Betting workflow
python betting.py init                          # Initialize bets/ directory
python betting.py analyze --date YYYY-MM-DD    # Analyze matchups, select bets
python betting.py analyze                       # Auto-detect dates from output/
python betting.py results --date YYYY-MM-DD    # Process game results
python betting.py results                       # Process all active bets
python betting.py update-strategy              # Evolve strategy from history
python betting.py check                        # Re-evaluate open positions
python betting.py stats                        # Generate HTML analytics dashboard
python betting.py update-paper-strategy        # Evolve paper trading strategy
python polymarket.py                            # Place bets on Polymarket
```

## Environment

Required in `.env`: `NBA_RAPID_API_KEY`, `OPENROUTER_API_KEY`

Optional: `INJURIES_API_KEY`, `THE_ODDS_API`, `POLYMARKET_PRIVATE_KEY` / `POLYMARKET_FUNDER`, `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, `LLM_MODEL`, `PERPLEXITY_MODEL`

## Architecture

- **Matchup pipeline**: `main.py` orchestrates `helpers/api/` (client, processors, injuries, odds), `helpers/teams.py`, `helpers/games.py`, `helpers/matchup.py` (core engine: snapshots, edges, totals, signals)
- **Betting workflow**: `betting.py` CLI delegates to `workflow/` — `analyze.py` (pre-game), `results.py` (post-game), `strategy.py` (incremental LLM evolution), `paper.py` (contrarian paper trades on skipped games), `check.py` (position re-eval), `stats.py` (dashboard), `llm.py`, `search.py`, `prompts.py`, `io.py`, `types.py`
- **Polymarket**: `polymarket.py` + `polymarket_helpers/` (gamma.py, matching.py, odds.py)

## Output Locations

- `output/` — Matchup JSON files (cleared after results processing)
- `bets/active.json` — Open bets awaiting results
- `bets/history.json` — Completed bets with outcomes and reflections
- `bets/skips.json` — Skipped games with reasons and resolved outcomes
- `bets/strategy.md` — Evolving betting strategy (LLM-maintained)
- `bets/journal/` — Daily markdown entries
- `bets/dashboard.html` — Generated analytics dashboard
- `bets/paper/trades.json` — Paper trade picks + resolved outcomes
- `bets/paper/history.json` — Paper trade history with summary stats
- `bets/paper/strategy.md` — Paper trading strategy (LLM-maintained)
- `bets/paper/journal/` — Daily paper trade markdown entries

## Key Conventions

- TypedDicts throughout — not enforced at runtime, safe to add optional fields
- Season logic (`helpers/utils.py::get_current_nba_season_year()`): Sep-Dec → current year, Jan-May → previous year, Jun-Aug → None
- `run.sh` wraps commands for cron with venv, `.env`, logging, and Telegram notifications (see `CRONS.md`)