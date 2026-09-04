"""One door to the mailbox for every mail feed — provider-agnostic on purpose.

Providers ([mail].provider in career.toml, default gmail — nothing changes for
existing installs):
  gmail    imap.gmail.com + app password (CAREER_IMAP_PASS)
  outlook  outlook.office365.com + OAuth device-code sign-in (feeds/outlook_auth)
  imap     any host (CAREER_IMAP_HOST or [mail].imap_host) + password

The privacy contract is identical everywhere: read-only connections, scoped
searches, local storage. Switching providers changes WHERE the mailbox lives
(e.g. a school Outlook account instead of personal Gmail), not what is read."""
import imaplib
import os

from feeds import outlook_auth

GMAIL_HOST = "imap.gmail.com"


class MailNotReady(Exception):
    """Provider not configured/connected — the reason is the user-facing text."""


def _imap_host(cfg) -> str:
    return (os.environ.get("CAREER_IMAP_HOST", "").strip()
            or (getattr(cfg, "mail_imap_host", "") or "").strip())


def ready(cfg) -> tuple[bool, str]:
    """(ok, reason-when-not). Reasons double as run_log / connector messages."""
    provider = getattr(cfg, "mail_provider", "gmail")
    if provider == "outlook":
        if not outlook_auth.client_id(cfg):
            return False, ("Outlook needs a client id — set [mail].outlook_client_id "
                           "(see SETUP.md)")
        if not outlook_auth.connected():
            return False, "Outlook not connected — sign in from the app (see SETUP.md)"
        return True, ""
    if provider == "imap" and not _imap_host(cfg):
        return False, "no IMAP host — set CAREER_IMAP_HOST or [mail].imap_host"
    if not os.environ.get("CAREER_IMAP_PASS"):
        # exact historical wording — dashboards and tests key on it
        return False, ("CAREER_IMAP_PASS missing — add a Gmail app password to "
                       "config/.env (see SETUP.md)")
    return True, ""


def connect(user: str, cfg, _imap=None):
    """Open + authenticate an IMAP session for the configured provider.
    `_imap` injects a fake in tests (host selection skipped, auth still runs)."""
    provider = getattr(cfg, "mail_provider", "gmail")
    ok, reason = ready(cfg)
    if not ok:
        raise MailNotReady(reason)
    if provider == "outlook":
        imap = _imap or imaplib.IMAP4_SSL(outlook_auth.IMAP_HOST)
        token = outlook_auth.get_access_token(outlook_auth.client_id(cfg))
        if not token:
            raise MailNotReady("Outlook sign-in expired or was revoked — "
                               "reconnect from the app")
        try:
            imap.authenticate("XOAUTH2", lambda _c: outlook_auth.xoauth2(user, token))
        except Exception:
            imap.logout()
            raise
        return imap
    host = GMAIL_HOST if provider == "gmail" else _imap_host(cfg)
    imap = _imap or imaplib.IMAP4_SSL(host)
    try:
        imap.login(user, os.environ["CAREER_IMAP_PASS"])
    except Exception:
        imap.logout()
        raise
    return imap
