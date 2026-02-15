# Crypto Cron

Runs the poly_crypto edge scanner every 6 minutes. Scans BTC, ETH, SOL 1H candle markets, records paper trades, and resolves expired ones.

## Crontab

```cron
*/6 * * * * /home/nonroot/projects/nba-ai-betting-analysis/poly_crypto/cron.sh
```

No timezone guard needed — crypto markets run 24/7.

## API Calls Per Run

- 3 Synthdata calls (1 per symbol: BTC, ETH, SOL)
- 3 Polymarket Gamma calls (1 per symbol)
- 6 total per run, ~1,440/day

## Logs

```bash
# Today's log
cat logs/poly_crypto_2026-02-15.log

# Tail live
tail -f logs/poly_crypto_$(date -u +%Y-%m-%d).log
```

Logs use UTC dates and auto-delete after 30 days.

## Data

- `poly_crypto/paper/trades.json` — open trades
- `poly_crypto/paper/history.json` — resolved trades with summary stats

## Manual Run

```bash
./poly_crypto/cron.sh
```
