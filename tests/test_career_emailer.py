import os

from career_hunt import config as ch_config
from career_hunt.emailer import maybe_send_digest, render_digest

CFG = ch_config.load(ch_config.DEFAULT_PATH)
ROWS = [{"company": "Solva", "role": "AI Intern", "url": "https://x.co/1",
         "priority": "high", "source": "linkedin-mail"},
        {"company": "Tessera", "role": "PM Intern", "url": None,
         "priority": "medium", "source": "github"}]


def test_render_digest_contains_rows():
    html = render_digest(ROWS)
    assert "Solva" in html and "https://x.co/1" in html and "medium" in html


def test_no_send_without_high(monkeypatch):
    monkeypatch.setenv("CAREER_SMTP_PASS", "x")
    only_med = [r | {"priority": "medium"} for r in ROWS]
    assert maybe_send_digest(CFG, only_med, "test") is False


def test_no_send_without_pass(monkeypatch):
    monkeypatch.delenv("CAREER_SMTP_PASS", raising=False)
    assert maybe_send_digest(CFG, ROWS, "test") is False
