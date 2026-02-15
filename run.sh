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

exit $EXIT_CODE
