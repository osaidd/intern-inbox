"""Digest email: Gmail SMTP + app password, HTML table, sent only when a run lands
≥1 HIGH role. Failure never breaks the feed run."""
import html
import os
import smtplib
import sys
from email.mime.text import MIMEText

from .config import Config, EmailConfig


class EmailError(Exception):
    pass


def render_digest(rows: list) -> str:
    def cell(r):
        role = html.escape(r["role"])
        link = f'<a href="{html.escape(r["url"])}">{role}</a>' if r.get("url") else role
        return (f"<tr><td><b>{html.escape(r['company'])}</b></td><td>{link}</td>"
                f"<td>{r['priority']}</td><td>{r['source']}</td></tr>")
    body = "".join(cell(r) for r in sorted(
        rows, key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r["priority"], 3)))
    return ("<h3>Career hunt — new roles</h3>"
            "<table border='0' cellpadding='6'>"
            "<tr><th align='left'>Company</th><th align='left'>Role</th>"
            "<th align='left'>Priority</th><th align='left'>Source</th></tr>"
            f"{body}</table>")


def send(email_cfg: EmailConfig, subject: str, html_body: str, _smtp=None) -> None:
    password = os.environ.get("CAREER_SMTP_PASS")
    if not password:
        raise EmailError("CAREER_SMTP_PASS not set")
    msg = MIMEText(html_body, "html")
    msg["Subject"], msg["From"], msg["To"] = subject, email_cfg.smtp_user, email_cfg.to
    smtp_cls = _smtp or smtplib.SMTP
    try:
        with smtp_cls(email_cfg.smtp_host, email_cfg.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(email_cfg.smtp_user, password)
            s.send_message(msg)
    except Exception as e:  # noqa: BLE001
        raise EmailError(str(e)) from e


def maybe_send_digest(cfg: Config, new_rows: list, skill: str) -> bool:
    high = [r for r in new_rows if r["priority"] == "high"]
    if not high or not cfg.email.enabled or not os.environ.get("CAREER_SMTP_PASS"):
        return False
    subject = f"Intern Inbox: {len(new_rows)} new ({len(high)} high) — {skill}"
    try:
        send(cfg.email, subject, render_digest(new_rows))
        return True
    except EmailError as e:
        print(f"digest email failed (run continues): {e}", file=sys.stderr)
        return False
