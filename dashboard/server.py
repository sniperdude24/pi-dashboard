"""The web server the screen's browser talks to, plus the background fetching."""

import json
import logging
import mimetypes
import re
import socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, nws
from .cameras import Live, Timelapse
from .flights import Flights
from .radar import Radar
from .settings import EDITABLE, PAGE_SECONDS, Settings, get
from .weather import Weather

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TILE_RE = re.compile(r"^/tiles/(base|labels)/(\d{1,2})/(\d{1,5})/(\d{1,5})\.png$")
RADAR_RE = re.compile(r"^/radar/(\d{8}T\d{6}Z\.png)$")
LOCAL_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# The pages that rotate on the screen. Each also works on its own at /<name>.
PAGES = {
    "weather": {"title": "Weather", "icon": "cloud", "file": "weather.html"},
    "flights": {"title": "Flights", "icon": "plane", "file": "flights.html"},
    "backyard": {"title": "Backyard", "icon": "video", "file": "backyard.html"},
}
OTHER_FILES = {"/": "shell.html", "/settings": "settings.html"}

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")


def run_every(seconds, job, name):
    def loop():
        while True:
            try:
                job()
            except Exception:
                log.exception("%s refresh failed", name)
            time.sleep(seconds)

    threading.Thread(target=loop, name=name, daemon=True).start()


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; just picks the LAN address
            return s.getsockname()[0]
    except OSError:
        return "unknown"


