# Setup

The long version of the quickstart. Follow it top to bottom and you will have a
working internship inbox in about 10 minutes. Nothing here assumes you have
written code before.

[Claude Code](https://claude.com/claude-code) is recommended, not required —
section 6 covers what it adds if you have it.

---

## 1. Install it

One paste. It installs [uv](https://docs.astral.sh/uv/) (the tool that installs
Python and the dependencies) if you do not have it, downloads the project to
`~/intern-inbox`, installs everything, and starts the app.

**Mac** — open Terminal (⌘-Space, type "Terminal") and paste:

```bash
curl -LsSf https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.sh | sh
```

**Windows** — open PowerShell (Start menu, type "PowerShell") and paste:

```powershell
irm https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.ps1 | iex
```

It takes a minute the first time, mostly downloading Python. It touches nothing
else on your computer — everything lands in the `intern-inbox` folder.

If it stops and says git is missing, follow the one line it prints (Mac: click
**Install** in Apple's popup; Windows: `winget install --id Git.Git -e`), then
close the window, open a new one, and paste the command again.

When it finishes, your browser opens at <http://127.0.0.1:8477> on the setup
page. That is section 2.

One exception: if you already have Claude Code installed, the paste opens the
project in Claude Code instead of the browser. Type `/setup` there and it walks
you through the same questions in more depth — section 6.

## 2. The 3-step setup

The first time the app runs with no config, it sends you to the setup page
(<http://127.0.0.1:8477/welcome.html>) instead of an empty inbox.

**Step 1 — what are you looking for?** Checkboxes for role families: software /
AI engineering, product, data, GTM / growth / marketing, and bizops / operations
/ finance. Tick every one that applies. Each adds a curated bundle of keywords
and job titles that the scoring reads; ticking two merges both bundles.

**Step 2 — how big can the company be?** The headline control. Pick tiny (up to
~50 people), small (~100), mid-size (~500), any size, or type your own cap. A
listing from a company confirmed bigger than your cap gets dropped; a company
whose size nobody has confirmed yet is never dropped on a guess. Under it, a
checkbox that hides big-name companies (Google, Goldman, Meta, and about fifty
more) — on by default — and a text box for any other company you never want to
see.

**Step 3 — job-alert emails (optional).** Your Gmail address and a 16-character
app password, so the app can read LinkedIn / Built In / Wellfound alerts out of
your inbox. Section 3 is the walkthrough for getting that password. Skip it and
everything else still works: the company boards and the GitHub lists need no
email.

Press **Start my inbox**. It writes two files, starts a first pull, and drops
you in the inbox:

- `config/career.toml` — your roles, your size cap, your block list.
- `config/.env` — your email address and app password, if you gave them.

Both are gitignored. They stay on your laptop and cannot end up in a pull
request. `career.toml` starts with a `# written-by: intern-inbox-wizard` line,
which is how the app knows a later re-run is yours to overwrite.

Skipped the whole thing? You get the inbox on the shared defaults, plus a banner
offering the three questions. The **⚙** button at the top right reopens the
setup page any time, and re-running it just rewrites the same two files. If your
config came from `/setup` in Claude Code instead of the wizard, re-running asks
before replacing it.

## 3. Gmail app password

This lets the app read job-alert emails out of your inbox. It is a separate
16-character password that only works for this one purpose, and you can revoke
it at any time. Your real Google password is never used or stored.

1. Go to <https://myaccount.google.com/security>.
2. Turn on **2-Step Verification** if it is not on already. App passwords do not
   exist without it. Google will walk you through it with your phone.
3. Go to <https://myaccount.google.com/apppasswords>.
4. In the **App name** box, type `intern-inbox`, then click **Create**.
5. A yellow box shows a 16-character code in four groups. Copy it.
6. Paste it into step 3 of the setup page, along with your Gmail address. The
   spaces do not matter. Already past setup? Click **⚙** to reopen the page, or
   put the code in `config/.env` by hand, spaces removed:

   ```
   CAREER_IMAP_PASS=abcdefghijklmnop
   ```

7. Click **Done** in Google.

If the app-passwords page says the option is not available for your account,
that is 2-Step Verification not being fully on yet. Go back to step 2.

The app reads the address you typed on the setup page — it is saved as
`CAREER_IMAP_USER` in `config/.env`. To read a different mailbox, change that
line.

## 4. Turn on job alerts

The email feed only sees what actually arrives in your inbox, so you have to
subscribe to the alerts yourself. Use the same address from section 3.

- **LinkedIn** — <https://www.linkedin.com/jobs/>. Search each role you want plus
  the word "internship", set the location to New York, then turn on the alert
  toggle at the top of the results. Choose **Daily**. Do this once per search.
- **Built In NYC** — <https://builtin.com/nyc>. Make an account, filter for
  internships, and save the search as a job alert.
- **Wellfound** — <https://wellfound.com/jobs>. In your profile settings, turn on
  email alerts for roles that match you.

Alerts take up to a day to start arriving. Zero email results on day one is
normal and not a bug — the company boards still bring in listings meanwhile.

## 5. The daily loop

```bash
uv run intern-inbox --open
```

Run that from the `intern-inbox` folder. `--open` opens your browser for you;
without it, start `uv run intern-inbox` and go to <http://127.0.0.1:8477>
yourself. Two tabs at the top:

- **Inbox** — everything from your alert emails, the GitHub lists, and JobSpy.
- **ATS boards** — internships pulled straight from company job boards.

Press **Check now** to pull fresh listings. Then go down the list: heart the ones
worth applying to, X the ones that are not, and move a row to **Applied** once
you have applied. Press **CSV** to export.

The **Email ♥** button emails you everything you have hearted or applied to. It
needs `CAREER_SMTP_PASS` in `config/.env` — the app password from section 3
works. Nothing writes that key for you, so out of the box the app sends no email
anywhere; without it the button shows "email failed: CAREER_SMTP_PASS not set",
which is expected, not a broken install. Ignore the button if you do not want
the email. The automatic digest after each check also needs `enabled = true`
under `[email]` in `config/career.toml`.

Run `git pull` every week or so — other students add company boards, and you get
them for free.

Optional, Mac only: `automation/install-intern-inbox-app.sh` makes an app icon in
`~/Applications` that does the start-and-open in one click. Add `--dock` to pin
it to the Dock.

## 6. Claude Code (recommended)

Everything above runs without it. Here is what it adds.

Open the `intern-inbox` folder in [Claude Code](https://claude.com/claude-code)
(File → Open… and pick the folder itself — not your home folder, not Desktop)
and type:

```
/setup
```

`/setup` is a conversation, not a form. It asks about the roles you want, what
you are good at, your dealbreakers, and dream companies; it reads your resume
(drop the PDF into the `intern-inbox` folder, or paste the text into the chat);
and it writes `config/career.toml`, `config/sources.local.toml`, `config/.env`,
and `profile/profile.md`. All four are gitignored. The difference from the
wizard: your keywords and rankings come out of your own resume instead of the
five starter bundles. It also walks you through sections 3 and 4 and runs a
first pull at the end.

If you already answered the wizard, `/setup` sees the config and asks what you
want to update instead of starting over — say "resume" and it rewrites your
keywords and rankings, showing you the before/after before it writes anything.

Two things that trip people up:

- **`/setup` not recognized?** Claude Code has the wrong folder open. Open the
  `intern-inbox` folder itself and try again.
- **Run it on your own computer.** A claude.ai cloud session runs in a sandbox
  that cannot reach the job-board APIs — the pull will fail there with
  "host not allowed" errors that have nothing to do with your setup.

Once you have a week of real rows, four more skills earn their keep:

- **/opportunity-scan** — full sourcing sweep plus company enrichment (stage,
  size, office), which is what turns the priority column into real tiers.
- **/skills-gap** — every stored job description against your profile: what the
  market wants, where you fall short, per-role fit briefs.
- **/add-opportunity** — paste a posting, a URL, or an alert email to file it.
- **/pipeline-review** — triage by talking: "kill 12", "applied to Ramp".

You can run `/setup` again any time — it asks what you want to update instead
of starting over. The most useful re-run: say **"update my resume"** after you
revise it, and your profile keywords and rankings follow the new version (you
see the before/after diff first). The resume file stays on your machine.

## Appendix: doing it by hand

For anyone who would rather not paste a script or click through a wizard. Same
result, more steps.

**Install uv** — Mac or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close the terminal, open a new one, and check with `uv --version`. If it says
command not found, the new terminal did not pick up the install — close every
terminal window and open a fresh one.

**Get the code.**

```bash
git clone https://github.com/osaidd/intern-inbox.git intern-inbox
cd intern-inbox
uv sync
```

**Write the config.**

```bash
cp config/career.example.toml config/career.toml
```

`config/career.example.toml` is commented block by block; the keys that matter
most:

- `[role].profile_keywords` and `[role].target_titles` — what you want. The
  `[scoring]` block carries deliberate copies of both lists, so edit them in
  both places.
- `[role].exclude_companies` — whole-word match on the company name.
- `[company].tier1_max_headcount`, `tier2_max_headcount`, `hard_cap_headcount` —
  the size cap the wizard's step 2 sets for you. `allow_late_stages = true` lets
  Series C and later through.
- `[email].to` and `[email].smtp_user` — where digests would go.

No secrets in `career.toml`. `CAREER_IMAP_USER`, `CAREER_IMAP_PASS`, and
`CAREER_SMTP_PASS` go in `config/.env`, one `KEY=value` per line, no quotes.
Both files are gitignored.

A `career.toml` you wrote by hand carries no wizard marker, so the wizard asks
before overwriting it. Then start the app: `uv run intern-inbox --open`.

## Windows notes

Everything works, with two differences.

- Run `uv run intern-inbox --open` from PowerShell, Windows Terminal, or the
  Claude Code terminal — any terminal, from inside the project folder. The
  browser link is the same: <http://127.0.0.1:8477>.
- The Mac app-icon script does not apply. Skip that part of section 5.

Honest status: `bootstrap.ps1` has been read line by line but has never been run
on a real Windows machine — there was no Windows box here to test it on. It does
the same steps as the appendix above, so if it stops early you can finish by
hand. If you are the first person to run it, open a GitHub issue saying whether
it worked. That saves the next person the trouble.

If you want the shared company boards to refresh on their own every morning,
open **Task Scheduler**, create a basic daily task, and set the action to run
this (adjust the path to where you cloned it):

```
uv run --directory C:\Users\you\intern-inbox python -m feeds.ats_pull
```

That is optional. Pressing **Check now** in the app does the same thing.

## Troubleshooting

**The setup page never opened.**
The app is probably running anyway — go to
<http://127.0.0.1:8477/welcome.html> yourself. If the browser says it cannot
connect, the server is not up: run `uv run intern-inbox --open` from the
`intern-inbox` folder and read what it prints.

**"address already in use" / the page will not load.**
Something else is on port 8477 — often a copy of the app you already started.
Use a different port:

```bash
uv run intern-inbox --port 8500 --open
```

**JobSpy says "skipped: optional extra not installed".**
That is the default: the Indeed/Google feed needs ~160MB of extra libraries and
is the least reliable source, so the core install leaves it out. The board and
email feeds are unaffected. Want it anyway? Run `uv sync --extra jobspy` once.

**A check finishes but JobSpy reports an error.**
JobSpy scrapes public job boards and those boards rate-limit. It fails some days
and works the next. Press **Check now** again later. The other sources are
unaffected.

**No email listings on day one.**
Expected. Your alerts have not been sent yet. Give it a day.

**"CAREER_IMAP_PASS missing".**
Step 3 of the setup page was skipped, or the code went into the wrong file. It
belongs in `config/.env`, on its own line, no quotes, no spaces in the code.
Click **⚙** in the app to fill it in through the setup page instead.

**Nothing shows up at all.**
Check the filters at the top of the list — the status dropdown may be on
something narrow. If the list is genuinely empty, run the board sweep directly
and read what it prints:

```bash
uv run python -m feeds.ats_pull
```

**Something looks broken and you cannot tell why.**
If you have Claude Code, ask it in the project folder — it can read the logs and
the database and tell you what happened. Otherwise open a GitHub issue and paste
what the terminal printed.
