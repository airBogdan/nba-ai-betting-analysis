# Crypto Paper Trading

Paper trades Polymarket crypto markets using Synthdata edge signals. Three strategies: hourly candles, daily up/down, and daily range brackets.

## Commands

```bash
# Hourly candle up/down (legacy)
python3.13 -m poly_crypto              # scan + trade + resolve
python3.13 -m poly_crypto stats        # HTML dashboard

# Daily up/down
python3.13 -m poly_crypto daily        # scan + trade + resolve
python3.13 -m poly_crypto daily stats  # HTML dashboard

# Daily range brackets
python3.13 -m poly_crypto range        # scan + trade + resolve
python3.13 -m poly_crypto range stats  # HTML dashboard

# Market discovery
python3.13 poly_crypto/markets.py list          # All active markets
python3.13 poly_crypto/markets.py BTC 1H        # Specific symbol/timeframe
```

## Strategies

### Hourly (`python3.13 -m poly_crypto`)
- Synthdata 1H candle signal vs Polymarket hourly markets
- Min edge: 6% | Assets: BTC, ETH, SOL
- Dedup: symbol + candle end time

### Daily Up/Down (`python3.13 -m poly_crypto daily`)
- Synthdata daily up/down signal vs Polymarket daily markets
- Min edge: 6% | Assets: BTC, ETH, SOL
- Binary Up/Down bet — entry price determines risk/reward asymmetry
- P&L: win = +(1 - entry), loss = -entry
- Dedup: asset + event end (one trade per asset per day)

### Range Brackets (`python3.13 -m poly_crypto range`)
- Synthdata range bracket probabilities vs Polymarket range markets
- Min edge: 5%, max ask: $0.25 | Assets: BTC, ETH, SOL
- Picks highest EV bracket per asset
- Dedup: asset + event end (one trade per asset per day)

## Data Files

All in `poly_crypto/paper/`:

| Strategy | Trades | History | Dashboard |
|----------|--------|---------|-----------|
| Hourly | `trades.json` | `history.json` | `dashboard.html` |
| Daily | `daily_trades.json` | `daily_history.json` | `daily_dashboard.html` |
| Range | `range_trades.json` | `range_history.json` | `range_dashboard.html` |

## Output Examples

### Daily Up/Down
```
--- Daily Up/Down | 2026-02-19 16:00:00 UTC ---
Scanning daily up/down...
  BTC: Up edge 7.2% (synth 18.0% vs market 10.8%) entry $0.110
  ETH: edge 2.4% below 6% threshold
  SOL: edge 1.6% below 6% threshold
1 new trade(s) recorded, 1 open total.
  PENDING BTC Up @ $0.110 | 2026-02-19T17:00:00Z
```

### Range Brackets
```
--- Range Brackets | 2026-02-19 16:00:00 UTC ---
Scanning range brackets...
  BTC: best bracket [66000, 68000] | edge 8.1% ev $0.052 ask $0.090
  ETH: no qualifying brackets (edge >= 5%, ask <= $0.25)
1 new trade(s) recorded, 2 open total.
  WIN BTC [64000, 66000] | P&L $+0.9100
  PENDING BTC [66000, 68000] @ $0.090 | 2026-02-20T00:00:00Z
```

## Cron

Range and daily can share a cron (run once or twice daily):
```
0 */6 * * * cd /Users/b/Projects/nba && python3.13 -m poly_crypto range >> logs/crypto-range.log 2>&1
0 */6 * * * cd /Users/b/Projects/nba && python3.13 -m poly_crypto daily >> logs/crypto-daily.log 2>&1
```
