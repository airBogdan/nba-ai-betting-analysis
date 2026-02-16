# Crypto 1H Edge Scanner

Detects pricing edges between Synthdata's AI model and Polymarket's 1-hour crypto candle markets. Paper trades edges automatically with full win/loss tracking.

## Usage

```bash
# Paper trading (scan + record + resolve in one pass)
python -m poly_crypto

# Dashboard — HTML analytics in browser
python -m poly_crypto stats
```

## Paper Trading

Each run does everything in one pass:
1. Hits Synthdata + Polymarket APIs for BTC, ETH, SOL
2. Records paper trades for edges >= 6%
3. Skips candles already traded (dedup by symbol + candle end time)
4. Resolves expired trades — moves results to history with win/loss stats

Data stored in `poly_crypto/paper/`:
- `trades.json` — open trades awaiting resolution
- `history.json` — resolved trades with summary stats
- `dashboard.html` — generated analytics dashboard

## Cron

```
*/5 * * * * cd /Users/b/Projects/nba && venv/bin/python -m poly_crypto >> logs/crypto-edges.log 2>&1
```

## Output

```
  TRADE BTC Down | edge 6.9% net 5.9% | 2025-02-15T19:00:00Z
  SKIP ETH 2025-02-15T19:00:00Z (already traded)
1 new trade(s) recorded, 2 open total.
  WIN BTC Down (actual: Down) | 2025-02-15T18:00:00Z
  PENDING SOL Up | 2025-02-15T19:00:00Z (waiting for oracle)
1 resolved, 1 still open.
```

## Market Discovery

```bash
python poly_crypto/markets.py list          # All active markets
python poly_crypto/markets.py BTC 1H        # Specific symbol/timeframe
```
