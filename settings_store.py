"""
وحدة إعدادات النظام القابلة للتعديل من لوحة الويب أو أوامر تيليجرام (اسم بوت الفحص الشرعي وصيغة السؤال)
تُحفظ في settings.json، وقيم ملف .env تُستخدم كقيم أولية فقط.
"""
import json
import os
import threading
from typing import Dict, Any
from config import HALAL_BOT_USERNAME, HALAL_BOT_QUERY_TEMPLATE

SETTINGS_FILE = "settings.json"

_lock = threading.Lock()

DEFAULT_SETTINGS = {
    "halal_bot_username": HALAL_BOT_USERNAME,
    "halal_bot_query_template": HALAL_BOT_QUERY_TEMPLATE
}

def load_settings() -> Dict[str, Any]:
    with _lock:
        if not os.path.exists(SETTINGS_FILE):
            return dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except Exception:
            return dict(DEFAULT_SETTINGS)

def save_settings(**fields) -> Dict[str, Any]:
    settings = {**load_settings(), **fields}
    with _lock:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    return settings
