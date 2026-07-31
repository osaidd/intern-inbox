"""config/.env parsing: the only secrets path the feeds use."""
import os

import pytest

from feeds import envfile


@pytest.fixture(autouse=True)
def _isolated_environ(monkeypatch):
    """load_env mutates os.environ via setdefault; restore it wholesale so
    CAREER_* values can never leak into later tests."""
    monkeypatch.setattr(os, "environ", os.environ.copy())


def _write_env(tmp_path, monkeypatch, body: str):
    """Point envfile at a throwaway repo root AND swap os.environ for an empty dict.
    load_env() writes with setdefault straight into os.environ, so without the swap a
    real CAREER_* in the developer's shell would decide the assertions, and the values
    these tests export would outlive them (monkeypatch only restores what it set)."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(body)
    monkeypatch.setattr(envfile, "ROOT", tmp_path)
    monkeypatch.setattr(os, "environ", {})


def test_missing_env_file_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(envfile, "ROOT", tmp_path)      # no config/.env at all
    envfile.load_env()                                  # a fresh clone must not crash


def test_parses_pairs_and_skips_comments_blanks_and_junk(tmp_path, monkeypatch):
    _write_env(tmp_path, monkeypatch, "\n".join([
        "# a comment", "", "  ", "CAREER_IMAP_PASS = app password ",
        "NO_EQUALS_SIGN", "CAREER_SMTP_PASS=pw2",
    ]))
    envfile.load_env()
    assert os.environ["CAREER_IMAP_PASS"] == "app password"   # key and value stripped
    assert os.environ["CAREER_SMTP_PASS"] == "pw2"


def test_value_keeps_inner_equals_signs(tmp_path, monkeypatch):
    _write_env(tmp_path, monkeypatch, "TOKEN=abc=def==")
    envfile.load_env()
    assert os.environ["TOKEN"] == "abc=def=="            # split on the FIRST = only


def test_already_exported_variable_wins(tmp_path, monkeypatch):
    _write_env(tmp_path, monkeypatch, "CAREER_IMAP_PASS=from-file")
    monkeypatch.setenv("CAREER_IMAP_PASS", "from-shell")
    envfile.load_env()
    assert os.environ["CAREER_IMAP_PASS"] == "from-shell"   # setdefault, never clobber
