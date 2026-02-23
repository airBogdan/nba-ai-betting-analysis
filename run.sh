#!/usr/bin/env bash
# Runner script for cron jobs — activates venv, loads .env, logs output.
#
# Usage: ./run.sh <command> [args...]
# Example: ./run.sh python main.py
#          ./run.sh python betting.py analyze
#
# Logs are written to logs/<command_label>_<date>.log

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Clean up logs older than 30 days
find "$LOGS_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null

# Build a log-friendly label from the arguments
LABEL=$(echo "$*" | sed 's/[^a-zA-Z0-9_-]/_/g' | sed 's/__*/_/g' | cut -c1-60)
DATE=$(TZ=America/New_York date +%Y-%m-%d)
LOGFILE="$LOGS_DIR/${LABEL}_${DATE}.log"

# Activate venv (abort if missing — running without it would cause import errors)
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

echo "===== $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z') =====" >> "$LOGFILE"
echo "Command: $*" >> "$LOGFILE"
echo "" >> "$LOGFILE"

# Run the command, capturing both stdout and stderr
"$@" >> "$LOGFILE" 2>&1
EXIT_CODE=$?

echo "" >> "$LOGFILE"
echo "===== Exit code: $EXIT_CODE =====" >> "$LOGFILE"
echo "" >> "$LOGFILE"

# Send Telegram notification if configured
send_telegram() {
    [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && return
    [ -z "${TELEGRAM_CHAT_ID:-}" ] && return
    local message="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "text=$message" \
        -d chat_id="$TELEGRAM_CHAT_ID" > /dev/null 2>&1
}


# Notify on specific commands
case "$*" in
    *"betting.py analyze"*)
        if [ $EXIT_CODE -eq 0 ]; then
            SUMMARY=$(grep -E '^Placed .+ bets |^  .+- \$|^Balance:' "$LOGFILE")
            if [ -n "$SUMMARY" ]; then
                send_telegram "$(printf 'Bets — %s\n\n%s' "$DATE" "$SUMMARY")"
            fi
        else
            send_telegram "$(printf 'Analyze FAILED (%s)\nExit code: %d' "$DATE" "$EXIT_CODE")"
        fi
        ;;
    *"polymarket.py"*)
        if [ $EXIT_CODE -eq 0 ]; then
            SUMMARY=$(grep -E '^  OK:|^Done:' "$LOGFILE")
            if echo "$SUMMARY" | grep -q 'OK:'; then
                send_telegram "$(printf 'Polymarket — %s\n\n%s' "$DATE" "$SUMMARY")"
            fi
        else
            send_telegram "$(printf 'Polymarket FAILED (%s)\nExit code: %d' "$DATE" "$EXIT_CODE")"
        fi
        ;;
    *"betting.py results"*)
        if [ $EXIT_CODE -eq 0 ]; then
            SUMMARY=$(grep -E '^Results:|^Dollar P&L:|bet\(s\) voided|bets still pending' "$LOGFILE")
            if [ -n "$SUMMARY" ]; then
                send_telegram "$(printf 'Results — %s\n\n%s' "$DATE" "$SUMMARY")"
            fi
        else
            send_telegram "$(printf 'Results FAILED (%s)\nExit code: %d' "$DATE" "$EXIT_CODE")"
        fi
        ;;
    *)
        if [ $EXIT_CODE -ne 0 ]; then
            send_telegram "$(printf 'FAILED: %s (%s)\nExit code: %d' "$*" "$DATE" "$EXIT_CODE")"
        fi
        ;;
esac

exit $EXIT_CODE
