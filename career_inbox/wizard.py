"""First-run wizard core: turns simple choices into config/career.toml +
config/.env. Writes GITIGNORED files only. The emitted career.toml starts with
WIZARD_MARKER so re-runs are safe and /setup-personalized files are never
silently clobbered (WizardConflict without force=True)."""
import os
import tomllib
from pathlib import Path

from career_hunt import config as ch_config

ROOT = Path(__file__).resolve().parent.parent
PRESETS_PATH = ROOT / "config" / "role_presets.toml"
ENV_PATH = ROOT / "config" / ".env"
WIZARD_MARKER = "# written-by: intern-inbox-wizard"

# Every preset keeps company_tier's semantics: unknown size passes, confirmed
# over-cap dies. tiny/small keep the late-stage auto-kill; mid/any disable it.
SIZE_PRESETS = {
    "tiny":  dict(cap=50,    allow_late=False),
    "small": dict(cap=100,   allow_late=False),
    "mid":   dict(cap=500,   allow_late=True),
    "any":   dict(cap=10**9, allow_late=True),
}


class WizardConflict(Exception):
    """career.toml exists and was not written by the wizard."""


def load_presets() -> dict:
    with open(PRESETS_PATH, "rb") as f:
        return tomllib.load(f)


def state() -> dict:
    p = ch_config.USER_PATH
    configured = p.exists()
    wizard_written = configured and p.read_text().startswith(WIZARD_MARKER)
    return {"configured": configured, "wizard_written": wizard_written}


def prefill() -> dict | None:
    """Invert the current career.toml back into wizard answers so the gear
    re-run opens pre-filled instead of blank. Exact for wizard-written configs
    (the emit is a pure union); best-effort for /setup ones; None when there is
    no config or it doesn't parse. Secrets never leave the server: imap_saved
    is a bool, never the value."""
    p = ch_config.USER_PATH
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            raw = tomllib.load(f)
        with open(ch_config.EXAMPLE_PATH, "rb") as f:
            example = tomllib.load(f)
        presets = load_presets()
        titles = set(raw["role"]["target_titles"])
        roles = [k for k, pr in presets.items()
                 if set(pr["target_titles"]) <= titles]
        cap = raw["company"]["hard_cap_headcount"]
        allow_late = raw["company"].get("allow_late_stages", False)
        size = next((k for k, r in SIZE_PRESETS.items()
                     if r["cap"] == cap and r["allow_late"] == allow_late), "custom")
        excludes = raw["role"]["exclude_companies"]
        base = example["role"]["exclude_companies"]
        startups_only = set(base) <= set(excludes)
        avoid = ([x for x in excludes if x not in base] if startups_only
                 else list(excludes))
        imap_saved = False
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "CAREER_IMAP_PASS" and v.strip():
                    imap_saved = True
        from career_inbox.pull import MAIL_CONSENT
        from feeds import outlook_auth
        return {"roles": roles, "size": size,
                "custom_cap": cap if size == "custom" else None,
                "startups_only": startups_only, "avoid": avoid,
                "email_address": raw["email"]["to"], "imap_saved": imap_saved,
                "provider": raw.get("mail", {}).get("provider", "gmail"),
                "imap_host": raw.get("mail", {}).get("imap_host", ""),
                "outlook_connected": outlook_auth.connected(),
                "mail_scan": MAIL_CONSENT.exists()}
    except Exception:  # noqa: BLE001 — foreign/broken configs prefill best-effort or not at all
        return None


def _union(lists):
    out = []
    for lst in lists:
        for x in lst:
            if x not in out:
                out.append(x)
    return out


def _has_control_char(s: str) -> bool:
    """True if s contains a raw control character (e.g. \\n, \\t, \\r) — those
    are never escaped by _toml_value and would corrupt the emitted file."""
    return any(ord(c) < 32 for c in s)


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value: {type(v)}")


def _emit(doc: dict, prefix="") -> str:
    """Emit nested dicts as TOML tables. Scalars/lists first, then subtables —
    matches tomllib round-trip for this config's two-level shape."""
    lines, tables = [], []
    for k, v in doc.items():
        if isinstance(v, dict):
            tables.append(k)
        else:
            lines.append(f"{k} = {_toml_value(v)}")
    out = "\n".join(lines)
    for k in tables:
        name = f"{prefix}{k}"
        out += f"\n\n[{name}]\n" + _emit(doc[k], prefix=name + ".")
    return out


