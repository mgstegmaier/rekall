# Set up Rekall

Cold-tested end to end on 2026-09-03: an empty folder became a working install with 43
meetings from the previous 30 days compiled into 53 wiki pages, indexed, and answering
through the recall hook.

You need a Mac, Claude Code (the VS Code extension is fine), and a Fathom account. Nothing
else.

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

1. Check the machine: macOS, git, and `claude` on PATH (run `claude -p "say ok"`). If
   claude is missing, install the Claude Code CLI and re-check.
2. Ask me where my wiki should live. If I have no vault, ask for a folder (suggest
   ~/rekall-vault) and copy the contents of vault-template/ into it. If I already have an
   Obsidian vault, ask for its path and copy vault-template/wiki/ and
   vault-template/memory/ into it, skipping anything already there. In the copied
   wiki/CLAUDE.md, replace REKALL_REPO with the rekall folder's absolute path.
3. Ask me for my name, the email address Fathom knows me by, and my timezone. Write
   rekall.toml from rekall.example.toml with those and the vault path.
4. Secrets: copy .env.example to .env and set its mode to 600. Ask whether I have a
   Fathom API key. If not, tell me where in Fathom to create one and wait for me. Write
   FATHOM_API_KEY and WORK_EMAIL into .env and leave the Monday and Jira lines blank.
5. Install: run `bash install.sh` in the rekall folder and show me its output. It checks
   for python 3.11 or newer, builds graph-memory/.venv, downloads the embedding model,
   merges the hooks into ~/.claude/settings.json, copies the skills and commands into
   ~/.claude/, and loads the three com.rekall.* schedules. Claude Code will ask me to
   approve this command; that is expected, tell me to approve it. If the script stops
   on python, tell me how to install a newer one and stop.
6. Test the Fathom key by listing my most recent meeting and show me its title. If the
   call fails with a certificate error, follow the corporate-CA note in SETUP.md and
   retry once.
7. First build: run graph-memory/reindex.sh and show me the counts it prints.
8. Backfill: run scripts/fathom-pipeline.py --since <30 days ago> --no-monday in the
   background. It ingests five meetings per Claude call and a month of meetings takes
   about an hour, so carry on with the steps below while it runs. When it finishes, tell
   me how many meeting notes landed in wiki/meetings/ and how many wiki pages it wrote.
9. Test: run graph-memory/search.py with a question about my most recent meeting and
   show me the top hits.
10. Tell me in five lines: where my wiki is, what runs when, how to drop a file into
    raw/, where the logs are, and that `bash install.sh --uninstall` turns all of it off.
```

Then type `/exit` and open Claude Code again so the hooks load. Everything that writes outside
the rekall folder (hooks, skills, schedules, permission rules) goes through `install.sh`. It is
safe to re-run after a `git pull`, and `bash install.sh --uninstall` removes exactly what it
added. From here on, meetings land
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

If step 6 fails with `CERTIFICATE_VERIFY_FAILED`, run this, then retry the step.

