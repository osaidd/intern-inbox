"""Job-alert emails -> opportunities, via plain IMAP + Gmail app password.
Deliberately low-tech: no OAuth, no token expiry — the boards' own push channel.

Multi-sender: one IMAP session, a small registry of
(name, sender, parse, to_jobs) triples — LinkedIn (config [linkedin_mail]),
Built In and Wellfound (config [mail_sources], each flag-disable-able). Each
sender is fetched and parsed in isolation: one broken template or one IMAP
hiccup degrades that sender only, and the run still writes ONE run_log row.
The skill key stays 'linkedin-mail-pull' — dashboards filter on it; only the
printed summary names the individual senders.

Run: uv run python -m feeds.linkedin_mail_pull [--dry-run]
Env (config/.env): CAREER_IMAP_USER (default = [email].to), CAREER_IMAP_PASS (required).
Writes: opportunities, companies, run_log."""
import email
import email.policy
import imaplib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db  # noqa: E402
from career_hunt import config as ch_config  # noqa: E402
from career_hunt.emailer import maybe_send_digest  # noqa: E402
from career_hunt.score import matches  # noqa: E402
from career_hunt.sources import builtin_mail, linkedin_mail, wellfound_mail  # noqa: E402
from career_hunt.store import get_or_create_company, insert_job  # noqa: E402
from feeds.envfile import load_env  # noqa: E402

SKILL = "linkedin-mail-pull"   # historical key — dashboards filter on it, do NOT rename


def build_sources(cfg) -> list:
    """(name, sender, parse_alert_html, to_jobs) for every enabled alert sender."""
    sources = [("linkedin", cfg.linkedin_sender,
                linkedin_mail.parse_alert_html, linkedin_mail.to_jobs)]
    for name, ms, mod in (("builtin", cfg.mail_sources.builtin, builtin_mail),
                          ("wellfound", cfg.mail_sources.wellfound, wellfound_mail)):
        if ms.enabled:
            sources.append((name, ms.sender, mod.parse_alert_html, mod.to_jobs))
    return sources


def fetch_alert_htmls(imap, sender: str, lookback_days: int) -> list:
    """Return the text/html body of every alert email from `sender` in the window.
    `imap` is any object with select/search/fetch (imaplib or a test fake)."""
    imap.select("INBOX")
    since = (date.today() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    _, data = imap.search(None, f'(FROM "{sender}" SINCE "{since}")')
    htmls = []
    for num in (data[0].split() if data and data[0] else []):
        _, parts = imap.fetch(num, "(RFC822)")
        raw = next((p[1] for p in parts if isinstance(p, tuple) and len(p) > 1), None)
        if not raw:
            continue
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        body = msg.get_body(preferencelist=("html",))
        if body is not None:
            htmls.append(body.get_content())
    return htmls


def _ingest(conn, cfg, name, parse, to_jobs, htmls, stats, per, new_rows, dry_run):
    """Parse one sender's emails and store what passes the gates."""
    for html in htmls:
        cards = parse(html)
        jobs = to_jobs(cards)            # 1:1 with cards, in order (parser contract)
        for card, job in zip(cards, jobs):
            stats["found"] += 1
            per[name]["found"] += 1
            hint = card.get("headcount_hint")
            if hint and not dry_run and matches(job, cfg):
                # Wellfound prints the headcount range in the card — seed the company
                # row with it before insert_job creates a hint-less one. Gated on
                # matches() so a remote-only card never leaves an orphan company.
                get_or_create_company(conn, job.company,
                                      hints={"headcount": hint,
                                             "enrich_source": f"{name}-mail"})
            outcome, pri = insert_job(conn, job, cfg, dry_run=dry_run)
            if outcome == "new":
                stats["new"] += 1
                stats[pri] += 1
                per[name]["new"] += 1
                new_rows.append({"company": job.company, "role": job.role,
                                 "url": job.url, "priority": pri, "source": job.source})
            else:
                stats[outcome] += 1
                per[name][outcome] += 1


def main(dry_run: bool = False, trigger: str = "manual"):
    started = datetime.now().isoformat(timespec="seconds")
    load_env()
    cfg = ch_config.load()
    sources = build_sources(cfg)
    user = os.environ.get("CAREER_IMAP_USER", cfg.email.to)
    password = os.environ.get("CAREER_IMAP_PASS")
    stats = {"emails": 0, "found": 0, "new": 0, "dup": 0, "excluded": 0,
             "high": 0, "medium": 0, "low": 0}
    per = {n: {"emails": 0, "found": 0, "new": 0, "dup": 0, "excluded": 0}
           for n, *_ in sources}
    errors = []
    if not password:
        # documented not-yet-configured state, not a failure: 'partial' keeps the
        # weekly scheduled run from painting a false red error row (final-review fix)
        msg = "CAREER_IMAP_PASS missing — add a Gmail app password to config/.env (see SETUP.md)"
        if not dry_run:
            db.log_run(skill=SKILL, trigger=trigger, status="partial",
                       summary=msg, started_at=started,
                       finished_at=datetime.now().isoformat(timespec="seconds"),
                       metrics_json=json.dumps(stats))
        print(msg, file=sys.stderr)
        return stats
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            imap.login(user, password)
        except Exception:
            imap.logout()
            raise
        fetched = {}
        try:
            for name, sender, _, _ in sources:      # one session, per-sender search
                try:
                    fetched[name] = fetch_alert_htmls(imap, sender,
                                                      cfg.linkedin_lookback_days)
                    per[name]["emails"] = len(fetched[name])
                    stats["emails"] += len(fetched[name])
                except Exception as e:
                    errors.append(f"{name} fetch: {type(e).__name__}: {e}"[:100])
        finally:
            imap.logout()
        new_rows = []
        conn = db.connect()
        try:
            for name, _, parse, to_jobs in sources:
                if name not in fetched:
                    continue                    # its fetch already failed and was logged
                try:
                    _ingest(conn, cfg, name, parse, to_jobs, fetched[name],
                            stats, per, new_rows, dry_run)
                except Exception as e:
                    errors.append(f"{name} parse: {type(e).__name__}: {e}"[:100])
        finally:
            conn.close()
    except Exception as e:
        if not dry_run:
            db.log_run(skill=SKILL, trigger=trigger, status="error",
                       summary=f"{type(e).__name__}: {e}"[:200], started_at=started,
                       finished_at=datetime.now().isoformat(timespec="seconds"),
                       metrics_json=json.dumps(stats))
        raise
    if not dry_run and new_rows:
        maybe_send_digest(cfg, new_rows, SKILL)
    by_sender = " ".join(f"{n}={per[n]['new']}new/{per[n]['found']}found"
                         for n, *_ in sources)
    summary = (f"emails={stats['emails']} found={stats['found']} new={stats['new']} "
               f"dup={stats['dup']} excluded={stats['excluded']} "
               f"high={stats['high']} med={stats['medium']} low={stats['low']} "
               f"| {by_sender}")
    if errors:
        summary += " | errors: " + "; ".join(errors)
    if not dry_run:
        db.log_run(skill=SKILL, trigger=trigger,
                   status="partial" if errors else "ok",
                   summary=summary[:500], started_at=started,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   metrics_json=json.dumps({**stats, "sources": per}))
    print(summary)
    return stats


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
