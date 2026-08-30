# Frictionless install, publishing, and standalone identity — design

Date: 2026-08-30 · Status: approved (design conversation, this date)

## Context

intern-inbox is a local, private internship pipeline: shared Ashby/Greenhouse
boards + the user's own job-alert emails, gated to NYC/NJ internships, triaged
in a local web inbox. The public repo (github.com/osaidd/intern-inbox) already
has a one-command bootstrap, in-repo Claude Code skills, CI, and a clean
history (no personal data, no references to prior personal projects).

Verified on this date from a fresh public clone: `uv sync` succeeds, 128/128
tests pass, the server boots and serves the UI with zero config.

## Goal

Make installing, using, and adapting intern-inbox as close to zero-friction as
possible for a student peer on a fresh Mac or Windows machine, and make the
repo presentable enough to link publicly (LinkedIn). It remains a standalone
project — public copy broadens from "NOC New York students" to "students
hunting NYC/NJ internships," with NOC as the origin story.

## Non-goals

- No PyPI distribution (conflicts with the git-pull shared-boards model).
- No rename, no new repo, no LinkedIn post draft.
- No change to the NYC/NJ internships-only product gate or scoring model.
- No change to the user's local personal config semantics (career.toml,
  sources.local.toml, .env, profile/ stay gitignored and authoritative).

## Design

### 1. Identity
Keep the name and repo. Sweep public copy (README, SETUP, repo description,
pyproject description) to the broader audience framing; NOC New York appears as
origin story only. Scrub the one stale personal-history comment from the LOCAL
gitignored career.toml (not a public change).

### 2. Install + first-run wizard (the "normal app" path)
- First-run wizard: when `config/career.toml` is absent, the inbox redirects
  to `/welcome` — three plain-language steps: (1) role types via checkboxes,
  mapped to curated keyword/title preset bundles in a tracked
  `config/role_presets.toml`; (2) company filter — startups-only default vs.
  show-everything, plus optional avoid list; (3) job-alert email, optional and
  skippable — address + Gmail app password with the three Google steps inline.
  Finish writes `config/career.toml` (+ `config/.env` if given) — gitignored
  files ONLY — kicks off a first pull, lands on the inbox. "Skip for now"
  opens the inbox on shared defaults with a slim banner back to the wizard.
  Re-runnable from a settings link; rewrites only the blocks it owns and warns
  before touching a resume-personalized file (never clobbers /setup's work).
  Claude Code `/setup` remains the deep path (resume-derived keywords,
  profile.md for skills-gap); the wizard's closing note points there.
- `bootstrap.ps1`: Windows PowerShell mirror of bootstrap.sh — install uv if
  missing, clone (or ff-pull) into `~\intern-inbox`, `uv sync`. Both bootstrap
  scripts then hand off to `claude` if the CLI is on PATH, ELSE launch the app
  and open the browser at the wizard. One paste ends in a running product on
  both OSes.
- SETUP.md: the wizard becomes the documented no-Claude path; hand-editing
  `career.example.toml` is demoted to a power-user appendix. States plainly
  which features stay Claude-only (setup interview, opportunity-scan,
  skills-gap, pipeline-review, add-opportunity).

### 3. Demo GIF
`automation/seed_demo.py` writes ~15 plausible fake internship rows (invented
companies, no personal data) into the current checkout's own `data/inbox.db`
— it is meant to run inside a scratch clone, and it REFUSES to run if the
database already has rows, so it can never pollute a real inbox. Boot the app against it, record the real loop — Check now →
heart → X → move to Applied — into `docs/demo.gif` (target ≤ 3 MB, README-safe).
Seed script is committed so the GIF is reproducible.

### 4. README + social polish
GIF above the fold; broadened intro; badges (CI, MIT, Python 3.12+); quickstart
kept as the hero one-liner with the Windows paste beside it; Claude Code moves
from Requirements to Recommended (deep personalization + scans); GitHub repo
description updated via `gh repo edit`. Generate `docs/social-card.png`
(1280×640); uploading it is a manual web-UI step for the owner (GitHub has no
API for social preview) — hand over file + settings link.

### 5. Landing page
`docs/index.html`, single self-contained file (inline CSS, no external assets
beyond the sibling GIF/screenshot): hero + GIF, per-OS install command, what it
pulls, privacy story (local-only data), short FAQ, GitHub link. Served by
GitHub Pages from `main:/docs` at osaidd.github.io/intern-inbox. Enable Pages
via `gh api` during rollout.

### 6. Verification gates
- Fresh public clone → `uv sync` → `uv run pytest` (128 passing) → server boot
  HTTP 200, re-run after changes land.
- Wizard exercised end-to-end in a driven browser: unconfigured → redirect →
  three steps → career.toml/.env written (gitignored paths only) → first pull
  starts; configured → no redirect; skip path shows the banner.
- Route/unit tests for the wizard write path, the redirect rule, and the
  resume-personalized warning.
- Landing page and GIF opened and visually checked in a browser before push.
- bootstrap.ps1 reviewed line-by-line but NOT executed (no Windows host here);
  README notes nothing misleading about its tested status.
- Nothing pushes to the public repo until the implementation plan is approved.

## Acceptance criteria

1. A Mac peer with no Claude Code goes from nothing → personalized, pulling
   inbox with exactly: one paste → browser opens → 3-step wizard.
2. A Windows peer has the same single-paste path via bootstrap.ps1.
3. Claude Code layers resume-level personalization on top via /setup without
   conflicting with wizard-written config (block ownership + confirm).
4. Repo README leads with a moving demo; landing page live at the Pages URL.
5. No public file or copy references prior personal projects; broadened
   audience framing throughout.
6. Owner's local pipeline (config, data, daily loop) is unchanged and working.

## Risks

- GIF size vs. readability — mitigate by cropping to the list area and keeping
  it short; fall back to a shorter loop if > 3 MB.
- Pages enablement needs repo admin via gh; if the token lacks scope, owner
  clicks Settings → Pages → main /docs (documented as fallback).
- bootstrap.ps1 untested on real Windows — flagged in rollout notes; ask one
  Windows peer to confirm the paste before promoting it hard.
- Wizard and /setup both write career.toml — mitigated by block ownership
  (wizard owns [role]/[email]/blocklist edits it made), a marker comment
  recording the writer, and an explicit confirm before overwriting.
