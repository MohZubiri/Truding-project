"""
سكربت اختبار إضافة عدة قنوات (بالاسم أو الرابط) وتخزينها وفحص التوصيات
"""
from channel_manager import add_channel, load_channels
from parser import extract_signal
from halal_checker import check_token_compliance
from binance_guide import generate_manual_trading_guide

print("=== 1. اختبار إضافة وتخزين عدة قنوات بالروابط والأسماء ===")
test_inputs = [
    ("https://t.me/BinanceSignalsVIP", "قناة إشارات بينانس"),
    ("@CryptoHalalTrades", "قناة صفقات كريبتو"),
    ("t.me/WhaleAlertsSpot", "قناة الحيتان سبوت")
]

for raw_link, title in test_inputs:
    res = add_channel(raw_link, title)
    print(f"-> {res['message']}")

print("\n📋 القنوات المحفوظة حالياً في ملف channels.json:")
for ch in load_channels():
    print(f" - الاسم: {ch['title']} | المعرف القياسي: {ch['identifier']} | المدخل الأصلي: {ch['raw_input']}")

print("\n=== 2. اختبار استخراج صفقة وتوليد إرشادات بينانس مع ذكر القناة المصدر ===")
sample_msg = """
Pair: #SOL/USDT
Entry Zone: 140 - 142
Targets:
TP1: 150
TP2: 165
Stop Loss: 134
"""
sig = extract_signal(sample_msg)
if sig:
    compliance = check_token_compliance(sig["coin"])
    if compliance["is_halal"]:
        guide = generate_manual_trading_guide(
            signal=sig,
            halal_info=compliance,
            current_price=141.2,
            source_channel="@BinanceSignalsVIP"
        )
        print(guide)
