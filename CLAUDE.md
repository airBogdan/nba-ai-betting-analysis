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

- **Matchup pipeline**: `main.py` → `sports/nba/pipeline.py` orchestrates `sports/nba/api/` (client, processors, injuries, odds), `sports/nba/teams.py`, `sports/nba/games.py`, `sports/nba/matchup/` (core engine: snapshots, edges, totals, signals)
- **Betting workflow**: `betting.py` → `betting/cli.py` delegates to `betting/` — `analyze/` (pre-game), `results/` (post-game: results.py, resolution.py, game_results.py, history.py), `strategy/` (incremental LLM evolution: strategy.py, format.py, sections.py), `stats/` (dashboard: stats.py, compute.py, html.py), `paper.py` (contrarian paper trades), `check.py` (position re-eval), `llm.py`, `search.py`, `prompts/`, `io.py`, `types.py`
- **Polymarket**: `polymarket.py` → `execution/polymarket.py` + `execution/` (gamma.py, matching.py, odds.py)
- **Crypto**: `crypto/` (Polymarket crypto paper trading, self-contained)

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
- Season logic (`sports/nba/utils.py::get_current_nba_season_year()`): Sep-Dec → current year, Jan-May → previous year, Jun-Aug → None
- `run.sh` wraps commands for cron with venv, `.env`, logging, and Telegram notifications (see `CRONS.md`)

## Before Editing Any File

- **Read the file first.** Do not edit a file you haven't read in this session.
- **Check its length.** If a module is already large, extract before adding.

## Code Style

### Function Readability

- If a function exceeds ~50–60 lines, extract blocks into named helper functions.
- Function names should make intent obvious — the caller should read like a sequence of steps, not a wall of implementation detail.
- Prefer many small functions over few large ones. A 5-line function with a clear name is better than an inline block with a comment.
- Naming: booleans use `is_x`/`has_x`/`can_x`. Use the same name for the same concept everywhere.

### File Size Guidelines

| File type | Target range | Action when exceeding |
|---|---|---|
| Utility / helper (`sports/nba/`) | 100–300 lines | Split into focused modules or subdirectory package |
| Workflow module (`betting/`) | 150–400 lines | Extract helper functions into separate files |
| Test file (`tests/`) | 200–600 lines | Split by feature area |

Some existing files exceed these ranges (e.g., `sports/nba/games.py`, `betting/strategy/strategy.py`, intent test files). When modifying them, look for opportunities to extract — don't just pile on.

### Data & Error Handling

- **Single source of truth.** Don't duplicate data across JSON files. If a value can be derived, derive it.
- **Validate at boundaries, trust internally.** Check data from JSON files, API responses, and user input. Don't litter internal functions with defensive checks.
- Always handle async errors. Don't leave coroutines unhandled.
- User-facing operations that fail → raise or log so the error is visible in output/Telegram.
- Background operations that fail → `logging.error` and fall back to safe defaults.
- Never swallow errors silently — at minimum log so failures are visible.

## Testing

- **Test intent, not implementation.** Ask "what would break if this function had a bug?" — not "what does this function currently return?"
- **Tests should survive refactoring.** If the implementation changes but behavior stays the same, tests should still pass. Test inputs/outputs, not internal details.
- **Cover edge cases and failure modes.** The happy path usually works. Test boundaries: empty lists, None inputs, missing keys, off-by-one.
- **Test names describe expected behavior**, not implementation: `test_completes_bet_and_updates_history` not `test_calls_save_with_updated_dict`.

## When Making Changes

- **If existing code looks wrong but works, ask before changing it.** It may be intentional.
- Don't add features, refactoring, or "improvements" beyond what was asked.
- Don't add new pip dependencies without asking first.
- Don't add comments explaining *what* code does — use clear function names instead. Only comment *why* when the reason isn't obvious.
- When extracting from a large file, create a new file in the same directory.

### Before Claiming Done

- Run `pytest` to verify no regressions.
- Verify there are no obvious import errors in the changed files.
- If you added a new import, confirm the target exists in the source module.
- If you changed a function signature, grep for all call sites and verify they match.
- If the change affects user-visible behavior, describe what the user should test.