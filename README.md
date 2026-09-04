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

## What it is not

- Not a note store. Your vault stays the source of truth, in plain markdown, portable, yours.
- Not a hosted service. Indexing and search run on your machine and send nothing anywhere. The only network calls are Fathom (your meetings) and the Claude calls that write pages and digests.

## Layout

```
rekall/
├── SETUP.md            # the guided install
├── rekall.example.toml # settings: vault path, data path, name, timezone (copy to rekall.toml)
├── .env.example        # secrets: Fathom key, optional Monday and Jira tokens (copy to .env)
├── hooks.json          # the two Claude Code hook entries
├── vault-template/     # what setup copies into a new vault
├── launchd/            # schedule templates: pipeline, reindex, lint
├── scripts/            # Fathom pipeline, wiki index/lint/cleanup
├── graph-memory/       # the index, the recall hook, distillation, the session digest
├── skills/ commands/   # Claude Code skills: wiki, wrap-up, fathom-sync
└── docs/               # vault CLI reference, prior art, plans
```

## Prior art

Andrej Karpathy's LLM Wiki pattern for the compiled wiki; Glitch Cat Club's graph-memory-starter (MIT, vendored under `graph-memory/`) for the index, hook, distillation, and digest; Cerebras's knowledge-base write-up for distil-then-embed and rank fusion. Details in `docs/prior-art.md`.
