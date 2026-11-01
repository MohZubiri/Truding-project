"""سجل دائم لمنع تكرار تحليل وإشعار رسالة تيليجرام نفسها."""
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict


PROCESSED_MESSAGES_FILE = "processed_messages.json"
RETENTION_DAYS = 7
_lock = threading.RLock()


def build_message_key(chat_id, message_id) -> str:
    if chat_id is None or message_id is None:
        return ""
    return f"{chat_id}:{message_id}"


def _load_unlocked() -> Dict[str, str]:
    if not os.path.exists(PROCESSED_MESSAGES_FILE):
        return {}
    try:
        with open(PROCESSED_MESSAGES_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _prune(data: Dict[str, str]) -> Dict[str, str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    kept = {}
    for key, value in data.items():
        try:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp >= cutoff:
                kept[key] = value
        except (TypeError, ValueError):
            continue
    return kept


def is_message_processed(message_key: str) -> bool:
    if not message_key:
        return False
    with _lock:
        return message_key in _load_unlocked()


def mark_message_processed(message_key: str) -> None:
    if not message_key:
        return
    with _lock:
        data = _prune(_load_unlocked())
        data[message_key] = datetime.now(timezone.utc).isoformat()
        temp_path = PROCESSED_MESSAGES_FILE + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, PROCESSED_MESSAGES_FILE)
