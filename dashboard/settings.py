"""Loads settings.yaml, filling in defaults for anything left out."""

import copy
from pathlib import Path

import yaml

DEFAULTS = {
    "port": 8090,
    "location": {"name": "Home", "latitude": None, "longitude": None},
    "clock": "12h",
    "weather": {
        "refresh_minutes": 5,
        "radar_frames": 12,
        "radar_minutes_between_frames": 5,
    },
    "map": {
        "base_tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "label_tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    },
}


def _merge(base, override):
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        settings = _merge(copy.deepcopy(DEFAULTS), yaml.safe_load(f))
    loc = settings["location"]
    if loc["latitude"] is None or loc["longitude"] is None:
        raise SystemExit(f"{path}: location latitude/longitude must be set")
    # The Weather Service rejects more than 4 decimal places.
    loc["latitude"] = round(float(loc["latitude"]), 4)
    loc["longitude"] = round(float(loc["longitude"]), 4)
    return settings
