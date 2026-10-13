"""The mini PC's health, read from CasaOS's own API (what its dashboard shows).
Read only: this logs in and reads statistics and the app list, nothing else."""

import json
import logging
import time
import urllib.error
import urllib.request

from . import nws
from .system import History, NetRate

log = logging.getLogger(__name__)

PHYSICAL_NIC = ("en", "eth", "wl")  # skip docker, veth, bridges and loopback


class CasaOSError(Exception):
    pass


class CasaOS:
    def __init__(self, settings):
        self.settings = settings
        self.token = None
        self.cpu_history = History()
        self.net = NetRate()
        self.net_rate = (0, 0)
        self.latest = {"error": None}

    def configured(self):
        cfg = self.settings["casaos"]
        return bool(cfg["user"] and cfg["password"])

    def _url(self, path):
        return self.settings["casaos"]["url"].rstrip("/") + path

    def _login(self):
        cfg = self.settings["casaos"]
        body = json.dumps({"username": cfg["user"], "password": cfg["password"]}).encode()
        req = urllib.request.Request(
            self._url("/v1/users/login"), data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": nws.USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                reply = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):
                raise CasaOSError("CasaOS refused the login. Check casaos → user and password in settings.yaml.")
            raise
        token = ((reply.get("data") or {}).get("token") or {}).get("access_token")
        if not token:
            raise CasaOSError("CasaOS refused the login. Check casaos → user and password in settings.yaml.")
        self.token = token

    def get(self, path, retry=True):
        if not self.token:
            self._login()
        req = urllib.request.Request(self._url(path), headers={"Authorization": self.token, "User-Agent": nws.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:  # the login ran out: log in again once
                self.token = None
                return self.get(path, retry=False)
            raise

    def refresh(self):
        if not self.configured():
            self.latest = {"error": "Add the CasaOS login to settings.yaml (casaos → user and password)."}
            return
        try:
            util = self.get("/v1/sys/utilization").get("data") or {}
        except CasaOSError as e:
            self.latest = {**self.latest, "error": str(e)}
            return
        except Exception as e:
            self.latest = {**self.latest, "error": f"Can't reach CasaOS ({e})."}
            return

        cpu = util.get("cpu") or {}
        mem = util.get("mem") or {}
        disk = util.get("sys_disk") or {}
        if cpu.get("percent") is not None:
            self.cpu_history.add(float(cpu["percent"]))

        rx = tx = 0
        stamp = None
        for nic in util.get("net") or []:
            if str(nic.get("name", "")).startswith(PHYSICAL_NIC):
                rx += nic.get("bytesRecv", 0)
                tx += nic.get("bytesSent", 0)
                stamp = nic.get("time") or stamp
        rate = self.net.update(rx, tx, stamp or time.time())
        if rate:
            self.net_rate = rate

        disks = []
        if disk.get("size"):
            disks.append({"name": "System disk", "used": disk.get("used", 0), "total": disk["size"]})

        self.latest = {
            "error": None,
            "updated": time.time(),
            "name": "daveserver",
            "model": "Mini PC · CasaOS",
            "cpu": round(float(cpu.get("percent") or 0), 1),
            "cpu_history": self.cpu_history.list(),
            "mem_percent": round(float(mem.get("usedPercent") or 0), 1),
            "mem_used": mem.get("used"),
            "mem_total": mem.get("total"),
            "temp": cpu.get("temperature"),
            "disks": disks,
            "net_down": round(self.net_rate[0]),
            "net_up": round(self.net_rate[1]),
            "apps": self._apps(),
        }

    def _apps(self):
        """The app list, or None if CasaOS won't share it."""
        try:
            grid = self.get("/v2/app_management/web/appgrid").get("data") or []
        except Exception as e:
            log.info("casaos: app list not available (%s)", e)
            return None
        apps = []
        for a in grid:
            title = a.get("title")
            name = (title.get("en_us") or title.get("en_US") or next(iter(title.values()), None)) if isinstance(title, dict) else title
            apps.append({"name": name or a.get("name") or "?", "running": a.get("status") == "running"})
        apps.sort(key=lambda a: (not a["running"], a["name"].lower()))
        return apps
