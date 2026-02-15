# Cron Jobs

All times are in **Eastern Time** (`CRON_TZ=America/New_York`).

| Time | Command | Description |
|---|---|---|
| 10:00 AM | `python main.py` | Generate matchup data for today's games |
| 10:30 AM | `python betting.py analyze` | Run LLM analysis and select bets |
| 11:00 AM | `python polymarket.py` | Place bets on Polymarket |
| 11:59 PM | `python betting.py results` | Process game results |

## Crontab

```cron
CRON_TZ=America/New_York

0 10 * * * /home/nonroot/projects/nba-ai-betting-analysis/run.sh python main.py
30 10 * * * /home/nonroot/projects/nba-ai-betting-analysis/run.sh python betting.py analyze
0 11 * * * /home/nonroot/projects/nba-ai-betting-analysis/run.sh python polymarket.py
59 23 * * * /home/nonroot/projects/nba-ai-betting-analysis/run.sh python betting.py results
```

Install with: `crontab -e` and paste the above, or pipe a file with `crontab crontab.txt`.

## How It Works

- `run.sh` is a wrapper that activates the venv, loads `.env`, runs the command, and appends timestamped output to a dated log file in `logs/`.
- `CRON_TZ=America/New_York` makes cron interpret all times as ET (handles EST/EDT automatically).
- Each run is delimited by timestamps and exit codes in the log.

## Viewing Logs

```bash
# Latest matchup generation log
cat logs/python_main_py_2026-02-15.log

# Tail a log in real-time
tail -f logs/python_betting_py_analyze_*.log

# All logs for today
ls logs/*_$(date +%Y-%m-%d).log
```

## Manual Run

Test any job by running it directly:

```bash
./run.sh python main.py
./run.sh python betting.py analyze
./run.sh python polymarket.py
./run.sh python betting.py results
```