def _build(choices: dict) -> dict:
    presets = load_presets()
    roles = choices.get("roles") or []
    if not roles or any(r not in presets for r in roles):
        raise ValueError("roles must be a non-empty list of known preset keys")
    size = choices.get("size")
    if size == "custom":
        cap = choices.get("custom_cap")
        if not isinstance(cap, int) or not (10 <= cap <= 10000):
            raise ValueError("custom_cap must be an int between 10 and 10000")
        rules = dict(cap=cap, allow_late=False)
    elif size in SIZE_PRESETS:
        rules = SIZE_PRESETS[size]
    else:
        raise ValueError(f"unknown size: {size!r}")

    with open(ch_config.EXAMPLE_PATH, "rb") as f:
        doc = tomllib.load(f)

    doc["company"]["tier1_max_headcount"] = rules["cap"]
    doc["company"]["tier2_max_headcount"] = rules["cap"]
    doc["company"]["hard_cap_headcount"] = rules["cap"]
    doc["company"]["allow_late_stages"] = rules["allow_late"]

    kws = _union([presets[r]["profile_keywords"] for r in roles])
    titles = _union([presets[r]["target_titles"] for r in roles])
    avoid = [a.strip() for a in choices.get("avoid", []) if a.strip()]
    if any(_has_control_char(a) for a in avoid):
        raise ValueError("avoid entries must not contain control characters")
    base_block = doc["role"]["exclude_companies"] if choices.get("startups_only", True) else []
    excludes = _union([base_block, avoid])
    # [role] and [scoring] lists are deliberate copies — keep in sync (see example)
    for block in ("role", "scoring"):
        doc[block]["profile_keywords"] = kws
        doc[block]["target_titles"] = titles
    doc["role"]["exclude_companies"] = excludes

    addr = (choices.get("email_address") or "").strip()
    if addr and _has_control_char(addr):
        raise ValueError("email_address must not contain control characters")
    if addr:
        doc["email"]["to"] = addr
        doc["email"]["smtp_user"] = addr

    provider = choices.get("provider", "gmail")
    if provider not in ("gmail", "outlook", "imap"):
        raise ValueError(f"unknown mail provider: {provider!r}")
    host = (choices.get("imap_host") or "").strip()
    if host and _has_control_char(host):
        raise ValueError("imap_host must not contain control characters")
    if provider == "imap" and not host:
        raise ValueError("the IMAP option needs a host (e.g. imap.yourschool.edu)")
    doc.setdefault("mail", {})
    doc["mail"]["provider"] = provider
    if provider == "imap":
        doc["mail"]["imap_host"] = host
    return doc


def _write_env(addr: str, imap_pass: str, host: str = "") -> None:
    """Upsert CAREER_IMAP_USER whenever addr is given. CAREER_IMAP_PASS is only
    touched when a non-empty imap_pass is given — an address-only re-run (e.g.
    changing the email without re-entering the app password) must never delete
    a previously-saved password.

    Also mirrors the same keys into os.environ. feeds/envfile.py's load_env()
    uses setdefault, so it only ever seeds os.environ once at boot — without
    this, a credential rotated via a gear re-run would sit correctly in the
    file while the already-running process kept using its stale, possibly
    revoked, in-memory value until a restart."""
    updates = {"CAREER_IMAP_USER": addr}
    if imap_pass:
        updates["CAREER_IMAP_PASS"] = imap_pass.replace(" ", "")
    if host:
        updates["CAREER_IMAP_HOST"] = host
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    kept = [l for l in lines if l.split("=", 1)[0].strip() not in updates]
    kept += [f"{k}={v}" for k, v in updates.items()]
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(kept) + "\n")
    for k, v in updates.items():
        os.environ[k] = v


def apply(choices: dict, force: bool) -> dict:
    st = state()
    if st["configured"] and not st["wizard_written"] and not force:
        raise WizardConflict("config/career.toml was personalized outside the "
                            "wizard (/setup or by hand) — confirm overwrite")
    doc = _build(choices)                     # validate BEFORE any write
    header = (f"{WIZARD_MARKER}\n"
              "# Re-running the wizard rewrites this file. /setup (Claude Code)\n"
              "# replaces it with resume-derived personalization.\n\n")
    ch_config.USER_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Validate-then-swap: emit to a sibling temp file, confirm it loads, only
    # THEN replace the real config atomically. A failure here (or any future
    # gap in _toml_value's escaping) must never leave a half-written or
    # unparseable career.toml in place of a working one.
    staging = ch_config.USER_PATH.with_name("career.toml.tmp")
    try:
        staging.write_text(header + _emit(doc) + "\n")
        ch_config.load(staging)                # emit must round-trip, or blow up now
        os.replace(staging, ch_config.USER_PATH)   # atomic swap, only after validation
    finally:
        staging.unlink(missing_ok=True)         # no-op once swapped; cleans up on failure
    addr = (choices.get("email_address") or "").strip()
    if addr:
        host = ((choices.get("imap_host") or "").strip()
                if choices.get("provider") == "imap" else "")
        _write_env(addr, choices.get("imap_pass") or "", host=host)
    # Reply-scan consent: the checkbox IS the truth when present — checked
    # writes the marker, unchecked on a re-run removes it. Absent key (older
    # clients, tests) leaves consent untouched.
    if "mail_scan" in choices:
        from datetime import datetime

        from career_inbox.pull import MAIL_CONSENT
        if choices.get("mail_scan"):
            MAIL_CONSENT.parent.mkdir(parents=True, exist_ok=True)
            MAIL_CONSENT.write_text(datetime.now().isoformat(timespec="seconds"))
        else:
            MAIL_CONSENT.unlink(missing_ok=True)
    return state()
