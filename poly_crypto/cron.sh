#!/usr/bin/env bash
# Runner script for poly_crypto cron — activates venv, loads .env, logs output.
#
# Usage: ./poly_crypto/cron.sh

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Clean up logs older than 30 days
find "$LOGS_DIR" -name "poly_crypto_*.log" -mtime +30 -delete 2>/dev/null

DATE=$(date -u +%Y-%m-%d)
LOGFILE="$LOGS_DIR/poly_crypto_${DATE}.log"

# Activate venv
if [ ! -f "$PROJECT_DIR/venv/bin/activate" ]; then
    echo "ERROR: venv not found at $PROJECT_DIR/venv" >> "$LOGFILE"
    exit 1
fi
source "$PROJECT_DIR/venv/bin/activate"

# Load .env if present
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR"

send_telegram() {
    [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && return
    [ -z "${TELEGRAM_CHAT_ID:-}" ] && return
    local message="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "text=$message" \
        -d chat_id="$TELEGRAM_CHAT_ID" > /dev/null 2>&1
}

echo "===== $(date -u '+%Y-%m-%d %H:%M:%S UTC') =====" >> "$LOGFILE"

RESULTS=""

# Daily up/down
DAILY_OUT=$(python -m poly_crypto daily 2>&1)
DAILY_EXIT=$?
echo "$DAILY_OUT" >> "$LOGFILE"
echo "--- daily exit: $DAILY_EXIT ---" >> "$LOGFILE"
DAILY_RESULTS=$(echo "$DAILY_OUT" | grep -E '^\s+(WIN|LOSS) ')
if [ -n "$DAILY_RESULTS" ]; then
    RESULTS="${RESULTS}Daily Up/Down\n${DAILY_RESULTS}\n\n"
fi

# Range brackets
RANGE_OUT=$(python -m poly_crypto range 2>&1)
RANGE_EXIT=$?
echo "$RANGE_OUT" >> "$LOGFILE"
echo "--- range exit: $RANGE_EXIT ---" >> "$LOGFILE"
RANGE_RESULTS=$(echo "$RANGE_OUT" | grep -E '^\s+(WIN|LOSS) ')
if [ -n "$RANGE_RESULTS" ]; then
    RESULTS="${RESULTS}Range Brackets\n${RANGE_RESULTS}"
fi

echo "" >> "$LOGFILE"

# Send Telegram if any trades resolved
if [ -n "$RESULTS" ]; then
    send_telegram "$(printf "Crypto Results (%s)\n\n%b" "$DATE" "$RESULTS")"
fi
