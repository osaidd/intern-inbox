"""Secrets loader: the tiny KEY=VALUE parser for config/.env (gitignored).
Every feed that needs a credential calls load_env() first — no third-party dotenv
dependency, and an already-exported environment variable always wins."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Tiny KEY=VALUE parser for config/.env — exports into os.environ."""
    env_path = ROOT / "config" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
