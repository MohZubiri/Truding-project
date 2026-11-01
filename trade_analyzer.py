"""تحليل رقمي مبسط لصفقات Spot الطويلة المستخرجة من قنوات التوصيات."""
from typing import Any, Dict, List, Optional


def _rounded(value: Optional[float], digits: int = 4) -> Optional[float]:
    return round(value, digits) if value is not None else None


def analyze_trade(signal: Dict[str, Any], current_price: float = None) -> Dict[str, Any]:
    """حساب الربح والمخاطرة والعائد/المخاطرة لصفقة شراء Spot."""
    entries = [float(value) for value in signal.get("entry", []) if float(value) > 0]
    targets = [float(value) for value in signal.get("targets", []) if float(value) > 0]
    stop_loss = signal.get("stop_loss")
    stop_loss = float(stop_loss) if stop_loss is not None else None

    reference_entry = sum(entries) / len(entries) if entries else current_price
    entry_source = "متوسط نطاق الدخول" if entries else "السعر اللحظي"
    warnings: List[str] = []

    if not entries:
        warnings.append("لم تُحدد منطقة دخول؛ استُخدم السعر اللحظي للتحليل.")
    if not targets:
        warnings.append("لا توجد أهداف واضحة في التوصية.")
    if stop_loss is None:
        warnings.append("لا يوجد وقف خسارة واضح.")
    if not reference_entry or reference_entry <= 0:
        warnings.append("تعذر تحديد سعر مرجعي صالح للتحليل.")
        return {
            "reference_entry": None,
            "entry_source": entry_source,
            "risk_percent": None,
            "targets": [],
            "warnings": warnings,
        }

    risk_percent = None
    if stop_loss is not None:
        risk_percent = ((reference_entry - stop_loss) / reference_entry) * 100
        if risk_percent <= 0:
            warnings.append("وقف الخسارة ليس أقل من سعر الدخول في صفقة الشراء.")

    target_analysis = []
    for target in targets:
        profit_percent = ((target - reference_entry) / reference_entry) * 100
        risk_reward = None
        if risk_percent is not None and risk_percent > 0:
            risk_reward = profit_percent / risk_percent
        if profit_percent <= 0:
            warnings.append(f"الهدف {target:g} ليس أعلى من سعر الدخول المرجعي.")
        target_analysis.append({
            "price": target,
            "profit_percent": _rounded(profit_percent, 2),
            "risk_reward": _rounded(risk_reward, 2),
        })

    return {
        "reference_entry": _rounded(reference_entry, 8),
        "entry_source": entry_source,
        "risk_percent": _rounded(risk_percent, 2),
        "targets": target_analysis,
        "warnings": list(dict.fromkeys(warnings)),
    }


def format_trade_analysis(analysis: Dict[str, Any]) -> str:
    """تنسيق مختصر مناسب لتنبيه تيليجرام."""
    reference = analysis.get("reference_entry")
    risk = analysis.get("risk_percent")
    lines = ["📊 **التحليل الرقمي:**"]
    if reference is not None:
        lines.append(f"• سعر التحليل المرجعي: `{reference}` ({analysis.get('entry_source', '')})")
    if risk is not None:
        lines.append(f"• المخاطرة حتى وقف الخسارة: `{risk}%`")
    for index, target in enumerate(analysis.get("targets", []), 1):
        rr = target.get("risk_reward")
        rr_text = f" | عائد/مخاطرة: `{rr}`" if rr is not None else ""
        lines.append(
            f"• الهدف {index}: ربح محتمل `{target.get('profit_percent')}%`{rr_text}"
        )
    for warning in analysis.get("warnings", []):
        lines.append(f"⚠️ {warning}")
    return "\n".join(lines)
