"""Fetches forecast, current conditions and alerts from the Weather Service and
saves a ready-to-show summary to data/weather.json."""

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import nws, sun

log = logging.getLogger(__name__)

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def c_to_f(c):
    return None if c is None else round(c * 9 / 5 + 32)


def kmh_to_mph(k):
    return None if k is None else round(k / 1.609344)


def value(qv):
    """Weather Service numbers come as {"value": ..., "unitCode": ...}."""
    return (qv or {}).get("value")


def icon_code(url):
    """'.../icons/land/night/rain_showers,40/bkn?size=medium' -> ('rain_showers', False)."""
    if not url:
        return None
    m = re.search(r"/icons/land/(day|night)/([a-z_]+)", url)
    return {"code": m.group(2), "day": m.group(1) == "day"} if m else None


def write_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


class Weather:
    def __init__(self, settings, data_dir: Path):
        self.lat = settings["location"]["latitude"]
        self.lon = settings["location"]["longitude"]
        self.name = settings["location"]["name"]
        self.path = data_dir / "weather.json"
        self.points_path = data_dir / "nws-points.json"
        self.summary = json.loads(self.path.read_text()) if self.path.exists() else {}

    # -- The Weather Service's lookup of which office/grid/stations serve us --
    def points(self):
        key = f"{self.lat},{self.lon}"
        if self.points_path.exists():
            cached = json.loads(self.points_path.read_text())
            if cached.get("key") == key and time.time() - cached["fetched"] < 7 * 86400:
                return cached
        props = nws.get_json(f"https://api.weather.gov/points/{key}")["properties"]
        stations = nws.get_json(props["observationStations"])["features"]
        cached = {
            "key": key,
            "fetched": time.time(),
            "forecast": props["forecast"],
            "hourly": props["forecastHourly"],
            "radar": props["radarStation"],
            "stations": [
                [s["properties"]["stationIdentifier"], s["properties"]["name"]] for s in stations[:4]
            ],
        }
        write_json(self.points_path, cached)
        return cached

    def refresh(self):
        """Fetch everything. Parts that fail keep their last good value."""
        pts = self.points()
        s = dict(self.summary)
        s["location"] = {"name": self.name, "latitude": self.lat, "longitude": self.lon}
        s["radar_station"] = pts["radar"]
        for part, fn in [
            ("current", lambda: self.current(pts["stations"])),
            ("hourly", lambda: self.hourly(pts["hourly"])),
            ("daily", lambda: self.daily(pts["forecast"])),
            ("alerts", self.alerts),
        ]:
            try:
                s[part] = fn()
                s.setdefault("updated", {})[part] = now_iso()
            except Exception as e:  # network hiccups are normal; try again next time
                log.warning("weather %s failed: %s", part, e)
        s["sun"] = sun.upcoming(self.lat, self.lon, datetime.now(timezone.utc))
        self.summary = s
        write_json(self.path, s)

    def current(self, stations):
        """Latest observation from the nearest station that has a recent one."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        for station, station_name in stations:
            o = nws.get_json(f"https://api.weather.gov/stations/{station}/observations/latest")[
                "properties"
            ]
            temp = value(o["temperature"])
            if temp is None or datetime.fromisoformat(o["timestamp"]) < cutoff:
                continue
            feels = value(o["heatIndex"]) or value(o["windChill"]) or temp
            direction = value(o["windDirection"])
            return {
                "station": station,
                "station_name": station_name,
                "time": o["timestamp"],
                "text": o["textDescription"],
                "icon": icon_code(o["icon"]),
                "temp": c_to_f(temp),
                "feels": c_to_f(feels),
                "humidity": round(value(o["relativeHumidity"]) or 0),
                "wind_mph": kmh_to_mph(value(o["windSpeed"])) or 0,
                "gust_mph": kmh_to_mph(value(o["windGust"])),
                "wind_dir": None if direction is None else COMPASS[round(direction / 45) % 8],
            }
        raise RuntimeError("no station has a recent observation")

    def hourly(self, url):
        periods = nws.get_json(url)["properties"]["periods"]
        now = datetime.now(timezone.utc)
        upcoming = [p for p in periods if datetime.fromisoformat(p["endTime"]) > now]
        return [
            {
                "time": p["startTime"],
                "temp": p["temperature"],
                "pop": value(p["probabilityOfPrecipitation"]) or 0,
                "icon": icon_code(p["icon"]),
                "text": p["shortForecast"],
            }
            for p in upcoming[:24]
        ]

    def daily(self, url):
        """Combine the day/night forecast periods into one row per day."""
        days = []
        for p in nws.get_json(url)["properties"]["periods"]:
            date = p["startTime"][:10]
            if p["isDaytime"]:
                days.append(
                    {
                        "date": date,
                        "name": p["name"],
                        "high": p["temperature"],
                        "low": None,
                        "pop": value(p["probabilityOfPrecipitation"]) or 0,
                        "icon": icon_code(p["icon"]),
                        "text": p["shortForecast"],
                        "detail": p["detailedForecast"],
                        "night": None,
                    }
                )
            elif days and days[-1]["night"] is None:
                days[-1]["low"] = p["temperature"]
                days[-1]["night"] = p["detailedForecast"]
                days[-1]["pop"] = max(days[-1]["pop"], value(p["probabilityOfPrecipitation"]) or 0)
            else:
                # The forecast starts at night ("Tonight"): a day with only a low.
                days.append(
                    {
                        "date": date,
                        "name": p["name"],
                        "high": None,
                        "low": p["temperature"],
                        "pop": value(p["probabilityOfPrecipitation"]) or 0,
                        "icon": icon_code(p["icon"]),
                        "text": p["shortForecast"],
                        "detail": None,
                        "night": p["detailedForecast"],
                    }
                )
        return days[:7]

    def alerts(self):
        feats = nws.get_json(
            f"https://api.weather.gov/alerts/active?point={self.lat},{self.lon}"
        )["features"]
        out = []
        for f in feats:
            p = f["properties"]
            out.append(
                {
                    "id": p["id"],
                    "event": p["event"],
                    "severity": p["severity"],
                    "headline": p.get("headline"),
                    "description": p.get("description"),
                    "instruction": p.get("instruction"),
                    "onset": p.get("onset"),
                    "ends": p.get("ends") or p.get("expires"),
                }
            )
        order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
        out.sort(key=lambda a: order.get(a["severity"], 4))
        return out


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
