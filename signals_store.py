"""
وحدة تخزين الصفقات المستخرجة من القنوات (المقبولة والمرفوضة شرعياً)
لعرضها في لوحة الويب. تُحفظ في signals.json والأحدث أولاً.
"""
import json
import os
import threading
import uuid
from datetime import datetime
from typing import List, Dict, Any

SIGNALS_FILE = "signals.json"
MAX_SIGNALS = 500

# الكتابة تتم من خيط تيليجرام والقراءة من خيط لوحة الويب
_lock = threading.Lock()

def load_signals() -> List[Dict[str, Any]]:
    with _lock:
        if not os.path.exists(SIGNALS_FILE):
            return []
        try:
            with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

def save_signal(signal: Dict[str, Any], halal_info: Dict[str, Any], source_channel: str,
                current_price: float = None) -> Dict[str, Any]:
    """حفظ صفقة جديدة مع نتيجة الفحص الشرعي والقناة المصدر"""
    record = {
        "id": uuid.uuid4().hex[:12],
        "coin": signal["coin"],
        "pair": signal["pair"],
        "entry": signal.get("entry", []),
        "targets": signal.get("targets", []),
        "stop_loss": signal.get("stop_loss"),
        "current_price": current_price,
        "source": source_channel,
        "is_halal": halal_info["is_halal"],
        "halal_status": halal_info.get("status", ""),
        "halal_notes": halal_info.get("notes", ""),
        "verified_by": halal_info.get("verified_by", ""),
        "raw_text": signal.get("raw_text", ""),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    signals = load_signals()
    signals.insert(0, record)
    with _lock:
        tmp_path = SIGNALS_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(signals[:MAX_SIGNALS], f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SIGNALS_FILE)
    return record

def clear_signals():
    with _lock:
        if os.path.exists(SIGNALS_FILE):
            os.remove(SIGNALS_FILE)
