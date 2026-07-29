"""Sources config: communal config/sources.toml + optional personal overlay
config/sources.local.toml (gitignored). Lists union (communal first, deduped);
scalars and nested tables from the overlay win."""
import tomllib
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
COMMUNAL = CONFIG_DIR / "sources.toml"
LOCAL = CONFIG_DIR / "sources.local.toml"


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, list) and isinstance(out.get(k), list):
            out[k] = out[k] + [x for x in v if x not in out[k]]
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_sources() -> dict:
    with open(COMMUNAL, "rb") as f:
        src = tomllib.load(f)
    if LOCAL.exists():
        with open(LOCAL, "rb") as f:
            src = _merge(src, tomllib.load(f))
    return src
