import json

from career_hunt.geocode import geocode


def fake_opener(payload, calls):
    """Records each request OUTSIDE geocode's blanket except — assertions on
    `calls` after the call can actually fail (the old in-opener asserts were
    swallowed by geocode's `except Exception: return None`)."""
    def _open(url, timeout):
        calls.append({"url": url.full_url, "ua": url.headers.get("User-agent")})

        class R:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()
    return _open


def test_geocode_hit():
    calls = []
    got = geocode("One Manhattan West, New York",
                  _opener=fake_opener([{"lat": "40.7527", "lon": "-73.9973"}], calls))
    assert got == (40.7527, -73.9973)
    assert len(calls) == 1
    assert "nominatim.openstreetmap.org" in calls[0]["url"]
    assert calls[0]["ua"]                      # honest UA present


def test_geocode_miss():
    calls = []
    assert geocode("zzz nowhere", _opener=fake_opener([], calls)) is None
    assert len(calls) == 1                     # miss = empty result, not a silent no-call
