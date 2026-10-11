"""Sunrise and sunset times (accurate to about a minute), no internet needed."""

import math
from datetime import date, datetime, timedelta, timezone

_J2000 = date(2000, 1, 1)


def _from_julian(j: float) -> datetime:
    return datetime.fromtimestamp((j - 2440587.5) * 86400, tz=timezone.utc)


def sun_times(lat: float, lon: float, day: date):
    """Return (sunrise, sunset) in UTC for the given local date, or (None, None)
    when the sun doesn't rise or set that day."""
    n = (day - _J2000).days
    j_star = n - lon / 360
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = 2451545.0 + j_star + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    decl = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(decl)) / (
        math.cos(phi) * math.cos(decl)
    )
    if not -1 <= cos_w <= 1:
        return None, None
    w = math.degrees(math.acos(cos_w)) / 360
    return _from_julian(transit - w), _from_julian(transit + w)


def upcoming(lat: float, lon: float, now: datetime):
    """Sunrise/sunset for the location's today and tomorrow, as ISO strings."""
    local_day = (now + timedelta(hours=lon / 15)).date()
    events = []
    for d in (local_day, local_day + timedelta(days=1)):
        rise, set_ = sun_times(lat, lon, d)
        if rise:
            events += [("sunrise", rise), ("sunset", set_)]
    return [{"type": t, "time": when.isoformat()} for t, when in events]
