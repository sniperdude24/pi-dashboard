"""Reads live planes from the ADS-B feed (ultrafeeder/tar1090 aircraft.json on
the mini PC) and, for airline flights, looks up where they're flying from/to."""

import json
import logging
import math
import queue
import re
import threading
import time
from pathlib import Path

from . import nws

log = logging.getLogger(__name__)

KNOTS_TO_MPH = 1.15078
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
AIRLINE_CALLSIGN = re.compile(r"^[A-Z]{3}\d{1,4}[A-Z]{0,2}$")
EMERGENCY = {"7500": "Hijack", "7600": "Radio failure", "7700": "Emergency"}
ROUTE_KEEP_SECONDS = 12 * 3600


def _distance_mi(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360


def _on_the_way(route, lat, lon):
    """Flight numbers get reused, so the looked-up route can be stale. Only
    trust it if the plane is roughly between the two airports."""
    a, b = route["from"], route["to"]
    if a.get("lat") is None or b.get("lat") is None:
        return False
    direct = _distance_mi(a["lat"], a["lon"], b["lat"], b["lon"])
    via = _distance_mi(a["lat"], a["lon"], lat, lon) + _distance_mi(lat, lon, b["lat"], b["lon"])
    return via <= direct * 1.15 + 100


class Routes:
    """Where airline flights are going, from adsbdb.com (free, no account).
    Looked up one at a time in the background and remembered for 12 hours."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "routes.json"
        try:
            self.cache = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.cache = {}
        self.pending = set()
        self.queue = queue.Queue()
        threading.Thread(target=self._worker, name="routes", daemon=True).start()

    def get(self, callsign):
        entry = self.cache.get(callsign)
        if entry and time.time() - entry["fetched"] < ROUTE_KEEP_SECONDS:
            return entry["route"]
        if callsign not in self.pending:
            self.pending.add(callsign)
            self.queue.put(callsign)
        return entry["route"] if entry else None

    def _worker(self):
        while True:
            callsign = self.queue.get()
            try:
                self.cache[callsign] = {"fetched": time.time(), "route": self._lookup(callsign)}
                self._save()
            except Exception as e:
                log.info("route lookup %s failed: %s", callsign, e)
            finally:
                self.pending.discard(callsign)
            time.sleep(2)  # be gentle with a free service

    def _lookup(self, callsign):
        try:
            data = json.loads(nws.get_bytes(f"https://api.adsbdb.com/v0/callsign/{callsign}", 15))
        except Exception as e:
            if "404" in str(e):
                return None  # unknown flight: remember that too
            raise
        fr = data["response"]["flightroute"]

        def airport(a):
            return {
                "code": a["iata_code"] or a["icao_code"],
                "city": a["municipality"],
                "name": a["name"],
                "lat": a["latitude"],
                "lon": a["longitude"],
            }

        return {
            "airline": (fr.get("airline") or {}).get("name"),
            "from": airport(fr["origin"]),
            "to": airport(fr["destination"]),
        }

    def _save(self):
        now = time.time()
        self.cache = {k: v for k, v in self.cache.items() if now - v["fetched"] < ROUTE_KEEP_SECONDS}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache), encoding="utf-8")
        tmp.replace(self.path)


class Flights:
    def __init__(self, settings, data_dir: Path):
        self.settings = settings
        self.routes = Routes(data_dir)
        self.latest = {"planes": [], "updated": None, "error": "Waiting for the plane feed"}

    def refresh(self):
        cfg = self.settings["flights"]
        try:
            feed = json.loads(nws.get_bytes(cfg["feed_url"], timeout=5))
        except Exception as e:
            self.latest = {**self.latest, "error": f"Can't reach the plane feed ({e})"}
            return
        home = self.settings["location"]
        planes = []
        for a in feed.get("aircraft", []):
            plane = self._plane(a, home, cfg)
            if plane:
                planes.append(plane)
        planes.sort(key=lambda p: p["distance_mi"])
        self.latest = {"planes": planes, "updated": time.time(), "error": None}

    def _plane(self, a, home, cfg):
        if "lat" not in a or a.get("seen_pos", 99) > 60:
            return None
        dist = _distance_mi(home["latitude"], home["longitude"], a["lat"], a["lon"])
        if dist > cfg["range_miles"]:
            return None
        alt = a.get("alt_baro")
        on_ground = alt == "ground"
        alt_ft = 0 if on_ground else alt if isinstance(alt, (int, float)) else a.get("alt_geom")
        if cfg["max_altitude_ft"] and alt_ft and alt_ft > cfg["max_altitude_ft"]:
            return None
        callsign = (a.get("flight") or "").strip()
        route = None
        if cfg["route_lookup"] and AIRLINE_CALLSIGN.match(callsign):
            route = self.routes.get(callsign)
            if route and not _on_the_way(route, a["lat"], a["lon"]):
                route = None
        gs = a.get("gs")
        return {
            "id": a["hex"],
            "callsign": callsign or a.get("r") or a["hex"].upper(),
            "registration": a.get("r"),
            "type": a.get("t"),
            "model": a.get("desc"),
            "owner": a.get("ownOp"),
            "year": a.get("year"),
            "military": bool((a.get("dbFlags") or 0) & 1),
            "emergency": EMERGENCY.get(a.get("squawk")),
            "lat": a["lat"],
            "lon": a["lon"],
            "track": a.get("track") or a.get("true_heading") or 0,
            "on_ground": on_ground,
            "altitude_ft": None if alt_ft is None else round(alt_ft),
            "climb_fpm": a.get("baro_rate"),
            "speed_mph": None if gs is None else round(gs * KNOTS_TO_MPH),
            "distance_mi": round(dist, 1),
            "direction": COMPASS[round(_bearing(home["latitude"], home["longitude"], a["lat"], a["lon"]) / 45) % 8],
            "route": route,
        }
