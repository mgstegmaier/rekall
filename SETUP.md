# Set up Rekall

Cold-tested end to end on macOS on 2026-09-03: an empty folder became a working install with
43 meetings from the previous 30 days compiled into 53 wiki pages, indexed, and answering
through the recall hook. The Windows path landed on 2026-09-10 and has not had its own cold
test yet, so on Windows expect to read the errors rather than trust the script.

You need a Mac or a Windows 10-or-later machine, Claude Code (the VS Code extension is fine),
and a Fathom account. Rekall also needs Python 3.11 or newer; if the machine doesn't have it,
setup offers to install it and asks before it does. On Windows, Claude Code already requires Git for Windows, and
every step below runs in the Git Bash it installs.

## The short way

Open Claude Code in the folder where you want Rekall to live and paste this. Claude clones the
repo and tells you what to do next.

```
Clone https://github.com/mgstegmaier/rekall into a folder called rekall here. Then tell me
to open the rekall folder in Claude Code and paste the setup message from rekall/SETUP.md.
```

Opening the rekall folder matters: the repo carries its own Claude Code permission rules
(`.claude/settings.json`), and they only load when Claude Code runs inside that folder. They
make the one step that writes outside the repo ask for your approval instead of failing.

## The setup message

If you already cloned the repo, open Claude Code in the `rekall` folder and paste this instead.
"The rekall folder" below means the folder this file is in.

```
Set up Rekall for me, one step at a time. Read SETUP.md first. Stop and tell me if a step
fails. Never skip a failed step and never overwrite a file that already exists.

1. Check the machine: macOS or Windows 10 or later, git, and `claude` on PATH (run
   `claude -p "say ok"`). If claude is missing, install the Claude Code CLI and re-check.
   Tell me which OS you found, because steps 5, 8 and 10 branch on it. On Windows, also
   confirm Git Bash exists at `C:\Program Files\Git\bin\bash.exe` and run every later
   step in it, not in PowerShell.
   Then check for Python 3.11 or newer the way install.sh does: try python3.13,
   python3.12, python3.11, python3 and python, and take the first one that reports 3.11
   or newer. The Windows `python3` that only opens the Microsoft Store doesn't count. If
   none qualifies, tell me what you found and ask before installing anything. On my yes:
   - macOS with Homebrew (`brew` on PATH): run `brew install python@3.13`.
   - macOS without Homebrew: download the current macOS installer from
     https://www.python.org/downloads/macos/, open it, and tell me to click through it.
     It asks for my Mac password, so I do that part, not you. Wait until I say it's done.
   - Windows: run `winget install -e --id Python.Python.3.13 --scope user`. It needs no
     admin rights. The new Python isn't on PATH for this session, so tell me to type
     `/exit`, open Claude Code in the rekall folder again, and paste this setup message
     again.
   Re-check after the install. If there's still no Python 3.11 or newer, stop.
2. Ask me where my wiki should live. If I have no vault, ask for a folder (suggest
   ~/rekall-vault) and copy the contents of vault-template/ into it. If I already have an
   Obsidian vault, ask for its path and copy vault-template/wiki/ into it, skipping
   anything already there. In the copied
   wiki/CLAUDE.md, replace REKALL_REPO with the rekall folder's absolute path.
3. Ask me for my name, the email address Fathom knows me by, and my timezone. Write
   rekall.toml from rekall.example.toml with those and the vault path.
4. Secrets: they go in the system keychain (macOS Keychain, Windows Credential Manager), not a
   file. Don't create a .env. If graph-memory/.venv doesn't exist yet, create it and run
   `pip install keyring` in it (install.sh in step 5 reuses it). Then start
   `scripts/setup-server.py` with the venv interpreter (the same one step 8 uses), open
   http://localhost:8086 for me, and ask whether I have a Fathom API key. If not, tell me
   where in Fathom to create one (Settings, Integrations, API) and wait for me. I paste
   FATHOM_API_KEY and WORK_EMAIL into the page and click Save keys. Wait until the page shows
   both as Present, then stop the server. Leave Monday and Jira alone.
5. Install: run `bash install.sh` in the rekall folder and show me its output. It checks
   for python 3.11 or newer, builds graph-memory/.venv, downloads the embedding model,
   merges the hooks into ~/.claude/settings.json, copies the skills and commands into
   ~/.claude/, registers the rekall MCP server in Claude Desktop's config if Claude Desktop
   is installed, and loads the three com.rekall.* schedules (launchd agents on macOS, Task
   Scheduler tasks on Windows; on Windows it also adds tzdata to the venv, because Windows
   ships no timezone database). Claude Code will ask me to approve this command; that is
   expected, tell me to approve it. If the script stops on python, tell me how to install
   a newer one and stop.
6. Test the Fathom key by listing my most recent meeting and show me its title. If the
   call fails with a certificate error, follow the corporate-CA note in SETUP.md and
   retry once.
7. First build: run graph-memory/reindex.sh and show me the counts it prints.
8. Backfill: run scripts/fathom-pipeline.py --since <30 days ago> --no-monday in the
   background, with the venv interpreter (graph-memory/.venv/bin/python on macOS,
   graph-memory/.venv/Scripts/python.exe on Windows). The system python lacks certifi on
   macOS and tzdata on Windows, and the venv has both. It ingests five
   meetings per Claude call and a month of meetings takes about an hour, so carry on with
   the steps below while it runs. When it finishes, tell me how many meeting notes landed
   in wiki/meetings/ and how many wiki pages it wrote.
9. Test: run graph-memory/search.py with the same venv interpreter as step 8, asking a
   question about my most recent meeting, and show me the top hits.
10. Tell me in five lines: where my wiki is, what runs when (name the schedule mechanism
    for my OS: `launchctl list | grep rekall` on macOS, `schtasks /Query /TN com.rekall.*`
    on Windows), how to drop a file into raw/, where the logs are, and that
    `bash install.sh --uninstall` turns all of it off.
```

