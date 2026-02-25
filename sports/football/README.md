# Football Live Odds Monitor

Detects live football goals via APIFootball's WebSocket and queries Polymarket for current match odds on every goal. Tie-breaking goals are flagged — these are where the pricing lag is most exploitable before the market adjusts.

## How It Works

1. Connects to APIFootball's WebSocket (`wss://wss.apifootball.com/livescore`)
2. Polls Polymarket odds every 60s in the background and caches them
3. Tracks scores for all live matches
4. On every goal: shows the score and compares **before** (cached) vs **after** (fresh query) Polymarket odds
5. Tie-breaking goals are flagged — a small or zero delta after a tie-breaker confirms the lag

## Setup

Requires `APIFOOTBAL` in `.env` (APIFootball API key).

```bash
pip install -r requirements.txt
```

## Usage

```bash
python football_live.py
```

Output:

```
Connected to APIFootball WebSocket.
[GOAL 19:25:03] Arsenal vs Chelsea (1-0) - Saka 25' ** TIE-BREAKER **
  Polymarket: Arsenal FC vs. Chelsea FC
                           Before →    After       Δ
    Arsenal FC               0.550 →    0.552  +0.002  ← barely moved = lag!
    draw                     0.250 →    0.248  -0.002
    Chelsea FC               0.200 →    0.200  +0.000
[GOAL 19:50:10] Arsenal vs Chelsea (2-0) - Havertz 50'
  Polymarket: Arsenal FC vs. Chelsea FC
                           Before →    After       Δ
    Arsenal FC               0.750 →    0.780  +0.030
    draw                     0.120 →    0.100  -0.020
    Chelsea FC               0.130 →    0.120  -0.010
```

## Covered Leagues

EPL, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, Europa League.

## Files

- `football_live.py` — Entry point
- `sports/football/api.py` — APIFootball data parsing (goal events, tie detection)
- `sports/football/live.py` — WebSocket listener, score tracking, Polymarket odds lookup
- `tests/football/` — Unit tests (`pytest tests/football/ -v`)
