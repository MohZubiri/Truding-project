#!/usr/bin/env bash

# Run one foreground batch scan. Cron owns this process until it exits; there
# is intentionally no background process or daemon loop here.
set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/venv/bin/python}"
LOG_FILE="${BATCH_LOG_FILE:-$SCRIPT_DIR/batch_scan.log}"
LOCK_FILE="${BATCH_LOCK_FILE:-$SCRIPT_DIR/batch_scan.lock}"

if ! command -v flock >/dev/null 2>&1; then
    echo "run_batch_scan.sh: flock is required but was not found." >&2
    exit 127
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "run_batch_scan.sh: Python executable not found: $PYTHON_BIN" >&2
    exit 127
fi

cd "$SCRIPT_DIR" || exit 1

# -n prevents overlapping cron runs. The lock is released automatically when
# batch_scan.py exits, including error exits.
exec flock -n "$LOCK_FILE" "$PYTHON_BIN" "$SCRIPT_DIR/batch_scan.py" >>"$LOG_FILE" 2>&1
