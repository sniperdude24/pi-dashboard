"""Downloads recent radar pictures around home from NOAA and keeps the last
hour or so in data/radar/ for the animated loop."""

import json
import logging
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import nws

log = logging.getLogger(__name__)

# Nationwide radar mosaic (all radars combined, quality-controlled), served by
# NOAA's National Centers for Environmental Prediction. Free, no account.
WMS = "https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows"
LAYER = "conus_bref_qcd"

EARTH_RADIUS = 6378137
HALF_WIDTH_M = 250_000  # map metres from home to the picture's edge
IMAGE_PX = 1200
FRAMES = 12  # pictures in the loop, spread evenly over the loop length


def _to_mercator(lat, lon):
    x = EARTH_RADIUS * math.radians(lon)
    y = EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def _to_latlon(x, y):
    return (
        math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2),
        math.degrees(x / EARTH_RADIUS),
    )


class Radar:
    def __init__(self, settings, data_dir: Path):
        loc = settings["location"]
        self.weather = settings["weather"]  # read each time: the screen can change it
        self.dir = data_dir / "radar"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = data_dir / "radar.json"
        x, y = _to_mercator(loc["latitude"], loc["longitude"])
        self.bbox = (x - HALF_WIDTH_M, y - HALF_WIDTH_M, x + HALF_WIDTH_M, y + HALF_WIDTH_M)
        south, west = _to_latlon(self.bbox[0], self.bbox[1])
        north, east = _to_latlon(self.bbox[2], self.bbox[3])
        self.bounds = [[south, west], [north, east]]
        # Location changed since last run: old pictures show the wrong area.
        if self.index_path.exists():
            if json.loads(self.index_path.read_text())["bounds"] != self.bounds:
                for old in self.dir.glob("*.png"):
                    old.unlink()
                self.index_path.unlink()

    def available_times(self):
        caps = nws.get_bytes(
            f"{WMS}?service=WMS&version=1.3.0&request=GetCapabilities", accept="text/xml"
        ).decode()
        m = re.search(r'<Dimension name="time"[^>]*>([^<]+)</Dimension>', caps)
        if not m:
            raise RuntimeError("radar time list not found")
        return [t.strip() for t in m.group(1).split(",") if t.strip()]

    def pick(self, times):
        """Newest first, then going back in time at least `spacing` apart."""
        spacing = timedelta(minutes=self.weather["radar_loop_minutes"] / (FRAMES - 1))
        picked = []
        for t in reversed(times):
            when = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if not picked or picked[-1][1] - when >= spacing - timedelta(seconds=90):
                picked.append((t, when))
            if len(picked) == FRAMES:
                break
        return list(reversed(picked))

    def refresh(self):
        frames = []
        for t, when in self.pick(self.available_times()):
            name = when.strftime("%Y%m%dT%H%M%SZ") + ".png"
            path = self.dir / name
            if not path.exists():
                bbox = ",".join(f"{v:.0f}" for v in self.bbox)
                url = (
                    f"{WMS}?service=WMS&version=1.3.0&request=GetMap&layers={LAYER}&styles="
                    f"&crs=EPSG:3857&bbox={bbox}&width={IMAGE_PX}&height={IMAGE_PX}"
                    f"&format=image/png&transparent=true&time={t}"
                )
                try:
                    data = nws.get_bytes(url, timeout=60)
                except Exception as e:
                    log.warning("radar frame %s failed: %s", t, e)
                    continue
                path.with_suffix(".tmp").write_bytes(data)
                path.with_suffix(".tmp").replace(path)
            frames.append({"time": when.isoformat(), "file": name})
        if not frames:
            return
        keep = {f["file"] for f in frames}
        for old in self.dir.glob("*.png"):
            if old.name not in keep:
                old.unlink()
        index = {"bounds": self.bounds, "frames": frames}
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=1), encoding="utf-8")
        tmp.replace(self.index_path)
