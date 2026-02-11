# NBA Betting Workflow

## Setup

Requires `OPENROUTER_API_KEY` in `.env` file.

```bash
python3.13 betting.py init
```

## Daily Workflow

### 1. Generate matchup data
```bash
python3.13 main.py 2026-02-11
```
Creates analysis files in `output/` for today's games.

### 2. Pre-game: Analyze and select bets
```bash
python3.13 betting.py analyze
```
- Analyzes all matchups for the date
- Selects up to 3 bets (use `--max-bets N` to change)
- Saves to `active.json` and `journal/YYYY-MM-DD.md`

### 3. Post-game: Process results
```bash
python3.13 betting.py results
```
- Fetches final scores from API
- Evaluates bets and updates history
- Appends results to journal

### 4. Update strategy (after 5+ bets)
```bash
python3.13 betting.py update-strategy
```
Rewrites `strategy.md` based on performance patterns.

## Files

- `active.json` - Open bets awaiting results
- `history.json` - Completed bets with outcomes
- `strategy.md` - Evolving betting strategy
- `journal/` - Daily entries with analysis and results