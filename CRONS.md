# Cron Jobs

All times are in **Eastern Time** (`CRON_TZ=America/New_York`).

| Time | Command | Description |
|---|---|---|
| 10:00 AM | `python main.py` | Generate matchup data for today's games |
| 10:30 AM | `python betting.py analyze` | Run LLM analysis and select bets |
| 11:00 AM | `python polymarket.py` | Place bets on Polymarket |
| 11:59 PM | `python betting.py results` | Process game results |

## Crontab

The server runs in UTC. Since ET shifts between UTC-5 (EST) and UTC-4 (EDT), each job is scheduled at both possible UTC hours with a guard that checks the actual ET hour before running.

```cron
SHELL=/bin/bash

# 10:00 AM ET — Generate matchup data
0 14,15 * * * [ "$(TZ=America/New_York date +\%H)" = "10" ] && /home/nonroot/projects/nba-ai-betting-analysis/run.sh python main.py

# 10:30 AM ET — LLM analysis and bet selection
30 14,15 * * * [ "$(TZ=America/New_York date +\%H)" = "10" ] && /home/nonroot/projects/nba-ai-betting-analysis/run.sh python betting.py analyze

# 11:00 AM ET — Place bets on Polymarket
0 15,16 * * * [ "$(TZ=America/New_York date +\%H)" = "11" ] && /home/nonroot/projects/nba-ai-betting-analysis/run.sh python polymarket.py

# 11:59 PM ET — Process game results
59 3,4 * * * [ "$(TZ=America/New_York date +\%H)" = "23" ] && /home/nonroot/projects/nba-ai-betting-analysis/run.sh python betting.py results
```

Install with: `crontab -e` and paste the above, or pipe a file with `crontab crontab.txt`.

## How It Works

- `run.sh` is a wrapper that activates the venv, loads `.env`, runs the command, and appends timestamped output to a dated log file in `logs/`.
- `CRON_TZ=America/New_York` makes cron interpret all times as ET (handles EST/EDT automatically).
- Each run is delimited by timestamps and exit codes in the log.

## Telegram Notifications

`run.sh` sends a Telegram message after `betting.py analyze` and `betting.py results` complete (success or failure). On success it also sends `bets/active.json` (after analyze) and the daily journal entry (after results) as file attachments.

Add to `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=your_chat_id
```

To get these:
1. Create a bot via [@BotFather](https://t.me/BotFather) and copy the token.
2. Send any message to your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`.

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
