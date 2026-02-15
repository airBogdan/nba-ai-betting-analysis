# Crypto 1H Edge Scanner

Detects pricing edges between Synthdata's AI model and Polymarket's 1-hour crypto candle markets. Paper trades edges automatically with full win/loss tracking.

## Usage

```bash
# Paper trading (scan + record + resolve in one pass)
python -m poly_crypto

# Dashboard — HTML analytics in browser
python -m poly_crypto stats

# Raw signal scan (no persistence)
python poly_crypto/signals.py
python poly_crypto/signals.py BTC
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
*/5 * * * * cd /path/to/nba && /path/to/venv/bin/python -m poly_crypto >> /var/log/crypto-edges.log 2>&1
```

## Output

```
=== Crypto 1H Edge Scanner ===

BTC | Bitcoin Up or Down - February 15, 2PM ET
  Candle:  $68,473 -> $68,469 (currently Down)
  Synth:   49.6% Up
  Market:  56.5% Up
  Edge:    -6.9% -> BET DOWN
  Bid/Ask: 0.56 / 0.57 (spread 1.0%)
  Net:     5.9% (edge after spread)
  Tokens:  Up=...69098257  Down=...00550455

ETH | No edge (synth=52.1% market=50.5% edge=1.6%)

SOL | Synthdata unavailable

No edges above threshold.
```

- **Edge**: synth probability minus market probability. Positive = bet Up, negative = bet Down.
- **Net**: edge after subtracting the bid/ask spread — your real edge.
- **Tokens**: Polymarket CLOB token IDs for placing orders.

## Market Discovery

```bash
python poly_crypto/markets.py list          # All active markets
python poly_crypto/markets.py BTC 1H        # Specific symbol/timeframe
```
