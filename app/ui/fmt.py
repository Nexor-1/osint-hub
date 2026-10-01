"""Russian-language formatting helpers shared by UI pages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core.schema import TargetType

MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
              "октября", "ноября", "декабря"]

FINDING_LABELS = {
    "account": "Аккаунт", "email": "Email", "phone": "Телефон", "username": "Никнейм", "domain": "Домен",
    "ip": "IP", "url": "Ссылка", "geo": "Геоданные", "location": "Место", "device": "Устройство",
    "datetime": "Дата", "author": "Автор", "software": "Программа", "carrier": "Оператор",
    "person": "Персона", "other": "Прочее",
}
CONFIDENCE = {"high": "Высокая", "medium": "Средняя", "low": "Низкая"}
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
STATUS = {"queued": ("В очереди", "neutral"), "running": ("Идёт", "active"), "done": ("Готово", "success"),
          "error": ("Ошибка", "error"), "cancelled": ("Остановлено", "warn")}


def local_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def relative(iso: str | None) -> str:
    """«Сегодня, 11:42» / «Вчера, 16:08» / «28 сен, 09:27» / «28 сен 2025»."""
    dt = local_dt(iso)
    if dt is None:
        return "—"
    now = datetime.now().astimezone()
    if dt.date() == now.date():
        return f"Сегодня, {dt:%H:%M}"
    if dt.date() == (now - timedelta(days=1)).date():
        return f"Вчера, {dt:%H:%M}"
    if dt.year == now.year:
        return f"{dt.day} {MONTHS_SHORT[dt.month - 1]}, {dt:%H:%M}"
    return f"{dt.day} {MONTHS_SHORT[dt.month - 1]} {dt.year}"


def long_date(iso: str | None, with_time: bool = True) -> str:
    """«1 октября 2026, 11:42»."""
    dt = local_dt(iso)
    if dt is None:
        return "—"
    s = f"{dt.day} {MONTHS_GEN[dt.month - 1]} {dt.year}"
    return f"{s}, {dt:%H:%M}" if with_time else s


def exif_date(value: str) -> str:
    """ExifTool «2026-09-28 17:24:00» → «28 сентября 2026, 17:24» (other strings unchanged)."""
    try:
        dt = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def duration(start: str | None, end: str | None) -> str:
    a, b = local_dt(start), local_dt(end)
    if not a or not b:
        return "—"
    sec = max(0, int((b - a).total_seconds()))
    if sec < 60:
        return f"{sec} сек"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m} мин {s} сек"
    h, m = divmod(m, 60)
    return f"{h} ч {m} мин"


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        word = one
    elif 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}"


def findings(n: int) -> str:
    return plural(n, "находка", "находки", "находок")


def size(num: int | float) -> str:
    """Bytes → «4,8 МБ»."""
    units = ["Б", "КБ", "МБ", "ГБ"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return (f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}").replace(".", ",")
        value /= 1024
    return str(num)


def target_label(target_type: str) -> str:
    try:
        return TargetType(target_type).label
    except ValueError:
        return target_type


def target_display(target: str, target_type: str) -> str:
    """Show usernames as «@nick» and files by name only."""
    if target_type == TargetType.USERNAME.value:
        return f"@{target}"
    if target_type == TargetType.FILE.value:
        return target.replace("\\", "/").rsplit("/", 1)[-1]
    return target


def coord(lat: float, lon: float) -> str:
    """55.7512, 37.6184 → «55.7512° N, 37.6184° E»."""
    return f"{abs(lat):.4f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.4f}° {'E' if lon >= 0 else 'W'}"
