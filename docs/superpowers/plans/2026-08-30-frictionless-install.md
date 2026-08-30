# Frictionless Install + Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-paste install that ends in a running app with a 3-step first-run wizard (no Claude Code required to start), plus demo GIF, README/social polish, and a GitHub Pages landing page.

**Architecture:** The wizard is a static page (`welcome.html` + `wizard.js`) served by the existing FastAPI/StaticFiles app, backed by two new JSON endpoints that write the gitignored `config/career.toml` / `config/.env` through a new pure-logic module `career_inbox/wizard.py`. Bootstrap scripts (sh + new ps1) end by launching the app with a new `--open` flag when the `claude` CLI is absent. Publishing assets (GIF, social card, landing page) live in `docs/`.

**Tech Stack:** Python 3.12+ (stdlib `tomllib`, no new runtime deps), FastAPI + vanilla JS (existing), pytest, uv. Pillow only ad-hoc via `uv run --with pillow` for GIF/card assembly (never a project dep).

## Global Constraints

- `requires-python = ">=3.12"`; everything runs via `uv` (`uv run pytest`, `uv run intern-inbox`).
- No new `[project.dependencies]` entries. Stdlib + existing FastAPI/uvicorn only.
- Personal files are gitignored and are the ONLY files the wizard may write: `config/career.toml`, `config/.env`. Never write personal values into tracked files.
- `[role]` and `[scoring]` keyword/title lists are deliberate copies — every writer keeps them in sync (career.example.toml documents this).
- Copy rules: no mention of prior personal projects anywhere; audience is "students hunting NYC/NJ internships"; NOC New York appears as origin story only; Claude Code is "Recommended", not "Required".
- A company whose size is UNKNOWN is never auto-dead; only confirmed over-cap (or late-stage with `allow_late_stages = false`) dies. Preset mappings must preserve `career_hunt/score.py::company_tier` semantics.
- Owner's local `config/career.toml` scoring values are untouched (hard cap 75 / Series B ≤50 stays).
- `docs/index.html` (landing page) must be fully self-contained: inline CSS, no external requests except sibling files `demo.gif` / `screenshot.png`.
- Nothing is pushed to `origin` until the final rollout task's checkpoint.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `allow_late_stages` config key

`company_tier` hard-kills `LATE_STAGES = ("series c", "series c+", "series d", "series e", "growth", "public", "acquired")` before reading config. The wizard's Mid/Any presets need a config way past that. Optional key, default false via `.get` — no existing career.toml (including the owner's) needs editing.

**Files:**
- Modify: `career_hunt/config.py` (CompanyRules dataclass + `load()`)
- Modify: `career_hunt/score.py` (`company_tier`, lines ~96-110)
- Modify: `config/career.example.toml` (`[company]` block)
- Test: `tests/test_career_score.py` (append), `tests/test_career_config.py` (append)

**Interfaces:**
- Consumes: existing `CompanyRules`, `company_tier(stage, headcount, cfg)`.
- Produces: `CompanyRules.allow_late_stages: bool` (default `False`) — Task 2's SIZE_PRESETS and Task 2's round-trip tests rely on this exact field name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_career_score.py`:

```python
def test_late_stage_dead_by_default(example_cfg):
    from career_hunt.score import company_tier
    assert company_tier("series c", 40, example_cfg) == "dead"


def test_allow_late_stages_lets_late_companies_through(example_cfg):
    from career_hunt.score import company_tier
    example_cfg.company.allow_late_stages = True
    # late stage no longer auto-dead; falls through to tier lists -> unknown
    assert company_tier("series c", 40, example_cfg) == "unknown"
    # but the hard cap still applies regardless of stage
    example_cfg.company.hard_cap_headcount = 100
    assert company_tier("series c", 5000, example_cfg) == "dead"
```

(`example_cfg` is the existing fixture pattern in this file — if the file instead builds configs via `config.load()`, follow its local convention and construct the same two asserts.)

Append to `tests/test_career_config.py`:

```python
def test_allow_late_stages_defaults_false():
    from career_hunt import config as ch_config
    cfg = ch_config.load(ch_config.EXAMPLE_PATH)
    assert cfg.company.allow_late_stages is False
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_career_score.py tests/test_career_config.py -q`
Expected: FAIL — `AttributeError: ... no attribute 'allow_late_stages'`.

- [ ] **Step 3: Implement**

`career_hunt/config.py` — add the field with a default so ALL existing constructions stay valid:

```python
@dataclass
class CompanyRules:
    tier1_stages: list
    tier1_max_headcount: int
    tier2_stages: list
    tier2_max_headcount: int
    hard_cap_headcount: int
    allow_late_stages: bool = False   # optional key: late-stage cos pass to tier logic
```

In `load()`, inside the `CompanyRules(...)` construction add:

```python
            allow_late_stages=c.get("allow_late_stages", False)),
```

`career_hunt/score.py::company_tier` — gate the kill:

```python
    if not cfg.company.allow_late_stages and any(st.startswith(l) for l in LATE_STAGES):
        return "dead"
```

`config/career.example.toml` `[company]` block — document it (commented-out default):

```toml
# Late-stage companies (series c+, public, …) are auto-dead by default. The
# first-run wizard's "Mid"/"Any size" choices set this true.
# allow_late_stages = false
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: 128 existing + new tests all pass.

- [ ] **Step 5: Commit**

```bash
git add career_hunt/config.py career_hunt/score.py config/career.example.toml tests/test_career_score.py tests/test_career_config.py
git commit -m "feat(config): optional allow_late_stages key — late-stage kill becomes configurable"
```

---

### Task 2: Role presets + wizard core logic (`career_inbox/wizard.py`)

Pure logic, no HTTP: preset loading, size mapping, TOML emit, config/env writes, state detection. This module is the ONLY thing that writes wizard config.

**Files:**
- Create: `config/role_presets.toml`
- Create: `career_inbox/wizard.py`
- Test: `tests/test_wizard.py`

