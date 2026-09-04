"""Reply/outreach mail scan -> email_messages, contact_events, suggestions.

PRIVACY CONTRACT (binding; tests/test_mail_scan.py asserts it):
- Runs only after explicit consent (data/mail_scan_enabled marker via the app
  or wizard) AND [mail_scan] enabled (default true) AND an IMAP app password.
- INBOX is searched ONLY for mail FROM known ATS/LinkedIn notification hosts
  and FROM the domains of companies already worked in the tracker; the Sent
  folder ONLY for mail TO those tracked-company domains. Nothing else is ever
  downloaded, and every fetched message is re-verified in Python (IMAP search
  is a substring-ish prefilter, not the gate).
- Connections are read-only (readonly select + BODY.PEEK): no message is ever
  marked read, moved, or sent.
- Stored locally: headers, a verdict, and a <=200-char snippet. Bodies are
  never persisted.
- This feed NEVER writes opportunities.* — everything interpretive lands in
  `suggestions`, applied only when the user confirms in the app
  (career_inbox.actions.accept_suggestion).

Run: uv run python -m feeds.mail_scan [--dry-run]
Env (config/.env): CAREER_IMAP_USER (default = [email].to), CAREER_IMAP_PASS.
Writes: email_messages, contact_events, suggestions (create/expire),
company_domains (seed), run_log — never opportunities."""
import email
import email.policy
import email.utils
import hashlib
import imaplib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db  # noqa: E402
from career_hunt import config as ch_config  # noqa: E402
from career_hunt.mail_classify import (ATS_DOMAINS, LINKEDIN_SENDERS,  # noqa: E402
                                       body_text, candidate_domains, classify,
                                       is_ats_host, is_bulk, is_linkedin_host,
                                       registrable_domain)
from feeds.envfile import load_env  # noqa: E402

SKILL = "mail-scan"
CONSENT_MARKER = Path(__file__).resolve().parents[1] / "data" / "mail_scan_enabled"

# A worked row = the user has touched it; 'new' and 'dead' are excluded so the
# Sent fan-out stays bounded to companies actually in play.
WORKED = "('shortlisted','applied','interviewing','offer','rejected')"

VERDICT_TO_KIND = {"application_received": "set_applied",
                   "interview": "set_interviewing",
                   "offer": "set_offer",
                   "rejection": "set_rejected"}
# A suggestion is only useful while the row sits BEFORE the target stage; the
# same map gates creation and expires stale open suggestions.
ELIGIBLE = {"set_applied": ("new", "shortlisted"),
            "set_interviewing": ("new", "shortlisted", "applied"),
            "set_offer": ("new", "shortlisted", "applied", "interviewing"),
            "set_rejected": ("new", "shortlisted", "applied", "interviewing", "offer")}
CONTACT_VERDICTS = ("application_received", "interview", "offer", "rejection",
                    "human_reply", "linkedin_message")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sync_company_domains(conn) -> int:
    """Idempotent seed: derive mail domains from companies.website + posting
    URLs for every company with at least one opportunity. Never deletes."""
    rows = conn.execute(
        "SELECT c.id, c.website, GROUP_CONCAT(o.url, ' ') AS urls "
        "FROM companies c JOIN opportunities o ON o.company_id = c.id "
        "GROUP BY c.id").fetchall()
    added = 0
    for r in rows:
        site_dom = registrable_domain(r["website"] or "")
        for dom in candidate_domains(r["website"], (r["urls"] or "").split()):
            cur = conn.execute(
                "INSERT OR IGNORE INTO company_domains (company_id, domain, source, "
                "created_at) VALUES (?,?,?,?)",
                (r["id"], dom, "website" if dom == site_dom else "url", _now()))
            added += cur.rowcount
    conn.commit()
    return added


def pipeline_domains(conn) -> dict:
    """domain -> company_id for companies with >=1 worked opportunity."""
    rows = conn.execute(
        "SELECT DISTINCT cd.domain, cd.company_id FROM company_domains cd "
        "JOIN opportunities o ON o.company_id = cd.company_id "
        f"WHERE o.status IN {WORKED}").fetchall()
    return {r["domain"]: r["company_id"] for r in rows}


def _worked_companies(conn) -> list:
    return conn.execute(
        "SELECT DISTINCT c.id, c.name FROM companies c "
        "JOIN opportunities o ON o.company_id = c.id "
        f"WHERE o.status IN {WORKED}").fetchall()


