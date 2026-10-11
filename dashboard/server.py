"""The web server the screen's browser talks to, plus the background fetching."""

import json
import logging
import mimetypes
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, nws
from .radar import Radar
from .weather import Weather

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TILE_RE = re.compile(r"^/tiles/(base|labels)/(\d{1,2})/(\d{1,5})/(\d{1,5})\.png$")
RADAR_RE = re.compile(r"^/radar/(\d{8}T\d{6}Z\.png)$")
PAGES = {"/weather": "weather.html"}

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


class App:
    def __init__(self, settings, data_dir: Path):
        self.settings = settings
        self.data_dir = data_dir
        self.started = int(time.time())
        self.tiles_dir = data_dir / "tiles"
        self.weather = Weather(settings, data_dir)
        self.radar = Radar(settings, data_dir)

    def start_background(self):
        minutes = self.settings["weather"]["refresh_minutes"]
        run_every(minutes * 60, self.weather.refresh, "weather")
        run_every(4 * 60, self.radar.refresh, "radar")

    def page_config(self):
        """Settings the pages need (no secrets live in settings anyway)."""
        return {
            # Changes on every restart, so open pages reload after an update.
            "version": f"{__version__}-{self.started}",
            "clock": self.settings["clock"],
            "location": self.settings["location"],
        }

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

        def send_bytes(self, data: bytes, ctype: str, cache: str = "no-cache"):
            self.send_response(HTTPStatus.OK)
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

        def send_json(self, obj):
            self.send_bytes(json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/weather")
                self.end_headers()
            elif path in PAGES:
                self.send_file(WEB_DIR / PAGES[path])
            elif path == "/api/config":
                self.send_json(app.page_config())
            elif path == "/api/weather":
                self.send_json(app.weather.summary)
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

    return Handler


def serve(settings, data_dir: Path, host: str = "0.0.0.0"):
    app = App(settings, data_dir)
    app.start_background()
    server = ThreadingHTTPServer((host, settings["port"]), make_handler(app))
    log.info("Pi Dashboard %s on http://localhost:%d", __version__, settings["port"])
    server.serve_forever()
