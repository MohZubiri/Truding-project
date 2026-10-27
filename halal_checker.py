"""
وحدة فحص مشروعية العملة وإدارة القائمة البيضاء للعملات المباحة
بالإضافة إلى تفسير ردود بوت الفحص الشرعي وتخزين أحكامه مؤقتاً.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from config import HALAL_KEYWORDS, HARAM_KEYWORDS, HALAL_CACHE_DAYS

HALAL_CACHE_FILE = "halal_bot_cache.json"

HALAL_LIST_FILE = "halal_tokens.json"

DEFAULT_HALAL_TOKENS = {
    "BTC": {"status": "مباحة", "notes": "أصل تشفيري لامركزي (سلعة رقمية)"},
    "ETH": {"status": "مباحة", "notes": "منصة عقود ذكية مباحة في أغلب المعايير"},
    "SOL": {"status": "مباحة", "notes": "شبكة حوسبة عامة وسريعة"},
    "ADA": {"status": "مباحة", "notes": "بلوكتشين من الجيل الثالث"},
    "AVAX": {"status": "مباحة", "notes": "منصة عقود ذكية وبنية تحتية"},
    "MATIC": {"status": "مباحة", "notes": "شبكة توسعة وبنية تحتية"},
    "POL": {"status": "مباحة", "notes": "رمز Polygon المحدث"},
    "DOT": {"status": "مباحة", "notes": "بروتوكول ربط الشبكات اللامركزي"},
    "LINK": {"status": "مباحة", "notes": "شبكة أوراكل لامركزية لربط البيانات"},
    "NEAR": {"status": "مباحة", "notes": "بنية تحتية لتطبيقات الويب 3"},
    "SUI": {"status": "مباحة", "notes": "شبكة بلوكتشين عامة"},
    "APT": {"status": "مباحة", "notes": "شبكة بلوكتشين عامة"},
    "RENDER": {"status": "مباحة", "notes": "شبكة حوسبة سحابية ورندرة رسوميات"},
    "FET": {"status": "مباحة", "notes": "تحالف الذكاء الاصطناعي الفائق"},
    "INJ": {"status": "مباحة", "notes": "شبكة خدمات تقنية مالية مباحة"},
    "TIA": {"status": "مباحة", "notes": "شبكة بيانات وبنية تحتية"},
    "ATOM": {"status": "مباحة", "notes": "شبكة منظومة كوزموس للبنى التحتية"}
}

def load_halal_tokens():
    if not os.path.exists(HALAL_LIST_FILE):
        with open(HALAL_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_HALAL_TOKENS, f, ensure_ascii=False, indent=2)
        return DEFAULT_HALAL_TOKENS
    try:
        with open(HALAL_LIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_HALAL_TOKENS

def add_halal_token(ticker: str, notes: str = "مضافة يدوياً للقائمة البيضاء"):
    tokens = load_halal_tokens()
    t_clean = ticker.upper().strip()
    tokens[t_clean] = {"status": "مباحة", "notes": notes}
    with open(HALAL_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)

def check_token_compliance(ticker: str) -> dict:
    tokens = load_halal_tokens()
    ticker_clean = ticker.upper().strip()
    if ticker_clean in tokens:
        return {
            "is_halal": True,
            "ticker": ticker_clean,
            "status": tokens[ticker_clean].get("status", "مباحة"),
            "notes": tokens[ticker_clean].get("notes", "معتمدة ضمن القائمة البيضاء")
        }
    return {
        "is_halal": False,
        "ticker": ticker_clean,
        "status": "غير مفحوصة أو غير متوافقة",
        "notes": "الرمز غير مسجل في القائمة البيضاء المحلية، يرجى التثبت يدوياً."
    }

def classify_bot_reply(text: str) -> Optional[bool]:
    """تفسير رد بوت الفحص: True مباحة، False غير مباحة، None رد غير محسوم"""
    if not text:
        return None
    lowered = text.lower()
    if any(k in lowered for k in HARAM_KEYWORDS):
        return False
    if any(k in lowered for k in HALAL_KEYWORDS):
        return True
    return None

def _load_bot_cache() -> dict:
    if not os.path.exists(HALAL_CACHE_FILE):
        return {}
    try:
        with open(HALAL_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_cached_verdict(ticker: str) -> Optional[dict]:
    """إرجاع حكم البوت المخزن للعملة إذا لم تنتهِ صلاحيته"""
    entry = _load_bot_cache().get(ticker.upper().strip())
    if not entry:
        return None
    try:
        checked_at = datetime.strptime(entry["checked_at"], "%Y-%m-%d %H:%M")
    except (KeyError, ValueError):
        return None
    if datetime.now() - checked_at > timedelta(days=HALAL_CACHE_DAYS):
        return None
    return entry

def save_cached_verdict(ticker: str, verdict: dict):
    cache = _load_bot_cache()
    cache[ticker.upper().strip()] = {**verdict, "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(HALAL_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def clear_bot_cache():
    """مسح أحكام البوت المخزنة (عند تغيير بوت الفحص)"""
    if os.path.exists(HALAL_CACHE_FILE):
        os.remove(HALAL_CACHE_FILE)
