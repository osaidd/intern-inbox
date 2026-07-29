import json

from career_hunt.geocode import geocode


def fake_opener(payload):
    def _open(url, timeout):
        class R:
            def read(self):
                return json.dumps(payload).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        assert "nominatim.openstreetmap.org" in url.full_url
        assert url.headers.get("User-agent")
        return R()
    return _open


def test_geocode_hit():
    got = geocode("One Manhattan West, New York",
                  _opener=fake_opener([{"lat": "40.7527", "lon": "-73.9973"}]))
    assert got == (40.7527, -73.9973)


def test_geocode_miss():
    assert geocode("zzz nowhere", _opener=fake_opener([])) is None
