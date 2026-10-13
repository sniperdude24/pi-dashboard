"""This Pi's own health: processor, memory, temperature, SSD, network, power."""

import shutil
import subprocess
import time
from collections import deque
from pathlib import Path

HISTORY_STEP = 30  # seconds per point on the one-hour processor graph
HISTORY_POINTS = 3600 // HISTORY_STEP

# get_throttled bits (https://www.raspberrypi.com/documentation/computers/os.html#get_throttled)
THROTTLE_BITS = {
    0: "Low voltage right now",
    1: "Processor speed capped right now",
    2: "Slowed down right now",
    3: "Temperature limit right now",
    16: "Low voltage happened since start-up",
    17: "Processor speed was capped since start-up",
    18: "Slowed down since start-up",
    19: "Hit the temperature limit since start-up",
}


def _read(path, default=None):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def _vcgencmd(*args):
    try:
        return subprocess.run(["vcgencmd", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


class History:
    """Averages samples into one point per HISTORY_STEP seconds, for an hour."""

    def __init__(self):
        self.points = deque(maxlen=HISTORY_POINTS)
        self.bucket, self.bucket_start = [], time.time()

    def add(self, value):
        self.bucket.append(value)
        if time.time() - self.bucket_start >= HISTORY_STEP:
            self.points.append(round(sum(self.bucket) / len(self.bucket), 1))
            self.bucket, self.bucket_start = [], time.time()

    def list(self):
        return list(self.points)


class NetRate:
    """Bytes per second from ever-growing byte counters."""

    def __init__(self):
        self.last = None

    def update(self, rx, tx, now):
        rate = None
        if self.last and now > self.last[2]:
            dt = now - self.last[2]
            rate = (max(0, rx - self.last[0]) / dt, max(0, tx - self.last[1]) / dt)
        self.last = (rx, tx, now)
        return rate


class PiSystem:
    def __init__(self):
        self.prev_cpu = None
        self.cpu_history = History()
        self.net = NetRate()
        self.net_rate = (0, 0)
        self.model = (_read("/proc/device-tree/model", "") or "").replace("\x00", "").replace(" Model B", "")
        try:
            raw = Path("/proc/device-tree/chosen/power/max_current").read_bytes()
            self.supply_amps = int.from_bytes(raw[:4], "big") / 1000
        except OSError:
            self.supply_amps = None
        self.latest = {"error": "Starting…"}

    def _cpu_percent(self):
        fields = list(map(int, _read("/proc/stat").splitlines()[0].split()[1:]))
        idle, total = fields[3] + fields[4], sum(fields)
        percent = None
        if self.prev_cpu:
            d_total, d_idle = total - self.prev_cpu[1], idle - self.prev_cpu[0]
            percent = 100 * (1 - d_idle / d_total) if d_total else 0
        self.prev_cpu = (idle, total)
        return percent

    def sample(self):
        if not Path("/proc/stat").exists():
            self.latest = {"error": "This computer isn't a Raspberry Pi."}
            return
        cpu = self._cpu_percent()
        if cpu is None:
            return  # need two readings
        self.cpu_history.add(cpu)

        mem = {}
        for line in _read("/proc/meminfo").splitlines():
            key, value = line.split(":")
            mem[key] = int(value.split()[0]) * 1024
        disk = shutil.disk_usage("/")

        rx = tx = 0
        for line in _read("/proc/net/dev").splitlines()[2:]:
            name, data = line.split(":", 1)
            if name.strip() == "lo" or name.strip().startswith(("docker", "veth", "br-")):
                continue
            cols = data.split()
            rx, tx = rx + int(cols[0]), tx + int(cols[8])
        rate = self.net.update(rx, tx, time.time())
        if rate:
            self.net_rate = rate

        volts = None
        out = _vcgencmd("pmic_read_adc", "EXT5V_V")
        if "=" in out:
            volts = float(out.split("=")[1].rstrip("V"))
        throttled = _vcgencmd("get_throttled")
        bits = int(throttled.split("=")[1], 16) if "=" in throttled else 0

        self.latest = {
            "error": None,
            "name": _read("/proc/sys/kernel/hostname", "Pi"),
            "model": self.model,
            "uptime": float(_read("/proc/uptime").split()[0]),
            "cpu": round(cpu, 1),
            "cpu_history": self.cpu_history.list(),
            "mem_percent": round(100 * (1 - mem["MemAvailable"] / mem["MemTotal"]), 1),
            "mem_used": mem["MemTotal"] - mem["MemAvailable"],
            "mem_total": mem["MemTotal"],
            "temp": round(int(_read("/sys/class/thermal/thermal_zone0/temp", "0")) / 1000, 1),
            "disks": [{"name": "SSD", "used": disk.used, "total": disk.total}],
            "net_down": round(self.net_rate[0]),
            "net_up": round(self.net_rate[1]),
            "power": {
                "volts": volts,
                "supply_amps": self.supply_amps,
                "warnings": [text for bit, text in THROTTLE_BITS.items() if bits & (1 << bit)],
            },
        }
