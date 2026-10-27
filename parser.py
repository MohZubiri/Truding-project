"""
وحدة استخراج بيانات الصفقات من رسائل قنوات التوصيات
"""
import re
from typing import Optional, Dict, Any

def extract_signal(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    
    pair_match = re.search(r'(?:#)?([A-Z0-9]{2,10})\s*(?:/|\s+)?(USDT|BUSD|FDUSD|USDC)', text, re.IGNORECASE)
    base_coin = None
    quote_coin = "USDT"
    
    if pair_match:
        base_coin = pair_match.group(1).upper()
        quote_coin = pair_match.group(2).upper()
    else:
        buy_match = re.search(r'(?:BUY|LONG|دخول|شراء)\s+(?:#)?([A-Z0-9]{2,10})', text, re.IGNORECASE)
        if buy_match:
            base_coin = buy_match.group(1).upper()

    if not base_coin:
        return None

    base_coin = re.sub(r'[^A-Z0-9]', '', base_coin)

    entry_match = re.search(r'(?:Entry|Buy\s*Zone|دخول|سعر\s*الدخول|منطقة\s*الدخول)[\s:]*([0-9\.\s\-–]+)', text, re.IGNORECASE)
    entry_prices = []
    if entry_match:
        raw_entries = re.findall(r'\d+(?:\.\d+)?', entry_match.group(1))
        entry_prices = [float(x) for x in raw_entries]

    targets = []
    tp_matches = re.findall(r'(?:TP\s*\d*|Target\s*\d*|هدف\s*\d*)[\s:]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if tp_matches:
        targets = [float(x) for x in tp_matches]
    else:
        targets_block = re.search(r'(?:Targets|الأهداف)[\s:]*([\d\.\s,\-]+)', text, re.IGNORECASE)
        if targets_block:
            targets = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', targets_block.group(1))]

    sl_match = re.search(r'(?:SL|Stop\s*Loss|وقف|وقف\s*الخسارة)[\s:]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    stop_loss = float(sl_match.group(1)) if sl_match else None

    if not entry_prices and not targets:
        return None

    return {
        "coin": base_coin,
        "pair": f"{base_coin}/{quote_coin}",
        "entry": entry_prices,
        "targets": targets,
        "stop_loss": stop_loss,
        "raw_text": text
    }
