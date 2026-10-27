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
    PANEL_PASSWORD
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
from signals_store import save_signal
from binance_guide import generate_manual_trading_guide
from web_panel import app as flask_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# جلسة الـ Userbot لقراءة القنوات
client = TelegramClient("crypto_listener_session", TG_API_ID, TG_API_HASH)

# الفاصل الزمني لفحص القنوات الجديدة المضافة من لوحة الويب، وانتظار إعادة المحاولة عند الفشل
JOIN_SYNC_INTERVAL = 60
JOIN_RETRY_AFTER = 600
_join_failures = {}

def send_telegram_alert(text: str):
    """إرسال رسالة أو تنبيه إلى حسابك الشخصي عبر Telegram Bot API"""
    if not TG_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.warning("لم يتم ضبط TG_BOT_TOKEN أو ADMIN_CHAT_ID في ملف .env")
        return
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
    except Exception as e:
        logger.error(f"خطأ أثناء إرسال رسالة البوت: {e}")

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
        await client(JoinChannelRequest(entity))
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

    # 1. استخراج بيانات الصفقة
    signal = extract_signal(message_text)
    if not signal:
        return

    coin = signal["coin"]
    logger.info(f"تم اكتشاف توصية للعملة {coin} من {source_label}")

    # 2. الفحص الشرعي للعملة (القائمة البيضاء ثم بوت الفحص)
    halal_status = await verify_coin(client, coin)

    # 3. جلب السعر الفوري من بينانس
    current_price = get_binance_spot_price(signal["pair"])

    # 4. حفظ الصفقة لعرضها في لوحة الويب (المرفوضة تُحفظ أيضاً للمراجعة)
    save_signal(signal, halal_status, source_label, current_price)

    if not halal_status["is_halal"]:
        logger.warning(f"العملة {coin} {halal_status['status']} حسب {halal_status['verified_by']}. لن يُرسل تنبيه.")
        return

    # 5. توليد خطوات التنفيذ اليدوي مع اسم القناة المصدر وإرسالها إلى حسابك في تيليجرام
    guide_text = generate_manual_trading_guide(
        signal=signal,
        halal_info=halal_status,
        current_price=current_price,
        source_channel=source_label
    )
    send_telegram_alert(guide_text)
    logger.info(f"تم إرسال خطوات الصفقة للعملة {coin} بنجاح!")

def run_web_dashboard():
    """تشغيل لوحة التحكم الويب في الخلفية"""
    flask_app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)

async def main():
    # تشغيل لوحة الويب في خيط موازٍ (Thread) ليتسنى لك إضافة القنوات من المتصفح في أي وقت
    web_thread = threading.Thread(target=run_web_dashboard, daemon=True)
    web_thread.start()
    logger.info(f"🌐 لوحة التحكم لإضافة القنوات وعرض الصفقات تعمل على: http://127.0.0.1:{WEB_PORT}")

    logger.info("جاري تشغيل مستمع تيليجرام (Multi-Channel Listener)...")
    await client.start()
    if not PANEL_PASSWORD:
        logger.warning("⚠️ لم يتم ضبط PANEL_PASSWORD، لوحة الويب مفتوحة لأي شخص يعرف رابطها!")
    if not load_settings()["halal_bot_username"]:
        logger.warning("لم يتم تحديد بوت الفحص الشرعي، أضفه من لوحة الويب أو بالأمر /bot @اسم_البوت. حالياً يتم الاكتفاء بالقائمة البيضاء.")
    channels = load_channels()
    logger.info(f"البوت يعمل الآن ويراقب ({len(channels)}) قناة مخزنة.")
    asyncio.create_task(sync_channel_joins())
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