**Interfaces:**
- Consumes: `career_hunt.config` module (`ch_config.USER_PATH`, `ch_config.EXAMPLE_PATH`, `ch_config.load`) — always referenced via the module object so test/conftest monkeypatching works.
- Produces (Task 3 depends on these exact signatures):
  - `wizard.state() -> dict` — `{"configured": bool, "wizard_written": bool}`
  - `wizard.load_presets() -> dict[str, dict]` — key → `{"label": str, "profile_keywords": [str], "target_titles": [str]}`
  - `wizard.apply(choices: dict, force: bool) -> dict` — validates, refuses (`raises WizardConflict`) when a non-wizard career.toml exists and `force` is false; writes career.toml (+ .env when email given); returns `state()`.
  - `wizard.WizardConflict(Exception)`
  - `wizard.SIZE_PRESETS: dict[str, dict]` with keys `tiny|small|mid|any`.
  - `choices` shape: `{"roles": [preset keys], "size": "tiny"|"small"|"mid"|"any"|"custom", "custom_cap": int|None, "startups_only": bool, "avoid": [str], "email_address": str, "imap_pass": str}`.

- [ ] **Step 1: Write `config/role_presets.toml`**

```toml
# Curated starter bundles for the first-run wizard. Each maps role checkboxes to
# the [role]/[scoring] keyword + title lists. /setup replaces these with
# resume-derived lists; the wizard just unions the chosen bundles.

[swe_ai]
label = "Software / AI Engineering"
profile_keywords = ["ai", "llm", "rag", "genai", "agent", "software", "backend", "frontend", "full stack", "python", "typescript", "infrastructure", "api"]
target_titles = ["software engineering intern", "engineering intern", "ai engineer intern", "ai engineering intern", "machine learning intern", "backend intern", "full stack intern"]

[product]
label = "Product"
profile_keywords = ["product", "roadmap", "user research", "prd", "analytics", "figma", "experimentation", "a/b"]
target_titles = ["product manager intern", "product management intern", "product intern", "apm intern", "product analyst intern"]

[data]
label = "Data"
profile_keywords = ["data", "sql", "python", "analytics", "dashboard", "etl", "pipeline", "statistics", "machine learning"]
target_titles = ["data analyst intern", "data science intern", "data engineering intern", "analytics intern", "business intelligence intern"]

[gtm_growth]
label = "GTM / Growth / Marketing"
profile_keywords = ["gtm", "growth", "marketing", "sales", "outbound", "content", "seo", "crm", "hubspot", "partnerships"]
target_titles = ["growth intern", "marketing intern", "gtm intern", "sales intern", "business development intern", "partnerships intern"]

[bizops]
label = "BizOps / Operations / Finance"
profile_keywords = ["operations", "bizops", "strategy", "finance", "fintech", "excel", "modeling", "process", "chief of staff"]
target_titles = ["business operations intern", "operations intern", "bizops intern", "strategy intern", "finance intern", "founders associate", "chief of staff intern"]
```

- [ ] **Step 2: Write the failing tests**

`tests/test_wizard.py`:

```python
"""Wizard core: preset mapping, TOML emit, write refusal. All writes go to
tmp paths via monkeypatched module constants — never the real config/."""
import tomllib

import pytest

from career_hunt import config as ch_config
from career_hunt.score import company_tier
from career_inbox import wizard


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    user = tmp_path / "career.toml"
    env = tmp_path / ".env"
    monkeypatch.setattr(ch_config, "USER_PATH", user)
    monkeypatch.setattr(wizard, "ENV_PATH", env)
    return user, env


BASE = {"roles": ["swe_ai"], "size": "tiny", "custom_cap": None,
        "startups_only": True, "avoid": [], "email_address": "", "imap_pass": ""}


def test_apply_writes_loadable_config_with_marker(paths):
    user, _ = paths
    st = wizard.apply(dict(BASE), force=False)
    assert st == {"configured": True, "wizard_written": True}
    assert user.read_text().startswith(wizard.WIZARD_MARKER)
    cfg = ch_config.load(user)                      # loader accepts the emit
    assert cfg.company.hard_cap_headcount == 50


@pytest.mark.parametrize("size,cap,late_tier", [
    ("tiny", 50, "dead"), ("small", 100, "dead"),
    ("mid", 500, "unknown"), ("any", 10**9, "unknown"),
])
def test_size_presets_map_to_tier_semantics(paths, size, cap, late_tier):
    user, _ = paths
    wizard.apply(dict(BASE, size=size), force=False)
    cfg = ch_config.load(user)
    assert cfg.company.hard_cap_headcount == cap
    assert company_tier("seed", None, cfg) == "tier1"          # unknown size never dead
    assert company_tier("seed", cap + 1, cfg) == "dead"        # confirmed over-cap dies
    assert company_tier("series c", 40, cfg) == late_tier      # late-stage rule per preset


def test_custom_cap(paths):
    user, _ = paths
    wizard.apply(dict(BASE, size="custom", custom_cap=70), force=False)
    cfg = ch_config.load(user)
    assert cfg.company.hard_cap_headcount == 70
    assert cfg.company.tier1_max_headcount == 70


def test_roles_union_dedupes_and_mirrors_scoring(paths):
    user, _ = paths
    wizard.apply(dict(BASE, roles=["swe_ai", "data"]), force=False)
    raw = tomllib.loads(user.read_text())
    assert raw["role"]["profile_keywords"] == raw["scoring"]["profile_keywords"]
    assert raw["role"]["target_titles"] == raw["scoring"]["target_titles"]
    kws = raw["role"]["profile_keywords"]
    assert "python" in kws and kws.count("python") == 1        # union, deduped


def test_show_everything_clears_blocklist_and_avoid_appends(paths):
    user, _ = paths
    wizard.apply(dict(BASE, startups_only=False, avoid=["BadCo"]), force=False)
    raw = tomllib.loads(user.read_text())
    assert raw["role"]["exclude_companies"] == ["BadCo"]


def test_email_written_to_config_and_env(paths):
    user, env = paths
    wizard.apply(dict(BASE, email_address="a@b.com", imap_pass="abcd efgh ijkl mnop"),
                 force=False)
    raw = tomllib.loads(user.read_text())
    assert raw["email"]["to"] == "a@b.com" and raw["email"]["smtp_user"] == "a@b.com"
    assert raw["email"]["enabled"] is False                    # digests stay off
    text = env.read_text()
    assert "CAREER_IMAP_PASS=abcdefghijklmnop" in text          # spaces stripped
    assert "CAREER_IMAP_USER=a@b.com" in text


def test_refuses_non_wizard_config_without_force(paths):
    user, _ = paths
    user.write_text("# hand-written by /setup\n[hunt]\n")
    with pytest.raises(wizard.WizardConflict):
        wizard.apply(dict(BASE), force=False)
    wizard.apply(dict(BASE), force=True)                       # explicit force wins
    assert user.read_text().startswith(wizard.WIZARD_MARKER)


def test_rerun_over_wizard_file_needs_no_force(paths):
    wizard.apply(dict(BASE), force=False)
    wizard.apply(dict(BASE, size="small"), force=False)        # no exception


def test_env_update_preserves_other_keys(paths):
    user, env = paths
    env.write_text("OTHER=1\nCAREER_IMAP_PASS=old\n")
    wizard.apply(dict(BASE, email_address="a@b.com", imap_pass="new"), force=False)
    text = env.read_text()
    assert "OTHER=1" in text and "CAREER_IMAP_PASS=new" in text
    assert "CAREER_IMAP_PASS=old" not in text


def test_validation_rejects_junk(paths):
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, roles=[]), force=False)
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, roles=["nope"]), force=False)
    with pytest.raises(ValueError):
        wizard.apply(dict(BASE, size="custom", custom_cap=3), force=False)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_wizard.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'career_inbox.wizard'` (or ImportError).

