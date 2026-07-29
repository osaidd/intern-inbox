"""Forward geocoding via Nominatim (OpenStreetMap) — free, so be polite: one
request per second, honest User-Agent with contact, cache results in the
companies table (callers' job). https://operations.osmfoundation.org/policies/nominatim/"""
import json
import time
import urllib.parse
import urllib.request

from .config import load, user_agent

_last_call = [0.0]


def geocode(query: str, _opener=None):
    if not query or not query.strip():
        return None
    if _opener is None:
        wait = 1.0 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        _opener = urllib.request.urlopen
    url = ("https://nominatim.openstreetmap.org/search?"
           + urllib.parse.urlencode({"q": query, "format": "json", "limit": 1}))
    try:
        # UA (with contact) comes from the user's config; built inside the try so a
        # bad config file can never make best-effort geocoding fatal.
        req = urllib.request.Request(url, headers=user_agent(load()))
        with _opener(req, timeout=15) as resp:
            rows = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001 — geocoding is best-effort, never fatal
        return None
    if not rows:
        return None
    try:
        return (float(rows[0]["lat"]), float(rows[0]["lon"]))
    except (KeyError, TypeError, ValueError):
        return None
