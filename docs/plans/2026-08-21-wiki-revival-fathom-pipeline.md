# Wiki Revival + Fathom Pipeline

**Date:** 2026-08-21
**Status:** EXECUTED 2026-08-21 — all phases complete. Wiki: 385 flat pages. Meetings: 191 notes (Feb–Aug backfilled). Pipeline live: launchd `com.heckatron.fathom-pipeline`, hourly 7am–7pm; manual `/fathom-sync`. Auto-Capture group created on board 18406890255.
**Owner:** Mike

## What this is

Revive the Karpathy-style LLM wiki in the Obsidian vault and feed it automatically from Fathom meeting transcripts, with action items pushed to a Monday triage group. Open Brain gets frozen. The goal: capture project context (details, members, state, next steps) so Claude can dredge it up on demand, and stop losing to-dos and context buried in meeting notes.

## Why (diagnosis from the grilling)

- **Open Brain failed on capture friction, visibility, and structure.** Nothing was ever migrated to it — it was additive, and it can't model projects and people or be browsed like a vault.
- **The wiki failed the same way.** `wiki/log.md` records 5 ingests over 6 days (2026-04-14 to 2026-04-19), then 4 months of silence. Ingest was manual ceremony: curate into `raw/`, run `/wiki`, discuss before writing. No automatic feed, so it starved.
- **The lesson:** anything that depends on Mike initiating it stops within weeks. The pipeline pushes without asking; review happens after the fact (reading pages, `log.md`) and at Monday triage time.

## Decisions

| Decision | Choice |
|----------|--------|
| Wiki structure | Flat Karpathy — all pages directly in `wiki/`, no subdirectories. PARA is fully dropped (folders and frontmatter). Good linking is the goal, not taxonomy. |
| Existing 155-page hierarchy | One-time flatten migration (Phase 1). No split-brain wiki. |
| Vault | The one vault: `~/Documents/heck-db` (symlink into Upland OneDrive — same directory as the OneDrive path). |
| Open Brain | Freeze now (stop the memory-mirror rule, no new captures), decommission later. Readable until anything worth keeping is pulled over. |
| Write access | Standing scoped grant: the pipeline may create and update `wiki/`, `meetings/`, `wiki/index.md`, `wiki/log.md`. Everything else keeps the no-touch rule. |
| Ingest ceremony | Discuss-first is removed for automated ingest (Fathom meetings and `raw/` files both). Every claim cited to its source; `log.md` is the audit trail. |
| Trigger | launchd on the MacBook, hourly, gated to 7am–7pm local (CST). Missed runs fire on wake. Manual trigger: shell script + slash command wrapper. |
| Action items → Monday | Only items explicitly assigned to Mike Stegmaier. Other attendees' items live in the meeting note only. |
| Monday destination | New group **"Auto-Capture"** on the generic requests board: https://upland-bunch.monday.com/boards/18406890255. Items carry action text, meeting name + date, vault note link, Fathom share URL. Pipeline never creates Monday projects — a possible new project lands as a flagged item to promote by hand at triage. |
| Backfill | Wiki: yes, including the Fathom gap (2026-05-13 → today, pulled via API into `meetings/` first). Monday: forward-only — no historical action items on the board. |
| Meeting notes | `meetings/` stays a source layer (like `raw/`), one file per meeting, wiki pages cite into it. |
| Review gate | The Monday Auto-Capture group IS the review gate. Mike grooms it in a scheduled triage session. A messy group is acceptable. |

## Phases

Each phase leaves the vault usable if work stops after it.

### Phase 0 — Hygiene and rule updates

1. Rewrite `skills/wiki/SKILL.md`: flat namespace stays the rule (the vault will be made to match it, not the reverse); remove discuss-first for automated ingest; define `meetings/` as a source layer alongside `raw/`.
2. Update vault-write rules (`identity/`/`rules/` in this repo, redeploy) with the pipeline's scoped standing write grant.
3. Fix stale repo paths in the vault's `CLAUDE.md` (`~/github_repos/familiar` → `~/github_repos/personal_projects/familiar`; `setup-familiar.sh` → `install/setup.py`).
4. Delete zero-byte root strays (`TrueSight.md`, `2026-05-26.md`, `chicken fried rice.md`, the `Untitled` base/canvas files).
5. Mark `memory/decisions/2026-03-03-para-folder-restructure.md` superseded.
6. Stop the Open Brain memory-mirror rule (edit `connections/services/open-brain.md` line ~50 and any deployed rule that carries it).

