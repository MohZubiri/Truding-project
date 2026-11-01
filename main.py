"""
المحرك الرئيسي للنظام (الإصدار الثالث - متعدد القنوات مع التحقق عبر بوت الفحص الشرعي)
1. يستمع لجميع القنوات المخزنة في channels.json بشكل ديناميكي دون الحاجة لإعادة التشغيل.
2. ينضم تلقائياً لأي قناة جديدة تضاف من تيليجرام أو من لوحة الويب (عامة أو برابط دعوة خاص).
3. يستخرج الصفقة ويتحقق من مشروعية العملة عبر بوت تيليجرام ثم يحفظها لعرضها في لوحة الويب.
"""
import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone
from telethon import TelegramClient, events
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.utils import get_peer_id
import requests

from config import (
    TG_API_ID,
    TG_API_HASH,
    TG_BOT_TOKEN,
    ADMIN_CHAT_ID,
    WEB_PORT,
    WEB_HOST,
    PANEL_PASSWORD,
    APP_TIMEZONE,
    DAILY_SCAN_ENABLED,
    DAILY_SCAN_TIMES,
)
from channel_manager import (
    load_channels,
    add_channel,
    remove_channel,
    update_channel,
    is_monitored_chat
)
from parser import extract_signal
from halal_checker import add_halal_token
from bot_verifier import verify_coin, set_halal_bot
from settings_store import load_settings
from signals_store import (
    get_signal_by_id,
    get_signal_by_message_key,
    load_pending_signals,
    save_signal_once,
    update_signal,
)
from binance_guide import generate_manual_trading_guide
from processed_messages_store import (
    build_message_key,
    is_message_processed,
    mark_message_processed,
)
from schedule_utils import (
    next_scan_at,
    parse_scan_times,
    resolve_timezone_name,
    start_of_today_utc,
)
from trade_analyzer import analyze_trade
from web_panel import app as flask_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
ACTIVE_TIMEZONE = resolve_timezone_name(APP_TIMEZONE)
if ACTIVE_TIMEZONE != APP_TIMEZONE:
    logger.warning(
        "المنطقة الزمنية %s غير صالحة؛ سيُستخدم %s.",
        APP_TIMEZONE,
        ACTIVE_TIMEZONE,
    )

# جلسة الـ Userbot لقراءة القنوات
client = TelegramClient("crypto_listener_session", TG_API_ID, TG_API_HASH)

# الفاصل الزمني لفحص القنوات الجديدة المضافة من لوحة الويب، وانتظار إعادة المحاولة عند الفشل
JOIN_SYNC_INTERVAL = 60
JOIN_RETRY_AFTER = 600
NOTIFICATION_RETRY_INTERVAL = 300
_join_failures = {}
_processing_keys = set()
_processing_keys_lock = asyncio.Lock()
_notification_delivery_lock = asyncio.Lock()
_daily_scan_state_lock = asyncio.Lock()
_daily_scan_running = False

def send_telegram_alert(text: str):
    """إرسال رسالة أو تنبيه إلى حسابك الشخصي عبر Telegram Bot API"""
    if not TG_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.warning("لم يتم ضبط TG_BOT_TOKEN أو ADMIN_CHAT_ID في ملف .env")
        return False
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"فشل إرسال التنبيه: {resp.text}")
            return False
        return True
    except Exception as e:
        # قد يتضمن نص استثناء requests رابط Bot API وفيه التوكن؛ لا نسجله.
        logger.error(
            "تعذر الاتصال بخدمة Telegram Bot API (%s)",
            type(e).__name__,
        )
        return False

def get_binance_spot_price(pair: str) -> float:
    """جلب السعر اللحظي للزوج من منصة بينانس"""
    try:
        clean_symbol = pair.replace("/", "")
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={clean_symbol}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return float(res.json().get("price", 0))
    except Exception:
        pass
    return None

async def join_channel(ch: dict) -> str:
    """الانضمام لقناة مخزنة وحفظ معرفها الرقمي (chat_id) لمطابقة رسائلها بدقة"""
    ident = ch["identifier"]
    if ident.startswith("@"):
        entity = await client.get_entity(ident)
        try:
            await client(JoinChannelRequest(entity))
        except UserAlreadyParticipantError:
            pass
    elif "t.me/+" in ident or "joinchat/" in ident:
        invite_hash = re.split(r't\.me/\+|joinchat/', ident)[-1].strip("/")
        try:
            updates = await client(ImportChatInviteRequest(invite_hash))
            entity = updates.chats[0]
        except UserAlreadyParticipantError:
            entity = (await client(CheckChatInviteRequest(invite_hash))).chat
    elif re.match(r'^-?\d+$', ident):
        entity = await client.get_entity(int(ident))
    else:
        # اسم نصي للقناة: تتم المطابقة بالاسم فقط
        return ""

    tg_title = getattr(entity, "title", "") or ident
    update_channel(ident, chat_id=get_peer_id(entity), tg_title=tg_title)
    return tg_title

