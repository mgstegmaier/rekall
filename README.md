# Rekall

We remember it for you wholesale.

Rekall is the machinery around a personal knowledge wiki: capture pipelines in, a query layer out. The notes themselves live in your own vault (Obsidian or any folder of markdown). Rekall never owns your content. It ingests into it, indexes it, and answers questions from it.

Named after the memory-implant company in *Total Recall*.

## What it does

- **Capture** - pipelines that feed the wiki: meeting transcripts, session wrap-ups, quick idea capture, web clips
- **Index** - an entity/backlink graph built from the vault, so "what do I know about X" has an answer
- **Recall** - the query interface: CLI commands and Claude Code skills that read the graph and the pages

## What it is not

- Not a note store. Your vault stays the source of truth, in plain markdown, portable, yours.
- Not a second brain app. It assumes you already have the vault; Rekall is the plumbing.

## Status

Pre-alpha. Extracting the working pieces from a personal setup (wiki conventions, Fathom meeting sync, graph indexing) into something another person can point at their own vault.

## Layout

```
rekall/
├── docs/       # architecture, vault conventions, page schemas
├── scripts/    # ingest pipelines and indexers
└── skills/     # Claude Code skills (capture, query, wrap-up)
```
