"""
وحدة تخزين الصفقات المستخرجة من القنوات (المقبولة والمرفوضة شرعياً)
لعرضها في لوحة الويب. تُحفظ في signals.json والأحدث أولاً.
"""
import json
import os
import threading
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

SIGNALS_FILE = "signals.json"
MAX_SIGNALS = 500

# الكتابة تتم من خيط تيليجرام والقراءة من خيط لوحة الويب
_lock = threading.RLock()


def _has_pending_delivery(record: Dict[str, Any]) -> bool:
    return bool(
        record.get("telegram_required", False)
        and not record.get("telegram_sent", False)
    )


def _load_signals_unlocked() -> List[Dict[str, Any]]:
    if not os.path.exists(SIGNALS_FILE):
        return []
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_signals_unlocked(signals: List[Dict[str, Any]]) -> None:
    records = signals[:MAX_SIGNALS]
    retained_ids = {record.get("id") for record in records}
    records.extend(
        record
        for record in signals[MAX_SIGNALS:]
        if record.get("id") not in retained_ids and _has_pending_delivery(record)
    )
    tmp_path = SIGNALS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SIGNALS_FILE)

def load_signals() -> List[Dict[str, Any]]:
    with _lock:
        return _load_signals_unlocked()

def save_signal(signal: Dict[str, Any], halal_info: Dict[str, Any], source_channel: str,
                current_price: float = None, analysis: Dict[str, Any] = None,
                source_chat_id: Optional[int] = None,
                source_message_id: Optional[int] = None,
                published_at: Optional[str] = None,
                telegram_required: bool = False) -> Dict[str, Any]:
    """حفظ صفقة وإرجاع السجل؛ يحافظ على التوافق مع الاستدعاءات القديمة."""
    record, _ = save_signal_once(
        signal=signal,
        halal_info=halal_info,
        source_channel=source_channel,
        current_price=current_price,
        analysis=analysis,
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        published_at=published_at,
        telegram_required=telegram_required,
    )
    return record


def save_signal_once(signal: Dict[str, Any], halal_info: Dict[str, Any],
                     source_channel: str, current_price: float = None,
                     analysis: Dict[str, Any] = None,
                     source_chat_id: Optional[int] = None,
                     source_message_id: Optional[int] = None,
                     published_at: Optional[str] = None,
                     telegram_required: bool = False) -> Tuple[Dict[str, Any], bool]:
    """حفظ ذري مع منع تكرار الرسالة نفسها، وإرجاع (السجل، هل أُنشئ الآن)."""
    message_key = ""
    if source_chat_id is not None and source_message_id is not None:
        message_key = f"{source_chat_id}:{source_message_id}"

    with _lock:
        signals = _load_signals_unlocked()
        if message_key:
            for existing in signals:
                if existing.get("source_message_key") == message_key:
                    if existing.get("halal_status") == "غير محسومة":
                        existing.update({
                            "current_price": current_price,
                            "analysis": analysis or {},
                            "is_halal": halal_info["is_halal"],
                            "halal_status": halal_info.get("status", ""),
                            "halal_notes": halal_info.get("notes", ""),
                            "verified_by": halal_info.get("verified_by", ""),
                            "telegram_required": telegram_required,
                            "telegram_sent": False,
                        })
                        _write_signals_unlocked(signals)
                        became_resolved = halal_info.get("status") != "غير محسومة"
                        return existing, became_resolved
                    return existing, False

        record = {
            "id": uuid.uuid4().hex[:12],
            "coin": signal["coin"],
            "pair": signal["pair"],
            "entry": signal.get("entry", []),
            "targets": signal.get("targets", []),
            "stop_loss": signal.get("stop_loss"),
            "current_price": current_price,
            "analysis": analysis or {},
            "source": source_channel,
            "source_chat_id": source_chat_id,
            "source_message_id": source_message_id,
            "source_message_key": message_key,
            "published_at": published_at,
            "is_halal": halal_info["is_halal"],
            "halal_status": halal_info.get("status", ""),
            "halal_notes": halal_info.get("notes", ""),
            "verified_by": halal_info.get("verified_by", ""),
            "telegram_required": telegram_required,
            "telegram_sent": False,
            "raw_text": signal.get("raw_text", ""),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        signals.insert(0, record)
        _write_signals_unlocked(signals)
        return record, True


def get_signal_by_message_key(message_key: str) -> Optional[Dict[str, Any]]:
    if not message_key:
        return None
    with _lock:
        for record in _load_signals_unlocked():
            if record.get("source_message_key") == message_key:
                return record
    return None


def get_signal_by_id(signal_id: str) -> Optional[Dict[str, Any]]:
    if not signal_id:
        return None
    with _lock:
        for record in _load_signals_unlocked():
            if record.get("id") == signal_id:
                return record
    return None


def update_signal(signal_id: str, **fields) -> Optional[Dict[str, Any]]:
    """تحديث ذري لحالة إرسال التنبيهات أو أي حقول تشغيلية أخرى."""
    with _lock:
        signals = _load_signals_unlocked()
        for record in signals:
            if record.get("id") == signal_id:
                record.update(fields)
                _write_signals_unlocked(signals)
                return record
    return None


def load_pending_signals() -> List[Dict[str, Any]]:
    with _lock:
        return [record for record in _load_signals_unlocked() if _has_pending_delivery(record)]

def clear_signals():
    with _lock:
        if os.path.exists(SIGNALS_FILE):
            os.remove(SIGNALS_FILE)
