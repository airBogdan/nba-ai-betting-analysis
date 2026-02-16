# NBA Betting Workflow

## Setup

Requires `OPENROUTER_API_KEY` in `.env` file. For Polymarket placement, also set `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_FUNDER`.

```bash
python3.13 betting.py init
```

## Daily Workflow

### 1. Generate matchup data
```bash
python3.13 main.py
```
Creates analysis files in `output/` for today's games.

### 2. Pre-game: Analyze and select bets
```bash
python3.13 betting.py analyze
```
- Analyzes all matchups for the date
- Selects up to 3 bets (use `--max-bets N` to change)
- Saves to `active.json` and `journal/YYYY-MM-DD.md`
- Paper trades all skipped games via a contrarian LLM analyst (saved to `paper/`)

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
- Resolves paper trade outcomes
- Appends results to journal

### 6. Stats dashboard
```bash
python3.13 betting.py stats
```
Generates `dashboard.html` with performance charts (cumulative P&L, rolling win rate), breakdown tables (by confidence, edge type, bet type, home/away), and a skipped games table. Opens in browser automatically.

### 7. Update strategy (after 15+ bets)
```bash
python3.13 betting.py update-strategy
```
Produces 1-3 targeted adjustments to `strategy.md` based on performance patterns. Includes paper trade aggregate stats (when 15+ paper trades exist) and actionable insights saved by `update-paper-strategy`.

### 8. Update paper strategy (after 15+ paper trades)
```bash
python3.13 betting.py update-paper-strategy
```
Evolves the paper trading strategy and saves actionable insights to `paper/insights.json`. These insights are automatically included in the next `update-strategy` run, creating a feedback loop where profitable patterns in skipped games flow back to the main strategy.

## Files

- `polymarket.py` - Place bets on Polymarket from active.json
- `polymarket_helpers/` - Polymarket Gamma API client, team matching, odds conversion
- `active.json` - Open bets awaiting results
- `history.json` - Completed bets with outcomes
- `skips.json` - Skipped games with reasons and resolved outcomes
- `strategy.md` - Evolving betting strategy
- `dashboard.html` - Generated stats dashboard
- `journal/` - Daily entries with analysis and results
- `paper/trades.json` - Active paper trades (contrarian bets on skipped games)
- `paper/history.json` - Resolved paper trades with summary stats
- `paper/strategy.md` - Paper-specific evolving strategy
- `paper/insights.json` - Actionable insights for main strategy (persisted across runs)
- `paper/journal/` - Daily paper trade entries