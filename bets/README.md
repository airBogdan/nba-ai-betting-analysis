# NBA Betting Workflow

## Setup

Requires `OPENROUTER_API_KEY` in `.env` file. For Polymarket placement, also set `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_FUNDER`.

```bash
python3.13 betting.py init
```

## Daily Workflow

### 1. Generate matchup data
```bash
python3.13 main.py 2026-02-12
```
Creates analysis files in `output/` for today's games.

### 2. Pre-game: Analyze and select bets
```bash
python3.13 betting.py analyze
```
- Analyzes all matchups for the date
- Selects up to 3 bets (use `--max-bets N` to change)
- Saves to `active.json` and `journal/YYYY-MM-DD.md`

### 3. Place bets on Polymarket
```bash
python3.13 polymarket.py
```
- Resolves active bets against live Polymarket markets
- Places market buy orders via the CLOB API
- Skips bets where the live price drifted >5pp from the analysis price
- Requires `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_FUNDER` in `.env`

### 4. Check open positions
```bash
python3.13 betting.py check
```
- Fetches live Polymarket prices for all placed positions
- Computes P&L (shares, unrealized profit/loss, percentage move)
- Re-evaluates positions that moved adversely by >10pp (searches for injury/lineup news, asks LLM to HOLD or CLOSE)
- Auto-sells positions recommended for close and updates bankroll
- Appends position check results to journal

### 5. Post-game: Process results
```bash
python3.13 betting.py results
```
- Fetches final scores from API
- Evaluates bets and updates history
- Appends results to journal

### 6. Update strategy (after 15+ bets)
```bash
python3.13 betting.py update-strategy
```
Produces 1-3 targeted adjustments to `strategy.md` based on performance patterns.

## Files

- `polymarket.py` - Place bets on Polymarket from active.json
- `polymarket_helpers/` - Polymarket Gamma API client, team matching, odds conversion
- `active.json` - Open bets awaiting results
- `history.json` - Completed bets with outcomes
- `strategy.md` - Evolving betting strategy
- `journal/` - Daily entries with analysis and results