def _expire_satisfied(conn) -> int:
    """Auto-dismiss open suggestions the user already handled by hand — manual
    control wins, and stale rows must not pile up in the review strip."""
    rows = conn.execute(
        "SELECT s.id, s.kind, o.status FROM suggestions s "
        "JOIN opportunities o ON o.id = s.opportunity_id "
        "WHERE s.status='open'").fetchall()
    n = 0
    for r in rows:
        if r["status"] not in ELIGIBLE.get(r["kind"], ()):
            conn.execute("UPDATE suggestions SET status='dismissed', resolved_at=? "
                         "WHERE id=?", (_now(), r["id"]))
            n += 1
    conn.commit()
    return n


def find_sent_folder(imap) -> str:
    """RFC 6154 \\Sent special-use flag (Gmail sends it), so localized folder
    names work; fall back to the en-US Gmail name."""
    try:
        _typ, boxes = imap.list()
        for b in boxes or []:
            line = b.decode(errors="replace") if isinstance(b, bytes) else str(b)
            if "\\Sent" in line:
                name = line.rsplit(' "/" ', 1)[-1].strip()
                return name if name.startswith('"') else f'"{name}"'
    except Exception:  # noqa: BLE001 — fall back rather than fail the scan
        pass
    return '"[Gmail]/Sent Mail"'


def _gm_msgid(data) -> str | None:
    blob = b" ".join(p if isinstance(p, bytes) else (p[0] or b"")
                     for p in (data or []) if p)
    m = re.search(rb"X-GM-MSGID (\d+)", blob)
    return m.group(1).decode() if m else None


def _raw_message(data) -> bytes | None:
    return next((p[1] for p in (data or [])
                 if isinstance(p, tuple) and len(p) > 1), None)