- [ ] **Step 4: Implement `career_inbox/wizard.py`**

```python
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
```

- [ ] **Step 5: Run the wizard tests**

Run: `uv run pytest tests/test_wizard.py -q`
Expected: PASS (all).

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add config/role_presets.toml career_inbox/wizard.py tests/test_wizard.py
git commit -m "feat(wizard): preset bundles + config writer — size gate maps 1:1 onto tier semantics"
```

---

### Task 3: Wizard API routes + unconfigured redirect

**Files:**
- Modify: `career_inbox/web.py` (three additions, all ABOVE the `StaticFiles` mount at the bottom)
- Test: `tests/test_wizard_api.py`

**Interfaces:**
- Consumes: `wizard.state()`, `wizard.load_presets()`, `wizard.apply(choices, force)`, `wizard.WizardConflict` from Task 2; existing `_require_json`, `STATIC`.
- Produces (Task 4's JS depends on these):
  - `GET /api/wizard/state` → `{"configured": bool, "wizard_written": bool, "presets": {key: {"label": ...}}, "sizes": ["tiny","small","mid","any"]}`
  - `POST /api/wizard/complete` (JSON body = `choices` + `"force": bool`) → 200 `state()` dict | 409 `{"detail": "..."}` on conflict | 422 on bad values
  - `GET /` → index.html when configured, 302 → `/welcome.html` when not.

- [ ] **Step 1: Write the failing tests**

`tests/test_wizard_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

import db
from career_hunt import config as ch_config
from career_inbox import wizard


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.migrate()
    monkeypatch.setattr(ch_config, "USER_PATH", tmp_path / "career.toml")
    monkeypatch.setattr(wizard, "ENV_PATH", tmp_path / ".env")
    from career_inbox.web import app
    return TestClient(app, base_url="http://127.0.0.1", follow_redirects=False)


BODY = {"roles": ["swe_ai"], "size": "tiny", "custom_cap": None,
        "startups_only": True, "avoid": [], "email_address": "",
        "imap_pass": "", "force": False}


def test_root_redirects_to_welcome_when_unconfigured(client):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["location"] == "/welcome.html"


def test_state_lists_presets(client):
    s = client.get("/api/wizard/state").json()
    assert s["configured"] is False
    assert s["presets"]["swe_ai"]["label"]
    assert s["sizes"] == ["tiny", "small", "mid", "any"]


def test_complete_writes_config_then_root_serves_app(client):
    r = client.post("/api/wizard/complete", json=BODY)
    assert r.status_code == 200 and r.json()["configured"] is True
    r = client.get("/")
    assert r.status_code == 200 and "Intern Inbox" in r.text


def test_complete_conflicts_on_foreign_config(client):
    ch_config.USER_PATH.write_text("# by /setup\n")
    assert client.post("/api/wizard/complete", json=BODY).status_code == 409
    ok = client.post("/api/wizard/complete", json=dict(BODY, force=True))
    assert ok.status_code == 200


def test_complete_validates(client):
    assert client.post("/api/wizard/complete",
                       json=dict(BODY, roles=[])).status_code == 422
    assert client.post("/api/wizard/complete",
                       json=dict(BODY, size="custom")).status_code == 422


