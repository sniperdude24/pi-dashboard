"""Small helpers for talking to the National Weather Service (api.weather.gov)."""

import json
import urllib.request

from . import __version__

# The Weather Service asks every program to identify itself.
USER_AGENT = f"pi-dashboard/{__version__} (https://github.com/sniperdude24/pi-dashboard)"


def get_bytes(url: str, timeout: float = 30, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url: str, timeout: float = 30) -> dict:
    return json.loads(get_bytes(url, timeout, accept="application/geo+json"))
