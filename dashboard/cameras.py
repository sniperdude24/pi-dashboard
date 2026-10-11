"""Backyard camera: the live picture (pulled from the recorder by ffmpeg and
passed straight through, no re-encoding) and the last-hour timelapse
(downloaded from the timelapse server on the mini PC whenever it changes,
then shrunk to the size it's shown at)."""

import base64
import collections
import json
import logging
import re
import struct
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

# The last hour arrives as 1920x1080 at 60 fps but is shown at 936x527.
# Decoding that took ~42% of a core while on screen; a copy at the shown
# size and 30 fps costs a short burst every 5 minutes instead.
SHRINK = ["-vf", "scale=960:-2,fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
          "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


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
    """Keeps data/backyard/last_hour_<version>.mp4 in step with the timelapse
    server. The previous versions stay for a while: the screen finishes playing
    the hour it started before switching, and must keep getting the same file."""

    KEEP_VERSIONS = 3

    def __init__(self, settings, data_dir: Path):
        self.settings = settings
        self.dir = data_dir / "backyard"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.dir / "last_hour.json"
        try:
            self.meta = json.loads(self.meta_path.read_text())
        except (OSError, ValueError):
            self.meta = {"version": 0, "updated": None, "size": None}
        old = self.dir / "last_hour.mp4"  # from before versions had their own files
        if old.exists():
            old.replace(self.path_for(self.meta["version"]))
        self.error = None

    def path_for(self, version):
        return self.dir / f"last_hour_{int(version)}.mp4"

    @property
    def path(self):
        return self.path_for(self.meta["version"])

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
        fetched = time.time()  # the timeline is based on this, not on when shrinking ends
        version = self.meta["version"] + 1
        src = self.dir / "last_hour_download.tmp"
        src.write_bytes(data)
        small = self.dir / "last_hour_small.tmp"
        started = time.time()
        done = subprocess.run(
            ["nice", "-n", "10", "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
             "-an", *SHRINK, "-threads", "2", "-f", "mp4", str(small)],
            capture_output=True, text=True, timeout=300,
        )
        if done.returncode == 0:
            small.replace(self.path_for(version))
            src.unlink()
        else:  # shrinking failed: show the full-size one rather than nothing
            log.warning("backyard: couldn't shrink the last hour: %s", done.stderr.strip()[-200:])
            src.replace(self.path_for(version))
        self.meta = {"version": version, "updated": fetched, "size": len(data),
                     "shrink_seconds": round(time.time() - started, 1)}
        self.meta_path.write_text(json.dumps(self.meta))
        for f in self.dir.glob("last_hour_*.mp4"):
            if f.stem.split("_")[-1].isdigit() and int(f.stem.split("_")[-1]) <= version - self.KEEP_VERSIONS:
                f.unlink()
        self.error = None
        log.info("backyard: new last-hour timelapse (%.1f MB, shrunk in %ss)",
                 len(data) / 1e6, self.meta["shrink_seconds"])


class Live:
    """The live picture. While the Backyard page is in the rotation, one ffmpeg
    stays connected to the recorder and the Pi keeps the pieces since the last
    full picture (keyframe, every ~4 s). A viewer gets those at once, so the
    picture appears straight away instead of after a new connection plus the
    next keyframe (measured ~11 s before this)."""

    def __init__(self, settings):
        self.settings = settings
        self.codec = None  # what the recorder sends, learned on first use
        self.error = None
        self.cond = threading.Condition()
        self.proc = None
        self.generation = 0  # goes up each time the relay (re)connects
        self.init = None  # the stream's header (ftyp + moov)
        self.gop = []  # fragments since the last full picture
        self.seq = 0  # fragments received so far
        self.recent = collections.deque(maxlen=64)  # (seq, fragment) for viewers
        threading.Thread(target=self._run, name="live-relay", daemon=True).start()

    def url(self):
        cfg = self.settings["backyard"]["live"]
        return _with_login(cfg["url"], cfg["user"], cfg["password"])

    def configured(self):
        cfg = self.settings["backyard"]["live"]
        return bool(cfg["user"] and cfg["password"])

    def wanted(self):
        on = {p["name"]: p["enabled"] for p in self.settings["pages"]["list"]}
        return bool(on.get("backyard")) and self.configured()

    def status_error(self):
        if not self.configured():
            return "Add the recorder's user and password to settings.yaml (backyard → live)."
        return self.error

    def restart(self):
        """Settings changed: reconnect with the new ones."""
        self.codec = None
        if self.proc:
            self.proc.kill()

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

    def command(self):
        if self.codec is None:
            self.codec, w, h = self.probe()
            log.info("backyard live: %s %sx%s", self.codec, w, h)
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

    # ---------- the relay: one connection to the recorder ----------

    def _run(self):
        while True:
            if not self.wanted():
                self._forget()
                time.sleep(3)
                continue
            try:
                self._relay()
            except Exception as e:
                self.codec = None
                self.error = hide_login(str(e))  # e.g. a timeout repeats the whole command
                log.info("backyard live: %s", self.error)
            self._forget()
            time.sleep(5)

    def _forget(self):
        with self.cond:
            self.init, self.gop = None, []
            self.cond.notify_all()

    def _relay(self):
        proc = self.proc = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self.cond:
            self.generation += 1
        last_data = time.time()

        def watchdog():  # the recorder went quiet, or the page was turned off
            while proc.poll() is None:
                if time.time() - last_data > STALL_SECONDS or not self.wanted():
                    proc.kill()
                time.sleep(2)

        threading.Thread(target=watchdog, daemon=True).start()
        buf, header, moof = bytearray(), [], None
        try:
            while chunk := proc.stdout.read1(64 * 1024):
                last_data = time.time()
                self.error = None
                buf += chunk
                pos = 0
                while (box := _next_box(buf, pos)) is not None:
                    kind, end = box
                    data = bytes(buf[pos:end])
                    pos = end
                    if kind in (b"ftyp", b"moov"):
                        header.append(data)
                        if kind == b"moov":
                            with self.cond:
                                self.init = b"".join(header)
                    elif kind == b"moof":
                        moof = data
                    elif kind == b"mdat" and moof:
                        self._add(moof + data)
                        moof = None
                del buf[:pos]
        finally:
            proc.kill()
            proc.wait()
            err = proc.stderr.read().decode(errors="replace").strip()
            if err:
                log.info("backyard live ffmpeg: %s", hide_login(err.splitlines()[-1]))

    def _add(self, data):
        frag = _Fragment(data)
        with self.cond:
            if frag.keyframe or not self.gop:
                self.gop = [frag]  # a full picture: older pieces aren't needed any more
            elif len(self.gop) < 120:
                self.gop.append(frag)
            self.seq += 1
            self.recent.append((self.seq, frag))
            self.cond.notify_all()

    # ---------- one viewer ----------

    def stream_to(self, write):
        """Send the live picture to one viewer until they leave."""
        if not self.configured():
            raise RuntimeError(self.status_error())
        with self.cond:
            ready = self.cond.wait_for(lambda: self.init and self.gop and self.gop[0].keyframe, timeout=15)
            if not ready:
                raise RuntimeError(self.status_error() or "No picture from the recorder yet.")
            generation, init, backlog, next_seq = self.generation, self.init, list(self.gop), self.seq + 1
        base = backlog[0].time  # each viewer's video starts at 0
        write(init)
        for frag in backlog:
            write(frag.rebased(base))
        while True:
            with self.cond:
                self.cond.wait_for(lambda: self.seq >= next_seq or self.generation != generation,
                                   timeout=STALL_SECONDS)
                if self.generation != generation or self.seq < next_seq:
                    return  # reconnected or stalled: the page starts over
                todo = [f for s, f in self.recent if s >= next_seq]
                if len(todo) < self.seq - next_seq + 1:
                    return  # this viewer fell too far behind: the page starts over
                next_seq = self.seq + 1
            for frag in todo:
                write(frag.rebased(base))


def _next_box(buf, pos):
    """(type, end) of the complete MP4 box starting at pos, or None if more
    data is needed."""
    if len(buf) - pos < 8:
        return None
    size, kind = struct.unpack_from(">I4s", buf, pos)
    if size == 1:
        if len(buf) - pos < 16:
            return None
        size = struct.unpack_from(">Q", buf, pos + 8)[0]
    if size < 8 or len(buf) - pos < size:
        return None
    return kind, pos + size


def _children(data, start, end):
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        if size < 8:
            return
        yield kind, pos + 8, min(pos + size, end)
        pos += size


class _Fragment:
    """One moof+mdat piece of the live stream: whether it starts with a full
    picture, and its decode time (rewritten per viewer so each starts at 0)."""

    def __init__(self, data):
        self.data = data
        self.keyframe = False
        self.time = 0
        self.time_at = None  # (offset, 64-bit?) of the decode time inside data
        moof_end = struct.unpack_from(">I", data, 0)[0]
        for kind, s, e in _children(data, 8, moof_end):
            if kind != b"traf":
                continue
            default_flags = None
            for k, cs, ce in _children(data, s, e):
                version, flags = data[cs], int.from_bytes(data[cs + 1 : cs + 4], "big")
                if k == b"tfhd":
                    p = cs + 8  # after version/flags and track id
                    p += 8 if flags & 0x1 else 0
                    p += 4 if flags & 0x2 else 0
                    p += 4 if flags & 0x8 else 0
                    p += 4 if flags & 0x10 else 0
                    if flags & 0x20:
                        default_flags = struct.unpack_from(">I", data, p)[0]
                elif k == b"tfdt":
                    wide = version == 1
                    self.time_at = (cs + 4, wide)
                    self.time = struct.unpack_from(">Q" if wide else ">I", data, cs + 4)[0]
                elif k == b"trun":
                    p = cs + 8  # after version/flags and sample count
                    p += 4 if flags & 0x1 else 0
                    if flags & 0x4:
                        sample_flags = struct.unpack_from(">I", data, p)[0]
                    elif flags & 0x400:
                        p += 4 if flags & 0x100 else 0
                        p += 4 if flags & 0x200 else 0
                        sample_flags = struct.unpack_from(">I", data, p)[0]
                    else:
                        sample_flags = default_flags
                    # the "not a full picture" bit is clear: this starts with a keyframe
                    self.keyframe = sample_flags is not None and not sample_flags & 0x10000
            break

    def rebased(self, base):
        if not self.time_at:
            return self.data
        out = bytearray(self.data)
        offset, wide = self.time_at
        struct.pack_into(">Q" if wide else ">I", out, offset, max(0, self.time - base))
        return bytes(out)