def _sent_at(msg) -> str:
    try:
        dt = email.utils.parsedate_to_datetime(msg.get("Date"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001 — a broken Date header falls back to now
        return _now()


def _seen(conn, key: str) -> bool:
    return conn.execute("SELECT 1 FROM email_messages WHERE dedupe_key=?",
                        (key,)).fetchone() is not None


def match_company(conn, from_domain, subject, body, domains) -> int | None:
    """Pipeline sender-domain hit wins; ATS/LinkedIn notifications fall back to
    whole-word company-name matching (subject first, then the body head; names
    shorter than 4 chars match the subject only). Ambiguity -> None."""
    if from_domain in domains:
        return domains[from_domain]
    hay_subject = (subject or "").lower()
    hay_body = (body or "")[:500].lower()
    hits = []
    for r in _worked_companies(conn):
        nm = (r["name"] or "").strip().lower()
        if not nm:
            continue
        pat = rf"(?<![a-z0-9]){re.escape(nm)}(?![a-z0-9])"
        if re.search(pat, hay_subject) or (len(nm) >= 4 and re.search(pat, hay_body)):
            hits.append(r["id"])
    return hits[0] if len(hits) == 1 else None


def match_opportunity(conn, company_id, subject) -> int | None:
    """Unique live opportunity, else role-title-in-subject; ambiguity -> None
    (the contact still records at company level; no suggestion)."""
    rows = conn.execute("SELECT id, role FROM opportunities WHERE company_id=? "
                        "AND status != 'dead'", (company_id,)).fetchall()
    if len(rows) == 1:
        return rows[0]["id"]
    subj = (subject or "").lower()
    hits = [r["id"] for r in rows if r["role"] and r["role"].lower() in subj]
    return hits[0] if len(hits) == 1 else None


def _record_message(conn, **fields) -> int | None:
    cur = conn.execute(
        "INSERT OR IGNORE INTO email_messages (dedupe_key, gm_msgid, message_id, "
        "folder, from_addr, to_addrs, subject, sent_at, matched_company_id, "
        "classification, processed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fields["key"], fields.get("gm"), fields.get("mid"), fields["folder"],
         fields.get("from_addr"), fields.get("to_addrs"), fields.get("subject"),
         fields.get("sent_at"), fields.get("company_id"), fields["verdict"], _now()))
    return cur.lastrowid if cur.rowcount else None


def _record_contact(conn, *, company_id, opportunity_id, direction, occurred_at,
                    subject, snippet, key) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO contact_events (company_id, opportunity_id, direction, "
        "channel, occurred_at, subject, snippet, message_id, created_by, created_at) "
        "VALUES (?,?,?,'email',?,?,?,?,'mail-scan',?)",
        (company_id, opportunity_id, direction, occurred_at, subject,
         (snippet or "").strip()[:200] or None, key, _now()))
    return cur.rowcount


def _maybe_suggest(conn, *, verdict, company_id, opportunity_id, msg_row_id,
                   from_addr, subject, sent_at) -> int:
    kind = VERDICT_TO_KIND.get(verdict)
    if not kind or not opportunity_id:
        return 0
    status = conn.execute("SELECT status FROM opportunities WHERE id=?",
                          (opportunity_id,)).fetchone()
    if not status or status["status"] not in ELIGIBLE[kind]:
        return 0
    if conn.execute("SELECT 1 FROM suggestions WHERE opportunity_id=? AND kind=? "
                    "AND status='open'", (opportunity_id, kind)).fetchone():
        return 0
    evidence = f"{from_addr or '?'} · {(subject or '')[:80]} · {(sent_at or '')[:10]}"
    conn.execute(
        "INSERT INTO suggestions (kind, opportunity_id, company_id, email_message_id, "
        "evidence, created_at) VALUES (?,?,?,?,?,?)",
        (kind, opportunity_id, company_id, msg_row_id, evidence, _now()))
    return 1


def _iter_messages(imap, criteria: str):
    """Yield (num, gm_msgid_or_None) for every message matching the search."""
    _typ, data = imap.search(None, criteria)
    for num in (data[0].split() if data and data[0] else []):
        gm = None
        try:
            _typ, mdata = imap.fetch(num, "(X-GM-MSGID)")
            gm = _gm_msgid(mdata)
        except Exception:  # noqa: BLE001 — non-Gmail servers lack the extension
            pass
        yield num, gm


def _fetch_message(imap, num):
    _typ, data = imap.fetch(num, "(BODY.PEEK[])")
    raw = _raw_message(data)
    if not raw:
        return None
    return email.message_from_bytes(raw, policy=email.policy.default)


def _dedupe_key(gm, msg) -> str:
    if gm:
        return f"gm:{gm}"
    mid = (msg.get("Message-ID") or "").strip()
    if mid:
        return f"mid:{mid}"
    blob = f"{msg.get('From', '')}|{msg.get('Subject', '')}|{msg.get('Date', '')}"
    return "sha:" + hashlib.sha256(blob.encode()).hexdigest()


def _inbox_pass(conn, imap, domains, own_addr, since, stats, dry_run):
    imap.select("INBOX", readonly=True)
    senders = sorted(ATS_DOMAINS | LINKEDIN_SENDERS) + sorted(domains)
    handled = set()
    for sender in senders:
        for num, gm in _iter_messages(imap, f'(FROM "{sender}" SINCE "{since}")'):
            if num in handled:
                continue
            handled.add(num)
            stats["inbox"] += 1
            if gm and _seen(conn, f"gm:{gm}"):
                continue
            msg = _fetch_message(imap, num)
            if msg is None:
                continue
            key = _dedupe_key(gm, msg)
            if _seen(conn, key):
                continue
            from_addr = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            if not from_addr or from_addr == own_addr:
                continue
            host = from_addr.rsplit("@", 1)[-1]
            from_dom = registrable_domain(host)
            is_ats = is_ats_host(host) or is_linkedin_host(host)
            is_pipe = from_dom in domains
            if not is_ats and not is_pipe:
                continue        # Python re-verification IS the gate
            subject = str(msg.get("Subject") or "")
            body = body_text(msg)
            bulk = is_bulk({k: msg.get(k) for k in ("List-Unsubscribe", "Precedence")})
            verdict = classify(subject, body, is_ats=is_ats, is_pipeline=is_pipe,
                               bulk=bulk)
            company_id = (domains.get(from_dom) if is_pipe
                          else match_company(conn, from_dom, subject, body, domains))
            if dry_run:
                stats["new_msgs"] += 1
                continue
            msg_row = _record_message(conn, key=key, gm=gm,
                                      mid=(msg.get("Message-ID") or "").strip() or None,
                                      folder="inbox", from_addr=from_addr,
                                      to_addrs=str(msg.get("To") or "") or None,
                                      subject=subject[:200], sent_at=_sent_at(msg),
                                      company_id=company_id, verdict=verdict)
            if msg_row is None:
                continue
            stats["new_msgs"] += 1
            if company_id and verdict in CONTACT_VERDICTS:
                opp = match_opportunity(conn, company_id, subject)
                stats["contacts"] += _record_contact(
                    conn, company_id=company_id, opportunity_id=opp,
                    direction="in", occurred_at=_sent_at(msg),
                    subject=subject[:200], snippet=body, key=key)
                stats["suggestions"] += _maybe_suggest(
                    conn, verdict=verdict, company_id=company_id,
                    opportunity_id=opp, msg_row_id=msg_row, from_addr=from_addr,
                    subject=subject, sent_at=_sent_at(msg))
            conn.commit()


def _sent_pass(conn, imap, domains, own_addr, since, stats, dry_run):
    imap.select(find_sent_folder(imap), readonly=True)
    handled = set()
    for dom in sorted(domains):
        for num, gm in _iter_messages(imap, f'(TO "{dom}" SINCE "{since}")'):
            if num in handled:
                continue
            handled.add(num)
            stats["sent"] += 1
            if gm and _seen(conn, f"gm:{gm}"):
                continue
            msg = _fetch_message(imap, num)
            if msg is None:
                continue
            key = _dedupe_key(gm, msg)
            if _seen(conn, key):
                continue
            addrs = [a.lower() for _n, a in
                     email.utils.getaddresses(msg.get_all("To", [])) if a]
            matched = {domains[d]: d for d in
                       {registrable_domain(a) for a in addrs if a != own_addr}
                       if d in domains}
            if not matched:
                continue        # re-verification: recipient must be a tracked company
            subject = str(msg.get("Subject") or "")
            if dry_run:
                stats["new_msgs"] += 1
                continue
            msg_row = _record_message(conn, key=key, gm=gm,
                                      mid=(msg.get("Message-ID") or "").strip() or None,
                                      folder="sent", from_addr=own_addr,
                                      to_addrs=", ".join(addrs)[:300],
                                      subject=subject[:200], sent_at=_sent_at(msg),
                                      company_id=next(iter(matched)),
                                      verdict="outbound")
            if msg_row is None:
                continue
            stats["new_msgs"] += 1
            body = body_text(msg)
            for cid in matched:
                opp = match_opportunity(conn, cid, subject)
                stats["contacts"] += _record_contact(
                    conn, company_id=cid, opportunity_id=opp, direction="out",
                    occurred_at=_sent_at(msg), subject=subject[:200],
                    snippet=body, key=f"{key}:c{cid}" if len(matched) > 1 else key)
            conn.commit()


def main(dry_run: bool = False, trigger: str = "manual", _imap=None):
    started = _now()
    load_env()
    cfg = ch_config.load()
    user = (os.environ.get("CAREER_IMAP_USER") or cfg.email.to or "").lower()
    password = os.environ.get("CAREER_IMAP_PASS")
    stats = {"inbox": 0, "sent": 0, "new_msgs": 0, "contacts": 0,
             "suggestions": 0, "expired": 0, "domains": 0, "new": 0}
    errors = []

    def _log(status, summary):
        if not dry_run:
            db.log_run(skill=SKILL, trigger=trigger, status=status,
                       summary=summary[:500], started_at=started,
                       finished_at=_now(), metrics_json=json.dumps(stats))

    if not cfg.mail_scan_enabled:
        msg = "disabled in config ([mail_scan] enabled = false)"
        _log("partial", msg)
        print(msg, file=sys.stderr)
        return stats
    if not password:
        msg = ("CAREER_IMAP_PASS missing — add a Gmail app password to "
               "config/.env (see SETUP.md)")
        _log("partial", msg)
        print(msg, file=sys.stderr)
        return stats
    conn = db.connect()
    try:
        if not dry_run:
            stats["domains"] = sync_company_domains(conn)
            stats["expired"] = _expire_satisfied(conn)
        domains = pipeline_domains(conn)
        domains.pop(registrable_domain(user or ""), None)   # own domain is never a company
        since = (date.today()
                 - timedelta(days=cfg.mail_scan_lookback_days)).strftime("%d-%b-%Y")
        imap = _imap or imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            imap.login(user, password)
        except Exception:
            imap.logout()
            raise
        try:
            try:
                _inbox_pass(conn, imap, domains, user, since, stats, dry_run)
            except Exception as e:  # noqa: BLE001 — one folder failing degrades, not kills
                errors.append(f"inbox: {type(e).__name__}: {e}"[:100])
            try:
                _sent_pass(conn, imap, domains, user, since, stats, dry_run)
            except Exception as e:  # noqa: BLE001
                errors.append(f"sent: {type(e).__name__}: {e}"[:100])
        finally:
            imap.logout()
    except Exception as e:
        _log("error", f"{type(e).__name__}: {e}"[:200])
        raise
    finally:
        conn.close()
    stats["new"] = stats["suggestions"]      # full_check prints ok:<new>new
    summary = (f"inbox={stats['inbox']} sent={stats['sent']} "
               f"new_msgs={stats['new_msgs']} contacts={stats['contacts']} "
               f"suggestions={stats['suggestions']} expired={stats['expired']} "
               f"domains={stats['domains']}")
    if errors:
        summary += " | errors: " + "; ".join(errors)
    _log("partial" if errors else "ok", summary)
    print(summary)
    return stats


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
