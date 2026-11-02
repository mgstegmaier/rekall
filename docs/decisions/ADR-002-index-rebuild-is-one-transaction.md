---
adr: 2
title: Rebuild the index inside one SQLite transaction per builder, instead of building a shadow copy and swapping it in
date: 2026-11-01
status: DECIDED
decider: mgstegmaier
recorded_by: Claude Code, in the rekall rebuild-safety night-shift session
ticket:
validation_by: 2026-11-15
decided: 2026-11-01, EGM design review of "Rekall index rebuild safety"
reversible: yes
---

# ADR-002: Rebuild the index inside one SQLite transaction per builder, instead of building a shadow copy and swapping it in

## Summary

**Where it stands.** Decided and built in PR #56. The decision takes effect when that PR merges.

### The problem

Rekall's search index is one SQLite file, `rag.db`, written by two builders. `build_index.py` owns
the text tables (`chunks`, `chunks_fts`, `vectors`, `files`, `meta`), and `build_graph.py` owns the
graph tables (`entities`, `relations`, `aliases`). Both builders used to drop and recreate their
tables through `executescript()`, which commits at once. They then committed the refilled rows
only at the end of the run. Every reader (the recall hook, the MCP server, `search.py`, the
session digest) found an empty index for the length of a rebuild. On 2026-11-01 a full re-embed
of 15,254 chunks took 47 minutes. A rebuild that failed or was killed partway left the index
empty until a later run succeeded.

### The recommendation

Each builder starts its own transaction with `BEGIN IMMEDIATE` and commits once, after its
consistency check. The schema runs one statement at a time through `execute`, never through
`executescript`. In WAL mode, every reader keeps seeing the last committed snapshot until that
commit, and a failed or killed run commits nothing. The change costs a few lines per builder. Its
cost at run time is the write lock. An incremental run now holds it from the start of the run
instead of from its first write, which adds a few seconds. A full re-embed holds it for the whole
run, as before. A session digest whose own rebuild collides with a full re-embed waits 60
seconds, fails, and gets indexed by the next hourly run.

### Other options

| Option | Trade-off |
|---|---|
| B. Build a shadow `rag.db` and rename it into place | The live file is never written during a build. But each builder would swap in a file without the other builder's latest tables, and renaming a WAL database under open connections can pair the old `-wal` and `-shm` files with the new file. |
| C. Shadow tables in the same file, renamed into place | One file keeps both builders' tables together. But each builder needs twice the table logic, FTS5 tables carry shadow tables of their own that must rename with them, and readers still need a transaction around the rename. |
| D. Put `BEGIN;` at the top of the `executescript()` script | It's the smallest diff. It works only because no write runs before the script and because of one Python default, and it breaks without an error if either changes. It's also a deferred `BEGIN`, so two overlapping runs can both plan from stale state. |
| E. Do nothing | It costs nothing. Recall stays blind during every full rebuild, and any failed rebuild empties the index. |

### Decision needed

Nothing open.

## Detail

### The decision check (answer all five before ratifying)

1. Is the option of waiting or doing nothing on the table? Yes, as option E.
2. Have the facts changed since the current plan was made? The 2026-09-13 decision to stay on
   SQLite recorded "a long-running reader can see rows vanish during a full rebuild" as a known
   gap. The 2026-11-01 night-shift review of the repo against its docs (findings F-recall-2,
   F-recall-14, F-recall-15) measured the cost: up to 47 minutes of empty recall per full
   re-embed.
3. Is every option priced? In write-lock time and code size, yes. None of the options costs
   money. Each one runs locally.
4. Whose decision is this? The repo owner's. He approved the EGM design on 2026-11-01.
5. What check, on what date, tells us whether the decision was right? See Consequences and
   check.

### Context

- WAL mode gives each new read connection the last committed snapshot, and every reader already
  opens a connection per call (`recall_hook.py`, `graph_recall.py`, `digest/common.py`, and
  `mcp_server.py` through `recall_hook.hits()`). Readers therefore need no code change.
- SQLite runs DDL inside a transaction, including `CREATE VIRTUAL TABLE ... USING fts5`. This
  was verified on SQLite 3.45.3, the version in the venv that `reindex.sh` runs.
- `executescript()` commits any open transaction before it runs, so the schema can't go through
  it inside the transaction.

### Options

| Option | Gains | Costs and risks | Priced? |
|---|---|---|---|
| A. One `BEGIN IMMEDIATE` transaction per builder | Readers keep the last good index, and a failed run changes nothing. `IMMEDIATE` stops two overlapping runs from planning against the same stale `files` table. | The write lock now covers the vault walk on every run. A full re-embed blocks a digest's rebuild for its whole length. | Yes: seconds per incremental run, and 24 to 47 minutes per full re-embed, as before |
| B. Shadow `rag.db`, renamed into place | The live file is untouched until the swap. | It loses the other builder's tables, and it can corrupt the file under open WAL connections. | Yes |
| C. Shadow tables, renamed into place | One file. | It doubles the table logic, adds FTS5 rename handling, and still needs a transaction. | Yes |
| D. `BEGIN;` inside `executescript()` | Smallest diff. | It breaks silently under small edits, and its deferred lock lets two runs plan from stale state. | Yes |
| E. Wait / do nothing | No work. | Empty recall during every full rebuild, and an empty index after any failed one. | Yes |

### Decision

Option A. The transaction already gives readers everything a shadow copy would, without a second
file or a second set of tables. An explicit `BEGIN IMMEDIATE` doesn't depend on how
`executescript` commits. The release-gate tests in `graph-memory/test_db_concurrency.py` fail if a
later edit breaks the transaction.

### Consequences and check

- We now own the rule that `SCHEMA` never goes back through `executescript()`. A comment at each
  `BEGIN IMMEDIATE` line says so, and `test_release_gate_*` enforces it.
- A session digest that collides with a full re-embed is indexed an hour late. It writes
  `build_index: rebuild failed rc=1` to the digest log.
- Check on 2026-11-15: grep the digest log for `build_index: rebuild failed` and
  `~/.config/rekall/logs/wiki-reindex.log` for `FAILED`. If digest rebuilds fail more than once a
  week, build the deferred option from the design: embed before taking the write lock.

## Changes

- 2026-11-01: decided in the EGM design review, recorded, and built in PR #56.
