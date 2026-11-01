"""دوال نقية لحساب حدود اليوم وموعد المسح المجدول التالي."""
from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Tuple
from zoneinfo import ZoneInfo


def resolve_timezone_name(timezone_name: str,
                          fallback: str = "Asia/Riyadh") -> str:
    """إرجاع منطقة صالحة، أو المنطقة الاحتياطية عند خطأ الإعداد."""
    try:
        ZoneInfo(timezone_name)
        return timezone_name
    except (KeyError, ValueError):
        ZoneInfo(fallback)
        return fallback


def parse_scan_times(values: Iterable[str]) -> Tuple[time, ...]:
    parsed = []
    for value in values:
        try:
            parsed.append(datetime.strptime(value.strip(), "%H:%M").time())
        except ValueError as exc:
            raise ValueError(f"وقت المسح غير صالح: {value}. استخدم HH:MM") from exc
    unique = tuple(sorted(set(parsed)))
    if not unique:
        raise ValueError("يجب تحديد وقت واحد على الأقل في DAILY_SCAN_TIMES")
    return unique


def start_of_today_utc(timezone_name: str, now: datetime = None) -> datetime:
    zone = ZoneInfo(timezone_name)
    current = now.astimezone(zone) if now else datetime.now(zone)
    day_start = datetime.combine(current.date(), time.min, tzinfo=zone)
    return day_start.astimezone(timezone.utc)


def next_scan_at(scan_times: Iterable[time], timezone_name: str,
                 now: datetime = None) -> datetime:
    zone = ZoneInfo(timezone_name)
    current = now.astimezone(zone) if now else datetime.now(zone)
    times = tuple(scan_times)
    if not times:
        raise ValueError("لا توجد أوقات مسح مجدولة")
    for scan_time in times:
        candidate = datetime.combine(current.date(), scan_time, tzinfo=zone)
        if candidate > current:
            return candidate
    tomorrow = current.date() + timedelta(days=1)
    return datetime.combine(tomorrow, times[0], tzinfo=zone)
