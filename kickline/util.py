"""Small helpers: time, odds math, Pacific-time weeks."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if re.match(r".*T\d\d:\d\d\+", s):  # ESPN sometimes omits seconds
        s = s.replace("+", ":00+", 1)
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except ValueError:
        return None


def pt_date(dt: datetime) -> str:
    return dt.astimezone(PT).strftime("%Y-%m-%d")


def pt_label(s: str | datetime) -> str:
    dt = parse_iso(s) if isinstance(s, str) else s
    if not dt:
        return "?"
    return dt.astimezone(PT).strftime("%a %-I:%M%p").replace("AM", "am").replace("PM", "pm")


def et_dates(start: datetime, end: datetime) -> list[str]:
    """ESPN scoreboard dates (US-Eastern) covering [start, end]."""
    d = start.astimezone(ET).date()
    last = end.astimezone(ET).date()
    out = []
    while d <= last:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def week_bounds(dt: datetime) -> tuple[str, datetime, datetime]:
    """Kickline week: Monday 00:00 Pacific to next Monday."""
    local = dt.astimezone(PT)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.strftime("%Y-%m-%d"), monday.astimezone(timezone.utc), (monday + timedelta(days=7)).astimezone(timezone.utc)


# ---------- odds ----------
def to_num(a) -> float | None:
    if a is None:
        return None
    if isinstance(a, (int, float)):
        return float(a)
    s = str(a).strip().upper()
    if s in ("EVEN", "EV", "PK"):
        return 100.0
    m = re.search(r"[+-]?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


def american_str(a) -> str | None:
    n = to_num(a)
    if n is None:
        return None
    n = int(round(n))
    return f"+{n}" if n > 0 else str(n)


def decimal(a) -> float | None:
    n = to_num(a)
    if n is None or n == 0:
        return None
    return 1 + n / 100 if n > 0 else 1 + 100 / abs(n)


def implied(a) -> float | None:
    d = decimal(a)
    return 1 / d if d else None


def dec_to_american(d: float) -> str:
    if d >= 2:
        return f"+{round((d - 1) * 100)}"
    return f"-{round(100 / (d - 1))}"


def novig(*prices) -> list[float] | None:
    imps = [implied(p) for p in prices]
    if any(i is None for i in imps):
        return None
    t = sum(imps)
    return [i / t for i in imps]


def price_band(a) -> str:
    n = to_num(a)
    if n is None:
        return "unknown"
    if n > 0:
        return "plus"
    if n <= -300:
        return "<=-300"
    if n <= -200:
        return "-200..-299"
    if n <= -150:
        return "-150..-199"
    return "-100..-149"


def price_in_pick(pick: str) -> str | None:
    m = re.search(r"\(([+-]\d+)\)", pick or "")
    return m.group(1) if m else None