class App:
    def __init__(self, settings: Settings, data_dir: Path):
        self.settings = settings
        self.data_dir = data_dir
        self.started = int(time.time())
        self.settings_rev = 0  # goes up on every change, so pages know to reload
        self.tiles_dir = data_dir / "tiles"
        self.weather = Weather(settings, data_dir)
        self.radar = Radar(settings, data_dir)
        self.flights = Flights(settings, data_dir)
        self.timelapse = Timelapse(settings, data_dir)
        self.live = Live(settings)

    def start_background(self):
        minutes = self.settings["weather"]["refresh_minutes"]
        run_every(minutes * 60, self.weather.refresh, "weather")
        run_every(4 * 60, self.radar.refresh, "radar")
        run_every(2, self.flights.refresh, "flights")
        run_every(60, self.timelapse.refresh, "timelapse")
        run_every(5, self.check_settings_file, "settings")

    def check_settings_file(self):
        """settings.yaml edited by hand: use it now, no restart needed."""
        if self.settings.reload_if_changed():
            self.settings_rev += 1  # open pages reload
            self.live.restart()  # the camera address or login may have changed
            threading.Thread(target=self.timelapse.refresh, daemon=True).start()

    def backyard_status(self):
        return {
            "timelapse": {**self.timelapse.meta, "error": self.timelapse.error},
            "live": {"error": self.live.status_error()},
        }

    def can_edit(self, client):
        return client in LOCAL_ADDRESSES or self.settings["allow_settings_from_network"]

    def page_config(self, client):
        """Settings the pages need (no secrets live in settings anyway)."""
        s = self.settings
        return {
            # Changes on every restart, so open pages reload after an update.
            "version": f"{__version__}-{self.started}",
            "settings_rev": self.settings_rev,
            "clock": s["clock"],
            "location": s["location"],
            "weather": s["weather"],
            "flights": {k: v for k, v in s["flights"].items() if k != "feed_url"},
            "screen": s["screen"],
            "resume_after_touch_seconds": s["pages"]["resume_after_touch_seconds"],
            "pages": [{**PAGES[p["name"]], **p} for p in s["pages"]["list"] if p["name"] in PAGES],
            "can_edit": self.can_edit(client),
        }

    def settings_info(self, client):
        """Everything the settings page shows."""
        fields = []
        for key, spec in EDITABLE.items():
            section, label, kind = spec[:3]
            field = {"key": key, "section": section, "label": label, "kind": kind, "value": get(self.settings.values, key)}
            if kind != "bool":
                field.update(min=spec[3], max=spec[4], step=spec[5], unit=spec[6])
            fields.append(field)
        lo, hi, step = PAGE_SECONDS
        return {
            "can_edit": self.can_edit(client),
            "fields": fields,
            "pages": [{**PAGES[p["name"]], **p} for p in self.settings["pages"]["list"]],
            "page_seconds": {"min": lo, "max": hi, "step": step},
            "about": {
                "version": __version__,
                "address": f"http://{local_ip()}:{self.settings['port']}",
                "settings_file": str(self.settings.path),
                "location": self.settings["location"],
                "flight_feed": self.settings["flights"]["feed_url"],
                "flight_feed_ok": self.flights.latest["error"] is None,
                "weather_updated": self.weather.summary.get("updated", {}).get("current"),
            },
        }

    def exit_kiosk(self):
        """Close the full-screen browser (see kiosk.sh) to show the desktop."""
        data = self.data_dir.resolve()
        (data / "kiosk-stopped").touch()
        subprocess.run(["pkill", "-f", "--", f"--user-data-dir={data / 'browser'}"], check=False)

    def tile(self, layer, z, x, y):
        """Map background squares: downloaded once, then kept forever."""
        path = self.tiles_dir / layer / str(z) / str(x) / str(y)
        if not path.exists():
            template = self.settings["map"]["base_tiles" if layer == "base" else "label_tiles"]
            data = nws.get_bytes(template.format(z=z, x=x, y=y))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("%s " + fmt, self.address_string(), *args)

        @property
        def client(self):
            return self.client_address[0]

        def send_bytes(self, data: bytes, ctype: str, cache: str = "no-cache", status=HTTPStatus.OK):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path: Path, cache: str = "no-cache"):
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_bytes(path.read_bytes(), ctype, cache)

        def send_video(self, path: Path):
            """Videos need byte ranges so the browser can loop and skip."""
            try:
                data = path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            total, start, end = len(data), 0, len(data) - 1
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), end) if m.group(2) else end
                else:
                    start = max(0, total - int(m.group(2)))
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{total}")
                self.end_headers()
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT if m else HTTPStatus.OK)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if m:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.send_header("Cache-Control", "max-age=86400")  # each version has its own ?v=
            self.end_headers()
            try:
                self.wfile.write(data[start : end + 1])
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser only wanted part of it (normal when skipping)

        def send_live(self):
            """The live picture, for as long as the viewer keeps the connection open."""
            started = False

            def write(chunk):
                nonlocal started
                if not started:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    started = True
                self.wfile.write(chunk)

            try:
                app.live.stream_to(write)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the viewer left (page hidden or closed); ffmpeg is stopped
            except Exception as e:
                if not started:
                    self.send_json({"error": str(e)}, HTTPStatus.BAD_GATEWAY)

        def send_json(self, obj, status=HTTPStatus.OK):
            self.send_bytes(json.dumps(obj).encode(), "application/json", status=status)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in OTHER_FILES:
                self.send_file(WEB_DIR / OTHER_FILES[path])
            elif path[1:] in PAGES:
                self.send_file(WEB_DIR / PAGES[path[1:]]["file"])
            elif path == "/api/config":
                self.send_json(app.page_config(self.client))
            elif path == "/api/settings":
                self.send_json(app.settings_info(self.client))
            elif path == "/api/weather":
                self.send_json(app.weather.summary)
            elif path == "/api/flights":
                self.send_json(app.flights.latest)
            elif path == "/api/backyard":
                self.send_json(app.backyard_status())
            elif path == "/camera/last_hour.mp4":
                # ?v=<version>: keep serving the hour the screen started playing
                m = re.search(r"[?&]v=(\d+)", self.path)
                wanted = app.timelapse.path_for(m.group(1)) if m else None
                self.send_video(wanted if wanted and wanted.exists() else app.timelapse.path)
            elif path == "/camera/live.mp4":
                self.send_live()
            elif path == "/api/radar":
                index = app.data_dir / "radar.json"
                self.send_json(json.loads(index.read_text()) if index.exists() else {"frames": []})
            elif m := RADAR_RE.match(path):
                self.send_file(app.radar.dir / m.group(1), "max-age=86400")
            elif m := TILE_RE.match(path):
                layer, z, x, y = m.group(1), *map(int, m.groups()[1:])
                try:
                    data = app.tile(layer, z, x, y).read_bytes()
                    ctype = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
                    self.send_bytes(data, ctype, "max-age=604800")
                except Exception as e:
                    log.warning("map tile %s failed: %s", path, e)
                    self.send_error(HTTPStatus.BAD_GATEWAY)
            elif path.startswith("/static/") and ".." not in path:
                self.send_file(WEB_DIR / path[len("/static/") :])
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if self.path not in ("/api/settings", "/api/exit-kiosk"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            # JSON-only means other websites can't post here from a browser.
            if not app.can_edit(self.client) or self.headers.get("Content-Type") != "application/json":
                self.send_json({"error": "Settings can only be changed on the touchscreen."}, HTTPStatus.FORBIDDEN)
                return
            if self.path == "/api/exit-kiosk":
                app.exit_kiosk()
                self.send_json({"ok": True})
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                app.settings.change(body["key"], body["value"])
            except (ValueError, KeyError, TypeError) as e:
                self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
                return
            app.settings_rev += 1
            log.info("setting %s changed to %r", body["key"], body["value"])
            if body["key"] == "weather.radar_loop_minutes":  # fetch the new loop now
                threading.Thread(target=app.radar.refresh, daemon=True).start()
            self.send_json({"ok": True, "settings_rev": app.settings_rev})

    return Handler


def serve(settings: Settings, data_dir: Path, host: str = "0.0.0.0"):
    app = App(settings, data_dir)
    app.start_background()
    server = ThreadingHTTPServer((host, settings["port"]), make_handler(app))
    log.info("Pi Dashboard %s on http://localhost:%d", __version__, settings["port"])
    server.serve_forever()
