# Wiki OKF Restructure

**Date:** 2026-08-22
**Status:** EXECUTED 2026-08-22 — 386 pages into type folders (93 people / 24 projects / 61 entities / 126 concepts / 82 summaries), 192 meeting notes into `wiki/meetings/` with frontmatter, 18 legacy pages type-backfilled, log headings ISO, `index.md` regenerated with `okf_version: "0.2"`, pipeline + skills + rules + bases + sortspec updated and redeployed. Migration script: `scripts/okf-restructure.py`. Pre-migration backup: `~/.config/familiar/backups/heck-db-pre-okf-20260822-170634.tar.gz`.
**Owner:** Mike
**Builds on:** `2026-08-21-wiki-revival-fathom-pipeline.md` (executed) and `docs/research/2026-08-22-okf-for-obsidian-wiki.md`

## What this is

Reshape the flat wiki into a shallow, type-based folder layout matching OKF's idiom, pull meeting notes inside the wiki so it becomes one self-contained OKF bundle, and apply the four cheap OKF v0.2 alignment moves from the research. One wiki — no personal/work split; the `upland` tag remains the export-time separator.

## Why folders now, two days after flattening

New information: the OKF research confirmed folders never hurt Obsidian searchability (wikilinks resolve by basename, so moves break nothing), and OKF's path-as-identity rule makes *now* — before any external OKF consumer exists — the cheapest moment to pick final paths. The April hierarchy failed because it was a judgment-heavy taxonomy; this layout is mechanical (filing = the `wiki-type` the pipeline already assigns), so the classification friction that killed PARA doesn't apply.

## Target layout

```
wiki/
├── index.md, log.md          (root; index frontmatter becomes okf_version only)
├── people/                   (~93 pages: tagged `people`)
├── projects/                 (entity pages with State/Next-steps sections or project tag)
├── entities/                 (remaining entities: servers, tools, orgs, places)
├── concepts/                 (wiki-type: concept)
├── summaries/                (wiki-type: summary)
├── meetings/                 (moved from vault root, 191+ notes, frontmatter added)
└── daily-notes-archive/      (unchanged — /today machinery)
```

Rules: never deeper than one level; filing is mechanical by `wiki-type` + `people` tag; ambiguous entities land in `entities/`.

## Phases

### Phase A — Backup + classify + move wiki pages

1. Tar `wiki/` + `meetings/` to `~/.config/familiar/backups/` (rollback insurance).
2. Migration script classifies each flat page: `people` tag → `people/`; `wiki-type: summary` → `summaries/`; `wiki-type: concept` → `concepts/`; entity with a `## State` or `## Next steps` section or `project` tag → `projects/`; remaining entities → `entities/`. Script prints the full mapping before moving (review gate for misfiles).
3. Move files. No link rewrites needed — Obsidian resolves `[[name]]` by basename; basenames stay unique.

Verify: zero `.md` files left loose at `wiki/` root except `index.md`/`log.md`; Obsidian graph intact.

### Phase B — Meetings into the wiki

1. Move `meetings/*.md` → `wiki/meetings/`; delete the emptied vault-root `meetings/`.
2. Backfill frontmatter on all notes: `type: meeting`, `date` (from filename), `title` (from H1).
3. Rewrite all `[[meetings/…]]` path-style links vault-wide (today.md, archived dailies) to basename links — immune to any future move.
4. Update every path reference:
   - `scripts/fathom-pipeline.py` — `MEETINGS` path; `write_note()` emits the new frontmatter.
   - `skills/today/references/note-template.md` + `workflow.md` — write location and link format (basename links).
   - `skills/wiki/SKILL.md` — architecture diagram and source-layer wording.
   - `identity/obsidian-vault.md` — permitted dirs (`meetings/` → `wiki/meetings/`); redeploy via `install/setup.py`.
   - `docs/obsidian-vault-cli.md` — write-locations table (canonical).
   - `connections/services/fathom.md` — pipeline blurb.
   - `notes/meetings.base` — folder filter → `wiki/meetings`; add `note.date` column.
   - `notes/sortspec.md` — `target-folder: wiki/meetings`.
   - Pipeline state file needs no migration: stale `meetings/…` paths only matter for pending ingests, and all entries are `ingested: true`.

Verify: `bash scripts/run-fathom-pipeline.sh --hours 4 --dry-run` runs clean; meetings.base and file-explorer sort still work after Obsidian reload.

### Phase C — OKF v0.2 alignment (the four cheap moves + two cosmetic fixes)

1. Pipeline prompt additions (forward-only): new pages get `title`, `description`, and `generated: {by, at}`; folder placement rules for the new layout.
2. `type` backfill on the 28 legacy pages missing frontmatter (default `type: wiki-page`, `wiki-type: concept`; report listed for review).
3. `log.md` headings → bare ISO dates per SPEC.md §9: historical `## [YYYY-MM-DD] tag | name` becomes `## YYYY-MM-DD` with the tag/name demoted to a bold first line; skill + pipeline prompt updated to the new format.
4. `index.md` root frontmatter → `okf_version: 0.2` only, per §8.

Explicitly skipped (per research): restructuring the `sources:` family (breaks Obsidian's properties UI), footnote citations, trust/lifecycle/attestation fields, wikilink→markdown export (build when a real OKF consumer exists), deeper folder nesting, and a personal/work wiki split (tag-filtered export covers it).

### Phase D — Regenerate + verify

1. Regenerate `index.md` grouped by the new folders.
2. Append a migration entry to `log.md` (new heading format).
3. Lint: broken-link scan, loose-file scan, frontmatter parse check across all pages.
4. One real pipeline run against the next new meeting to confirm a page lands in the right folder with the new frontmatter.
5. Update auto-memory + the executed-plans status lines.

## Risks

- Path-style `[[meetings/…]]` links in archived dailies are the only links that can break — Phase B step 3 rewrites them first.
- Obsidian open during the move: fine (it reindexes external changes), but reload after Phase B so the plugin sortspec and bases pick up new paths.
- OneDrive will re-sync ~580 moved files; harmless, just noisy in the sync log.
