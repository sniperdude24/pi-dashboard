"""settings.yaml: loading (with defaults), and saving changes made on the
touchscreen without losing the notes written in the file."""

import copy
import logging
import os
import threading
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

DEFAULTS = {
    "port": 8090,
    "location": {"name": "Home", "latitude": None, "longitude": None},
    "clock": "12h",
    # Only the touchscreen (this Pi) may change settings, unless this is true.
    "allow_settings_from_network": False,
    "pages": {
        "resume_after_touch_seconds": 120,
        "list": [
            {"name": "weather", "enabled": True, "seconds": 60},
            {"name": "flights", "enabled": True, "seconds": 30},
            {"name": "backyard", "enabled": True, "seconds": 45},
            {"name": "pihole", "enabled": True, "seconds": 30},
        ],
    },
    "pihole": {
        "url": "http://192.168.1.76:8053",
        "password": "",
    },
    "backyard": {
        "timelapse": {
            "url": "http://192.168.1.76:8177/live/Backyard/last_hour.mp4",
            "user": "dashboard",
            "pin": "",
        },
        "live": {
            # The recorder's copy of the Backyard camera (channel 3, smaller "sub" stream).
            "url": "rtsp://192.168.1.176:554/h264Preview_03_sub",
            "user": "",
            "password": "",
        },
    },
    "weather": {
        "refresh_minutes": 5,
        "show_radar": True,
        "show_hourly": True,
        "show_daily": True,
        "show_forecast_text": True,
        "radar_loop_minutes": 60,
        "radar_zoom": 8,
    },
    "flights": {
        "feed_url": "http://192.168.1.76:8080/data/aircraft.json",
        "range_miles": 50,
        "list_count": 6,
        "max_altitude_ft": 0,
        "show_labels": True,
        "route_lookup": True,
    },
    "screen": {
        "night_dim": False,
        "night_start": "22:00",
        "night_end": "06:30",
        "night_brightness": 40,
    },
    "map": {
        "base_tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "label_tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    },
}

# Everything the settings page can change. Anything not listed here can only be
# changed by editing settings.yaml.
#   key: (section, label, kind, min, max, step, unit)
EDITABLE = {
    "pages.resume_after_touch_seconds": ("pages", "After I touch the screen, wait before rotating again", "int", 30, 900, 30, "sec"),
    "weather.show_radar": ("weather", "Radar", "bool"),
    "weather.show_hourly": ("weather", "Next 12 hours", "bool"),
    "weather.show_daily": ("weather", "7 days", "bool"),
    "weather.show_forecast_text": ("weather", "Written forecast", "bool"),
    "weather.radar_loop_minutes": ("weather", "Radar loop length", "int", 30, 120, 15, "min"),
    "weather.radar_zoom": ("weather", "Radar starts zoomed", "int", 8, 10, 1, "zoom"),
    "flights.range_miles": ("flights", "Show planes within", "int", 10, 150, 5, "mi"),
    "flights.list_count": ("flights", "Planes in the list", "int", 3, 8, 1, ""),
    "flights.max_altitude_ft": ("flights", "Hide planes higher than (0 = show all)", "int", 0, 45000, 2500, "ft"),
    "flights.show_labels": ("flights", "Flight numbers on the map", "bool"),
    "flights.route_lookup": ("flights", "Look up where airline flights are going", "bool"),
    "screen.night_dim": ("screen", "Dim the screen at night", "bool"),
    "screen.night_start": ("screen", "Night starts", "time", 0, 1410, 30, ""),
    "screen.night_end": ("screen", "Night ends", "time", 0, 1410, 30, ""),
    "screen.night_brightness": ("screen", "Brightness at night", "int", 10, 90, 10, "%"),
}

PAGE_SECONDS = (10, 600, 5)  # min, max, step for each page's time on screen

log = logging.getLogger(__name__)
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't wrap long web addresses onto two lines
_lock = threading.Lock()


