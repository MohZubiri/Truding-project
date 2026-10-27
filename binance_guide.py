"""
وحدة تنسيق إرشادات التداول اليدوي على منصة بينانس (Binance Spot)
مع إظهار اسم القناة المصدر التي التُقطت منها التوصية.
"""
from typing import Dict, Any

def generate_manual_trading_guide(
    signal: Dict[str, Any],
    halal_info: Dict[str, Any],
    current_price: float = None,
    source_channel: str = "قناة التوصيات"
) -> str:
    coin = signal["coin"]
    pair = signal["pair"]
    entries = signal.get("entry", [])
    targets = signal.get("targets", [])
    sl = signal.get("stop_loss")
    
    entry_str = " - ".join([str(e) for e in entries]) if entries else "سعر السوق الحالي"
    targets_str = ", ".join([f"TP{i+1}: {t}" for i, t in enumerate(targets)]) if targets else "غير محدد بدقة"
    sl_str = str(sl) if sl else "غير محدد (يُنصح بوضعه يدوياً)"

    curr_price_str = f"⚡ السعر اللحظي في بينانس: `{current_price}`\n" if current_price else ""

    guide_message = f"""
🔔 **توصية تداول جديدة (مباحة شرعياً)**
📡 **المصدر:** `{source_channel}`
━━━━━━━━━━━━━━━━━━━━
🪙 **الزوج:** `{pair}` (Spot فوري فقط)
✅ **المشروعية الشرعية:** {halal_info['status']}
📝 **ملاحظة الفحص:** {halal_info['notes']}
{curr_price_str}
🎯 **نطاق الدخول المقترح:** `{entry_str}`
🏁 **الأهداف المقترحة:** `{targets_str}`
🛑 **وقف الخسارة:** `{sl_str}`
━━━━━━━━━━━━━━━━━━━━
📌 **خطوات التنفيذ اليدوي في منصة بينانس (Binance App/Web):**

1️⃣ **فتح السوق الفوري (Spot Market):**
   • افتح تطبيق بينانس ⬅️ اختر قسم **Trade (تداول)** ⬅️ تأكد من اختيار **Spot (فوري)** في الأعلى.
   • ابحث عن الزوج: `{pair}`.

2️⃣ **تنفيذ أمر الشراء (Buy Order):**
   • اختر أمر **Limit (حد)** إذا أردت الشراء عند النطاق المقترح (`{entry_str}`).
   • أو اختر **Market (سوق)** للشراء فوراً بسعر اللحظة.
   • حدد مبلغ الشراء (يُوصى بألا يتجاوز 3% إلى 5% من إجمالي محفظتك).
   • اضغط **Buy {coin}**.

3️⃣ **تأمين الصفقة بأمر OCO المزدوج (بيع بالهدف + وقف خسارة معاً):**
   • بعد اكتمال الشراء، انتقل لخانة **Sell (بيع)**.
   • غيّر نوع الأمر من Limit إلى **Stop-Limit / OCO** (One-Cancels-the-Other).
   • في خانة **Price (السعر):** ضع الهدف الأول أو الهدف الذي ترغبه (مثلاً: `{targets[0] if targets else 'هدف الربح'}`).
   • في خانة **Stop:** ضع رقم التفعيل لوقف الخسارة (مثلاً: `{sl if sl else 'وقف الخسارة'}`).
   • في خانة **Limit:** ضع سعراً أقل بقليل جداً من سعر الـ Stop لضمان التنفيذ الفوري عند الهبوط.
   • حدد كمية العملات ⬅️ اضغط **Sell {coin}**.

⚠️ **تنبيه شرعي ومخاطر:**
• ابتعد تماماً عن تداول العقود (Futures) والرافعة (Margin).
• لا تفرط في توزيع رأس مالك وراقب حركة السوق باستمرار.
"""
    return guide_message.strip()
