import os
from dotenv import load_dotenv

load_dotenv()

TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# قراءة القنوات الأولية من ملف البيئة إن وجدت
raw_channels = os.getenv("SOURCE_CHANNELS", os.getenv("SOURCE_CHANNEL_ID", ""))
INITIAL_CHANNELS = [c.strip() for c in raw_channels.split(",") if c.strip()]

WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "5000")))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
# كلمة مرور لوحة الويب (ضرورية عند الرفع على استضافة عامة)
PANEL_USERNAME = os.getenv("PANEL_USERNAME", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

def _csv_env(name: str, default: str) -> list:
    return [k.strip().lower() for k in os.getenv(name, default).split(",") if k.strip()]

# بوت تيليجرام الخارجي المستخدم للتحقق من مشروعية العملة (مثال: @HalalCryptoBot)
# قيمة أولية فقط: يُعدَّل من لوحة الويب أو بالأمر /bot ويُحفظ في settings.json
HALAL_BOT_USERNAME = os.getenv("HALAL_BOT_USERNAME", "").strip()
# صيغة الرسالة المرسلة للبوت، {coin} يُستبدل برمز العملة
HALAL_BOT_QUERY_TEMPLATE = os.getenv("HALAL_BOT_QUERY_TEMPLATE", "{coin}")
HALAL_BOT_TIMEOUT = int(os.getenv("HALAL_BOT_TIMEOUT", "30"))
# مدة الاحتفاظ بحكم البوت قبل إعادة السؤال (بالأيام)
HALAL_CACHE_DAYS = int(os.getenv("HALAL_CACHE_DAYS", "7"))

# كلمات تحديد الحكم من رد البوت (تُفحص كلمات المنع أولاً لأن "غير مباح" تحتوي على "مباح")
HARAM_KEYWORDS = _csv_env(
    "HARAM_KEYWORDS",
    "غير مباح,غير مباحة,غير حلال,غير متوافق,غير متوافقة,غير جائز,محرم,محرمة,حرام,مشبوه,مشبوهة,"
    "haram,not halal,non-compliant,not compliant,questionable"
)
HALAL_KEYWORDS = _csv_env(
    "HALAL_KEYWORDS",
    "مباح,مباحة,حلال,متوافق,متوافقة,جائز,جائزة,halal,compliant,permissible"
)
