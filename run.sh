#!/usr/bin/env bash
# Runner script for cron jobs — activates venv, loads .env, logs output.
#
# Usage: ./run.sh <command> [args...]
# Example: ./run.sh python main.py
#          ./run.sh python betting.py analyze
#
# Logs are written to logs/<command_label>_<date>.log

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Build a log-friendly label from the arguments
LABEL=$(echo "$*" | sed 's/[^a-zA-Z0-9_-]/_/g' | sed 's/__*/_/g' | cut -c1-60)
DATE=$(TZ=America/New_York date +%Y-%m-%d)
LOGFILE="$LOGS_DIR/${LABEL}_${DATE}.log"

# Activate venv
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
        -d chat_id="$TELEGRAM_CHAT_ID" \
        -d text="$message" \
        -d parse_mode="Markdown" > /dev/null 2>&1
}

send_telegram_file() {
    [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && return
    [ -z "${TELEGRAM_CHAT_ID:-}" ] && return
    local filepath="$1"
    local caption="${2:-}"
    [ ! -f "$filepath" ] && return
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
        -F chat_id="$TELEGRAM_CHAT_ID" \
        -F document=@"$filepath" \
        -F caption="$caption" > /dev/null 2>&1
}

# Notify on specific commands
case "$*" in
    *"betting.py analyze"*)
        if [ $EXIT_CODE -eq 0 ]; then
            SUMMARY=$(tail -25 "$LOGFILE" | head -20)
            send_telegram "$(printf '*Betting Analyze Complete* (%s)\n\n```\n%s\n```' "$DATE" "$SUMMARY")"
            send_telegram_file "$PROJECT_DIR/bets/active.json" "Active bets — $DATE"
        else
            send_telegram "$(printf '*Betting Analyze FAILED* (%s)\nExit code: %d\nCheck: %s' "$DATE" "$EXIT_CODE" "$LOGFILE")"
        fi
        ;;
    *"betting.py results"*)
        if [ $EXIT_CODE -eq 0 ]; then
            SUMMARY=$(tail -25 "$LOGFILE" | head -20)
            send_telegram "$(printf '*Betting Results Complete* (%s)\n\n```\n%s\n```' "$DATE" "$SUMMARY")"
            send_telegram_file "$PROJECT_DIR/bets/journal/${DATE}.md" "Journal — $DATE"
        else
            send_telegram "$(printf '*Betting Results FAILED* (%s)\nExit code: %d\nCheck: %s' "$DATE" "$EXIT_CODE" "$LOGFILE")"
        fi
        ;;
esac

exit $EXIT_CODE
