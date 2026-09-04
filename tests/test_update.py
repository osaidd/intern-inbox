# tests/test_update.py
"""In-app Update: scripted subprocess fakes — no real git/uv ever runs here."""
import subprocess

import pytest

from career_inbox import update


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


def _fake_run(script):
    """script: list of (arg-substring, CompletedProcess|Exception) consumed in order
    of matching; records every command line."""
    calls = []

    def run(args, cwd, timeout):
        calls.append(args)
        for i, (frag, result) in enumerate(script):
            if frag in " ".join(args):
                script.pop(i)
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected command {args}")
    return run, calls


def test_no_change_skips_sync(monkeypatch):
    run, calls = _fake_run([("rev-parse", _proc(out="abc123\n")),
                            ("pull", _proc(out="Already up to date.\n")),
                            ("rev-parse", _proc(out="abc123\n"))])
    monkeypatch.setattr(update, "_run", run)
    d = update.run_update()
    assert d == {"updated": False, "head": "abc123", "output": "already up to date",
                 "restart_needed": False}
    assert not any("sync" in " ".join(c) for c in calls)


def test_change_syncs_and_flags_restart(monkeypatch):
    run, calls = _fake_run([("rev-parse", _proc(out="abc123\n")),
                            ("pull", _proc(out="Updating abc123..def456\n")),
                            ("rev-parse", _proc(out="def456789012ffff\n")),
                            ("sync", _proc(out="ok"))])
    monkeypatch.setattr(update, "_run", run)
    d = update.run_update()
    assert d["updated"] is True and d["restart_needed"] is True
    assert d["head"] == "def456789012"
    assert any("sync" in " ".join(c) for c in calls)


def test_git_failure_surfaces_stderr(monkeypatch):
    run, _ = _fake_run([("rev-parse", _proc(out="abc\n")),
                        ("pull", _proc(rc=1, err="fatal: not possible to fast-forward"))])
    monkeypatch.setattr(update, "_run", run)
    with pytest.raises(update.UpdateFailed, match="fast-forward"):
        update.run_update()


def test_sync_failure_surfaces(monkeypatch):
    run, _ = _fake_run([("rev-parse", _proc(out="a\n")),
                        ("pull", _proc(out="Updating\n")),
                        ("rev-parse", _proc(out="b\n")),
                        ("sync", _proc(rc=2, err="resolution failed"))])
    monkeypatch.setattr(update, "_run", run)
    with pytest.raises(update.UpdateFailed, match="resolution failed"):
        update.run_update()


def test_timeout_is_an_update_failure(monkeypatch):
    run, _ = _fake_run([("rev-parse", subprocess.TimeoutExpired(["git"], 30))])
    monkeypatch.setattr(update, "_run", run)
    with pytest.raises(update.UpdateFailed, match="timed out"):
        update.run_update()


def test_missing_git_checkout_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "ROOT", tmp_path)
    with pytest.raises(update.UpdateBlocked, match="not a git checkout"):
        update.run_update()
