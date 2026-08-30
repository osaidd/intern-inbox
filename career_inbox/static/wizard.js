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

/* A click on the number field does NOT tick its own radio — labels ignore
   clicks on interactive descendants — so a typed cap whose option was never
   selected would be silently discarded on finish. Typing is the intent signal,
   never focus: the radio group is one tab stop and this field is the next, so
   a focus handler would rewrite a deliberate size choice on plain tab-through.
   Typing, pasting, and the spinner arrows all fire input. */
$("customCap").addEventListener("input", () => {
  document.querySelector('input[name="size"][value="custom"]').checked = true;
});

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
