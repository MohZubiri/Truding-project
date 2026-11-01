#!/bin/bash
# حارس Cron: flock يمنع تشغيل أكثر من نسخة حتى عند تزامن استدعاءين.
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1

# في cPanel اضبط PYTHON_BIN على المسار المطلق لبايثون داخل البيئة الافتراضية.
PYTHON_BIN=${PYTHON_BIN:-"$SCRIPT_DIR/venv/bin/python"}
LOG_FILE=${BOT_LOG_FILE:-"$SCRIPT_DIR/bot.log"}
LOCK_FILE=${BOT_LOCK_FILE:-"$SCRIPT_DIR/bot.lock"}

if [ ! -x "$PYTHON_BIN" ]; then
    printf '%s Python executable not found: %s\n' "$(date -Iseconds)" "$PYTHON_BIN" >> "$LOG_FILE"
    exit 1
fi

if ! command -v flock >/dev/null 2>&1; then
    printf '%s flock is required to prevent duplicate bot processes.\n' "$(date -Iseconds)" >> "$LOG_FILE"
    exit 1
fi

# عملية flock تبقى ممسكة بالقفل طوال عمر main.py؛ الاستدعاءات اللاحقة تخرج فوراً.
nohup flock -n "$LOCK_FILE" "$PYTHON_BIN" "$SCRIPT_DIR/main.py" >> "$LOG_FILE" 2>&1 &