async def sync_channel_joins():
    """الانضمام الدوري لأي قناة أضيفت من لوحة الويب ولم يتم الانضمام إليها بعد"""
    while True:
        for ch in load_channels():
            ident = ch["identifier"]
            if ch.get("chat_id") or time.time() - _join_failures.get(ident, 0) < JOIN_RETRY_AFTER:
                continue
            try:
                tg_title = await join_channel(ch)
                if tg_title:
                    logger.info(f"✅ تم الانضمام للقناة {ident} ({tg_title})")
            except Exception as e:
                _join_failures[ident] = time.time()
                logger.warning(f"تعذر الانضمام للقناة {ident}: {e}")
        await asyncio.sleep(JOIN_SYNC_INTERVAL)


def _published_at_iso(message_date) -> str:
    if not message_date:
        return ""
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)
    return message_date.astimezone(timezone.utc).isoformat()


def _guide_from_record(record: dict) -> str:
    signal = {
        "coin": record.get("coin"),
        "pair": record.get("pair"),
        "entry": record.get("entry", []),
        "targets": record.get("targets", []),
        "stop_loss": record.get("stop_loss"),
        "raw_text": record.get("raw_text", ""),
    }
    halal_info = {
        "is_halal": record.get("is_halal", False),
        "status": record.get("halal_status", ""),
        "notes": record.get("halal_notes", ""),
        "verified_by": record.get("verified_by", ""),
    }
    return generate_manual_trading_guide(
        signal=signal,
        halal_info=halal_info,
        current_price=record.get("current_price"),
        source_channel=record.get("source", "قناة التوصيات"),
        analysis=record.get("analysis", {}),
    )


async def _deliver_trade_notifications_unlocked(record: dict) -> dict:
    """إرسال تنبيه تيليجرام الذي لم ينجح سابقاً وتثبيت حالته في السجل."""
    result = {"telegram": "not_required"}
    signal_id = record.get("id")
    attempt_time = datetime.now(timezone.utc).isoformat()

    telegram_required = record.get("telegram_required", False)
    if telegram_required:
        if record.get("telegram_sent"):
            result["telegram"] = "already_sent"
        else:
            sent = await asyncio.to_thread(send_telegram_alert, _guide_from_record(record))
            result["telegram"] = "sent" if sent else "failed"
            fields = {"telegram_last_attempt_at": attempt_time}
            if sent:
                fields["telegram_sent"] = True
                record["telegram_sent"] = True
            await asyncio.to_thread(update_signal, signal_id, **fields)

    return result


async def deliver_trade_notifications(record: dict) -> dict:
    """تسلسل الإرسال ومنع سباق العامل الدوري مع المعالجة اللحظية."""
    async with _notification_delivery_lock:
        latest_record = get_signal_by_id(record.get("id")) or record
        return await _deliver_trade_notifications_unlocked(latest_record)


