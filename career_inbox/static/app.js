/* career-inbox — UI core (Task 6). Ports the rental-inbox architecture:
   one state object S, a client-side applyFilters() pipeline, render()/renderHead(),
   URL-hash sync (readHash on load, syncHash on every change via replaceState),
   debounced search, sortable headers. Status filter refetches (statuses param);
   every other filter, search, and sort is client-side over the loaded rows.

   Scope: table / filters / search / sort / hash / header-counts / empty-states.
   Row actions, bulk bar, notes editing, detail panel, map render, CSV/Email/Check
   land in Tasks 7 & 8 — their controls are wired into the DOM here but stubbed. */
"use strict";

const $ = (id) => document.getElementById(id);
const TODAY = new Date().toISOString().slice(0, 10);

/* status filter option → API `statuses` param value */
const STATUS_OPTS = [
  ["live", "Live"], ["new", "New"], ["shortlisted", "Shortlisted"],
  ["applied", "Applied"], ["interviewing", "Interviewing"], ["offer", "Offer"],
  ["rejected", "Rejected"], ["dead", "Dead"], ["all", "All"],
];
const PRI_RANK = { high: 0, medium: 1, low: 2 };
const LIVE_SET = new Set(["new", "shortlisted", "applied", "interviewing"]);
/* sources that live on the ATS page; everything else (mail feeds, boards,
   browser, manual) stays on the Inbox page — the two never mix in one view */
const ATS_SOURCES = new Set(["ashby", "greenhouse"]);
/* full funnel — used by the row select + detail panel button row */
const FUNNEL = [
  ["new", "New"], ["shortlisted", "Shortlisted"], ["applied", "Applied"],
  ["interviewing", "Interviewing"], ["offer", "Offer"], ["rejected", "Rejected"],
  ["dead", "Dead"],
];

/* ---------------- state ---------------- */
const S = {
  rows: [],            // rows for the current status filter (server-fetched)
  page: "inbox",       // "inbox" | "ats" — hard partition by source (never mixed)
  meta: null,          // /api/meta payload
  filters: { s: "live", q: "", pri: "all", fam: "all", stg: "all",
             mode: "all", src: "all" },
  sort: { key: "priority", dir: "asc" },   // default: priority rank, score desc
  view: "table",
  stripOpen: true,     // map strip expanded (table view); collapsed state in hash
  offices: null,       // /api/offices cache (invalidated after a pull)
  pullRunning: false,  // a Check-now pull is in flight (auto-refresh guard)
  sel: new Set(),      // selected row ids (bulk)
  detailId: null,      // open detail row id
  detailJob: null,     // full /api/jobs/{id} payload for the open panel
  shownIds: [],        // ids currently rendered (for select-all-shown)
};

/* career.jsx priority tokens — office pin fill by priority */
const OFFICE_COLORS = { high: "#7fc484", medium: "#d8a75c", low: "#8f8e8a" };
const coKey = (name) => (name == null ? "" : String(name)).trim().toLowerCase();

/* leaflet map singletons (one visible map at a time: strip OR full) */
let MAP = null;
let MARKERS = {};        // company key -> circleMarker on the current map
let pullTimer = null;    // /api/pull/status poll handle
let toastTimer = null;

/* ---------------- helpers ---------------- */
const norm = (v) => (v == null ? "" : String(v)).toLowerCase();
/* the internships-only red line is enforced at ingest (parser + feed re-check —
   a row may qualify via JD text or an 'Intern' type label the UI can't see, so
   no title-based hiding here); the page split is purely by source */
const pageMatch = (r) => (S.page === "ats") === ATS_SOURCES.has(r.source);

function ageDays(r) {
  const d = r.posted_date || r.discovered_date;
  if (!d) return null;
  const ms = Date.parse(TODAY) - Date.parse(d);
  return Number.isFinite(ms) ? Math.max(0, Math.round(ms / 86400000)) : null;
}
function staleDays(r) {
  const basis = r.last_seen || r.discovered_date;
  if (!basis) return null;
  const ms = Date.parse(TODAY) - Date.parse(basis);
  return Number.isFinite(ms) ? Math.round(ms / 86400000) : null;
}
const modeLabel = (r) =>
  (!r.work_mode || r.work_mode === "unknown") ? "" : r.work_mode;
const isHttps = (u) => typeof u === "string" && /^https:\/\//i.test(u);

/* true if `status` still belongs in the active status filter (drives optimistic
   drop-from-view after a row action — no refetch needed) */
