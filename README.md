# Rekall

We remember it for you wholesale.

Rekall gives Claude Code a memory of your work. Every session you close is written up as a note: what happened, what you decided, what you learned, and what's still open. Your meetings and the documents you drop in become notes too. Before each prompt in your next session, Rekall finds the notes that bear on it and hands them to Claude, so you can ask "what did we decide about the retry logic last week?" and get the answer from your own record without pointing Claude at it.

The notes live in your own vault (Obsidian or any folder of markdown). Rekall never owns your content. It writes into the vault, indexes it, and answers questions from it.

Named after the memory-implant company in *Total Recall*.

## Getting started

You need a Mac, Claude Code (the VS Code extension is fine), and a Fathom account. Open Claude Code in the folder where you want Rekall to live and paste this:

```
Clone https://github.com/mgstegmaier/rekall into a folder called rekall here. Then tell me
to open the rekall folder in Claude Code and paste the setup message from rekall/SETUP.md.
```

Then open the `rekall` folder in Claude Code and paste the setup message from `SETUP.md`. Claude walks you through the questions (where your wiki should live, your Fathom key, your timezone), runs `install.sh` for the index, the hooks, and the schedules (it asks you to approve that one command), and backfills your last 30 days of meetings. When it finishes, type `/exit` and open Claude Code again so the hooks load. `SETUP.md` has the full step list and the corporate-proxy fix if your laptop rewrites HTTPS.

## Upgrading

In the rekall folder, run these two commands:

```bash
git pull
bash install.sh
```

`git pull` brings in the new code. Re-running `install.sh` refreshes everything it writes outside the repo: the Claude Code hooks, the skills and commands in `~/.claude/`, the venv packages (brought to their pinned versions), the Claude Desktop MCP entry, and the schedules. It replaces older copies instead of adding duplicates, and a second run with nothing changed prints `unchanged` for each copy. It never overwrites a skill or command you changed, a file it didn't write, or a symlink. It names each one and prints the `mv` command that installs the new version and the `diff` command that compares them afterwards. Hand edits to the `com.rekall.*` schedules are overwritten. The installer doesn't remember optional flags, so pass the ones you installed with again (`bash install.sh --with-graph`, `--with-granola`, `--with-repos`). Without the flag, that schedule stays in place but isn't refreshed. After you change `[vault].path` or `[data].state` in `rekall.toml`, re-run `install.sh`; the old state folder isn't moved. Then type `/exit` and open Claude Code again so any changed hooks load. [`CHANGELOG.md`](CHANGELOG.md) lists what changed, and which changes need the `install.sh` step.

`bash install.sh --standard` also opens the setup page for the keys and the Sign in to Claude button; `python3 scripts/setup-server.py --reauth` signs in again when the expiry dialog appears. At the end, `install.sh` makes one test call to Claude and prints a warning if it doesn't answer.

One machine runs one Rekall install. `install.sh` refuses to run from a second clone or a git worktree while another clone owns the install, and prints the `--uninstall` command that moves the install. To run the scripts against a test vault without installing anything, point them at another config with `REKALL_CONFIG=/path/to/test.toml`.

If `install.sh` fails partway, fix what its error names and run it again. A re-run repeats every step and changes only what differs.

## What it does

- **Recall** - a hook that runs before every Claude Code prompt and hands Claude up to five of the best hits plus entity-graph facts, so it answers from your notes without being asked to look
- **Session memory** - when you close a Claude Code session, a hook writes it up in `wiki/sessions/YYYY-MM-DD.md` under headings such as What happened, Decisions, Lessons, and Open loops. A session you resume and close again gets a continuation entry that records only what changed. The next reindex makes the entry searchable, so recall can bring back last week's decision or a lesson that cost you an afternoon. Sessions shorter than `min_turns` (default 5) are skipped. See "Session digest" in `graph-memory/README.md`.
- **Meetings and documents** - a Fathom pipeline writes one note per meeting, and a `raw/` folder takes any `.md` file you drop in, nested folders included
- **Mail and Teams (optional)** - a read-only Microsoft Graph ingest adds new facts and decisions from email threads and the Teams chats you pick to the project pages they name; `scripts/setup-server.py` is its local setup page (see SETUP.md)
- **Wiki** - a headless Claude call compiles those sources into interlinked pages (people, projects, entities, concepts), every claim cited, in Karpathy's LLM Wiki pattern
- **Index** - a local SQLite index over the wiki: keyword search, embeddings from a 67 MB model on your CPU, and an entity graph built from the wikilinks
- **Repo mirrors (optional)** - read-only copies of the GitHub repos you list, fetched twice a day, so Claude reads current `main` instead of a stale clone (see "Read your GitHub repos" below)
- **MCP server** - Claude Desktop chat has no prompt hook, so `install.sh` registers a read-only MCP server there with two tools, `search_wiki` and `read_page`, over the same index (see "Use your wiki from Claude Desktop chat" below)