async def process_signal_message(message_text: str, source_label: str,
                                 source_chat_id=None, source_message_id=None,
                                 message_date=None) -> dict:
    """مسار موحد لمعالجة الرسائل اللحظية ورسائل المسح المجدول."""
    if not message_text or message_text.startswith("/"):
        return {"status": "ignored"}

    signal = extract_signal(message_text)
    if not signal:
        return {"status": "not_signal"}

    message_key = build_message_key(source_chat_id, source_message_id)
    retry_record = None
    if message_key:
        async with _processing_keys_lock:
            if message_key in _processing_keys:
                return {"status": "duplicate"}
            if is_message_processed(message_key):
                retry_record = get_signal_by_message_key(message_key)
                if retry_record is None:
                    return {"status": "duplicate"}
                if retry_record and retry_record.get("halal_status") == "غير محسومة":
                    retry_record = None
            _processing_keys.add(message_key)

    try:
        if retry_record is not None:
            delivery = await deliver_trade_notifications(retry_record)
            return {
                "status": "duplicate",
                "record": retry_record,
                "delivery": delivery,
            }

        coin = signal["coin"]
        logger.info("تم اكتشاف توصية للعملة %s من %s", coin, source_label)

        halal_status = await verify_coin(client, coin)
        current_price = await asyncio.to_thread(
            get_binance_spot_price, signal["pair"]
        )
        analysis = analyze_trade(signal, current_price)
        unresolved = halal_status.get("status") == "غير محسومة"
        telegram_required = bool(halal_status["is_halal"])

        record, created = save_signal_once(
            signal=signal,
            halal_info=halal_status,
            source_channel=source_label,
            current_price=current_price,
            analysis=analysis,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            published_at=_published_at_iso(message_date),
            telegram_required=telegram_required,
        )
        if message_key and not unresolved:
            mark_message_processed(message_key)
        if not created:
            delivery = await deliver_trade_notifications(record)
            return {
                "status": "duplicate",
                "record": record,
                "delivery": delivery,
            }

        if not halal_status["is_halal"]:
            logger.warning(
                "العملة %s %s حسب %s. لن يُرسل تنبيه تداول.",
                coin,
                halal_status["status"],
                halal_status["verified_by"],
            )
            delivery = await deliver_trade_notifications(record)
            return {"status": "rejected", "record": record, "delivery": delivery}

        delivery = await deliver_trade_notifications(record)
        logger.info(
            "اكتملت معالجة %s (Telegram: %s)",
            coin,
            delivery["telegram"],
        )
        return {
            "status": "approved",
            "record": record,
            "delivery": delivery,
        }
    finally:
        if message_key:
            async with _processing_keys_lock:
                _processing_keys.discard(message_key)

# --- أوامر إدارة القنوات مباشرة من داخل تيليجرام ---
@client.on(events.NewMessage(from_users=ADMIN_CHAT_ID if ADMIN_CHAT_ID else None))
async def handle_admin_commands(event):
    text = (event.message.message or "").strip()
    if not text.startswith("/"):
        return

    # أمر إضافة قناة: /add https://t.me/ChannelName أو /add @ChannelName أو رابط دعوة خاص
    if text.startswith("/add "):
        raw_ch = text.replace("/add ", "", 1).strip()
        res = add_channel(raw_ch)
        if res["success"]:
            try:
                tg_title = await join_channel(res["channel"])
                if tg_title:
                    res["message"] += f"\n✅ تم الانضمام للقناة `{tg_title}`."
            except Exception as e:
                res["message"] += f"\n⚠️ تعذر الانضمام تلقائياً: {e}"
        await event.reply(f"📌 {res['message']}")

    # أمر عرض القنوات المخزنة: /channels
    elif text == "/channels":
        channels = load_channels()
        if not channels:
            await event.reply("📭 لا توجد قنوات مخزنة حالياً. أضف قناة بالأمر:\n`/add @ChannelName`")
            return
        lines = ["📡 **القنوات المخزنة والنشطة حالياً:**\n"]
        for i, ch in enumerate(channels, 1):
            joined = "✅" if ch.get("chat_id") else "⏳"
            lines.append(f"{i}. {joined} `{ch['identifier']}` ({ch.get('title', '')})")
        lines.append("\nلإضافة قناة جديدة أرسل: `/add رابط_أو_اسم_القناة`")
        lines.append("لحذف قناة أرسل: `/del رابط_أو_اسم_القناة`")
        await event.reply("\n".join(lines))

    # أمر حذف قناة: /del @ChannelName
    elif text.startswith("/del "):
        raw_ch = text.replace("/del ", "", 1).strip()
        res = remove_channel(raw_ch)
        await event.reply(f"🗑️ {res['message']}")

    # أمر إضافة عملة للقائمة البيضاء: /halal SOL
    elif text.startswith("/halal "):
        coin = text.replace("/halal ", "", 1).strip().upper()
        if coin:
            add_halal_token(coin, "تمت إضافتها عبر أوامر تيليجرام")
            await event.reply(f"✅ تمت إضافة العملة `{coin}` إلى القائمة البيضاء المباحة.")

    # أمر تعيين بوت الفحص الشرعي: /bot @HalalBot أو /bot off للإلغاء
    elif text == "/bot":
        bot_username = load_settings()["halal_bot_username"] or "غير محدد"
        await event.reply(f"🤖 بوت الفحص الحالي: `{bot_username}`\nلتغييره أرسل: `/bot @اسم_البوت`")

    elif text.startswith("/bot "):
        raw_bot = text.replace("/bot ", "", 1).strip()
        res = set_halal_bot("" if raw_bot.lower() == "off" else raw_bot, load_settings()["halal_bot_query_template"])
        await event.reply(f"🤖 {res['message']}")

    # أمر فحص عملة يدوياً عبر بوت الفحص: /check SOL
    elif text.startswith("/check "):
        coin = text.replace("/check ", "", 1).strip().upper()
        if coin:
            res = await verify_coin(client, coin)
            icon = "✅" if res["is_halal"] else "⛔"
            await event.reply(f"{icon} `{coin}`: {res['status']}\n📝 {res['notes']}\n🔎 المصدر: {res['verified_by']}")

    # تشغيل مسح رسائل اليوم يدوياً لاختبار الجدولة
    elif text in ("/scan", "/scan_today"):
        await event.reply("🔎 بدأ مسح صفقات اليوم في القنوات المخزنة...")
        stats = await scan_today_signals()
        if stats.get("skipped"):
            await event.reply("⏳ يوجد مسح آخر يعمل حالياً.")
        else:
            await event.reply(
                "✅ اكتمل المسح: "
                f"{stats['messages']} رسالة، "
                f"{stats['new_signals']} صفقة جديدة، "
                f"{stats['duplicates']} مكررة، "
                f"{stats['errors']} أخطاء."
            )

