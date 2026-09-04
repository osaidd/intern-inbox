# career_inbox/update.py
"""In-app Update: `git pull --ff-only` + `uv sync` behind one button, so
"run git pull now and then" stops being a thing batchmates must remember.

Safety posture: explicit arg lists (no shell), cwd pinned to the repo, nothing
user-supplied ever reaches a command line, and git's own refusals (dirty
tracked files, non-ff history) ARE the guardrail — surfaced honestly instead
of worked around. Personal config is gitignored, so it never conflicts.
Migrations are NEVER run from the old process: __main__ migrates on the next
start, which is why the response says restart_needed."""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class UpdateBlocked(Exception):
    """Not updatable here (no git checkout) — endpoint maps to 409."""


class UpdateFailed(Exception):
    """git/uv exited nonzero or timed out — endpoint maps to 502."""


def _run(args: list, cwd: Path, timeout: int):
    """Subprocess seam (tests fake this)."""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def _uv_path() -> str:
    """The launcher's probe order (automation/intern-inbox-launcher.sh): the
    server may be running with almost no PATH."""
    for cand in (Path.home() / ".local/bin/uv", Path("/opt/homebrew/bin/uv")):
        if cand.is_file():
            return str(cand)
    return shutil.which("uv") or "uv"


def _tail(s: str, n: int = 300) -> str:
    s = (s or "").strip()
    return s[-n:]


def run_update() -> dict:
    if not (ROOT / ".git").exists():
        raise UpdateBlocked("not a git checkout — reinstall with the bootstrap paste")
    try:
        before = _run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], ROOT, 30)
        pull = _run(["git", "-C", str(ROOT), "pull", "--ff-only"], ROOT, 120)
        if pull.returncode != 0:
            raise UpdateFailed(_tail(pull.stderr or pull.stdout))
        after = _run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], ROOT, 30)
    except subprocess.TimeoutExpired:
        raise UpdateFailed("git timed out — check your connection and try again")
    head = (after.stdout or "").strip()[:12]
    if before.stdout == after.stdout:
        return {"updated": False, "head": head, "output": "already up to date",
                "restart_needed": False}
    try:
        sync = _run([_uv_path(), "sync"], ROOT, 300)
    except subprocess.TimeoutExpired:
        raise UpdateFailed("uv sync timed out — run it by hand: uv sync")
    if sync.returncode != 0:
        raise UpdateFailed(_tail(sync.stderr or sync.stdout))
    return {"updated": True, "head": head, "output": _tail(pull.stdout, 200),
            "restart_needed": True}
