# Rekall changelog

The changes that affect an installed Rekall, newest first. Rekall has no version numbers, so each entry is dated and links the pull request or commit that made it.

To upgrade, run `git pull` and then `bash install.sh` in the rekall folder (see "Upgrading" in the README). An entry marked **Re-run install.sh** changes something the installer writes outside the repo, such as the Claude Code hooks, the Claude Desktop MCP entry, or the venv packages, so `git pull` alone doesn't pick it up.

## 2026-10-24

- The settings page has a **Sign in to Claude** button. It runs `claude setup-token`, which opens the Claude sign-in in your browser, and saves the token it prints to your system keychain as `CLAUDE_CODE_OAUTH_TOKEN`. The token never appears on the page or in a log. A **Test** button makes one background call the way the scheduled jobs do. If the sign-in can't capture the token, you can paste one from `claude setup-token` into the keys form. The Fathom pipeline, the reindex distiller, the session digest and the Graph ingest pass the stored token to `claude -p`, so they no longer depend on an interactive login. Without a stored token they use the CLI's own login, as before. `install.sh --standard` requires the sign-in before **Finish setup**.
- Rekall watches its Claude sign-in. When a background `claude -p` call is refused (`Not logged in`, an expired or invalid token), the job writes `~/.config/rekall/claude-auth-failed`. The next successful call deletes it. The settings page records when it saved the token in `~/.config/rekall/claude-token.json`, and the hourly pipeline treats a token 330 days old or older as close to expiry. In either case, a macOS dialog asks you to sign in again, at most once a day. Its **Sign in** button runs `scripts/setup-server.py --reauth`, which opens the Claude sign-in in your browser, saves the new token, tests it, and posts a notification. The recall hook also shows the problem in Claude Code and gives Claude the command, so you can ask Claude to sign you back in.
- On a new install, `install.sh --standard` starts the 30-day Fathom backfill in the background when it finishes. Progress goes to `~/.config/rekall/logs/backfill.log`, and closing Terminal doesn't stop it.

## 2026-10-23