function statusInView(status) {
  const s = S.filters.s;
  if (s === "all") return true;
  if (s === "live") return LIVE_SET.has(status);
  return s === status;
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/* merge a write response into the loaded row (company-join + computed fields are
   absent from the opportunities SELECT * and so survive the merge) */
function patchRow(id, patch) {
  const row = S.rows.find((x) => x.id === id);
  if (row) Object.assign(row, patch);
  return row;
}

/* ---------------- URL hash sync ---------------- */
function syncHash() {
  const f = S.filters;
  const p = new URLSearchParams();
  p.set("s", f.s);
  if (S.page !== "inbox") p.set("page", S.page);
  if (f.q) p.set("q", f.q);
  for (const k of ["pri", "fam", "stg", "mode", "src"])
    if (f[k] !== "all") p.set(k, f[k]);
  p.set("sort", `${S.sort.key}:${S.sort.dir}`);
  p.set("view", S.view);
  if (!S.stripOpen) p.set("mstrip", "0");
  if (S.detailId != null) p.set("d", String(S.detailId));
  history.replaceState(null, "", "#" + p.toString());
}
function readHash() {
  const p = new URLSearchParams(location.hash.replace(/^#/, ""));
  const f = S.filters;
  if (p.has("s")) f.s = p.get("s");
  S.page = p.get("page") === "ats" ? "ats" : "inbox";
  f.q = p.get("q") || "";
  for (const k of ["pri", "fam", "stg", "mode", "src"])
    f[k] = p.get(k) || "all";
  const sort = p.get("sort");
  if (sort && sort.includes(":")) {
    const [key, dir] = sort.split(":");
    S.sort = { key, dir: dir === "asc" ? "asc" : "desc" };
  }
  if (p.get("view") === "map") S.view = "map";
  S.stripOpen = p.get("mstrip") !== "0";
  const d = p.get("d");
  if (d && /^\d+$/.test(d)) S.detailId = Number(d);
}

/* ---------------- data load ---------------- */
async function loadMeta() {
  try {
    S.meta = await (await fetch("/api/meta")).json();
  } catch { S.meta = null; }
  renderCounts();
  updateEmailBtn();
}

async function load() {
  S.sel.clear();          // row set changes on refetch; drop stale selection
  try {
    const r = await fetch(`/api/jobs?statuses=${encodeURIComponent(S.filters.s)}`);
    const d = await r.json();
    S.rows = d.jobs || [];
  } catch {
    S.rows = [];
  }
  buildFilterOptions();
  render();
  renderCounts();          // ATS header counts derive from the loaded rows
}

/* ---------------- filter option population ---------------- */
function fillSelect(sel, options, current, allLabel) {
  sel.innerHTML = "";
  const mk = (val, label) => {
    const o = document.createElement("option");
    o.value = val; o.textContent = label; return o;
  };
  sel.appendChild(mk("all", allLabel));
  for (const [val, label] of options) sel.appendChild(mk(val, label));
  sel.value = [...sel.options].some((o) => o.value === current) ? current : "all";
}

function buildFilterOptions() {
  // status: fixed list
  const fs = $("fStatus");
  if (!fs.options.length) {
    for (const [val, label] of STATUS_OPTS) {
      const o = document.createElement("option");
      o.value = val; o.textContent = label; fs.appendChild(o);
    }
  }
  fs.value = S.filters.s;

  // union of meta + loaded rows so options stay valid across status refetches
  const meta = S.meta || {};
  const onPage = (src) => (S.page === "ats") === ATS_SOURCES.has(src);
  const fams = new Set(meta.families || []);
  const stages = new Set(meta.stages || []);
  const sources = new Set((meta.sources || []).filter(onPage));
  const modes = new Set();
  for (const r of S.rows.filter(pageMatch)) {
    if (r.family) fams.add(r.family);
    if (r.stage) stages.add(r.stage);
    if (r.source) sources.add(r.source);
    const m = modeLabel(r);
    if (m) modes.add(m);
  }
  const pairs = (set) => [...set].sort().map((v) => [v, v]);

  fillSelect($("fPri"),
    [["high", "High"], ["medium", "Medium"], ["low", "Low"]],
    S.filters.pri, "All priority");
  fillSelect($("fFam"), pairs(fams), S.filters.fam, "All family");
  fillSelect($("fStage"), pairs(stages), S.filters.stg, "All stage");
  fillSelect($("fMode"), pairs(modes), S.filters.mode, "All mode");
  fillSelect($("fSrc"), pairs(sources), S.filters.src, "All source");
}

/* ---------------- filter + sort pipeline ---------------- */
function applyFilters() {
  const f = S.filters;
  const q = f.q.trim().toLowerCase();
  let rows = S.rows.filter((r) => {
    if (!pageMatch(r)) return false;             // hard page partition (inbox|ats)
    if (!statusInView(r.status)) return false;   // optimistic drop after actions
    if (f.pri !== "all" && r.priority !== f.pri) return false;
    if (f.fam !== "all" && r.family !== f.fam) return false;
    if (f.stg !== "all" && r.stage !== f.stg) return false;
    if (f.mode !== "all" && modeLabel(r) !== f.mode) return false;
    if (f.src !== "all" && r.source !== f.src) return false;
    if (q) {
      const hay = norm(r.company) + " " + norm(r.role) + " " + norm(r.notes) +
                  " " + norm(r.location) + " " + norm(r.source);
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  return sortRows(rows);
}

function sortRows(rows) {
  const { key, dir } = S.sort;
  const mul = dir === "asc" ? 1 : -1;
  const priOf = (r) => (r.priority in PRI_RANK ? PRI_RANK[r.priority] : 3);
  const cmp = (a, b) => {
    if (key === "priority") {
      const d = priOf(a) - priOf(b);
      if (d) return d * mul;
      // stable tiebreak: score desc regardless of dir
      return (b.score ?? -Infinity) - (a.score ?? -Infinity);
    }
    if (key === "score") {
      return ((a.score ?? -Infinity) - (b.score ?? -Infinity)) * mul;
    }
    if (key === "age") {
      return ((ageDays(a) ?? -Infinity) - (ageDays(b) ?? -Infinity)) * mul;
    }
    // string columns
    const sv = (r) => {
      if (key === "work_mode") return modeLabel(r);
      return r[key] ?? "";
    };
    return String(sv(a)).localeCompare(String(sv(b)),
      undefined, { sensitivity: "base" }) * mul;
  };
  return [...rows].sort(cmp);
}

/* ---------------- rendering ---------------- */
const COLS = [
  { key: "sel", label: "", sortable: false },
  { key: "priority", label: "Priority", sortable: true },
  { key: "company", label: "Company", sortable: true },
  { key: "role", label: "Role", sortable: true },
  { key: "family", label: "Family", sortable: true },
  { key: "work_mode", label: "Mode", sortable: true },
  { key: "score", label: "Fit", sortable: true, cls: "r" },
  { key: "age", label: "Age", sortable: true, cls: "r" },
  { key: "source", label: "Source", sortable: true },
  { key: "notes", label: "Notes", sortable: false },
  { key: "actions", label: "", sortable: false },
];

function renderHead() {
  const tr = document.createElement("tr");
  for (const c of COLS) {
    const th = document.createElement("th");
    if (c.cls) th.className = c.cls;
    if (c.key === "sel") {
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.id = "selAll";
      cb.title = "select all shown";
      cb.onclick = (e) => e.stopPropagation();
      cb.onchange = onSelectAll;
      th.appendChild(cb);
      tr.appendChild(th);
      continue;
    }
    if (c.sortable) {
      th.classList.add("sortable");
      const on = S.sort.key === c.key;
      if (on) th.classList.add("on");
      th.textContent = c.label;
      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.textContent = on ? (S.sort.dir === "asc" ? "▲" : "▼") : "";
      th.appendChild(arrow);
      th.onclick = () => toggleSort(c.key);
    } else {
      th.textContent = c.label;
    }
    tr.appendChild(th);
  }
  const thead = $("grid").tHead;
  thead.innerHTML = "";
  thead.appendChild(tr);
}

function priCell(r) {
  const td = document.createElement("td");
  const span = document.createElement("span");
  const pri = r.priority || "low";
  span.className = `dot pri-${pri in PRI_RANK ? pri : "low"}`;
  span.textContent = r.priority || "—";
  td.appendChild(span);
  if (r.discovered_date === TODAY) {
    const tag = document.createElement("span");
    tag.className = "tag-new";
    tag.textContent = "new";
    td.appendChild(tag);
  }
  return td;
}

// Company logo: favicon via Google's s2 service when the enriched website is a
// real https URL; letter monogram otherwise. src is built from the parsed
// hostname only — never from raw scraped strings.
function logoEl(r, size) {
  if (r.website && /^https?:\/\//i.test(r.website)) {
    try {
      const host = new URL(r.website).hostname;
      const img = document.createElement("img");
      img.className = "co-logo";
      img.width = size; img.height = size;
      img.loading = "lazy"; img.alt = "";
      img.referrerPolicy = "no-referrer";
      img.src = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`;
      img.addEventListener("error", () => img.replaceWith(monogram(r, size)));
      return img;
    } catch { /* fall through to monogram */ }
  }
  return monogram(r, size);
}

function monogram(r, size) {
  const m = document.createElement("span");
  m.className = "co-logo co-mono";
  m.style.width = m.style.height = `${size}px`;
  m.style.lineHeight = `${size}px`;
  m.textContent = (r.company || "?").trim().charAt(0).toUpperCase();
  return m;
}

function companyCell(r) {
  const td = document.createElement("td");
  const wrap = document.createElement("div");
  wrap.className = "co-wrap";
  wrap.appendChild(logoEl(r, 18));
  const name = document.createElement("div");
  name.className = "co-name nowrap";
  name.textContent = r.company || "—";
  wrap.appendChild(name);
  td.appendChild(wrap);
  const sub = document.createElement("div");
  sub.className = "co-sub";
  if (r.enrich_status === "ok" && (r.stage || r.headcount != null)) {
    const size = r.headcount != null ? ` · ${r.headcount}p` : "";
    sub.textContent = `${r.stage || "—"}${size}`;
  } else {
    sub.textContent = "?";
    sub.title = "company not yet enriched — stage and size unknown";
  }
  td.appendChild(sub);
  return td;
}

function roleCell(r) {
  const td = document.createElement("td");
  td.className = "role-cell";
  if (r.url && /^https?:\/\//i.test(r.url)) {
    const a = document.createElement("a");
    a.href = r.url; a.target = "_blank"; a.rel = "noreferrer";
    a.title = r.role || "";
    a.className = "ellip";
    a.style.display = "inline-block";
    a.textContent = r.role || "—";
    td.appendChild(a);
    const out = document.createElement("span");
    out.className = "link-out"; out.textContent = " ↗";
    td.appendChild(out);
  } else {
    td.textContent = r.role || "—";
  }
  return td;
}

function ageCell(r) {
  const td = document.createElement("td");
  td.className = "age r";
  const days = ageDays(r);
  td.appendChild(document.createTextNode(days == null ? "—" : `${days}d`));
  const stale = staleDays(r);
  if (stale != null && stale > 21) {
    td.classList.add("stale");
    const f = document.createElement("span");
    f.className = "stale-flag"; f.textContent = " · stale";
    td.appendChild(f);
  }
  return td;
}

function render() {
  renderHead();
  const rows = applyFilters();
  S.shownIds = rows.map((r) => r.id);
  const pageRows = S.rows.filter(pageMatch);

  // showing N of M (M = rows on this page, not the whole fetch)
  $("shown").textContent = `showing ${rows.length} of ${pageRows.length}`;

  const tbody = $("grid").tBodies[0];
  tbody.innerHTML = "";
  const empty = $("empty");
  const grid = $("grid");

  if (rows.length === 0) {
    grid.style.display = "none";
    empty.hidden = false;
    empty.innerHTML = "";
    if (S.rows.length === 0) {
      empty.textContent = "Pipeline empty — hit Check now.";
    } else if (pageRows.length === 0) {
      empty.textContent = S.page === "ats"
        ? "No ATS rows yet — Check now pulls the Ashby + Greenhouse boards."
        : "No inbox rows in this status.";
    } else {
      const msg = document.createElement("div");
      msg.textContent = "No matches — clear filters.";
      empty.appendChild(msg);
      const btn = document.createElement("button");
      btn.className = "deck"; btn.textContent = "Clear filters";
      btn.onclick = clearFilters;
      empty.appendChild(btn);
    }
    updateSelectAll();
    updateBulkBar();
    return;
  }
  grid.style.display = "";
  empty.hidden = true;

  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = r.id;
    if (r.id === S.detailId) tr.classList.add("open");

    // row click → detail panel (ignore clicks landing on controls/links)
    tr.addEventListener("click", (e) => {
      if (e.target.closest("input, button, select, a, textarea, label")) return;
      openDetail(r.id);
    });

    // hovering a row highlights that company's office pin (strip sync)
    const ck = coKey(r.company);
    tr.addEventListener("mouseenter", () => pinHot(ck, true));
    tr.addEventListener("mouseleave", () => pinHot(ck, false));

    // ☐ select
    const selTd = document.createElement("td");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = S.sel.has(r.id);
    cb.title = "select row";
    cb.onchange = () => toggleSelect(r.id, cb.checked);
    selTd.appendChild(cb);
    tr.appendChild(selTd);

    tr.appendChild(priCell(r));
    tr.appendChild(companyCell(r));
    tr.appendChild(roleCell(r));

    const famTd = document.createElement("td");
    famTd.className = "sub nowrap"; famTd.textContent = r.family || "—";
    tr.appendChild(famTd);

    const modeTd = document.createElement("td");
    const ml = modeLabel(r);
    modeTd.className = ml ? "" : "sub";
    modeTd.textContent = ml || "—";
    tr.appendChild(modeTd);

    const fitTd = document.createElement("td");
    fitTd.className = "num r";
    fitTd.textContent = r.score == null ? "—" : r.score.toFixed(2);
    tr.appendChild(fitTd);

    tr.appendChild(ageCell(r));

    const srcTd = document.createElement("td");
    srcTd.className = "sub nowrap"; srcTd.textContent = r.source || "—";
    tr.appendChild(srcTd);

    // notes — inline edit, POST on change
    const noteTd = document.createElement("td");
    const note = document.createElement("input");
    note.className = "note-input"; note.type = "text";
    note.value = r.notes || ""; note.placeholder = "add note…";
    note.title = "add note";
    note.onchange = () => saveNote(r.id, note.value, note);
    noteTd.appendChild(note);
    tr.appendChild(noteTd);

    tr.appendChild(actionsCell(r));
    tbody.appendChild(tr);
  }
  updateSelectAll();
  updateBulkBar();
}

/* ---------------- row actions ---------------- */
function actionsCell(r) {
  const td = document.createElement("td");
  td.className = "actions nowrap";

  // ♥ new↔shortlisted
  const heart = document.createElement("button");
  heart.className = "act heart" + (r.status === "shortlisted" ? " on" : "");
  heart.textContent = r.status === "shortlisted" ? "♥" : "♡";
  heart.title = r.status === "shortlisted" ? "un-shortlist (→ new)"
                                           : "shortlist";
  heart.onclick = () => toggleHeart(r.id);
  td.appendChild(heart);

  // ✕ kill / Restore (Dead view)
  const inDead = S.filters.s === "dead";
  const kill = document.createElement("button");
  kill.className = "act" + (inDead ? " restore" : " kill");
  kill.textContent = inDead ? "Restore" : "✕";
  kill.title = inDead ? "restore (→ new)" : "kill (→ dead)";
  kill.onclick = () => killOrRestore(r.id);
  td.appendChild(kill);

  // compact status select — all 7 statuses
  const sel = document.createElement("select");
  sel.className = "status-sel";
  sel.title = "set status";
  for (const [val, label] of FUNNEL) {
    const o = document.createElement("option");
    o.value = val; o.textContent = label; sel.appendChild(o);
  }
  sel.value = r.status;
  sel.onchange = () => changeStatus(r.id, sel.value);
  td.appendChild(sel);

  return td;
}

async function applyStatus(id, next) {
  try {
    const resp = await postJSON(`/api/jobs/${id}/status`, { status: next });
    patchRow(id, resp);
    if (S.detailId === id) { Object.assign(S.detailJob, resp); renderDetail(); }
    render();
  } catch (e) { console.error("status change failed", e); }
}
function toggleHeart(id) {
  const r = S.rows.find((x) => x.id === id);
  applyStatus(id, r && r.status === "shortlisted" ? "new" : "shortlisted");
}
function killOrRestore(id) {
  applyStatus(id, S.filters.s === "dead" ? "new" : "dead");
}
function changeStatus(id, next) { applyStatus(id, next); }

async function saveNote(id, text, inputEl) {
  try {
    const resp = await postJSON(`/api/jobs/${id}/note`, { text });
    patchRow(id, resp);
    if (inputEl) inputEl.value = resp.notes || "";
    if (S.detailId === id && S.detailJob) {
      S.detailJob.notes = resp.notes;
      const ta = $("detailNote");
      if (ta && document.activeElement !== ta) ta.value = resp.notes || "";
    }
  } catch (e) { console.error("note save failed", e); }
}

/* ---------------- bulk selection ---------------- */
function toggleSelect(id, on) {
  if (on) S.sel.add(id); else S.sel.delete(id);
  updateSelectAll();
  updateBulkBar();
}
function onSelectAll(e) {
  const on = e.target.checked;
  for (const id of S.shownIds) { if (on) S.sel.add(id); else S.sel.delete(id); }
  render();
}
function updateSelectAll() {
  const cb = $("selAll");
  if (!cb) return;
  const ids = S.shownIds;
  const sel = ids.filter((id) => S.sel.has(id)).length;
  cb.checked = ids.length > 0 && sel === ids.length;
  cb.indeterminate = sel > 0 && sel < ids.length;
}
function updateBulkBar() {
  const bar = $("bulkbar");
  const n = S.sel.size;
  bar.hidden = n === 0;
  $("bulkCount").textContent = n === 1 ? "1 selected" : `${n} selected`;
}
async function runBulk(action) {
  const ids = [...S.sel];
  if (!ids.length) return;
  try {
    await postJSON("/api/jobs/bulk", { ids, action });
  } catch (e) { console.error("bulk failed", e); return; }
  S.sel.clear();
  await load();            // bulk refetches (per spec)
}
function clearSelection() { S.sel.clear(); render(); }

function renderCounts() {
  const el = $("counts");
  const m = S.meta;
  if (!m) { el.textContent = "…"; return; }
  const lc = m.last_check;
  const ago = checkedAgo(lc);
  if (S.page === "ats") {
    // ATS page has its own ledger: intern listings + orgs, not the funnel counts
    const rows = S.rows.filter(pageMatch);
    const orgs = new Set(rows.map((r) => coKey(r.company))).size;
    el.innerHTML = `<b>${rows.length}</b> intern listings · ` +
                   `<b>${orgs}</b> companies · checked ${ago}`;
  } else {
    const c = m.counts || {};
    el.innerHTML =
      `<b>${c.live ?? 0}</b> live · <b>${c.high ?? 0}</b> high · ` +
      `<b>${c.medium ?? 0}</b> med · <b>${c.low ?? 0}</b> low · checked ${ago}`;
  }
  if (lc && lc.summary) el.title = lc.summary;
}

function checkedAgo(lc) {
  if (!lc || !lc.started_at) return "never";
  const t = Date.parse(lc.started_at);
  if (!Number.isFinite(t)) return "never";
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/* ---------------- detail panel ---------------- */
async function openDetail(id) {
  S.detailId = id;
  syncHash();
  markOpenRow();
  try {
    const r = await fetch(`/api/jobs/${id}`);
    if (!r.ok) throw new Error(`${r.status}`);
    S.detailJob = await r.json();
  } catch (e) {
    console.error("detail load failed", e);
    closeDetail();
    return;
  }
  renderDetail();
}

function closeDetail() {
  S.detailId = null;
  S.detailJob = null;
  const aside = $("detail");
  aside.hidden = true;
  aside.innerHTML = "";
  document.body.classList.remove("detail-open");
  markOpenRow();
  syncHash();
}

/* highlight the open row without a full re-render */
function markOpenRow() {
  const tbody = $("grid").tBodies[0];
  if (!tbody) return;
  for (const tr of tbody.rows)
    tr.classList.toggle("open", Number(tr.dataset.id) === S.detailId);
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderDetail() {
  const j = S.detailJob;
  const aside = $("detail");
  if (!j) { closeDetail(); return; }
  aside.innerHTML = "";
  aside.hidden = false;
  document.body.classList.add("detail-open");
  markOpenRow();

  // top bar — title + close
  const top = el("div", "d-top");
  const titles = el("div", "d-titles");
  titles.appendChild(el("div", "d-role", j.role || "—"));
  const coLine = el("div", "d-co");
  coLine.appendChild(logoEl(j, 22));
  coLine.appendChild(document.createTextNode(j.company || "—"));
  titles.appendChild(coLine);
  top.appendChild(titles);
  const close = el("button", "d-close", "✕");
  close.title = "close";
  close.onclick = closeDetail;
  top.appendChild(close);
  aside.appendChild(top);

  // status button row (full funnel, current highlighted)
  const sb = el("div", "d-status");
  for (const [val, label] of FUNNEL) {
    const b = el("button", "d-stat" + (j.status === val ? " on" : ""), label);
    b.onclick = () => applyStatus(j.id, val);
    sb.appendChild(b);
  }
  aside.appendChild(sb);

  if (j.applied_date) {
    const ap = el("div", "d-applied");
    ap.appendChild(el("span", "sub", "applied "));
    ap.appendChild(el("span", "num", j.applied_date));
    aside.appendChild(ap);
  }

  // company card
  const card = el("div", "d-card");
  card.appendChild(el("div", "d-card-h", "Company"));
  const bits = [];
  if (j.stage) bits.push(j.stage);
  if (j.headcount != null) bits.push(`${j.headcount}p`);
  if (j.sector) bits.push(j.sector);
  card.appendChild(el("div", "d-card-line", bits.length ? bits.join(" · ") : "—"));
  if (j.office_area) card.appendChild(el("div", "d-card-sub", j.office_area));
  if (isHttps(j.website)) {
    const line = el("div", "d-card-sub");
    const a = el("a", "d-link", j.website.replace(/^https:\/\//i, ""));
    a.href = j.website; a.target = "_blank"; a.rel = "noreferrer";
    line.appendChild(a);
    card.appendChild(line);
  }
  const enr = el("div", "d-card-sub d-enrich");
  if (j.enrich_status === "ok") {
    enr.appendChild(el("span", "good", "enriched"));
  } else {
    enr.appendChild(el("span", "warn",
      "pending enrichment — run full scan in Claude"));
  }
  card.appendChild(enr);
  aside.appendChild(card);

  // notes textarea (POST on blur only when dirty)
  const nWrap = el("div", "d-field");
  nWrap.appendChild(el("label", "d-label", "Notes"));
  const ta = el("textarea", "d-note");
  ta.id = "detailNote";
  ta.value = j.notes || "";
  ta.placeholder = "add note…";
  ta.dataset.clean = j.notes || "";
  ta.onblur = () => {
    if (ta.value === ta.dataset.clean) return;   // dirty-only
    ta.dataset.clean = ta.value;
    saveNoteFromDetail(j.id, ta.value);
  };
  nWrap.appendChild(ta);
  aside.appendChild(nWrap);

  // full JD — plain text only, NEVER innerHTML
  const jdWrap = el("div", "d-field");
  jdWrap.appendChild(el("label", "d-label", "Job description"));
  const pre = el("pre", "d-jd");
  pre.textContent = j.jd_text || "(no description stored)";
  jdWrap.appendChild(pre);
  aside.appendChild(jdWrap);

  // outbound link (https-guarded)
  if (isHttps(j.url)) {
    const out = el("a", "d-out", "Open posting ↗");
    out.href = j.url; out.target = "_blank"; out.rel = "noreferrer";
    aside.appendChild(out);
  }
}

async function saveNoteFromDetail(id, text) {
  try {
    const resp = await postJSON(`/api/jobs/${id}/note`, { text });
    patchRow(id, resp);
    if (S.detailJob && S.detailJob.id === id) S.detailJob.notes = resp.notes;
    // refresh the matching row's inline input if present
    const tr = [...$("grid").tBodies[0].rows].find(
      (x) => Number(x.dataset.id) === id);
    const inp = tr && tr.querySelector(".note-input");
    if (inp && document.activeElement !== inp) inp.value = resp.notes || "";
  } catch (e) { console.error("note save failed", e); }
}

/* ---------------- interactions ---------------- */
function toggleSort(key) {
  if (S.sort.key === key) {
    S.sort.dir = S.sort.dir === "asc" ? "desc" : "asc";
  } else {
    S.sort.key = key;
    // sensible first-click direction: text asc, numeric-ish desc
    S.sort.dir = ["company", "role", "family", "work_mode", "source",
                  "priority"].includes(key) ? "asc" : "desc";
  }
  syncHash();
  render();
}

function clearFilters() {
  const f = S.filters;
  f.q = ""; f.pri = "all"; f.fam = "all"; f.stg = "all";
  f.mode = "all"; f.src = "all";
  $("search").value = "";
  buildFilterOptions();
  syncHash();
  render();
}

function applyPageChrome() {
  const ats = S.page === "ats";
  $("pageInbox").classList.toggle("on", !ats);
  $("pageAts").classList.toggle("on", ats);
  document.body.classList.toggle("ats-page", ats);
  $("pagebar").hidden = !ats;
  document.title = ats ? "Intern Inbox — ATS boards" : "Intern Inbox";
}

function setPage(page) {
  if (S.page === page) return;
  S.page = page;
  S.sel.clear();           // selection never crosses the partition
  const f = S.filters;     // a source filter from the other page can't apply here
  if (f.src !== "all" && (page === "ats") !== ATS_SOURCES.has(f.src)) f.src = "all";
  if (page === "ats" && S.view === "map") setView("table");  // ATS page is table-only
  applyPageChrome();
  buildFilterOptions();
  syncHash();
  render();
  renderCounts();
  buildMap();              // hides the strip on ATS, redraws page pins on inbox
}

function setView(view) {
  S.view = view;
  $("viewTable").classList.toggle("on", view === "table");
  $("viewMap").classList.toggle("on", view === "map");
  document.body.classList.toggle("map-view", view === "map");
  syncHash();
  buildMap();
}

function toggleStrip() {
  S.stripOpen = !S.stripOpen;
  syncHash();
  buildMap();
}

/* ---------------- map (Leaflet strip + full view) ---------------- */
function destroyMap() {
  if (MAP) { MAP.remove(); MAP = null; }
  MARKERS = {};
}

async function ensureOffices() {
  if (S.offices) return S.offices;
  try {
    const d = await (await fetch("/api/offices")).json();
    S.offices = Array.isArray(d.offices) ? d.offices : [];
  } catch { S.offices = []; }
  return S.offices;
}

/* single entry point — decides strip vs full vs collapsed and (re)draws */
async function buildMap() {
  const host = $("mapstrip");
  const mapEl = $("map");
  const tog = $("mapToggle");
  if (S.page === "ats") {            // ATS page is table-only — no map at all
    host.hidden = true;
    destroyMap();
    return;
  }
  const full = S.view === "map";
  const stripVisible = S.view === "table" && S.stripOpen;

  host.hidden = false;               // the strip bar is always present (holds toggle)
  tog.hidden = full;                 // in full map you leave via the Table|Map seg
  tog.textContent = S.stripOpen ? "Hide map ▴" : "Show map ▾";
  mapEl.hidden = !(full || stripVisible);
  mapEl.classList.toggle("fullmap", full);

  if (mapEl.hidden) { destroyMap(); return; }

  const offices = await ensureOffices();
  let list = offices;
  if (full) {
    // full map respects the active table filters (company-name match)
    const wanted = new Set(applyFilters().map((r) => coKey(r.company)));
    list = offices.filter((o) => wanted.has(coKey(o.company)));
  } else {
    // strip ignores filters but never crosses the page partition (inbox|ats)
    const pageCos = new Set(S.rows.filter(pageMatch).map((r) => coKey(r.company)));
    list = offices.filter((o) => pageCos.has(coKey(o.company)));
  }
  const pinnable = list.filter((o) => o.lat != null && o.lon != null);
  if (!pinnable.length) {                 // no geocoded offices → quiet placeholder
    destroyMap();
    mapEl.classList.add("mapempty");
    mapEl.textContent = "No mapped offices yet.";
    return;
  }
  mapEl.classList.remove("mapempty");
  drawMarkers(mapEl, pinnable, full);
}

function officePopup(o) {
  // scraped company text → textContent only (never innerHTML)
  const div = document.createElement("div");
  div.className = "pp";
  const stage = o.stage || "?";
  const head = o.headcount != null ? `${o.headcount}p` : "?";
  div.textContent =
    `${o.company} — ${o.roles} roles · ${o.priority} · ${stage} ${head}`;
  return div;
}

function officeTooltip(o) {
  const span = document.createElement("span");
  span.textContent = `${o.company} · ${o.roles}`;
  return span;
}

function drawMarkers(el, offices, full) {
  destroyMap();
  el.textContent = "";                    // clear any placeholder text node
  MAP = L.map(el, { zoomControl: full });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(MAP);
  const pts = [];
  for (const o of offices) {
    if (o.lat == null || o.lon == null) continue;
    const key = coKey(o.company);
    const mk = L.circleMarker([o.lat, o.lon], {
      radius: full ? 7.5 : 6.5, color: "#fff", weight: 2,
      fillColor: OFFICE_COLORS[o.priority] || OFFICE_COLORS.low, fillOpacity: 0.95,
    });
    mk.bindTooltip(officeTooltip(o));
    mk.bindPopup(officePopup(o));
    mk.on("click", () => onPinClick(key));
    mk.addTo(MAP);
    MARKERS[key] = mk;
    pts.push([o.lat, o.lon]);
  }
  MAP.setView([40.73, -74.0], 11);   // NYC default until we know the real size
  // the container just became visible — settle its layout, then size + fit so
  // Leaflet loads tiles for the full viewport (not a stale/zero-size rectangle)
  const fit = () => {
    if (!MAP) return;
    MAP.invalidateSize(false);
    if (pts.length) MAP.fitBounds(pts, { padding: full ? [46, 46] : [24, 24], maxZoom: 14 });
  };
  requestAnimationFrame(() => requestAnimationFrame(fit));
}

/* hovering a row (or, later, a pin) fattens the matching pin + rings it */
function pinHot(key, on) {
  const mk = MARKERS[key];
  if (!mk) return;
  mk.setStyle(on
    ? { radius: 9.5, weight: 4, color: "rgba(127,196,132,.55)" }
    : { radius: 6.5, weight: 2, color: "#fff" });
  if (on) mk.bringToFront();
}

/* clicking a pin flash-scrolls to & selects the first matching table row */
function onPinClick(key) {
  if (S.view === "map") setView("table");   // reveal the table to scroll into
  // next tick so the un-hidden table has laid out before we scroll
  setTimeout(() => flashRow(key), 0);
}

function flashRow(key) {
  const tbody = $("grid").tBodies[0];
  if (!tbody) return;
  for (const tr of tbody.rows) {
    const r = S.rows.find((x) => x.id === Number(tr.dataset.id));
    if (r && coKey(r.company) === key) {
      tr.scrollIntoView({ behavior: "smooth", block: "center" });
      tr.classList.add("rowflash");
      setTimeout(() => tr.classList.remove("rowflash"), 1200);
      const cb = tr.querySelector('input[type="checkbox"]');
      if (cb && !cb.checked) { cb.checked = true; toggleSelect(r.id, true); }
      return;
    }
  }
}

/* ---------------- CSV export (current filtered+sorted view) ---------------- */
const CSV_COLS = ["company", "role", "url", "priority", "status", "family",
  "stage", "headcount", "work_mode", "score", "posted_date", "discovered_date",
  "applied_date", "source", "notes"];

function csvCell(v) {
  const s = v == null ? "" : String(v);
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function exportCsv() {
  const rows = applyFilters();
  const lines = [CSV_COLS.join(",")];
  for (const r of rows) lines.push(CSV_COLS.map((c) => csvCell(r[c])).join(","));
  const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `jobs-${TODAY}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

/* ---------------- Email ♥ (shortlist digest) ---------------- */
function savedCount() {
  const c = (S.meta && S.meta.counts) || {};
  return (c.shortlisted || 0) + (c.applied || 0) + (c.interviewing || 0);
}

function updateEmailBtn() {
  const btn = $("emailSaved");
  if (!btn) return;
  const n = savedCount();
  btn.textContent = `Email ♥ · ${n}`;
  btn.disabled = n === 0;
  btn.title = n ? `email ${n} saved role${n === 1 ? "" : "s"} to your inbox`
                : "nothing shortlisted/applied/interviewing yet";
}

async function emailSaved() {
  const btn = $("emailSaved");
  btn.disabled = true;
  try {
    const d = await postJSON("/api/email-saved", {});
    showToast(`sent ${d.sent}`, "ok");
  } catch (e) {
    showToast(String(e && e.message ? e.message : e).slice(0, 140), "err");
  } finally {
    updateEmailBtn();   // restore enabled state per current count
  }
}

/* ---------------- Check now (POST /api/pull + poll) ---------------- */
function setChecking(on) {
  const btn = $("checkNow");
  btn.textContent = "";
  if (on) {
    const dot = document.createElement("span");
    dot.className = "livedot";
    btn.appendChild(dot);
    btn.appendChild(document.createTextNode("checking…"));
    btn.disabled = true;
  } else {
    btn.textContent = "Check now";
    btn.disabled = false;
  }
}

async function checkNow() {
  try {
    await postJSON("/api/pull", {});
  } catch (e) {
    const msg = String(e && e.message ? e.message : e);
    if (msg.startsWith("409")) { showToast("already running", "warn"); pollPull(); return; }
    showToast("check failed", "err");
    return;
  }
  pollPull();
}

function pollPull() {
  S.pullRunning = true;
  setChecking(true);
  if (pullTimer) return;
  let failCount = 0;
  pullTimer = setInterval(async () => {
    let st;
    try { st = await (await fetch("/api/pull/status")).json(); }
    catch {
      failCount++;
      if (failCount >= 5) {
        clearInterval(pullTimer); pullTimer = null;
        S.pullRunning = false;
        setChecking(false);
        showToast("check status lost — refresh to retry", "err");
      }
      return;
    }
    failCount = 0;
    if (st.steps) {
      $("checkNow").title = Object.entries(st.steps)
        .map(([k, v]) => `${k}: ${v}`).join("\n");
    }
    if (!st.running) {
      clearInterval(pullTimer); pullTimer = null;
      S.pullRunning = false;
      setChecking(false);
      S.offices = null;                 // geocode batch may have added pins
      await loadMeta();
      await load();
      if (S.view === "map" || S.stripOpen) buildMap();
      showToast("check done", "ok");
    }
  }, 2000);
}

/* ---------------- toast ---------------- */
function showToast(msg, kind) {
  const t = $("toast");
  if (!t) return;
  t.textContent = msg;
  t.className = "toast" + (kind ? " " + kind : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3400);
}

/* ---------------- auto-refresh (60s, polite) ---------------- */
function noteDirty() {
  const ta = $("detailNote");
  return !!(ta && ta.value !== ta.dataset.clean);
}

function startAutoRefresh() {
  setInterval(async () => {
    if (S.view === "map") return;                 // don't disturb the map
    if (S.pullRunning) return;                     // a pull is already refreshing
    const ae = document.activeElement;
    if (ae && /^(INPUT|SELECT|TEXTAREA)$/.test(ae.tagName)) return;  // mid-edit
    if (noteDirty()) return;                        // unsaved detail note
    await loadMeta();
    await load();
    // offices cache would otherwise stick forever (even a cached [] is truthy) —
    // pins appearing after enrichment/geocode must show up without a hard reload
    S.offices = null;
    if (S.stripOpen) await buildMap();
  }, 60000);
}

let searchTimer = null;
function onSearch(e) {
  const v = e.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    S.filters.q = v;
    syncHash();
    render();
  }, 150);
}

/* ---------------- wiring ---------------- */
function wire() {
  $("search").addEventListener("input", onSearch);

  $("fStatus").addEventListener("change", (e) => {
    S.filters.s = e.target.value;
    syncHash();
    load();               // status filter refetches from the server
  });
  const clientSelect = { fPri: "pri", fFam: "fam", fStage: "stg",
                         fMode: "mode", fSrc: "src" };
  for (const [id, key] of Object.entries(clientSelect)) {
    $(id).addEventListener("change", (e) => {
      S.filters[key] = e.target.value;
      syncHash();
      render();
    });
  }

  $("pageInbox").addEventListener("click", () => setPage("inbox"));
  $("pageAts").addEventListener("click", () => setPage("ats"));
  $("viewTable").addEventListener("click", () => setView("table"));
  $("viewMap").addEventListener("click", () => setView("map"));
  $("mapToggle").addEventListener("click", toggleStrip);

  // Task 8 deck buttons
  $("checkNow").addEventListener("click", checkNow);
  $("csv").addEventListener("click", exportCsv);
  $("emailSaved").addEventListener("click", emailSaved);

  // bulk bar
  $("bulkShortlist").addEventListener("click", () => runBulk("shortlist"));
  $("bulkKill").addEventListener("click", () => runBulk("kill"));
  $("bulkClear").addEventListener("click", clearSelection);

  // Escape closes the detail panel
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && S.detailId != null) closeDetail();
  });
}

/* ---------------- boot ---------------- */
async function boot() {
  readHash();
  wire();

  // reflect restored filter state into the controls
  $("search").value = S.filters.q;
  if (S.page === "ats" && S.view === "map") S.view = "table";  // ATS is table-only
  applyPageChrome();
  setView(S.view);

  await loadMeta();
  await load();           // buildFilterOptions() inside picks up restored values
  buildMap();             // rows are loaded now — draw strip/full with real data
  if (S.detailId != null) await openDetail(S.detailId);  // restore open panel
  startAutoRefresh();
  syncHash();             // normalize hash on first paint
}

boot();
