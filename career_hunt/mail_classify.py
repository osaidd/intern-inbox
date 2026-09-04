# career_hunt/mail_classify.py
"""Pure classification + domain helpers for the mail scan. Stdlib only (re,
email, urllib.parse), no DB, no network — fully unit-testable. The feed
(feeds/mail_scan.py) owns IMAP and storage; this module owns the judgment calls:
which domains count as a company's, which senders are shared ATS/board hosts,
and what kind of email a subject+body is."""
import re
import urllib.parse

from .htmltext import extract_text

# Shared ATS notification hosts — matched as SENDERS in the inbox pass, and
# blocked from ever becoming a company's own domain. Note the tradeoff: a
# company that IS one of these (Rippling, Wellfound) can't be domain-matched;
# name-matching and the manual domain affordance cover that gap.
ATS_DOMAINS = frozenset({
    "greenhouse.io", "greenhouse-mail.io", "ashbyhq.com", "lever.co",
    "myworkday.com", "myworkdayjobs.com", "icims.com", "smartrecruiters.com",
    "jobvite.com", "bamboohr.com", "rippling.com", "dover.com", "wellfound.com",
    "workable.com", "workablemail.com", "successfactors.com", "taleo.net",
    "breezy.hr", "recruitee.com", "hire.google.com"})

# LinkedIn is the sanctioned notification channel (never fetched, only read as
# alert/notification mail) — a sender set of its own so the feed can treat it
# like an ATS without it ever becoming a company domain.
LINKEDIN_SENDERS = frozenset({"linkedin.com"})

_FREEMAIL = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "live.com", "icloud.com", "me.com", "proton.me", "protonmail.com",
    "aol.com", "msn.com"})

_BOARDS = frozenset({
    "linkedin.com", "indeed.com", "builtin.com", "builtinnyc.com",
    "simplify.jobs", "glassdoor.com", "ziprecruiter.com", "joinhandshake.com",
    "otta.com", "welcometothejungle.com", "monster.com", "ycombinator.com"})

DOMAIN_BLOCKLIST = frozenset(ATS_DOMAINS | _BOARDS | _FREEMAIL)

SECOND_LEVEL_TLDS = frozenset({"co.uk", "com.au", "co.jp", "com.br", "co.in",
                               "co.nz", "com.sg"})


def registrable_domain(host_or_email: str) -> str | None:
    """'Jobs <a@mail.Ramp.com>' -> 'ramp.com'; URLs and bare hosts work too."""
    s = (host_or_email or "").strip().lower()
    if not s:
        return None
    if "://" in s:
        s = urllib.parse.urlsplit(s).hostname or ""
    if "@" in s:
        s = s.rsplit("@", 1)[-1]
    s = s.strip("<>() ").split("/", 1)[0].strip(".")
    if not s or "." not in s or " " in s:
        return None
    parts = s.split(".")
    if any(not p for p in parts):
        return None
    if ".".join(parts[-2:]) in SECOND_LEVEL_TLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_blocked(host: str, extra: frozenset = frozenset()) -> bool:
    """Suffix match against the blocklist: 'no-reply@us.greenhouse.io' is blocked."""
    h = (host or "").lower().strip(".")
    return any(h == b or h.endswith("." + b) for b in DOMAIN_BLOCKLIST | extra)


def is_ats_host(host: str) -> bool:
    h = (host or "").lower().strip(".")
    return any(h == b or h.endswith("." + b) for b in ATS_DOMAINS)


def is_linkedin_host(host: str) -> bool:
    h = (host or "").lower().strip(".")
    return any(h == b or h.endswith("." + b) for b in LINKEDIN_SENDERS)


def candidate_domains(website: str | None, urls: list) -> set:
    """Seed domains for a company from its website + posting URLs. Shared
    ATS/board/freemail hosts never qualify — a Greenhouse posting URL must not
    make 'greenhouse.io' the company's mail domain."""
    out = set()
    for src in [website, *(urls or [])]:
        d = registrable_domain(src or "")
        if d and not is_blocked(d):
            out.add(d)
    return out


def is_bulk(headers) -> bool:
    """Marketing/list mail: present List-Unsubscribe or bulk/list Precedence."""
    h = {str(k).lower(): str(v or "") for k, v in dict(headers or {}).items()}
    if "list-unsubscribe" in h:
        return True
    return h.get("precedence", "").strip().lower() in ("bulk", "list", "junk")


def body_text(msg) -> str:
    """Readable text from an EmailMessage — plain part preferred, HTML stripped."""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        payload = part.get_content()
    except Exception:  # noqa: BLE001 — malformed mail yields no text, never a crash
        return ""
    if part.get_content_type() == "text/html":
        return extract_text(payload)
    return payload or ""


# Ordered, first match wins. Order is load-bearing: rejections mention
# interviews ("thank you for interviewing… not moving forward"), so rejection
# is checked first; offers mention interviews too.
_REJECT = re.compile(
    r"unfortunately|regret to inform|not (?:be )?moving forward"
    r"|(?:move|moving) forward with other|no longer under consideration"
    r"|pursue other (?:candidates|applicants)|not (?:been )?selected"
    r"|will not be progressing|decided not to (?:proceed|move forward)", re.I)
_OFFER = re.compile(
    r"offer letter|pleased to (?:extend|offer)|congratulations.{0,60}offer"
    r"|your offer (?:details|is|letter)", re.I | re.S)
_INTERVIEW = re.compile(
    r"interview|phone screen|schedule (?:a|some) time|your availability"
    r"|next (?:round|step)s?\b|take.?home|coding challenge|hackerrank|codesignal"
    r"|recruiter (?:call|chat|screen)", re.I)
_APPLIED = re.compile(
    r"thank(?:s| you) for (?:applying|your (?:application|interest))"
    r"|application (?:was |has been )?(?:received|submitted|sent to)"
    r"|we(?:'ve| have) received your application", re.I)
_LI_MESSAGE = re.compile(r"sent you a message|new message from|messaged you", re.I)


def classify(subject: str, body: str, *, is_ats: bool, is_pipeline: bool,
             bulk: bool) -> str:
    """Verdicts: rejection | offer | interview | application_received |
    linkedin_message | human_reply | other."""
    text = f"{subject or ''}\n{(body or '')[:4000]}"
    if _REJECT.search(text):
        return "rejection"
    if _OFFER.search(text):
        return "offer"
    if _INTERVIEW.search(text):
        return "interview"
    if _APPLIED.search(text):
        return "application_received"
    if _LI_MESSAGE.search(text):
        return "linkedin_message"
    if is_pipeline and not bulk:
        return "human_reply"
    return "other"
