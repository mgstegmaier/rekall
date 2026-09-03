# Set up Rekall

Status: **spec, not yet runnable.** This file is the contract the turn-key work has to
satisfy. The table at the bottom says which step is real today and what makes the rest real.
When every row reads "real", delete the table and this paragraph.

You need a Mac, Claude Code (the VS Code extension is fine), and a Fathom account. Nothing
else. Clone this repo, open the folder in Claude Code, and paste the message below.

## The setup message

```
Set up Rekall for me, one step at a time. Read SETUP.md first. Stop and tell me if a step
fails. Never skip a failed step and never overwrite a file that already exists.

1. Check the machine: macOS, python3 3.11 or newer, git, and `claude` on PATH (run
   `claude -p "say ok"`). If claude is missing, install the Claude Code CLI and re-check.
   If python3 is too old, tell me how to install it and stop.
2. Ask me where my wiki should live. If I have no vault, ask for a folder (suggest
   ~/rekall-vault) and copy the contents of vault-template/ into it. If I already have an
   Obsidian vault, ask for its path and copy vault-template/wiki/ and
   vault-template/memory/ into it, skipping anything already there. In the copied
   wiki/CLAUDE.md, replace REKALL_REPO with this repo's absolute path.
3. Ask me for my name, the email address Fathom knows me by, and my timezone. Write
   rekall.toml from rekall.example.toml with those and the vault path.
4. Secrets: copy .env.example to .env and set its mode to 600. Ask whether I have a
   Fathom API key. If not, tell me where in Fathom to create one and wait for me. Write
   FATHOM_API_KEY and WORK_EMAIL into .env and leave the Monday and Jira lines blank.
   Test the key by listing my most recent meeting and show me its title. If the call
   fails with a certificate error, follow the corporate-CA note in SETUP.md and retry once.
5. Python environment: create graph-memory/.venv, install fastembed into it, and run
   graph-memory/fetch_model.sh. Confirm the model folder exists.
6. First build: run graph-memory/reindex.sh and show me the counts it prints.
7. Backfill: run scripts/fathom-pipeline.py --since <30 days ago> --no-monday. Tell me
   how many meeting notes landed in wiki/meetings/ and how many wiki pages ingest wrote.
8. Hooks: merge the UserPromptSubmit and SessionEnd entries from hooks.json into the hooks
   block of ~/.claude/settings.json, keeping everything already there, with __REPO__
   replaced by this repo's absolute path.
9. Skills: copy each folder in skills/ into ~/.claude/skills/ and each file in commands/
   into ~/.claude/commands/, skipping any that already exist, and replace __REPO__ in the
   copies with this repo's absolute path.
10. Schedules: copy the three plists in launchd/ to ~/Library/LaunchAgents/, replacing
    __REPO__ with this repo's absolute path, __HOME__ with my home folder, and __PYTHON__
    with the absolute path of the python3 from step 1. Create ~/.config/rekall/logs/. Load
    each one and show me `launchctl list | grep rekall`.
11. Test: run graph-memory/search.py with a question about my most recent meeting and
    show me the top hits.
12. Tell me in five lines: where my wiki is, what runs when, how to drop a file into
    raw/, where the logs are, and how to turn all of it off.
```

Then type `/exit` and open Claude Code again so the hooks load. From here on, meetings land
in your wiki within the hour, anything you save into `wiki/raw/` gets compiled on the next
run, and every session you close is written up and indexed by morning.

## Corporate CA note

On a company laptop whose security proxy re-signs HTTPS, Python's `urllib` rejects Fathom's
certificate. The fix is a combined CA bundle that the pipeline picks up automatically when
it exists. Replace `PROXY_CA_NAME` with the name of the proxy's root certificate as it appears
in Keychain Access under System > Certificates:

```bash
mkdir -p ~/.config/rekall
security find-certificate -a -c "PROXY_CA_NAME" -p /Library/Keychains/System.keychain > ~/.config/rekall/corp-ca.pem
cat "$(python3 -c 'import certifi; print(certifi.where())')" ~/.config/rekall/corp-ca.pem > ~/.config/rekall/ca-bundle.pem
```

If step 4 fails with `CERTIFICATE_VERIFY_FAILED`, run this, then retry the step.

## What is real today

| Step | Depends on | State |
|------|-----------|-------|
| 1 machine check | nothing | real |
| 2 vault template | `vault-template/`: generic `wiki/CLAUDE.md` schema, empty `index.md` and `log.md`, the type folders, `raw/`, `meetings/`, and `memory/sessions/` for digests. Done 2026-09-03 | real |
| 3 config | `rekall.toml` (from `rekall.example.toml`) read by every script through `rekall_config.py`; vault path, data path, name, timezone, Monday board and group. Done 2026-09-03 | real |
| 4 secrets | `.env.example` in the repo (Fathom required; Monday and Jira stubbed). `run-fathom-pipeline.sh` loads `.env` when it exists, else Doppler. Blank Monday token skips the push. Corp CA handling already exists | real |
| 5 venv + model | `fetch_model.sh`, model dir from config | real |
| 6 first build | `reindex.sh`, paths from config | real |
| 7 backfill | `--since` and `--no-monday`; email filter from `.env`, board from config | real |
| 8 hooks | `hooks.json` at repo root with the two entries (`__REPO__` placeholder). Done 2026-09-03 | real |
| 9 skills | `skills/wiki`, `skills/wrap-up` (generic version), and `commands/fathom-sync.md` (`__REPO__` placeholder) are in the repo. Done 2026-09-03 | real |
| 10 schedules | `launchd/` holds three templates named `com.rekall.*` with `__REPO__`, `__HOME__`, `__PYTHON__` placeholders. Mike's installed `com.heckatron.*` agents keep running until he migrates | real |
| 11 test | `search.py` | real |
| 12 summary | nothing | real |