def _merge(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _replace_in_place(old, new):
    """Make `old` equal `new` while keeping the same dict objects: parts of the
    program hold on to whole sections (e.g. settings["weather"])."""
    for key in list(old):
        if key not in new:
            del old[key]
    for key, value in new.items():
        if isinstance(value, dict) and isinstance(old.get(key), dict):
            _replace_in_place(old[key], value)
        else:
            old[key] = value


def _plain(node):
    """ruamel's comment-keeping types -> plain dicts/lists."""
    if isinstance(node, dict):
        return {k: _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    return node


def get(settings: dict, key: str):
    node = settings
    for part in key.split("."):
        node = node[part]
    return node


class Settings:
    """Holds the current settings; `values` is always a complete plain dict."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.values = self._load()
        except ValueError as e:
            raise SystemExit(str(e))
        self.mtime = path.stat().st_mtime

    def reload_if_changed(self):
        """Pick up changes typed into settings.yaml by hand, so no restart is
        needed. Returns True when something changed."""
        mtime = self.path.stat().st_mtime
        if mtime == self.mtime:
            return False
        with _lock:
            self.mtime = mtime
            try:
                new = self._load()
            except Exception as e:  # a typo while editing: keep what we had
                log.warning("settings.yaml has a mistake, keeping the previous settings: %s", e)
                return False
            if new == self.values:
                return False
            _replace_in_place(self.values, new)
        log.info("settings.yaml changed; using the new settings")
        return True

    def _load(self):
        with open(self.path, encoding="utf-8") as f:
            raw = _yaml.load(f) or {}
        values = _merge(copy.deepcopy(DEFAULTS), _plain(raw))
        loc = values["location"]
        if loc["latitude"] is None or loc["longitude"] is None:
            raise ValueError(f"{self.path}: location latitude/longitude must be set")
        # The Weather Service rejects more than 4 decimal places.
        loc["latitude"] = round(float(loc["latitude"]), 4)
        loc["longitude"] = round(float(loc["longitude"]), 4)
        known = {p["name"] for p in values["pages"]["list"]}
        for page in DEFAULTS["pages"]["list"]:  # pages added in newer versions
            if page["name"] not in known:
                values["pages"]["list"].append(dict(page))
        return values

    def __getitem__(self, key):
        return self.values[key]

    def change(self, key: str, value):
        """Validate and apply one change from the settings page, then save."""
        if key == "pages.list":
            value = self._check_pages(value)
        elif key in EDITABLE:
            value = self._check(EDITABLE[key], value)
        else:
            raise ValueError(f"{key} can't be changed from the screen")
        with _lock:
            with open(self.path, encoding="utf-8") as f:
                raw = _yaml.load(f) or CommentedMap()
            node = raw
            *parents, last = key.split(".")
            for part in parents:
                if part not in node or not isinstance(node[part], dict):
                    node[part] = CommentedMap()
                node = node[part]
            node[last] = value
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                _yaml.dump(raw, f)
            os.chmod(tmp, self.path.stat().st_mode)  # stays private: it holds logins
            tmp.replace(self.path)
            self.mtime = self.path.stat().st_mtime
            target = self.values
            for part in parents:
                target = target[part]
            target[last] = copy.deepcopy(value)

    @staticmethod
    def _check(spec, value):
        kind = spec[2]
        if kind == "bool":
            if not isinstance(value, bool):
                raise ValueError("expected on/off")
            return value
        lo, hi = spec[3], spec[4]
        if kind == "time":
            h, m = map(int, str(value).split(":"))
            if not 0 <= h * 60 + m <= hi:
                raise ValueError("bad time")
            return f"{h:02d}:{m:02d}"
        if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
            raise ValueError(f"must be a whole number from {lo} to {hi}")
        return value

    @staticmethod
    def _check_pages(pages):
        names = [p.get("name") for p in pages]
        if sorted(names) != sorted(p["name"] for p in DEFAULTS["pages"]["list"]):
            raise ValueError("page list must contain each page once")
        lo, hi, _ = PAGE_SECONDS
        out = []
        for p in pages:
            secs = p.get("seconds")
            if not isinstance(p.get("enabled"), bool) or not isinstance(secs, int) or not lo <= secs <= hi:
                raise ValueError(f"bad page entry {p}")
            out.append({"name": p["name"], "enabled": p["enabled"], "seconds": secs})
        if not any(p["enabled"] for p in out):
            raise ValueError("at least one page must be on")
        return out