## What it is not

- Not a note store. Your vault stays the source of truth, in plain markdown, portable, yours.
- Not a hosted service. Indexing and search run on your machine and send nothing anywhere. Rekall makes network calls to these destinations only:
  - `api.fathom.ai`: the Fathom pipeline fetches your meetings.
  - Anthropic, through the `claude` CLI: the calls that write pages, digests, distillations, and mail and Teams facts. Your text goes to Claude for these.
  - `api.monday.com`: the Fathom pipeline pushes meeting items to Monday. Optional: it needs a Monday token, and `--no-monday` skips it.
  - `graph.microsoft.com` and `login.microsoftonline.com`: the optional mail and Teams ingest, and its sign-in on the settings page.
  - `public-api.granola.ai`: the optional Granola sweep, scheduled only with `install.sh --with-granola`.
  - `huggingface.co`: `graph-memory/fetch_model.sh` downloads the embedding model once, at install. `pip` also fetches the Python packages then.
  - `github.com`: the optional repo sync fetches the repos you list under `[repos]`, scheduled only with `install.sh --with-repos`.

## Use your wiki from Claude Desktop chat

Chat in the Claude desktop app has no prompt hook, so it can't receive recall hits the way Claude Code does. It reaches your wiki through Rekall's local MCP server (`graph-memory/mcp_server.py`) instead. The server runs on your machine, reads the same index, and never writes anything. It gives chat two tools:

- `search_wiki(query, section)` returns up to five matching chunks, each labeled `[file § section]`, plus any entity-graph facts. `section` is optional. When given, it keeps only chunks under that heading, matched exactly and ignoring case, so `section="Decisions"` or `section="Open loops"` returns just those parts of past session digests, and the graph facts are left out.
- `read_page(name)` returns one note by its file name without `.md`, such as `index` or `log`, or by its vault-relative path. A long page comes back in parts; the reply ends with the offset to resume from.

The Code tab in the desktop app runs Claude Code, so it already gets the recall hook and doesn't need this.

To connect it:

1. Install Claude Desktop, then run `bash install.sh` in the rekall folder. If Rekall is already installed, run it again; re-running is safe. The script writes a `rekall` entry into Claude Desktop's `claude_desktop_config.json`. If the output says `Claude Desktop not found`, open Claude Desktop once so it creates its settings folder, then run the script again.
2. Quit Claude Desktop completely and open it again. Closing the window isn't enough, because the app starts MCP servers only when it launches.
3. In Claude Desktop, open Settings, then Developer. Check that `rekall` is listed and running.
4. Start a new chat and ask about something you know is in your wiki. Claude calls `search_wiki`, and the answer cites the `[file § section]` labels it found.

Claude decides for itself when to call the tools, and it sometimes answers without looking. To make it look first, add this line to your personal preferences in Claude's settings, or to the instructions of a Project you use for this work:

```
Before answering about a named project, person, system, or past decision, call search_wiki. Use read_page when a result names a page you need in full.
```

If `rekall` shows as failed under Settings > Developer, the server's log says why. On macOS it's `~/Library/Logs/Claude/mcp-server-rekall.log`, and on Windows it's `%APPDATA%\Claude\logs\mcp-server-rekall.log`. These are the usual causes:

- `No such file or directory` for the python path means the venv is missing or the rekall folder moved. Run `bash install.sh` again from the folder's current location.
- `ModuleNotFoundError: No module named 'mcp'` means the venv predates the MCP server. Run `bash install.sh` again, and it installs the package.
- A tool reply of `No index yet` means the index hasn't been built. Run `graph-memory/reindex.sh`. A reply that starts with `Search failed` carries the error that stopped the search.

