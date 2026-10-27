"""
وحدة إدارة وتخزين قنوات التوصيات (متعددة القنوات)
تدعم إضافة القناة عبر اسمها، معرفها (@username)، رابطها (https://t.me/...)، أو الرقم التعريفي (ID)
وتحفظها بشكل دائم في ملف channels.json.
"""
import json
import os
import re
from datetime import datetime
from typing import List, Dict, Any
from config import INITIAL_CHANNELS

CHANNELS_FILE = "channels.json"

def normalize_channel_input(raw_input: str) -> str:
    """
    تحويل رابط القناة أو اسمها إلى صيغة قياسية يفهمها تيليجرام
    أمثلة:
    https://t.me/crypto_signals -> @crypto_signals
    t.me/crypto_signals/123 -> @crypto_signals
    @crypto_signals -> @crypto_signals
    -100123456789 -> -100123456789
    """
    text = raw_input.strip()
    if not text:
        return ""

    # إذا كان معرفاً رقمياً سالباً أو موجباً
    if re.match(r'^-?\d+$', text):
        return text

    # إذا كان رابط دعوة خاص (https://t.me/+xxxx أو joinchat)
    if "t.me/+" in text or "joinchat/" in text:
        return text

    # إذا كان رابط قناة عامة مثل https://t.me/channel_name
    link_match = re.search(r'(?:https?://)?t\.me/([a-zA-Z0-9_]{3,64})', text, re.IGNORECASE)
    if link_match:
        return f"@{link_match.group(1)}"

    # إذا كان يبدأ بـ @
    if text.startswith("@"):
        return text

    # إذا كان اسماً برمجياً بدون مسافات نضع قبله @
    if re.match(r'^[a-zA-Z0-9_]{4,64}$', text):
        return f"@{text}"

    # إذا كان اسماً نصياً عادياً للقناة يحفظ كما هو للمطابقة بالاسم
    return text

def load_channels() -> List[Dict[str, Any]]:
    """تحميل جميع القنوات المخزنة في النظام"""
    if not os.path.exists(CHANNELS_FILE):
        initial_data = []
        for ch in INITIAL_CHANNELS:
            norm = normalize_channel_input(ch)
            if norm:
                initial_data.append({
                    "identifier": norm,
                    "raw_input": ch,
                    "title": norm,
                    "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
        save_channels(initial_data)
        return initial_data

    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def save_channels(channels: List[Dict[str, Any]]):
    """حفظ قائمة القنوات في ملف JSON"""
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)

def add_channel(raw_input: str, title: str = "") -> Dict[str, Any]:
    """إضافة قناة جديدة عبر الرابط أو الاسم وتخزينها في النظام"""
    norm = normalize_channel_input(raw_input)
    if not norm:
        return {"success": False, "message": "مدخل القناة فارغ أو غير صالح."}

    channels = load_channels()
    for ch in channels:
        if ch["identifier"].lower() == norm.lower() or ch["raw_input"].lower() == raw_input.strip().lower():
            return {"success": False, "message": f"القناة ({norm}) مضافة ومخزنة مسبقاً في النظام."}

    new_entry = {
        "identifier": norm,
        "raw_input": raw_input.strip(),
        "title": title.strip() if title else norm,
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    channels.append(new_entry)
    save_channels(channels)
    return {"success": True, "message": f"تمت إضافة القناة ({norm}) وحفظها بنجاح.", "channel": new_entry}

def remove_channel(identifier_or_raw: str) -> Dict[str, Any]:
    """حذف قناة من النظام"""
    target = identifier_or_raw.strip().lower()
    norm_target = normalize_channel_input(identifier_or_raw).lower()
    channels = load_channels()
    updated = [
        ch for ch in channels
        if ch["identifier"].lower() not in (target, norm_target)
        and ch["raw_input"].lower() != target
    ]
    if len(updated) == len(channels):
        return {"success": False, "message": "لم يتم العثور على هذه القناة في القائمة المخزنة."}

    save_channels(updated)
    return {"success": True, "message": f"تم حذف القناة ({identifier_or_raw}) من النظام."}

def update_channel(identifier: str, **fields) -> bool:
    """تحديث بيانات قناة مخزنة (مثل chat_id واسمها الفعلي بعد الانضمام)"""
    channels = load_channels()
    for ch in channels:
        if ch["identifier"] == identifier:
            ch.update(fields)
            save_channels(channels)
            return True
    return False

def is_monitored_chat(chat_id: int, username: str = None, title: str = None) -> bool:
    """التحقق مما إذا كانت الرسالة الواردة قادمة من إحدى القنوات المخزنة"""
    channels = load_channels()
    if not channels:
        return False

    chat_id_str = str(chat_id)
    full_chat_id_str = f"-100{abs(chat_id)}" if not str(chat_id).startswith("-100") else str(chat_id)
    uname_clean = f"@{username.lower()}" if username else ""
    title_clean = title.strip().lower() if title else ""

    for ch in channels:
        ident = ch["identifier"].strip().lower()
        ch_title = ch.get("title", "").strip().lower()

        if ident in (chat_id_str, full_chat_id_str) or str(ch.get("chat_id", "")) == chat_id_str:
            return True
        if uname_clean and ident == uname_clean:
            return True
        if title_clean and (ident == title_clean or ch_title == title_clean):
            return True

    return False