def test_complete_requires_json_content_type(client):
    r = client.post("/api/wizard/complete", content=b"x=1",
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_wizard_api.py -q`
Expected: FAIL — 404s (routes missing) and `/` served by StaticFiles instead of redirect.

- [ ] **Step 3: Implement in `career_inbox/web.py`**

Add import near the other career_inbox imports: `from career_inbox import actions, pull, wizard`.

Add ABOVE the `STATIC = ...` mount block:

```python
@app.get("/api/wizard/state")
def wizard_state():
    s = wizard.state()
    s["presets"] = {k: {"label": v["label"]} for k, v in wizard.load_presets().items()}
    s["sizes"] = list(wizard.SIZE_PRESETS)
    return s


@app.post("/api/wizard/complete")
async def wizard_complete(request: Request):
    _require_json(request)
    body = await request.json()
    force = bool(body.pop("force", False))
    try:
        return wizard.apply(body, force=force)
    except wizard.WizardConflict as e:
        raise HTTPException(409, str(e))
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(422, str(e))


@app.get("/")
def root():
    from fastapi.responses import FileResponse, RedirectResponse
    if wizard.state()["configured"]:
        return FileResponse(STATIC / "index.html")
    return RedirectResponse("/welcome.html", status_code=302)
```

NOTE: `STATIC` is defined just below today — move the `STATIC = Path(__file__).parent / "static"` line ABOVE these routes so `root()` can reference it, keeping the mount itself at the bottom.

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `uv run pytest tests/test_wizard_api.py -q && uv run pytest -q`
Expected: PASS. (Watch for existing tests that GET `/` expecting the app page — the `client` fixtures pin `USER_PATH` to a nonexistent tmp file via conftest, so `/` now 302s for them. If any existing test asserts on `/`, update it to follow the redirect or set a wizard-written config first; do NOT weaken the redirect rule.)

- [ ] **Step 5: Commit**

```bash
git add career_inbox/web.py tests/test_wizard_api.py
git commit -m "feat(wizard): API routes + unconfigured root redirects to /welcome.html"
```

---

### Task 4: Wizard frontend + skip banner + re-run gear

**Files:**
- Create: `career_inbox/static/welcome.html`
- Create: `career_inbox/static/wizard.js`
- Modify: `career_inbox/static/app.css` (append wizard styles)
- Modify: `career_inbox/static/index.html` (gear button in header nav)
- Modify: `career_inbox/static/app.js` (boot-time banner when unconfigured)

**Interfaces:**
- Consumes: `GET /api/wizard/state`, `POST /api/wizard/complete`, `POST /api/pull` (existing, JSON content-type required), `GET /api/pull/status`.
- Produces: `/welcome.html` (linked from redirect, banner, and gear).

- [ ] **Step 1: `welcome.html`** — three-step single card, size gate as the headline control of step 2. Reuses app.css variables; only wizard-specific styles are added in Step 3.

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Welcome — Intern Inbox</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/app.css"></head>
<body class="wizard-body">
<main class="wizard">
  <h1>Intern Inbox</h1>
  <p class="sub">Three quick questions and your inbox starts filling with NYC/NJ internships. Everything stays on your computer.</p>

  <section class="wstep" id="step1">
    <h2><span class="wnum">1</span> What are you looking for?</h2>
    <p class="whint">Pick everything that applies — this seeds your keywords and rankings.</p>
    <div id="roleBoxes" class="wchoices"></div>
  </section>

  <section class="wstep" id="step2">
    <h2><span class="wnum">2</span> How big can the company be?</h2>
    <p class="whint">Listings from bigger companies are hidden or killed automatically. Sizes are confirmed as companies get enriched — an unconfirmed company is never dropped.</p>
    <div class="wchoices" id="sizeBoxes">
      <label class="wcard"><input type="radio" name="size" value="tiny" checked>
        <b>Tiny startups</b><span>up to ~50 people · pre-seed to Series A</span></label>
      <label class="wcard"><input type="radio" name="size" value="small">
        <b>Small startups</b><span>up to ~100 people · through Series B</span></label>
      <label class="wcard"><input type="radio" name="size" value="mid">
        <b>Mid-size too</b><span>up to ~500 people · any stage</span></label>
      <label class="wcard"><input type="radio" name="size" value="any">
        <b>Any size</b><span>show me everything</span></label>
      <label class="wcard"><input type="radio" name="size" value="custom">
        <b>Custom cap</b><span><input type="number" id="customCap" min="10" max="10000" placeholder="70"> people max</span></label>
    </div>
    <label class="wtoggle"><input type="checkbox" id="startupsOnly" checked>
      Hide big-name companies (Google, Goldman, Meta …) — uncheck to include them</label>
    <input id="avoid" type="text" placeholder="Companies to avoid, comma-separated (optional)">
  </section>

  <section class="wstep" id="step3">
    <h2><span class="wnum">3</span> Job-alert emails <span class="wopt">optional</span></h2>
    <p class="whint">The app can read LinkedIn/Built In/Wellfound job alerts out of your Gmail inbox. It uses a separate 16-character app password — your real password is never used. You can skip this and add it later.</p>
    <details class="wapppass"><summary>How to get the app password (1 minute)</summary>
      <ol>
        <li>Turn on 2-Step Verification: <a href="https://myaccount.google.com/security" target="_blank" rel="noopener">myaccount.google.com/security</a></li>
        <li>Create an app password named <code>intern-inbox</code>: <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener">myaccount.google.com/apppasswords</a></li>
        <li>Copy the 16-character code below (spaces don't matter).</li>
      </ol>
    </details>
    <input id="emailAddr" type="email" placeholder="you@gmail.com">
    <input id="imapPass" type="password" placeholder="16-character app password">
  </section>

  <div class="wactions">
    <button id="finish" class="deck">Start my inbox</button>
    <a id="skip" href="/index.html">Skip for now →</a>
  </div>
  <p class="wnote">Deeper personalization — rankings derived from your resume, market scans, skills-gap reports — comes from opening this folder in <a href="https://claude.com/claude-code" target="_blank" rel="noopener">Claude Code</a> and saying "set me up". Recommended, not required.</p>
  <p id="werr" class="werr" hidden></p>
</main>
<script src="/wizard.js"></script>
</body></html>
```

- [ ] **Step 2: `wizard.js`**

```javascript
// First-run wizard. State + presets come from the API; finish POSTs choices,
// kicks the first pull, then lands on the inbox.
const $ = (id) => document.getElementById(id);
let RERUN_NEEDS_FORCE = false;

async function boot() {
  const s = await (await fetch("/api/wizard/state")).json();
  RERUN_NEEDS_FORCE = s.configured && !s.wizard_written;
  const boxes = $("roleBoxes");
  for (const [key, p] of Object.entries(s.presets)) {
    const l = document.createElement("label");
    l.className = "wcard";
    l.innerHTML = `<input type="checkbox" value="${key}"><b>${p.label}</b>`;
    boxes.appendChild(l);
  }
  boxes.querySelector("input").checked = true;
  if (RERUN_NEEDS_FORCE)
    show("Heads up: your config was personalized by /setup. Finishing here replaces it.");
}

function show(msg) { const e = $("werr"); e.textContent = msg; e.hidden = false; }

function choices() {
  const roles = [...document.querySelectorAll("#roleBoxes input:checked")].map(i => i.value);
  const size = document.querySelector('input[name="size"]:checked').value;
  return {
    roles, size,
    custom_cap: size === "custom" ? parseInt($("customCap").value, 10) || null : null,
    startups_only: $("startupsOnly").checked,
    avoid: $("avoid").value.split(",").map(s => s.trim()).filter(Boolean),
    email_address: $("emailAddr").value.trim(),
    imap_pass: $("imapPass").value,
    force: RERUN_NEEDS_FORCE,
  };
}

$("finish").addEventListener("click", async () => {
  const c = choices();
  if (!c.roles.length) return show("Pick at least one role type.");
  if (c.size === "custom" && !c.custom_cap) return show("Enter a number for the custom cap.");
  if (RERUN_NEEDS_FORCE &&
      !confirm("Replace your /setup-personalized config with wizard settings?")) return;
  $("finish").disabled = true; $("finish").textContent = "Setting up…";
  const r = await fetch("/api/wizard/complete", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify(c)});
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    $("finish").disabled = false; $("finish").textContent = "Start my inbox";
    return show(d.detail || "Something went wrong — try again.");
  }
  // fire the first pull; the inbox shows its progress
  await fetch("/api/pull", {method: "POST",
    headers: {"content-type": "application/json"}, body: "{}"}).catch(() => {});
  location.href = "/";
});

boot();
```

- [ ] **Step 3: append wizard styles to `app.css`** — follow the file's existing variables/class conventions (`.deck`, `.sub`). Keep it modest (~60 lines): `.wizard` centered max-width 640px card; `.wchoices` as a responsive grid of `.wcard` labels with `:has(input:checked)` accent border; `.wtoggle`, `.whint`, `.wnum` circled step number; `.werr` in the app's alert color; inputs matching existing form styling. No new fonts, no external assets.

- [ ] **Step 4: gear + banner**

`index.html` — add to the header, after the Email ♥ button:

```html
<button id="prefs" class="deck" title="Preferences">⚙</button>
```

`app.js` — at boot (top-level init area), add:

```javascript
document.getElementById("prefs").onclick = () => location.href = "/welcome.html";
fetch("/api/wizard/state").then(r => r.json()).then(s => {
  if (s.configured) return;
  const b = document.createElement("div");
  b.id = "wizbanner";
  b.innerHTML = 'Running on shared defaults — <a href="/welcome.html">answer 3 questions</a> to personalize your rankings.';
  document.querySelector("header").after(b);
});
```

Append `#wizbanner` styling to `app.css` (accent-tinted strip, matches existing `.sub` typography).

- [ ] **Step 5: Run the suite, boot and eyeball**

Run: `uv run pytest -q` — expected: all pass (no JS under test).
Run: `uv run intern-inbox --port 8992` with repo config present → `/` serves app, gear visits wizard, conflict confirm appears (config exists and is not wizard-written). Then in a scratch clone (no config): `/` redirects, complete the wizard end-to-end in the driven browser, verify `career.toml` written + first pull kicks + inbox loads. This is the browser gate from the spec — do it now, not at rollout.

- [ ] **Step 6: Commit**

```bash
git add career_inbox/static/welcome.html career_inbox/static/wizard.js career_inbox/static/app.css career_inbox/static/index.html career_inbox/static/app.js
git commit -m "feat(wizard): 3-step welcome flow — size gate headline, skip banner, gear re-run"
```

---

### Task 5: `--open` flag + bootstrap no-Claude branch + `bootstrap.ps1`

**Files:**
- Modify: `career_inbox/__main__.py`
- Modify: `bootstrap.sh` (tail)
- Create: `bootstrap.ps1`

**Interfaces:**
- Produces: `uv run intern-inbox --open` (Task 7's README quickstart and both bootstrap tails rely on this exact flag).

- [ ] **Step 1: `--open` in `__main__.py`**

```python
"""Entry point: uv run intern-inbox [--port 8477] [--open]."""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8477)
    ap.add_argument("--open", action="store_true",
                    help="open the browser once the server is up")
    a = ap.parse_args()
    import uvicorn
    from career_inbox.web import app     # also puts the repo root on sys.path
    import db
    from feeds.envfile import load_env
    load_env()
    db.migrate()                         # first launch may predate /setup; no-op when current
    if a.open:
        import threading
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(
            f"http://127.0.0.1:{a.port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: bootstrap.sh tail** — replace the final `if command -v claude` block with:

```sh
# zero-friction handoff: Claude Code if it's here, otherwise straight into the app
if command -v claude >/dev/null 2>&1; then
  printf '\nFound Claude Code — opening the project in it now. Type /setup when it loads.\n'
  cd "$DIR" && exec claude
fi
printf '\nStarting Intern Inbox — your browser will open with a 3-step setup.\n'
printf 'To stop: Ctrl+C.  To start again later:  cd %s && uv run intern-inbox --open\n\n' "$DIR"
cd "$DIR" && exec uv run intern-inbox --open
```

- [ ] **Step 3: `bootstrap.ps1`**

```powershell
# intern-inbox bootstrap (Windows) — one paste from PowerShell to a running app.
#   irm https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.ps1 | iex
$ErrorActionPreference = "Stop"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "git is missing. Install it first:  winget install --id Git.Git -e"
  Write-Host "Then close this window, open a new PowerShell, and paste the command again."
  return
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv (the Python tool this project uses)..."
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$HOME\.local\bin;$env:Path"
}

$dir = Join-Path $HOME "intern-inbox"
if (Test-Path (Join-Path $dir ".git")) {
  Write-Host "Already cloned at $dir - pulling updates."
  git -C $dir pull --ff-only
} else {
  git clone https://github.com/osaidd/intern-inbox.git $dir
}

Set-Location $dir
Write-Host "Installing dependencies (well under a minute on a normal connection)..."
uv sync

if (Get-Command claude -ErrorAction SilentlyContinue) {
  Write-Host ""
  Write-Host "Found Claude Code - opening the project in it now. Type /setup when it loads."
  claude
} else {
  Write-Host ""
  Write-Host "Starting Intern Inbox - your browser will open with a 3-step setup."
  Write-Host "To stop: Ctrl+C.  To start again later:  cd $dir; uv run intern-inbox --open"
  uv run intern-inbox --open
}
```

- [ ] **Step 4: Verify what's verifiable here**

Run: `sh -n bootstrap.sh` (syntax) — expected: silent.
Run: `uv run intern-inbox --port 8993 --open` briefly on the Mac — browser opens to the app; Ctrl+C. Confirm `--help` shows both flags.
`bootstrap.ps1`: line-by-line review only — NO Windows host here. It stays honest in Task 7's docs ("tested on Mac; Windows script reviewed, first Windows tester welcome").

- [ ] **Step 5: Commit**

```bash
git add career_inbox/__main__.py bootstrap.sh bootstrap.ps1
git commit -m "feat(install): --open flag; both bootstraps end in a running product without Claude"
```

---

### Task 6: `automation/seed_demo.py`

Fake rows for the demo GIF. Refuses to touch a database that already has opportunities.

**Files:**
- Create: `automation/seed_demo.py`
- Test: `tests/test_seed_demo.py`

**Interfaces:**
- Consumes: `db.insert`, `db.migrate`, `db.DB_PATH`.
- Produces: `uv run python automation/seed_demo.py` (Task 8's GIF procedure runs this inside a scratch clone).

- [ ] **Step 1: Write the failing test**

`tests/test_seed_demo.py`:

```python
import pytest

import db
from automation import seed_demo


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    db.migrate()


def test_seeds_fifteen_new_rows(fresh):
    n = seed_demo.seed()
    conn = db.connect_ro()
    rows = conn.execute("SELECT status, priority, company FROM opportunities").fetchall()
    conn.close()
    assert n == len(rows) == 15
    assert {r["status"] for r in rows} == {"new"}
    assert any(r["priority"] == "high" for r in rows)


def test_refuses_nonempty_db(fresh):
    seed_demo.seed()
    with pytest.raises(SystemExit):
        seed_demo.seed()
```

(`automation/` has no `__init__.py` — if the import fails under pytest, add an empty `automation/__init__.py` and include it in the commit.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_seed_demo.py -q`
Expected: FAIL — no module `automation.seed_demo`.

- [ ] **Step 3: Implement `automation/seed_demo.py`**

```python
"""Demo data for the README GIF: 15 invented companies, no real people or
listings. REFUSES to run on a database that already has rows — run it inside a
scratch clone, never your real checkout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

ROWS = [
    # company, stage, headcount, area, role, priority, salary
    ("Loomcraft AI", "seed", 18, "SoHo", "AI Engineering Intern", "high", "$28-35/hr"),
    ("Fernwave", "series a", 42, "Flatiron", "Software Engineering Intern", "high", "$30/hr"),
    ("Copperline Labs", "seed", 11, "Dumbo", "Founders Associate Intern", "high", None),
    ("Quartz & Vine", "pre-seed", 6, "Williamsburg", "Growth Intern", "medium", None),
    ("Halyard Health AI", "series a", 55, "Union Square", "Product Management Intern", "high", "$32/hr"),
    ("Mosslight", "seed", 23, "Greenpoint", "Data Science Intern", "medium", "$26/hr"),
    ("Petrel Systems", "series b", 48, "FiDi", "Backend Engineering Intern", "medium", "$33/hr"),
    ("Juniper Yard", "seed", 15, "Long Island City", "BizOps Intern", "medium", None),
    ("Arcline Robotics", "series a", 61, "Brooklyn Navy Yard", "Robotics Software Intern", "medium", "$31/hr"),
    ("Novabranch", "seed", 9, "NoMad", "Full Stack Intern", "high", "$29/hr"),
    ("Tidegate Capital", "seed", 19, "Tribeca", "Fintech Product Intern", "medium", None),
    ("Emberfold", "pre-seed", 4, "East Village", "GTM Engineering Intern", "medium", None),
    ("Skylark Bio", "series a", 70, "Hudson Yards", "Data Engineering Intern", "low", "$27/hr"),
    ("Paperbark", "seed", 27, "Chelsea", "Product Design Intern", "low", None),
    ("Windrose Metrics", "series a", 38, "Midtown", "Analytics Intern", "medium", "$25/hr"),
]


def seed() -> int:
    conn = db.connect_ro() if db.DB_PATH.exists() else None
    if conn is not None:
        n = conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()["c"]
        conn.close()
        if n:
            raise SystemExit(f"refusing: database already has {n} opportunities "
                             "(run this in a scratch clone, not your real inbox)")
    for i, (co, stage, hc, area, role, pri, salary) in enumerate(ROWS, 1):
        cid = db.insert("companies", {
            "name": co, "name_key": co.lower(), "stage": stage, "headcount": hc,
            "enrich_status": "ok", "office_area": area})
        db.insert("opportunities", {
            "source": "ashby" if i % 3 else "github", "company": co, "role": role,
            "url": f"https://example.com/jobs/{i}", "location": "New York, NY",
            "status": "new", "priority": pri, "company_id": cid,
            "office_area": area, "work_mode": "hybrid" if i % 2 else "onsite",
            "salary_text": salary, "dedupe_hash": f"demo-{i}",
            "jd_text": f"{co} is hiring a {role.lower()} in {area}. Invented demo listing."})
    return len(ROWS)


if __name__ == "__main__":
    db.migrate()
    print(f"seeded {seed()} demo rows into {db.DB_PATH}")
```

(Column names come from `migrations/003_career_overhaul.sql` + 004/006. If `db.insert` or `connect_ro` signatures differ, follow `db.py` — but keep the refusal guard and row count exactly.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_seed_demo.py -q && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add automation/seed_demo.py tests/test_seed_demo.py
git commit -m "feat(demo): seed_demo — 15 invented rows for the README GIF, refuses non-empty dbs"
```

---

### Task 7: Copy sweep — README, SETUP, pyproject, CLAUDE.md, local scrub

**Files:**
- Modify: `README.md`, `SETUP.md`, `pyproject.toml` (description), `CLAUDE.md` (write-contract row + fresh-install note)
- Modify (LOCAL ONLY, never committed): `config/career.toml` — delete the `(migrated from osaid-os settings.toml [scoring])` comment fragment.

**Interfaces:** none produced; consumes `--open`, wizard, bootstrap.ps1 from Tasks 3-5.

- [ ] **Step 1: README.md rewrite** — keep total length close to current. Required content, in order:
  1. Title + one-liner: "A local, private internship pipeline for students hunting **NYC/NJ internships**. Company job boards + your own job-alert emails, triaged in one inbox on your laptop." Then the origin line: "Built for and battle-tested by the NOC New York cohort."
  2. Badges line under the title: CI (`https://github.com/osaidd/intern-inbox/actions/workflows/ci.yml/badge.svg`), MIT, Python 3.12+.
  3. `![Triage in action](docs/demo.gif)` above the fold (Task 8 produces the file; the reference lands now).
  4. Quickstart — Mac paste (`curl -LsSf https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.sh | sh`) and Windows paste (`irm https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.ps1 | iex`) side by side, then: "The app opens in your browser with a 3-step setup. That's the whole install."
  5. Requirements: a Mac or Windows machine, ~10 minutes. **Claude Code moves to a "Recommended" subsection**: what it adds (resume-derived rankings via `/setup`, `/opportunity-scan`, `/skills-gap`, `/pipeline-review`) and that nothing else requires it.
  6. Keep (lightly edited for the broader audience): What it pulls table, Privacy section verbatim promises, Contributing a board, After a week of data, macOS app icon note, License. The "for NOC New York students" phrasing goes origin-story everywhere it appears.
- [ ] **Step 2: SETUP.md** — restructure: §1 one-paste per OS (wizard path, screenshots optional), §2 the wizard explained (what each step writes, where files live, all gitignored), §3 Gmail app password (keep current text), §4 job alerts (keep), §5 daily loop (keep; add `--open`), §6 "Claude Code (recommended)" — /setup conversation, what it layers on; §7 power-user appendix: hand-edit `config/career.example.toml → config/career.toml` (move current manual-config prose here); §8 Windows notes + Troubleshooting (keep; add "wizard didn't open → visit http://127.0.0.1:8477/welcome.html"; add ps1 honesty note).
- [ ] **Step 3: pyproject.toml** description → `"Local internship pipeline for NYC/NJ-hunting students — ATS boards, job-alert email parsing, and a triage inbox"`.
- [ ] **Step 4: CLAUDE.md** — write-contract table row: `| career_inbox wizard (/welcome.html) | config/career.toml, config/.env (gitignored; WIZARD_MARKER header) |`. Update the "Fresh install? Take the wheel." note: the app now self-onboards via the wizard; Claude's fresh-install move becomes "offer /setup as the deeper personalization on top of wizard config".
- [ ] **Step 5: Local scrub (no commit)** — in `config/career.toml` line ~73, change `# --- ranking weights (migrated from osaid-os settings.toml [scoring]) ---` to `# --- ranking weights ---`. Verify: `grep -ri "osaid.os\|osaid_os" config/career.toml` → empty.
- [ ] **Step 6: Proofread gate** — `grep -rin "osaid.os\|NOC students only\|required.*Claude" README.md SETUP.md pyproject.toml` and read both docs top to bottom once; every Claude mention says recommended/optional except the skills sections.
- [ ] **Step 7: Commit**

```bash
git add README.md SETUP.md pyproject.toml CLAUDE.md
git commit -m "docs: wizard-first install story — Claude Code recommended, not required; broadened audience"
```

---

### Task 8: Demo GIF + social card

**Files:**
- Create: `docs/demo.gif` (committed binary, target ≤ 3 MB)
- Create: `automation/social_card.py` → `docs/social-card.png` (1280×640, committed)
- Modify: `docs/screenshot.png` — refresh from the seeded demo app so README/landing screenshots match current UI.

**Procedure (execution-time, in a scratch clone):**

- [ ] **Step 1: Stage the demo app**

```bash
cd "$SCRATCHPAD" && rm -rf demo && git clone /Users/osaid/Code/intern-inbox demo
cd demo && uv sync && uv run python automation/seed_demo.py
uv run intern-inbox --port 8990 &
```

- [ ] **Step 2: Record frames** — drive the in-app browser at `http://127.0.0.1:8990` (1280×800): load inbox → hover/click heart on 2 high rows → X a low row → open a detail pane → move one row to Applied → filter dropdown. Screenshot after each action into `frames/NN.png` (12-16 frames).
- [ ] **Step 3: Assemble** — `uv run --with pillow python` one-shot script: load frames in order, quantize (`convert("P", palette=ADAPTIVE, colors=128)`), `save("docs/demo.gif", save_all=True, append_images=..., duration=850, loop=0, optimize=True)`. Check `ls -la docs/demo.gif` ≤ 3 MB; if over: crop frames to the table area, drop to 96 colors, or cut frames — in that order.
- [ ] **Step 4: Social card** — `automation/social_card.py` (committed, ~50 lines, Pillow via `uv run --with pillow`): 1280×640, app-matching dark background, "Intern Inbox" + "NYC/NJ internships, triaged on your laptop" in Helvetica (`/System/Library/Fonts/Helvetica.ttc`), a cropped screenshot pasted right-half with a subtle border, the one-paste command in monospace at the bottom. Output `docs/social-card.png`. Eyeball it before committing.
- [ ] **Step 5: Kill the demo server, copy `demo.gif`/`social-card.png`/refreshed `screenshot.png` into the real checkout, verify README renders them (open in browser), commit**

```bash
git add docs/demo.gif docs/social-card.png docs/screenshot.png automation/social_card.py
git commit -m "docs: demo GIF from seeded data, social card, fresh screenshot"
```

---

### Task 9: Landing page `docs/index.html`

**Files:**
- Create: `docs/index.html` — fully self-contained (inline CSS; only sibling requests: `demo.gif`, `screenshot.png`, `social-card.png` as og:image).

**Content contract (all copy final here, design polish at execution):**

- [ ] **Step 1: Build the page** with exactly these sections:
  1. **Hero** — "Intern Inbox" / "Every NYC & NJ internship, in one inbox on your laptop." / `demo.gif` full-width / two copy-buttons: Mac paste + Windows paste (the Task 7 commands verbatim, click-to-copy via tiny inline JS `navigator.clipboard`).
  2. **How it works** — three cards: "Paste one command" / "Answer 3 questions" (size gate called out: "tell it 50 people max and bigger companies never reach you") / "Triage daily" (heart · kill · applied).
  3. **What it pulls** — the README table's four sources, one line each.
  4. **Private by design** — data local, SQLite, localhost, resume never leaves, gitignored personal layer.
  5. **Goes further with Claude Code** — recommended-not-required, names the four skills.
  6. **FAQ** — 5 items: need Claude? (no); need to code? (no); Windows? (yes, reviewed script + honesty note); big companies? (hidden by default, one checkbox); who made this? (origin story, GitHub link).
  7. Footer — GitHub repo link, MIT, "built by a NOC New York student".
  `<head>`: title "Intern Inbox — NYC/NJ internships, triaged on your laptop", meta description, `og:image` → `social-card.png`, favicon = inline 📥 SVG data URI.
- [ ] **Step 2: Design constraints** — match the app's look (dark, same accent family as app.css), system font stack, max-width 880px, responsive to 375px (single column, buttons full-width), `prefers-color-scheme` both honored, GIF `loading="lazy"` with width/height set.
- [ ] **Step 3: Verify** — open `docs/index.html` from disk in the browser at desktop AND 375px width; click both copy buttons; confirm zero external requests (devtools network).
- [ ] **Step 4: Commit**

```bash
git add docs/index.html
git commit -m "docs: self-contained landing page for GitHub Pages"
```

---

### Task 10: Full verification + rollout checkpoint

- [ ] **Step 1: Fresh-clone gate (local)**

```bash
cd "$SCRATCHPAD" && rm -rf verify && git clone /Users/osaid/Code/intern-inbox verify
cd verify && uv sync && uv run pytest -q
uv run intern-inbox --port 8994 & sleep 2
curl -sf http://127.0.0.1:8994/ -o /dev/null -w "%{http_code}\n"   # expect 302 (no config)
kill %1
```

- [ ] **Step 2: Wizard e2e in the driven browser** on that clone: complete all 3 steps → inbox loads → `config/career.toml` starts with the marker → re-open `/welcome.html` via gear → no confirm needed (wizard-written). Then `uv run pytest -q` one final time in the REAL checkout.
- [ ] **Step 3: Owner checkpoint — STOP and confirm with Osaid before this step.** Then:

```bash
git push origin main
gh repo edit osaidd/intern-inbox --description "Local internship pipeline for students hunting NYC/NJ internships — job boards + your alert emails, one triage inbox. Built for the NOC New York cohort."
gh api -X POST repos/osaidd/intern-inbox/pages -f "source[branch]=main" -f "source[path]=/docs" || echo "MANUAL: Settings → Pages → main /docs"
```

- [ ] **Step 4: Post-push checks** — CI green on GitHub; Pages URL `https://osaidd.github.io/intern-inbox/` renders (allow a few minutes); README GIF renders on the repo page; re-run the REAL one-paste `curl … | sh` in the scratchpad HOME-overridden (`HOME=$SCRATCHPAD/pastehome sh -c "curl -LsSf https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.sh | sh"` — expect clone+sync+app boot; Ctrl+C).
- [ ] **Step 5: Hand Osaid the two manual items** — upload `docs/social-card.png` at `https://github.com/osaidd/intern-inbox/settings` (Social preview) ~30s; ask one Windows peer to run the ps1 paste and report.

---

## Self-review (done at write time)

- **Spec coverage:** identity/copy → T7; wizard incl. size headline + presets-map-faithfully (criterion 7 → T2 parametrized test) → T1-T4; bootstrap per-OS ending in running product → T5; seed+GIF → T6/T8; README/social → T7/T8; landing page → T9; verification gates + rollout → T4 step 5, T10. Owner config untouched (T7 only deletes a comment).
- **Placeholders:** none — every code step carries real code; T8/T9 are content tasks with exact procedures/contracts.
- **Type consistency:** `wizard.apply(choices, force)` / `state()` / `WizardConflict` / `SIZE_PRESETS` names match across T2/T3/T4; `--open` matches T5/T7; `allow_late_stages` matches T1/T2.
