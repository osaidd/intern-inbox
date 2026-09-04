// First-run wizard. State + presets come from the API; finish POSTs choices,
// kicks the first pull, then lands on the inbox.
const $ = (id) => document.getElementById(id);
let RERUN_NEEDS_FORCE = false;
let OUTLOOK_TIMER = null;

async function post(url) {
  const r = await fetch(url, { method: "POST",
    headers: { "content-type": "application/json" }, body: "{}" });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
  return d;
}

function provider() {
  return document.querySelector('input[name="mailprov"]:checked').value;
}

function syncProvider() {
  const p = provider();
  $("provGmail").hidden = p !== "gmail";
  $("provOutlook").hidden = p !== "outlook";
  $("provImap").hidden = p !== "imap";
  $("passWrap").hidden = p === "outlook";   // Outlook signs in, no password here
  $("emailAddr").placeholder = p === "gmail" ? "you@gmail.com" : "you@yourschool.edu";
  if ($("imapPass").placeholder.indexOf("saved") === -1) {
    $("imapPass").placeholder = p === "gmail" ? "16-character app password"
                                              : "mailbox password";
  }
}

function outlookSay(msg, code, url) {
  const s = $("outlookStatus");
  s.textContent = msg;
  if (code && url) {
    const a = document.createElement("a");
    a.href = url; a.target = "_blank"; a.rel = "noopener";
    a.textContent = url;
    s.append(" — enter code ", Object.assign(document.createElement("b"),
                                             { textContent: code }), " at ", a);
  }
}

async function connectOutlook() {
  clearInterval(OUTLOOK_TIMER);
  try {
    const d = await post("/api/outlook/start");
    outlookSay("waiting for sign-in", d.user_code, d.verification_uri);
    OUTLOOK_TIMER = setInterval(async () => {
      try {
        const p = await post("/api/outlook/poll");
        if (p.status === "connected") {
          clearInterval(OUTLOOK_TIMER);
          outlookSay("Connected ✓ — the feeds can read this mailbox now");
        } else if (p.status === "error") {
          clearInterval(OUTLOOK_TIMER);
          outlookSay(p.message || "sign-in failed — try again");
        }
      } catch (e) { clearInterval(OUTLOOK_TIMER); outlookSay(String(e.message || e)); }
    }, 5000);
  } catch (e) {
    outlookSay(String(e.message || e));
  }
}

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
  const pf = s.prefill;
  if (pf && pf.roles && pf.roles.length) {
    for (const i of boxes.querySelectorAll("input"))
      i.checked = pf.roles.includes(i.value);
  } else {
    boxes.querySelector("input").checked = true;
  }
  if (pf) {
    const r = document.querySelector(`input[name="size"][value="${pf.size}"]`);
    if (r) r.checked = true;
    if (pf.size === "custom" && pf.custom_cap) $("customCap").value = pf.custom_cap;
    $("startupsOnly").checked = !!pf.startups_only;
    $("avoid").value = (pf.avoid || []).join(", ");
    $("emailAddr").value = pf.email_address || "";
    if (pf.imap_saved) $("imapPass").placeholder = "saved — leave blank to keep";
    $("mailScan").checked = !!pf.mail_scan;
    const prov = document.querySelector(
      `input[name="mailprov"][value="${pf.provider || "gmail"}"]`);
    if (prov) prov.checked = true;
    $("imapHost").value = pf.imap_host || "";
    if (pf.outlook_connected) outlookSay("Connected ✓");
  }
  syncProvider();
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
    provider: provider(),
    imap_host: $("imapHost").value.trim(),
    mail_scan: $("mailScan").checked,
    force: RERUN_NEEDS_FORCE,
  };
}

/* A click on the number field does NOT tick its own radio — labels ignore
   clicks on interactive descendants — so a typed cap whose option was never
   selected would be silently discarded on finish. Typing is the intent signal,
   never focus: the radio group is one tab stop and this field is the next, so
   a focus handler would rewrite a deliberate size choice on plain tab-through.
   Typing, pasting, and the spinner arrows all fire input. */
$("customCap").addEventListener("input", () => {
  document.querySelector('input[name="size"][value="custom"]').checked = true;
});

for (const r of document.querySelectorAll('input[name="mailprov"]')) {
  r.addEventListener("change", syncProvider);
}
$("outlookConnect").addEventListener("click", connectOutlook);

$("finish").addEventListener("click", async () => {
  const c = choices();
  if (!c.roles.length) return show("Pick at least one role type.");
  if (c.size === "custom" && !c.custom_cap) return show("Enter a number for the custom cap.");
  if (c.provider === "imap" && !c.imap_host)
    return show("Enter your IMAP host (or pick Gmail/Outlook).");
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
