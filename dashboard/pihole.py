"""Pi-hole statistics, read from the Pi-hole on the mini PC (Pi-hole v6 API).
Read only: nothing here changes Pi-hole."""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import nws

log = logging.getLogger(__name__)


class PiholeError(Exception):
    pass


class Pihole:
    def __init__(self, settings, data_dir: Path):
        self.settings = settings
        # Pi-hole allows a limited number of logins at once, so the session is
        # kept on disk and reused after a restart instead of logging in again.
        self.session_path = data_dir / "pihole-session.json"
        try:
            self.sid = json.loads(self.session_path.read_text())["sid"]
        except (OSError, ValueError, KeyError):
            self.sid = None
        self.latest = {"error": None, "updated": None}

    def configured(self):
        return bool(self.settings["pihole"]["password"])

    def _url(self, path):
        return self.settings["pihole"]["url"].rstrip("/") + path

    def _login(self):
        body = json.dumps({"password": self.settings["pihole"]["password"]}).encode()
        req = urllib.request.Request(
            self._url("/api/auth"), data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": nws.USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                session = json.load(r)["session"]
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PiholeError("Pi-hole refused the password. Check pihole → password in settings.yaml.")
            if e.code == 429:
                raise PiholeError("Pi-hole has too many logins open; it will clear them by itself shortly.")
            raise
        if not session.get("valid"):
            raise PiholeError("Pi-hole refused the password. Check pihole → password in settings.yaml.")
        self.sid = session["sid"]
        self.session_path.write_text(json.dumps({"sid": self.sid}))
        os.chmod(self.session_path, 0o600)

    def _get(self, path, retry=True):
        if not self.sid:
            self._login()
        req = urllib.request.Request(self._url(path), headers={"X-FTL-SID": self.sid, "User-Agent": nws.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:  # the session ran out: log in again once
                self.sid = None
                return self._get(path, retry=False)
            raise

    def refresh(self):
        if not self.configured():
            self.latest = {"error": "Add the Pi-hole app password to settings.yaml (pihole → password).",
                           "updated": None}
            return
        try:
            summary = self._get("/api/stats/summary")
            blocking = self._get("/api/dns/blocking")
            history = self._get("/api/history")["history"]
            blocked = self._get("/api/stats/top_domains?blocked=true&count=7")["domains"]
            clients = self._get("/api/stats/top_clients?count=7")["clients"]
        except PiholeError as e:
            self.latest = {**self.latest, "error": str(e)}
            return
        except Exception as e:
            self.latest = {**self.latest, "error": f"Can't reach Pi-hole ({e})."}
            return
        q = summary.get("queries", {})
        self.latest = {
            "error": None,
            "updated": time.time(),
            "total": q.get("total", 0),
            "blocked": q.get("blocked", 0),
            "percent_blocked": q.get("percent_blocked", 0),
            "blocklist_size": summary.get("gravity", {}).get("domains_being_blocked", 0),
            "blocking": blocking.get("blocking", "unknown"),
            "blocking_timer": blocking.get("timer"),
            "history": [
                {"time": h["timestamp"], "total": h.get("total", 0), "blocked": h.get("blocked", 0)}
                for h in history
            ],
            "top_blocked": [{"name": d["domain"], "count": d["count"]} for d in blocked],
            "top_clients": [{"name": c.get("name") or c.get("ip"), "count": c["count"]} for c in clients],
        }