# --- الاستماع الديناميكي لجميع قنوات التوصيات المخزنة ---
@client.on(events.NewMessage())
async def handle_channel_messages(event):
    # نتجاهل الرسائل الخاصة التي تبدأ بأوامر إدارية
    message_text = event.message.message
    if not message_text or message_text.startswith("/"):
        return

    chat = await event.get_chat()
    chat_id = event.chat_id
    username = getattr(chat, "username", None)
    title = getattr(chat, "title", None)

    # التحقق مما إذا كانت القناة ضمن القنوات المخزنة في channels.json
    if not is_monitored_chat(chat_id, username, title):
        return

    source_label = f"@{username}" if username else (title or str(chat_id))
    logger.info(f"رسالة جديدة واردة من القناة المراقبة: {source_label}")
    await process_signal_message(
        message_text=message_text,
        source_label=source_label,
        source_chat_id=chat_id,
        source_message_id=event.message.id,
        message_date=event.message.date,
    )


async def scan_today_signals() -> dict:
    """قراءة تاريخ قنوات اليوم حسب المنطقة الزمنية وضخّه في المسار الموحد."""
    global _daily_scan_running
    async with _daily_scan_state_lock:
        if _daily_scan_running:
            return {"skipped": True}
        _daily_scan_running = True
    stats = {
        "messages": 0,
        "new_signals": 0,
        "duplicates": 0,
        "errors": 0,
        "notification_failures": 0,
    }
    try:
        day_start_utc = start_of_today_utc(ACTIVE_TIMEZONE)
        logger.info(
            "بدء مسح صفقات اليوم منذ %s (%s)",
            day_start_utc.isoformat(),
            ACTIVE_TIMEZONE,
        )
        for channel in load_channels():
            channel_identifier = channel.get("identifier")
            chat_id = channel.get("chat_id")
            lookup_identifier = chat_id or channel_identifier
            log_identifier = channel_identifier or chat_id or "<missing>"
            try:
                try:
                    entity = await client.get_entity(lookup_identifier)
                except Exception as chat_id_exc:
                    if chat_id and channel_identifier and channel_identifier != chat_id:
                        logger.warning(
                            "تعذر حل chat_id للقناة %s (%s)، ستتم المحاولة عبر المعرّف: %s",
                            log_identifier,
                            chat_id,
                            chat_id_exc,
                        )
                        entity = await client.get_entity(channel_identifier)
                    else:
                        raise
                source_chat_id = get_peer_id(entity)
                username = getattr(entity, "username", None)
                title = getattr(entity, "title", None)
                source_label = f"@{username}" if username else (title or str(source_chat_id))

                # reverse + offset_date يعيدان رسائل ما بعد منتصف الليل من الأقدم
                # إلى الأحدث دون جمع يوم كامل في الذاكرة.
                async for message in client.iter_messages(
                    entity,
                    reverse=True,
                    offset_date=day_start_utc,
                ):
                    message_date = message.date
                    if message_date.tzinfo is None:
                        message_date = message_date.replace(tzinfo=timezone.utc)
                    if message_date < day_start_utc:
                        continue
                    if not message.message:
                        continue
                    stats["messages"] += 1
                    result = await process_signal_message(
                        message_text=message.message,
                        source_label=source_label,
                        source_chat_id=source_chat_id,
                        source_message_id=message.id,
                        message_date=message.date,
                    )
                    if result["status"] in ("approved", "rejected"):
                        stats["new_signals"] += 1
                    elif result["status"] == "duplicate":
                        stats["duplicates"] += 1
                    if (result.get("delivery") or {}).get("telegram") == "failed":
                        stats["notification_failures"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.error("تعذر مسح قناة %s: %s", log_identifier, exc)

        logger.info(
            "اكتمل مسح اليوم: %s رسالة، %s صفقة جديدة، %s مكررة، "
            "%s أخطاء، %s إشعارات فاشلة",
            stats["messages"],
            stats["new_signals"],
            stats["duplicates"],
            stats["errors"],
            stats["notification_failures"],
        )
        return stats
    finally:
        async with _daily_scan_state_lock:
            _daily_scan_running = False


async def daily_scan_scheduler():
    """تشغيل مسح اليوم في الأوقات المضبوطة، ثلاث مرات افتراضياً."""
    try:
        scan_times = parse_scan_times(DAILY_SCAN_TIMES)
    except Exception as exc:
        logger.error("تعذر تشغيل جدولة المسح اليومي: %s", exc)
        return

    while True:
        next_run = next_scan_at(scan_times, ACTIVE_TIMEZONE)
        delay = max(0, (next_run.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
        logger.info("المسح المجدول التالي: %s", next_run.isoformat())
        await asyncio.sleep(delay)
        try:
            await scan_today_signals()
        except Exception:
            logger.exception("فشل المسح المجدول؛ ستستمر الجدولة للموعد التالي")


async def daily_scan_service():
    """مسح تعويضي عند الإقلاع ثم الانتقال للمواعيد اليومية."""
    try:
        await scan_today_signals()
    except Exception:
        logger.exception("فشل المسح التعويضي عند الإقلاع")
    await daily_scan_scheduler()


async def retry_pending_notifications() -> dict:
    """إعادة محاولة الإشعارات المعلقة دون الحاجة لإعادة قراءة رسائل تيليجرام."""
    stats = {"pending": 0, "sent": 0, "failed": 0}
    for record in load_pending_signals():
        stats["pending"] += 1
        delivery = await deliver_trade_notifications(record)
        statuses = tuple(delivery.values())
        if "sent" in statuses:
            stats["sent"] += 1
        if "failed" in statuses:
            stats["failed"] += 1
    return stats


async def notification_retry_worker():
    """عامل outbox دوري مستقل عن حدود اليوم ومواعيد مسح القنوات."""
    while True:
        try:
            stats = await retry_pending_notifications()
            if stats["pending"]:
                logger.info(
                    "فحص الإشعارات المعلقة: %s معلقة، %s أُرسلت، %s فشلت",
                    stats["pending"],
                    stats["sent"],
                    stats["failed"],
                )
        except Exception:
            logger.exception("تعذر تشغيل عامل إعادة الإشعارات")
        await asyncio.sleep(NOTIFICATION_RETRY_INTERVAL)

def run_web_dashboard():
    """تشغيل لوحة التحكم الويب في الخلفية"""
    flask_app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)

async def main():
    logger.info("جاري تشغيل مستمع تيليجرام (Multi-Channel Listener)...")
    await client.start()
    account = await client.get_me()
    if getattr(account, "bot", False):
        logger.error(
            "ملف crypto_listener_session.session مسجل كبوت. "
            "أنشئ جلسة جديدة برقم هاتف الحساب الشخصي، وليس Bot Token."
        )
        await client.disconnect()
        return

    # تشغيل لوحة الويب بعد التأكد من أن جلسة تيليجرام حساب مستخدم صالحة.
    web_thread = threading.Thread(target=run_web_dashboard, daemon=True)
    web_thread.start()
    logger.info(f"🌐 لوحة التحكم لإضافة القنوات وعرض الصفقات تعمل على: http://127.0.0.1:{WEB_PORT}")

    if not PANEL_PASSWORD:
        logger.warning("⚠️ لم يتم ضبط PANEL_PASSWORD، لوحة الويب مفتوحة لأي شخص يعرف رابطها!")
    if not load_settings()["halal_bot_username"]:
        logger.warning("لم يتم تحديد بوت الفحص الشرعي، أضفه من لوحة الويب أو بالأمر /bot @اسم_البوت. حالياً يتم الاكتفاء بالقائمة البيضاء.")
    channels = load_channels()
    logger.info(f"البوت يعمل الآن ويراقب ({len(channels)}) قناة مخزنة.")
    asyncio.create_task(sync_channel_joins())
    asyncio.create_task(notification_retry_worker())
    if DAILY_SCAN_ENABLED:
        logger.info(
            "مسح صفقات اليوم مفعّل في الأوقات %s حسب %s",
            ", ".join(DAILY_SCAN_TIMES),
            ACTIVE_TIMEZONE,
        )
        asyncio.create_task(daily_scan_service())
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
