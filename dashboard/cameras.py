"""Backyard camera: the live picture (pulled from the recorder by ffmpeg and
passed straight through, no re-encoding) and the last-hour timelapse
(downloaded from the timelapse server on the mini PC whenever it changes)."""

import base64
import json
import logging
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from . import nws

log = logging.getLogger(__name__)

STALL_SECONDS = 20  # no picture for this long means the recorder hung
# ffmpeg normally studies a stream for ~5 s before sending anything; half a
# second is plenty here (measured on the Pi: first picture after 1.4 s, not 6).
QUICK_START = ["-analyzeduration", "500000", "-probesize", "65536"]


def hide_login(text):
    """ffmpeg repeats the address in its errors, login included: blank it out
    before anything is logged or shown."""
    return re.sub(r"//[^/@\s]+:[^/@\s]*@", "//", text)


def _with_login(url, user, password):
    """rtsp://host/path -> rtsp://user:password@host/path"""
    if not user:
        return url
    parts = urlsplit(url)
    host = parts.netloc.rsplit("@", 1)[-1]
    login = f"{quote(user, safe='')}:{quote(password or '', safe='')}"
    return urlunsplit(parts._replace(netloc=f"{login}@{host}"))


class Timelapse:
    """Keeps data/backyard/last_hour.mp4 in step with the timelapse server."""

    def __init__(self, settings, data_dir: Path):
        self.settings = settings
        self.dir = data_dir / "backyard"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "last_hour.mp4"
        self.meta_path = self.dir / "last_hour.json"
        try:
            self.meta = json.loads(self.meta_path.read_text())
        except (OSError, ValueError):
            self.meta = {"version": 0, "updated": None, "size": None}
        self.error = None

    def _request(self, extra_headers=None):
        cfg = self.settings["backyard"]["timelapse"]
        headers = {"User-Agent": nws.USER_AGENT, **(extra_headers or {})}
        if cfg["user"]:
            token = base64.b64encode(f"{cfg['user']}:{cfg['pin'] or ''}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return urllib.request.Request(cfg["url"], headers=headers)

    def refresh(self):
        cfg = self.settings["backyard"]["timelapse"]
        if not cfg["pin"]:
            self.error = "Add the timelapse PIN to settings.yaml (backyard → timelapse → pin)."
            return
        try:
            # Ask for one byte: the reply says how big the whole file is now.
            with urllib.request.urlopen(self._request({"Range": "bytes=0-0"}), timeout=20) as r:
                total = r.headers.get("Content-Range", "").rsplit("/", 1)[-1]
                size = int(total) if total.isdigit() else int(r.headers.get("Content-Length", 0))
            if size and size == self.meta["size"] and self.path.exists():
                self.error = None
                return
            with urllib.request.urlopen(self._request(), timeout=120) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            self.error = (
                "The timelapse login was refused. Check the user and PIN in settings.yaml."
                if e.code == 401
                else f"The timelapse server answered with an error ({e.code})."
            )
            return
        except Exception as e:
            self.error = f"Can't reach the timelapse ({e})."
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(self.path)
        self.meta = {"version": self.meta["version"] + 1, "updated": time.time(), "size": len(data)}
        self.meta_path.write_text(json.dumps(self.meta))
        self.error = None
        log.info("backyard: new last-hour timelapse (%.1f MB)", len(data) / 1e6)


class Live:
    """The live picture. Each viewer gets its own ffmpeg, which only runs while
    someone is watching (the screen stops watching when the page is hidden)."""

    def __init__(self, settings):
        self.settings = settings
        self.codec = None  # what the recorder sends, learned on first use
        self.error = None
        self.lock = threading.Lock()

    def url(self):
        cfg = self.settings["backyard"]["live"]
        return _with_login(cfg["url"], cfg["user"], cfg["password"])

    def configured(self):
        cfg = self.settings["backyard"]["live"]
        return bool(cfg["user"] and cfg["password"])

    def status_error(self):
        if not self.configured():
            return "Add the recorder's user and password to settings.yaml (backyard → live)."
        return self.error

    def probe(self):
        """Ask the recorder what kind of video it sends (H.264 can be passed
        straight to the browser; anything else has to be converted)."""
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-rtsp_transport", "tcp", *QUICK_START, "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,width,height", "-of", "json", self.url()],
                capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired:  # its message would repeat the login
            raise RuntimeError("The recorder didn't answer in time.") from None
        if out.returncode != 0:
            msg = hide_login(out.stderr.strip().splitlines()[-1]) if out.stderr.strip() else "no answer"
            if "401" in msg:
                raise RuntimeError("The recorder refused the login. Check backyard → live in settings.yaml.")
            raise RuntimeError(f"Can't reach the recorder ({msg}).")
        stream = json.loads(out.stdout)["streams"][0]
        return stream["codec_name"], stream.get("width"), stream.get("height")

    def learn_codec(self):
        """Find out the stream format ahead of time, so viewers don't wait for it."""
        with self.lock:
            if self.codec is None and self.configured():
                self.codec, w, h = self.probe()
                log.info("backyard live: %s %sx%s", self.codec, w, h)

    def command(self):
        self.learn_codec()
        video = ["-c:v", "copy"] if self.codec == "h264" else [
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-vf", "scale=-2:540",
        ]
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
            "-fflags", "nobuffer", "-flags", "low_delay", *QUICK_START,
            # Reolink recorders send the stream without timestamps; use the Pi's clock.
            "-use_wallclock_as_timestamps", "1",
            "-i", self.url(),
            "-an", *video, "-f", "mp4",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "500000",
            "pipe:1",
        ]

    def stream_to(self, write):
        """Run ffmpeg and hand its output to `write` until the viewer leaves."""
        if not self.configured():
            raise RuntimeError(self.status_error())
        try:
            cmd = self.command()
        except Exception as e:
            self.codec = None
            self.error = hide_login(str(e))  # e.g. a timeout repeats the whole command
            raise RuntimeError(self.error) from None
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.error = None
        last_data = time.time()

        def watchdog():  # the recorder went quiet: stop, and the page reconnects
            while proc.poll() is None:
                if time.time() - last_data > STALL_SECONDS:
                    log.info("backyard live: no picture for %ss, reconnecting", STALL_SECONDS)
                    proc.kill()
                time.sleep(2)

        threading.Thread(target=watchdog, daemon=True).start()
        try:
            while chunk := proc.stdout.read1(64 * 1024):
                last_data = time.time()
                write(chunk)
        finally:
            proc.kill()
            proc.wait()
            err = proc.stderr.read().decode(errors="replace").strip()
            if err:
                log.info("backyard live ffmpeg: %s", hide_login(err.splitlines()[-1]))
