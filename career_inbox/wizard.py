"""First-run wizard core: turns simple choices into config/career.toml +
config/.env. Writes GITIGNORED files only. The emitted career.toml starts with
WIZARD_MARKER so re-runs are safe and /setup-personalized files are never
silently clobbered (WizardConflict without force=True)."""
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


def _union(lists):
    out = []
    for lst in lists:
        for x in lst:
            if x not in out:
                out.append(x)
    return out


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
    base_block = doc["role"]["exclude_companies"] if choices.get("startups_only", True) else []
    excludes = _union([base_block, avoid])
    # [role] and [scoring] lists are deliberate copies — keep in sync (see example)
    for block in ("role", "scoring"):
        doc[block]["profile_keywords"] = kws
        doc[block]["target_titles"] = titles
    doc["role"]["exclude_companies"] = excludes

    addr = (choices.get("email_address") or "").strip()
    if addr:
        doc["email"]["to"] = addr
        doc["email"]["smtp_user"] = addr
    return doc


def _write_env(addr: str, imap_pass: str) -> None:
    updates = {"CAREER_IMAP_USER": addr,
               "CAREER_IMAP_PASS": imap_pass.replace(" ", "")}
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    kept = [l for l in lines if l.split("=", 1)[0].strip() not in updates]
    kept += [f"{k}={v}" for k, v in updates.items()]
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(kept) + "\n")


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
    ch_config.USER_PATH.write_text(header + _emit(doc) + "\n")
    ch_config.load(ch_config.USER_PATH)       # emit must round-trip, or blow up now
    if (choices.get("email_address") or "").strip() and choices.get("imap_pass"):
        _write_env(choices["email_address"].strip(), choices["imap_pass"])
    return state()