Then type `/exit` and open Claude Code again so the hooks load. If you use Claude Desktop, quit
and reopen it too, so it starts the rekall MCP server; "Use your wiki from Claude Desktop chat" in
`README.md` covers checking it and getting chat to use it. Everything that writes outside
the rekall folder (hooks, skills, schedules, permission rules, the Claude Desktop MCP entry) goes through `install.sh`. It is
safe to re-run after a `git pull`, and `bash install.sh --uninstall` removes exactly what it
added. From here on, meetings land
in your wiki within the hour, anything you save into `wiki/raw/` gets compiled on the next
run, and every session you close is written up and indexed by morning.

## Optional: mail and Teams chats into project pages

`scripts/graph-ingest.py` reads your Outlook mail and the Teams chats you pick, through Microsoft
Graph, and adds new facts and decisions to the matching wiki project pages. It's off until you turn
it on, and an install that never turns it on behaves exactly as before. It only reads: it never
sends mail, posts to Teams, or changes anything in your mailbox.

How a message reaches a page:

- An email thread matches a project page when its subject names the project: the page's file name,
  `title`, an entry in `aliases`, or its `monday_label`. "RE: Apollo launch plan" matches
  `apollo.md`. A chat matches on its topic and the text of its new messages.
- A term that two pages share, like a Monday label used by several projects, matches neither.
- A thread that matches no page is dropped. Its body is never fetched and nothing about it is kept.
- For a matched thread, one Haiku call through `claude -p` picks out only facts the page doesn't
  already have. Each lands as one bullet in a dated entry at the top of the page's `## Updates`,
  citing the email subject or chat name, the sender, and the date. Full messages never reach the
  vault. Each run adds one line to `wiki/log.md`.
- A thread read again on the next run adds nothing. Token use per call goes to
  `~/.config/rekall/logs/graph-usage.jsonl`.

You need a Microsoft Entra app registration with the delegated permissions `User.Read`,
`Mail.Read`, `Chat.Read`, `Chat.ReadBasic` and `offline_access`. Your IT team may already have one
for your group. Ask for its client ID and tenant ID, and whether "Allow public client flows" is on.

- If public client flows are on, you need no client secret. The settings page signs you in with a
  device code.
- If they're off, you also need a client secret, and the app must list `http://localhost:8086` as a
  "Mobile and desktop applications" redirect URI.