`bash install.sh --uninstall` removes the `rekall` entry from Claude Desktop's config along with everything else. To write the entry by hand instead, see the MCP section of `graph-memory/README.md`, then run `python3 graph-memory/test_mcp_server.py` to check both tools against your index. `test_mcp_server_fixture.py` runs the same checks against a temporary index built from `vault-template/`.

## Read your GitHub repos

Your local clones sit on feature branches and fall behind `main`, so Claude reading them reads old code. Rekall can keep its own read-only copy of each GitHub repo you list, fetched at 07:00 and 13:00, so Claude reads current `main` without touching your clones. Each copy is a bare mirror (the git database with no checked-out files) at `<data>/repos/<name>.git`, where `<data>` is `[data].path`. It holds every branch on GitHub under `origin/*`, and nothing in it is ever run. This is macOS only.

To turn it on:

1. In `rekall.toml`, add a `[repos]` section with `enabled = true` and one `[[repos.repo]]` block per repo. `rekall.example.toml` shows the shape. `remote` is a GitHub `owner/name`, or any URL containing `://`, and `branch` defaults to `main`. A `name` is the mirror's folder name, so it takes letters, digits, `_`, `-` and `.`, and can't start with a dot.
2. Check that `gh auth status` shows you signed in. Git reaches GitHub through `gh`'s login, or through a `GH_TOKEN` in Rekall's secret store when one is saved.
3. Run `bash install.sh --with-repos`. It loads the `com.rekall.repo-sync` schedule.
4. Run `graph-memory/repo-sync.sh` once to make the first copies now instead of at the next scheduled time.

Claude finds the mirrors through the `repo-mirrors` skill, which runs `graph-memory/repo_sync.py --list` and then reads with commands such as `git -C <mirror> show origin/main:<path>` and `git -C <mirror> log -p origin/main -- <path>`. When a question is about the last few hours, the skill has Claude fetch the mirror first. Code changes still happen in your clone.

Each run writes `<state>/repo-sync-state.json` with each repo's head commit and last good sync, and logs to `<state>/logs/repo-sync.log`. A repo that fails logs `FAILED repo=<name> step=fetch: <error>` and makes the run exit 1, while the other repos still sync. A time missed while the Mac sleeps runs once when it wakes. If a repo misses two scheduled runs while you're working at the machine, the recall hook adds a `Rekall repo sync:` line naming it with its last error. A weekend with the lid shut raises nothing.

`scripts/wins-mine.py` reads your commits from these mirrors, on every pushed branch. It no longer reads `[wins].repos_dir`.

`bash install.sh --uninstall` removes the schedule and leaves the mirrors in place; it prints their folder. Delete `<data>/repos` yourself to reclaim the space. Removing a repo from `[repos]` drops it from the state file on the next run and keeps its mirror on disk, so adding it back costs no re-clone.

## Layout

```
rekall/
├── SETUP.md            # the guided install
├── CHANGELOG.md        # what changed, and when an upgrade needs install.sh
├── rekall.example.toml # settings: vault path, data path, name, timezone (copy to rekall.toml)
├── .env.example        # secrets: Fathom key, optional Monday and Jira tokens (copy to .env)
├── hooks.json          # the two Claude Code hook entries
├── vault-template/     # what setup copies into a new vault
├── launchd/            # macOS schedules: fathom-pipeline, wiki-reindex, wiki-lint, graph-ingest, granola-sweep, repo-sync
├── windows/            # Task Scheduler tasks: fathom-pipeline, wiki-reindex, wiki-lint, granola-sweep
├── scripts/            # Fathom pipeline, wiki index/lint/cleanup
├── graph-memory/       # the index, the recall hook, distillation, the session digest
├── skills/             # Claude Code skills: wiki, repo-mirrors
├── commands/           # Claude Code commands: fathom-sync
└── docs/               # vault CLI reference, prior art, plans
```

## Prior art

Andrej Karpathy's LLM Wiki pattern for the compiled wiki; Glitch Cat Club's graph-memory-starter (MIT, vendored under `graph-memory/`) for the index, hook, distillation, and digest; Cerebras's knowledge-base write-up for distil-then-embed and rank fusion. Details in `docs/prior-art.md`.