Verify: `/wiki` skill text matches the target design; `python3 install/setup.py --dry-run` shows the rule changes.

### Phase 1 — Flatten migration

Script (one-shot, in `scripts/`):

1. Move all 155 `wiki/**` pages to flat `wiki/`, resolving name collisions.
2. Rewrite all 918 wikilinks (index full-path links like `[[wiki/Homelab/Servers/worldmind|WORLDMIND]]` break on flatten).
3. Strip PARA frontmatter (`type: area|resource|project`, `parent:`) down to Karpathy properties (`type: wiki-page`, `wiki-type: entity|concept|summary`).
4. Merge the 6 stale `wiki/Work/Meetings/` notes (Notion-era, duplicate pairs) into `meetings/`.
5. Rebuild `wiki/index.md`; append a migration entry to `wiki/log.md`.
6. Lint pass: orphans, broken links (49 distinct broken targets pre-existing — fix or delete), leftover template placeholders.

Exception: `wiki/daily-notes-archive/` stays put — it's `/today`-owned machinery; touching it means touching that skill.

Verify: zero pages in subdirectories (except `daily-notes-archive/`), link-check passes, Obsidian graph opens clean.

### Phase 2 — Pipeline build

One job (script + headless `claude -p`, Doppler-injected secrets), idempotent via a state file of processed Fathom meeting IDs:

1. Pull new completed meetings from Fathom (`/meetings`, `/meetings/{id}/summary`, `/meetings/{id}/action-items` — key `FATHOM_API_KEY`, filter to meetings Mike attended via `JIRA_EMAIL`).
2. Write one meeting note per meeting to `meetings/{YYYY-MM-DD}-{slug}.md` (reuse the `/today` note template).
3. Extract to the flat wiki: people, projects, decisions, state, next steps — entity/concept/summary pages, every claim cited `(source: meeting-note-filename)`.
4. Push action items assigned to Mike to the Auto-Capture group on board 18406890255.
5. Process any files sitting in `raw/` the same way (2 are queued now, including the dbt Semantic Layer quickstart).
6. Update `wiki/index.md`, append to `wiki/log.md`.

Fathom's own summaries and action items are the extraction source (they're good; enhance later if needed), not raw transcript re-derivation.

Verify: run once manually against one new meeting; check the meeting note, wiki page diffs, `log.md` entry, and the Monday item.

### Phase 3 — Backfill

Run the pipeline in backfill mode:

1. Gap-fill `meetings/` from the Fathom API, 2026-05-13 → today.
2. Wiki extraction over all meeting notes (61 existing + gap-fill).
3. Monday push disabled.

Verify: spot-check project and people pages — they should carry ~6 months of cited context.

### Phase 4 — Schedule

1. launchd plist: hourly, `StartCalendarInterval` hours 7–19 local time, catch-up on wake.
2. Manual trigger: `scripts/` shell script + a slash command wrapping it.

Verify: two consecutive scheduled runs appear in `log.md`; manual trigger works; nothing fires outside 7am–7pm.

## Parked (pointers only — design when we get there)

- **Open Brain decommission**: after freeze, archive the Supabase `thoughts` table contents worth keeping into the wiki, then remove the MCP server, companion skill, and Doppler secrets.
- **Claude Code sessions + Monday projects interrelation**: documenting session work into the wiki and linking it to Monday projects. Constrained by whatever entity-page shape survives Phase 3.
- **/today revival**: stopped 2026-05-13. If revived, it displays pipeline output rather than re-capturing meetings, to avoid double-writing.

## Key references

- `/wiki` skill: `skills/wiki/SKILL.md` (Karpathy pattern definition)
- Fathom API: `connections/services/fathom.md`; existing pull code in `scripts/daily-briefing.py`
- Meeting note template: `skills/today/references/note-template.md`
- Open Brain: `connections/services/open-brain.md`
- Vault CLI rules: `docs/obsidian-vault-cli.md`
- PARA history: vault `memory/decisions/2026-03-03-para-folder-restructure.md`
