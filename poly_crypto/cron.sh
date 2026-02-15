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

echo "===== $(date -u '+%Y-%m-%d %H:%M:%S UTC') =====" >> "$LOGFILE"

python -m poly_crypto >> "$LOGFILE" 2>&1
EXIT_CODE=$?

echo "===== Exit code: $EXIT_CODE =====" >> "$LOGFILE"
echo "" >> "$LOGFILE"

exit $EXIT_CODE
