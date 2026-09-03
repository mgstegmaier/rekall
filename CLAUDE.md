# Rekall

Wiki machinery around the Obsidian vault (`~/obsidian-vault/heck-db/`): capture pipelines in,
entity graph index, query layer out. The vault owns the content; this repo owns the plumbing.

- `graph-memory/` — the LIVE copy (hooks in `~/.claude/settings.json` and the hourly
  `com.heckatron.wiki-reindex` LaunchAgent point here; familiar's stale copies of graph-memory
  and the wiki scripts were removed 2026-09-02). See `graph-memory/README.md` for operations.
- `scripts/` — ingest pipelines, indexers, wiki lint/cleanup, wins mining.
- `docs/obsidian-vault-cli.md` — canonical vault CLI reference; read before any vault write.
- Wiki structure rules live in the vault at `wiki/CLAUDE.md`, not here.

## Current state (2026-09-02)

Shipped: session-graph enrichment — digest prompt writes slug-form wikilinks, `build_graph.py
--extra` graphs session digests as `session` entities (wired in `reindex.sh`), and the deployed
`/wrap-up` skill promotes digest decisions/facts and `[open]` loops onto wiki project pages.
Wiki project page created: `wiki/projects/rekall.md` (tagged `needs-review`).

Open: working tree uncommitted (wins scripts + digest prompt + session-graph changes);
`wiki-index.py` still can't run unattended (three ingest batches blocked).

Next action: commit the working tree.