1. Save `MSGRAPH_CLIENT_ID` and `MSGRAPH_TENANT_ID` from the app registration to the keychain.
   Save `MSGRAPH_CLIENT_SECRET` only if the app has public client flows turned off. The settings
   page has no fields for these, so run this once per value with the venv interpreter:
   `python3 -c "import rekall_config as r; r.set_secret('MSGRAPH_CLIENT_ID', 'the-value')"`.
   If another tool already signed you in to the same app and can export these values, it can
   write them for you, refresh token included, and you can skip step 3's sign-in.
2. Run `python3 scripts/setup-server.py` in the rekall folder and open http://localhost:8086. If
   you use a secrets manager (see "Power users" below), run it under the manager's command, such
   as `doppler run --`, so the page can see the values.
3. On the settings page, check that every required secret shows "Present". Click **Sign in with
   Microsoft**.
   - With no client secret, the page shows a code and a Microsoft link. Open the link, enter the
     code, and sign in. The page notices within a few seconds.
   - With a client secret, the browser goes to Microsoft and comes back.

   Either way, the page then shows who you're signed in as, and `MSGRAPH_REFRESH_TOKEN` is in
   your keychain. If sign-in fails with `AADSTS7000218`, the app needs a client secret (public client
   flows are off). If it fails with `AADSTS50011`, the redirect URI on the app doesn't match
   `http://localhost:8086` exactly.
4. Click **Load my chats** and tick the chats to include. Nothing is read from a chat you don't
   tick.
5. Tick **Turn on the Graph ingest** and click **Save to rekall.toml**. Only the `[graph]` section
   of `rekall.toml` changes. Stop the server with Ctrl-C.
6. Run a dry run, which prints what it would write for the last 24 hours and writes nothing:

   ```bash
   bash scripts/run-graph-ingest.sh --dry-run --hours 24
   ```

7. When the dry run looks right, run it once without `--dry-run`, and read the new entries on the
   pages it names.
8. To change any of this later, run `python3 scripts/setup-server.py` again. The page reads
   `rekall.toml` and your secrets fresh each time it loads.
9. To run it every weekday hour from 07:45 to 17:45, run `bash install.sh --with-graph` (macOS
   only). `bash install.sh --uninstall` removes it with everything else.

The refresh token expires after 90 days without use. When it does, the job sends a notification
naming `AADSTS700082`; sign in again from the setup page.

## Power users: a secrets manager

If you keep secrets in Doppler or a similar tool, skip the settings page's key fields and add one
line to `rekall.toml`:

```toml
[secrets]
run_prefix = "doppler run --project myproject --config dev --"
```

The launchers run every scheduled job under that prefix, so the keys arrive as environment
variables. Rekall looks for each secret in the environment first, then the keychain, then a
legacy `.env` in the rekall folder, so existing `.env` files keep working.

## macOS Keychain prompt

The first scheduled run after you save a key may pop up a Keychain prompt asking whether python
can read it. Click **Always Allow**, or every hourly run will wait on the prompt.

## Corporate CA note

On a company laptop whose security proxy re-signs HTTPS, Python's `urllib` rejects Fathom's
certificate. On Windows this usually does not happen, because Python there reads the system
certificate store, which already trusts the proxy. If step 6 does fail on Windows with
`CERTIFICATE_VERIFY_FAILED`, find the proxy root with `certutil -store Root`, export it to
`~/.config/rekall/corp-ca.pem`, and build the same combined bundle as below, using
graph-memory/.venv/Scripts/python.exe in the `cat` line.

The macOS recipe. The fix is a combined CA bundle that the pipeline picks up automatically
when it exists. Replace `PROXY_CA_NAME` with the name of the proxy's root certificate as it appears
in Keychain Access under System > Certificates:

```bash
mkdir -p ~/.config/rekall
security find-certificate -a -c "PROXY_CA_NAME" -p /Library/Keychains/System.keychain > ~/.config/rekall/corp-ca.pem
cat "$(graph-memory/.venv/bin/python -c 'import certifi; print(certifi.where())')" ~/.config/rekall/corp-ca.pem > ~/.config/rekall/ca-bundle.pem
```

Run the `cat` line from the rekall folder. It uses the venv's python because the system
python3 usually has no certifi, and the pipeline runs under the venv anyway.

If step 6 fails with `CERTIFICATE_VERIFY_FAILED`, run this, then retry the step.

