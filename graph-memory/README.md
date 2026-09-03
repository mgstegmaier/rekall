# graph-memory

Semantic memory over the Obsidian wiki (`~/obsidian-vault/heck-db/wiki/`). A `UserPromptSubmit` hook searches a local SQLite index and injects the top wiki hits into every Claude Code prompt, so sessions get wiki context without grepping.

Vendored from [Glitch-Cat-Club/graph-memory-starter](https://github.com/Glitch-Cat-Club/graph-memory-starter) (see `LICENSE-upstream`), with three local changes: frontmatter is stripped before chunking, each page's `title`/`description` frontmatter becomes its own searchable row, and `distil.py` takes `--under <subfolder>` to scope distillation.

## How it works

- `build_index.py --corpus ~/obsidian-vault/heck-db/wiki` chunks every wiki page on headings (h1–h3, packed to ~1600 chars), embeds each chunk locally with BGE-small (fastembed, CPU, no API), and writes keyword (FTS5) + vector indexes to `rag.db` next to the script. Runs are incremental by default (a content hash per file in the `files` table; only new/changed/deleted files are touched, seconds on a typical day). `--full` drops and rebuilds everything (~24 min for the whole wiki) — the first run each Sunday promotes itself to full automatically (`last_full` date in the `meta` table, so a Mac asleep at the scheduled hour still gets its weekly full after waking), and `--full` stays required after an embedding-model change since stored vectors from the old model are invalid. A DB without the `files` table (pre-incremental) upgrades itself with one automatic full build.
- `recall_hook.py` runs on every prompt: keyword + semantic search, rank-fused, top 5 hits injected as context (1500-char cap). It fails open — any error, missing index, or empty result exits silently and never blocks a prompt. You'll see `memory: N hits` in the session when it fires.
- `search.py "your question"` is the CLI test tool; it shows which leg (keyword/meaning) found each hit.
- `distil.py ~/obsidian-vault/heck-db/wiki --under meetings` runs one `claude -p` call per meeting note, extracting question + verbatim-quote entries into `~/obsidian-vault/graph-memory/distilled/`, outside this repo because distillates carry meeting and company content. Quotes are validated word-for-word against the source or dropped. SHA256 state in `~/obsidian-vault/graph-memory/distilled/.state.json` skips unchanged notes on re-runs.

## Graph layer

`build_graph.py --corpus ~/obsidian-vault/heck-db/wiki` builds a deterministic knowledge graph into the same `rag.db`: one entity per wiki page (type from its folder, name/description from frontmatter), one untyped `mentions` edge per `[[wikilink]]`. No LLM involved. `--extra` folders (reindex.sh passes the vault's `memory/sessions/`) become `session`-type entities whose wikilinks become edges too, so "when did I last touch X" is answerable from the graph; wiki pages always win a slug collision, and spaced link text like `[[Familiar Cost Watch]]` resolves to its hyphenated slug. `graph_recall.py "question"` seeds entities named in the question and walks 2 hops with a recursive SQL query (~30ms). The recall hook runs this as a third leg and appends the triples as a "Wiki graph:" block.

## Session digest

`digest/session_end.py` runs on the `SessionEnd` hook: it filters the transcript down to your words and the replies (tool calls, results, and thinking dropped), stages it under `digest/pending/`, and spawns a detached `claude -p` (sonnet) that writes a structured digest (`digest/digest-prompt.md` is the voice) into the vault at `memory/sessions/YYYY-MM-DD.md`. Sessions under 5 turns are skipped. Failures never block a session close; they land in `digest/log/digest.log` and the staged file stays for retry. The reindex sweeps `memory/sessions/` (via `--extra`), so past sessions become searchable memory. This complements `/wrap-up`, which stays the deliberate close-out.

## Operations

| Task | Command |
|------|---------|
| Refresh index + graph | `./reindex.sh` (also runs hourly via `com.heckatron.wiki-reindex` LaunchAgent; incremental, with the week's first Sunday run auto-promoted to a full rebuild) |
| Force a full rebuild | `.venv/bin/python build_index.py --corpus ~/obsidian-vault/heck-db/wiki --extra ~/obsidian-vault/heck-db/memory/sessions --full` |
| Test a query | `.venv/bin/python search.py "what's next on QVal"` |
| Test graph recall | `.venv/bin/python graph_recall.py "who is involved in QVal"` |
| Distil new meeting notes | `.venv/bin/python distil.py ~/obsidian-vault/heck-db/wiki --under meetings` |
| Check the LaunchAgent | `launchctl list \| grep wiki-reindex`; log at `/tmp/wiki-reindex.log` |
| Check digest failures | `cat digest/log/digest.log`; staged retries sit in `digest/pending/` |

The index is disposable. If anything looks wrong, delete `rag.db` and run `./reindex.sh`. The wiki itself is never written — it's a read-only corpus, and it stays on OneDrive safely because only markdown syncs there; the SQLite DB lives here on local disk.

If a rebuild fails with unreadable files, OneDrive has dehydrated the vault: mark `heck-db` as "Always Keep on This Device" in Finder.

Hooks are registered in `~/.claude/settings.json`: `UserPromptSubmit` → `recall_hook.py`, `SessionEnd` → `digest/session_end.py`. Setup on a new machine: copy `rekall.example.toml` to `rekall.toml` at the repo root and set the vault and data paths, then `python3 -m venv .venv && .venv/bin/pip install fastembed && ./fetch_model.sh && ./reindex.sh`, then add both hooks. The full guided install is `SETUP.md`.