- New installs on macOS can start from one Terminal command: `curl -fsSL https://raw.githubusercontent.com/mgstegmaier/rekall/main/bootstrap.sh | bash`. `bootstrap.sh` installs git (Apple's Command Line Tools), Python 3.13 (through uv, with no admin password), and the Claude Code CLI when they're missing. It clones the repo to `~/rekall/repo` and runs `install.sh --standard`, which writes `rekall.toml` with your macOS name and timezone. The installer then opens the settings page in your browser. You pick a vault there, either one Obsidian already has open or a new one at `~/rekall/vault`, and you save your Fathom key and work email. When you click **Finish setup**, the page closes itself and the installer carries on. The installer copies the vault template only into a vault that has no `wiki/` folder. Set `REKALL_VAULT=/path` to preset the vault. The settings page now takes the next free port up to 8095 when 8086 is in use. With the standard layout, the installer also links `~/Documents/rekall` to `~/rekall` so the folder shows up in Finder. It skips the link when anything already exists at that path, and `--uninstall` removes it only when it's still that link. When `bootstrap.sh` finds an existing install through its `com.rekall.wiki-reindex` agent, it updates that repo in place and never creates a second install. The example config now defaults to `~/rekall/vault` and `~/rekall/data` instead of `~/rekall-vault` and `~/rekall-data`. Existing installs keep the paths in their own `rekall.toml`, so nothing moves.
- On Windows, the scheduled tasks start bash through `conhost.exe --headless`, so no terminal window opens on each run. Before this change, every run of the reindex, Fathom pipeline, Granola sweep, and lint tasks opened a blank Git Bash window until it finished. Output still goes to `~/.config/rekall/logs/`. **Re-run install.sh** to re-register the tasks.

## 2026-10-22

- `vault-template/wiki/CLAUDE.md` now carries the relation fields (`owner`, `people`, `maintainers`, `depends_on`, `about`, `part_of`, `runs_on`, `reads_from`, `writes_to`, `attendees`), the `plan`, `note`, `decision` and `context` types, and the `sessions/`, `plans/` and `meetings/transcripts/` folders. The ingest agent reads this file on every run, so without it no relation fields get written. The template also gains the six Bases (`people`, `projects`, `entities`, `concepts`, `summaries`, `meetings`) the index header points to. Setup copies the template only once, so an existing vault keeps its old copy. **Copy `vault-template/wiki/CLAUDE.md` and `vault-template/wiki/*.base` into your vault's `wiki/` folder**, keeping any rules you added to your own `CLAUDE.md`.
- Meeting ingest creates or updates a person page for each attendee the note shows making a decision, holding a stated role, or working on a project, citing the meeting. Attendees who are only listed get no page. Action items stay in the meeting note and never appear on a person page, because nothing tracks whether they closed. Before this change, person pages were updated only when the agent happened to treat someone as a major entity, and a fresh vault got almost none. This costs extra ingest tokens per meeting. The rule lives in `skills/wiki/SKILL.md`, which the installer copies once and then skips. **Delete `~/.claude/skills/wiki`, then re-run install.sh** to get the new copy.
- `wiki-index.py` double-quotes an unquoted `title` or `description` that YAML would reject, such as `description: Sigma at Acme: Radar results`. One such line made Obsidian drop the page's whole frontmatter block and show it as body text. The index runs after every ingest, so this repairs pages already written.
- The scheduled jobs run Python in UTF-8 mode (`PYTHONUTF8=1`). On Windows, Python otherwise reads and writes files as cp1252, which garbles box-drawing characters and arrows and fails on characters cp1252 lacks.

## 2026-10-21

- Rekall hooks never block a prompt. Before this change, a missing `recall_hook.py` made Python exit 2, and Claude Code treats exit 2 from a `UserPromptSubmit` hook as a block, so every prompt was rejected. Both hook commands now check that the script exists first and exit 0 on any failure. When recall can't run, Claude Code shows `rekall unavailable: <reason>` and the reason is logged to `~/.config/rekall/logs/hook.log`. The installer replaces your old hook commands; it doesn't add the new ones beside them. **Re-run install.sh.** ([#16](https://github.com/mgstegmaier/rekall/pull/16))

## 2026-10-20

- Secrets are stored in the OS keychain by default, and the settings page opens at the end of install. **Re-run install.sh** (it adds `keyring` to the venv). ([#15](https://github.com/mgstegmaier/rekall/pull/15))

## 2026-10-19

- The Fathom pipeline skips the Monday push when `rekall.toml` has no `[monday]` board. ([#14](https://github.com/mgstegmaier/rekall/pull/14))

## 2026-10-18

- Wiki pages live in per-type folders, `pages/<type>/<slug>.md`. Scripts read `pages/` recursively, `wiki-lint.py` warns about a page outside its type folder, and `scripts/wiki-type-folders.py` moves misfiled pages. ([#13](https://github.com/mgstegmaier/rekall/pull/13))
- When two recall results score close together, recall prefers the more recent one. The first reindex after upgrading rebuilds the index once. ([#12](https://github.com/mgstegmaier/rekall/pull/12))

## 2026-10-16

- Microsoft Graph sign-in uses a device code on the settings page, so it needs no client secret. ([#11](https://github.com/mgstegmaier/rekall/pull/11))
- The Graph ingest skips Outlook meeting notices. ([#10](https://github.com/mgstegmaier/rekall/pull/10))
- Optional Microsoft Graph ingest: new facts and decisions from mail and Teams go onto the project pages a thread names. A local setup page configures it. ([#9](https://github.com/mgstegmaier/rekall/pull/9))

## 2026-10-07

- An MCP server gives Claude Desktop chat two wiki tools, `search_wiki` and `read_page`. **Re-run install.sh**, then restart Claude Desktop. ([`7f55d1b`](https://github.com/mgstegmaier/rekall/commit/7f55d1b), [#7](https://github.com/mgstegmaier/rekall/pull/7))
- The recall hook skips the canned prompts sent by the open-asks pane buttons. ([`334030a`](https://github.com/mgstegmaier/rekall/commit/334030a))

## 2026-09-24

- Cost audit: the session digest's auth is fixed, and recall, ingest, and reindex each do less work per run. ([`7190513`](https://github.com/mgstegmaier/rekall/commit/7190513))

## 2026-09-15

- Optional Granola sweep brings Granola notes into the wiki beside Fathom's. ([`0f29243`](https://github.com/mgstegmaier/rekall/commit/0f29243))

## 2026-09-13

- The wiki graph has typed edges (owns, maintains, depends_on, and others) from relation frontmatter. The recall hook leaves out plain `mentions` edges. ([`be95515`](https://github.com/mgstegmaier/rekall/commit/be95515), [`755e727`](https://github.com/mgstegmaier/rekall/commit/755e727))

## 2026-09-10

- Rekall installs on Windows. ([`7dcecc8`](https://github.com/mgstegmaier/rekall/commit/7dcecc8))

## 2026-09-05

- The index runs in WAL mode, so a reindex never blocks the recall hook. ([`3ad2cf5`](https://github.com/mgstegmaier/rekall/commit/3ad2cf5))

## 2026-09-04

- `install.sh` performs every setup step that writes outside the repo, and re-running it is safe. `bash install.sh --uninstall` reverses it. ([#1](https://github.com/mgstegmaier/rekall/pull/1))
- Wiki pages carry a lifecycle `status` (active, retired, archive). ([`76be8be`](https://github.com/mgstegmaier/rekall/commit/76be8be))

## 2026-09-03

- First public release.
