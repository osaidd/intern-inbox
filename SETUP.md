# Setup

The long version of the quickstart. Follow it top to bottom and you will have a
working internship inbox in about 15 minutes. Nothing here assumes you have
written code before.

You need a [Claude Code](https://claude.com/claude-code) subscription. Most of
the setup happens by talking to Claude Code, so this is required.

---

> **Shortcut:** steps 1 and 2 are one paste in Terminal:
> `curl -LsSf https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.sh | sh`
> It installs uv if needed, downloads the project to `~/intern-inbox`, and
> installs dependencies. Then jump to step 3.

## 1. Install uv

`uv` is the tool that installs Python and the project's dependencies. One
command.

**Mac (Terminal):**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close the terminal and open a new one, then check it worked:

```bash
uv --version
```

If that prints a version number, you are done with this step. If it says command
not found, the new terminal did not pick up the install — close every terminal
window and open a fresh one.

## 2. Get the code

```bash
git clone https://github.com/osaidd/intern-inbox.git intern-inbox
cd intern-inbox
uv sync
```

`uv sync` downloads Python and every dependency into a folder inside the
project. It takes a minute the first time. It touches nothing else on your
computer.

## 3. Run /setup in Claude Code

Open the `intern-inbox` folder in Claude Code (File → Open… and pick the folder
itself — not your home folder, not Desktop) and type:

```
/setup
```

Two things that trip people up:

- **`/setup` not recognized?** Claude Code has the wrong folder open. Open the
  `intern-inbox` folder itself and try again.
- **Run it on your own computer.** A claude.ai cloud session runs in a sandbox
  that cannot reach the job-board APIs — the pull will fail there with
  "host not allowed" errors that have nothing to do with your setup.

Claude Code will (it also shows you the default company filters — big-tech names are excluded out of the box unless you say otherwise):

1. **Ask a few questions** — the kinds of roles you want, what you are good at,
   any dealbreakers, dream companies, and the email address where you want job
   alerts.
2. **Read your resume.** Drop the PDF into the `intern-inbox` folder, or paste
   the text into the chat.
3. **Write your config.** Four files: `config/career.toml`,
   `config/sources.local.toml`, `config/.env`, and `profile/profile.md`. All
   four are gitignored, so they never leave your laptop and cannot end up in a
   pull request.
4. **Walk you through the manual bits** — the Gmail app password and the job
   alerts. Those are steps 4 and 5 below; Claude Code waits for you at each one.
5. **Run a first pull** and open the app at http://127.0.0.1:8477.

The app cannot send any email until you add `CAREER_SMTP_PASS` to `config/.env`
yourself. `/setup` never adds it, so out of the box nothing is sent anywhere.
Adding it turns on the **Email ♥** button in the app (step 6); the automatic
digests after each check also need `enabled = true` under `[email]` in
`config/career.toml`.

You can run `/setup` again any time — it asks what you want to update instead
of starting over. The most useful re-run: say **"update my resume"** after you
revise it, and your profile keywords and rankings follow the new version (you
see the before/after diff first). The resume file stays on your machine.

## 4. Gmail app password

This lets the app read job-alert emails out of your inbox. It is a separate
16-character password that only works for this one purpose, and you can revoke
it at any time. Your real Google password is never used or stored.

1. Go to <https://myaccount.google.com/security>.
2. Turn on **2-Step Verification** if it is not on already. App passwords do not
   exist without it. Google will walk you through it with your phone.
3. Go to <https://myaccount.google.com/apppasswords>.
4. In the **App name** box, type `intern-inbox`, then click **Create**.
5. A yellow box shows a 16-character code in four groups. Copy it.
6. Open `config/.env` in the project folder and put the code after
   `CAREER_IMAP_PASS=`, with the spaces removed:

   ```
   CAREER_IMAP_PASS=abcdefghijklmnop
   ```

7. Save the file. Click **Done** in Google.

If the app-passwords page says the option is not available for your account,
that is 2-Step Verification not being fully on yet. Go back to step 2.

By default the app reads the address you gave in `/setup`. To use a different
mailbox, add `CAREER_IMAP_USER=you@gmail.com` to `config/.env` as well.

## 5. Turn on job alerts

The email feed only sees what actually arrives in your inbox, so you have to
subscribe to the alerts yourself. Use the same address from step 4.

- **LinkedIn** — <https://www.linkedin.com/jobs/>. Search each role you want plus
  the word "internship", set the location to New York, then turn on the alert
  toggle at the top of the results. Choose **Daily**. Do this once per search.
- **Built In NYC** — <https://builtin.com/nyc>. Make an account, filter for
  internships, and save the search as a job alert.
- **Wellfound** — <https://wellfound.com/jobs>. In your profile settings, turn on
  email alerts for roles that match you.

Alerts take up to a day to start arriving. Zero email results on day one is
normal and not a bug — the company boards still bring in listings meanwhile.

## 6. The daily loop

```bash
uv run intern-inbox
```

Then open <http://127.0.0.1:8477>. Two tabs at the top:

- **Inbox** — everything from your alert emails, the GitHub lists, and JobSpy.
- **ATS boards** — internships pulled straight from company job boards.

Press **Check now** to pull fresh listings. Then go down the list: heart the ones
worth applying to, X the ones that are not, and move a row to **Applied** once
you have applied. Press **CSV** to export.

The **Email ♥** button emails you everything you have hearted or applied to. It
needs `CAREER_SMTP_PASS` in `config/.env` — the app password from step 4 works.
Without it the button shows "email failed: CAREER_SMTP_PASS not set", which is
expected, not a broken install. Ignore the button if you do not want the email.

Run `git pull` every week or so — other students add company boards, and you get
them for free.

Optional, Mac only: `automation/install-intern-inbox-app.sh` makes an app icon in
`~/Applications` that does the start-and-open in one click. Add `--dock` to pin
it to the Dock.

## Windows notes

Everything works, with two differences.

- Run `uv run intern-inbox` from PowerShell, Windows Terminal, or the Claude Code
  terminal — any terminal, from inside the project folder. The browser link is
  the same: <http://127.0.0.1:8477>.
- The Mac app-icon script does not apply. Skip that section.

If you want the shared company boards to refresh on their own every morning,
open **Task Scheduler**, create a basic daily task, and set the action to run
this (adjust the path to where you cloned it):

```
uv run --directory C:\Users\you\intern-inbox python -m feeds.ats_pull
```

That is optional. Pressing **Check now** in the app does the same thing.

## Troubleshooting

**"address already in use" / the page will not load.**
Something else is on port 8477 — often a copy of the app you already started.
Use a different port:

```bash
uv run intern-inbox --port 8500
```

Then open <http://127.0.0.1:8500>.

**A check finishes but JobSpy reports an error.**
JobSpy scrapes public job boards and those boards rate-limit. It fails some days
and works the next. Press **Check now** again later. The other sources are
unaffected.

**No email listings on day one.**
Expected. Your alerts have not been sent yet. Give it a day.

**"CAREER_IMAP_PASS missing".**
Step 4 was not finished, or the code went into the wrong file. It belongs in
`config/.env`, on its own line, no quotes, no spaces in the code.

**Nothing shows up at all.**
Check the filters at the top of the list — the status dropdown may be on
something narrow. If the list is genuinely empty, run the board sweep directly
and read what it prints:

```bash
uv run python -m feeds.ats_pull
```

**Something looks broken and you cannot tell why.**
Ask Claude Code in the project folder. It can read the logs and the database and
tell you what happened.
