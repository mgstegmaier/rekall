# Rekall

We remember it for you wholesale.

Rekall is the machinery around a personal knowledge wiki: capture pipelines in, a query layer out. The notes themselves live in your own vault (Obsidian or any folder of markdown). Rekall never owns your content. It ingests into it, indexes it, and answers questions from it.

Named after the memory-implant company in *Total Recall*.

## Getting started

You need a Mac, Claude Code (the VS Code extension is fine), and a Fathom account. Open Claude Code in the folder where you want Rekall to live and paste this:

```
Clone https://github.com/mgstegmaier/rekall into a folder called rekall here. Then tell me
to open the rekall folder in Claude Code and paste the setup message from rekall/SETUP.md.
```

Then open the `rekall` folder in Claude Code and paste the setup message from `SETUP.md`. Claude walks you through the questions (where your wiki should live, your Fathom key, your timezone), runs `install.sh` for the index, the hooks, and the schedules (it asks you to approve that one command), and backfills your last 30 days of meetings. When it finishes, type `/exit` and open Claude Code again so the hooks load. `SETUP.md` has the full step list and the corporate-proxy fix if your laptop rewrites HTTPS.

## What it does

- **Capture** - a Fathom pipeline writes one note per meeting; a `raw/` folder takes anything you drop in; a session-end hook writes up every Claude Code session you close
- **Wiki** - a headless Claude call compiles those sources into interlinked pages (people, projects, entities, concepts), every claim cited, in Karpathy's LLM Wiki pattern
- **Index** - a local SQLite index over the wiki: keyword search, embeddings from a 67 MB model on your CPU, and an entity graph built from the wikilinks
- **Recall** - a hook that runs before every Claude Code prompt and hands Claude the five best hits, so it answers from your notes without being asked to look
- **MCP server** - Claude Desktop chat has no prompt hook, so `install.sh` registers a read-only MCP server there with two tools, `search_wiki` and `read_page`, over the same index (see "Use your wiki from Claude Desktop chat" below)

## What it is not

- Not a note store. Your vault stays the source of truth, in plain markdown, portable, yours.
- Not a hosted service. Indexing and search run on your machine and send nothing anywhere. The only network calls are Fathom (your meetings) and the Claude calls that write pages and digests.

## Use your wiki from Claude Desktop chat

Chat in the Claude desktop app has no prompt hook, so it can't receive recall hits the way Claude Code does. It reaches your wiki through Rekall's local MCP server (`graph-memory/mcp_server.py`) instead. The server runs on your machine, reads the same index, and never writes anything. It gives chat two tools:

- `search_wiki(query)` returns the five best matching chunks, each labeled `[file § section]`, plus any entity-graph facts.
- `read_page(name)` returns one whole note by its file name without `.md`, such as `index` or `log`.

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
- A tool reply that starts with `Search failed` means there's no index yet. Run `graph-memory/reindex.sh`.

`bash install.sh --uninstall` removes the `rekall` entry from Claude Desktop's config along with everything else. To write the entry by hand instead, see the MCP section of `graph-memory/README.md`, then run `python3 graph-memory/test_mcp_server.py` to check both tools against your index.

## Layout

```
rekall/
├── SETUP.md            # the guided install
├── rekall.example.toml # settings: vault path, data path, name, timezone (copy to rekall.toml)
├── .env.example        # secrets: Fathom key, optional Monday and Jira tokens (copy to .env)
├── hooks.json          # the two Claude Code hook entries
├── vault-template/     # what setup copies into a new vault
├── launchd/            # macOS schedule templates: pipeline, reindex, lint
├── windows/            # the same three as Task Scheduler tasks
├── scripts/            # Fathom pipeline, wiki index/lint/cleanup
├── graph-memory/       # the index, the recall hook, distillation, the session digest
├── skills/ commands/   # Claude Code skills: wiki, wrap-up, fathom-sync
└── docs/               # vault CLI reference, prior art, plans
```

## Prior art

Andrej Karpathy's LLM Wiki pattern for the compiled wiki; Glitch Cat Club's graph-memory-starter (MIT, vendored under `graph-memory/`) for the index, hook, distillation, and digest; Cerebras's knowledge-base write-up for distil-then-embed and rank fusion. Details in `docs/prior-art.md`.
