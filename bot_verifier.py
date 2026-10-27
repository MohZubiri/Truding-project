"""
وحدة التحقق من مشروعية العملة عبر بوت تيليجرام خارجي
ترتيب الفحص:
1. القائمة البيضاء المحلية (اعتماد يدوي من المشرف يتقدم على أي حكم آخر).
2. حكم البوت المخزن مؤقتاً (halal_bot_cache.json).
3. سؤال البوت مباشرة عبر حساب الـ Userbot وقراءة رده.
"""
import asyncio
import logging
import re
from typing import Optional
from telethon import TelegramClient

from config import HALAL_BOT_TIMEOUT
from channel_manager import normalize_channel_input
from settings_store import load_settings, save_settings
from halal_checker import (
    check_token_compliance,
    classify_bot_reply,
    get_cached_verdict,
    save_cached_verdict,
    clear_bot_cache
)

logger = logging.getLogger(__name__)

# محادثة واحدة فقط مع البوت في كل مرة حتى لا تختلط الردود بين العملات
_bot_lock = asyncio.Lock()

# أقصى عدد رسائل ننتظرها من البوت (بعض البوتات ترسل "جاري البحث..." قبل النتيجة)
MAX_BOT_REPLIES = 3

def _clean_reply(text: str) -> str:
    """تنظيف رد البوت من رموز Markdown حتى لا يكسر رسالة التنبيه"""
    text = re.sub(r'[*_`\[\]]', '', text or "").strip()
    return text[:300] + ("..." if len(text) > 300 else "")

def set_halal_bot(raw_username: str, query_template: str = "") -> dict:
    """حفظ بوت الفحص الشرعي (اسم أو رابط) ومسح أحكام البوت السابق المخزنة"""
    username = normalize_channel_input(raw_username) if raw_username.strip() else ""
    if username and not re.match(r'^@[a-zA-Z0-9_]{4,64}$', username):
        return {"success": False, "message": "اسم البوت غير صالح. مثال صحيح: @HalalCryptoBot أو https://t.me/HalalCryptoBot"}

    template = query_template.strip() or "{coin}"
    if "{coin}" not in template:
        return {"success": False, "message": "صيغة السؤال يجب أن تحتوي على {coin} ليُستبدل برمز العملة."}

    previous = load_settings()
    save_settings(halal_bot_username=username, halal_bot_query_template=template)
    if previous["halal_bot_username"].lower() != username.lower():
        clear_bot_cache()

    if not username:
        return {"success": True, "message": "تم إلغاء بوت الفحص، سيتم الاكتفاء بالقائمة البيضاء المحلية."}
    return {"success": True, "message": f"تم حفظ بوت الفحص الشرعي ({username}) بنجاح."}

async def ask_halal_bot(client: TelegramClient, bot_username: str, query_template: str, ticker: str) -> Optional[str]:
    """إرسال رمز العملة للبوت وإرجاع الرد الذي يحمل حكماً واضحاً (أو آخر رد إن لم يُحسم)"""
    async with _bot_lock:
        async with client.conversation(bot_username, timeout=HALAL_BOT_TIMEOUT) as conv:
            await conv.send_message(query_template.format(coin=ticker))
            last_reply = None
            for _ in range(MAX_BOT_REPLIES):
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    break
                last_reply = resp.raw_text
                if classify_bot_reply(last_reply) is not None:
                    break
            return last_reply

async def verify_coin(client: TelegramClient, ticker: str) -> dict:
    """التحقق من مشروعية العملة وإرجاع نتيجة موحدة مع مصدر الحكم"""
    whitelist = check_token_compliance(ticker)
    if whitelist["is_halal"]:
        return {**whitelist, "verified_by": "القائمة البيضاء"}

    settings = load_settings()
    bot_username = settings["halal_bot_username"]
    if not bot_username:
        return {**whitelist, "verified_by": "القائمة البيضاء"}

    cached = get_cached_verdict(ticker)
    if cached:
        return {**cached, "ticker": whitelist["ticker"], "verified_by": f"{bot_username} (محفوظ)"}

    try:
        reply = await ask_halal_bot(client, bot_username, settings["halal_bot_query_template"], whitelist["ticker"])
    except Exception as e:
        logger.error(f"تعذر التواصل مع بوت الفحص {bot_username}: {e}")
        reply = None

    verdict = classify_bot_reply(reply)
    if verdict is None:
        return {
            "is_halal": False,
            "ticker": whitelist["ticker"],
            "status": "غير محسومة",
            "notes": _clean_reply(reply) if reply else "لم يصل رد واضح من بوت الفحص.",
            "verified_by": bot_username
        }

    result = {
        "is_halal": verdict,
        "status": "مباحة" if verdict else "غير مباحة",
        "notes": _clean_reply(reply)
    }
    save_cached_verdict(whitelist["ticker"], result)
    return {**result, "ticker": whitelist["ticker"], "verified_by": bot_username}
