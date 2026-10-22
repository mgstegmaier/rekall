---
type: schema
title: "Wiki structure rules"
description: Source of truth for this wiki's layout, placement rules, page format, and hard rules.
date: 2026-10-22
---

# Wiki Structure Rules (source of truth)

This directory is an LLM-maintained knowledge wiki: Karpathy's LLM Wiki pattern in Google's OKF-style layout (Open Knowledge Format v0.2). This file is the schema layer. Workflows (ingest/query/lint) live in the `/wiki` skill. If the skill and this file disagree on *structure*, this file wins.

## Layout

```
wiki/
├── index.md          # content catalog; GENERATED from page frontmatter — never hand-edit entries; frontmatter is okf_version ONLY
├── log.md            # operations log; headings are bare ISO dates (## YYYY-MM-DD)
├── CLAUDE.md         # this file
├── *.base            # one Obsidian Base per type (people, projects, entities, concepts, summaries, meetings) — the human browsing surface
├── pages/            # every compiled page, at pages/<type>/<slug>.md; the folder name is the page's `type` (person, project, entity, system, pipeline, concept, summary, note, decision, context)
├── meetings/         # meeting notes written by the Fathom pipeline — SOURCE layer, immutable once written
│   └── transcripts/  # one person's side of a meeting transcript, `type: transcript-excerpt`, `meeting:` links the note; source layer, immutable, not indexed
├── sessions/         # SessionEnd digests, one file per day — indexed and graphed, cited by pages; no frontmatter, never edited, not in index.md
├── plans/            # Claude Code plan-mode plans and scopes, `type: plan`, dated `YYYY-MM-DD-slug.md`; recall-indexed, linked from the project page, not in index.md
├── raw/              # user-curated sources — IMMUTABLE to Claude; the wiki owner adds and removes files
└── archive/          # files marked `status: archive`, moved here by the lifecycle job; out of the wiki, links still resolve
```

`pages/` has one subfolder per type, and a page's folder always equals its `type`, so placement stays mechanical. Wikilinks resolve by basename, so a page's folder never appears in a link. Humans browse through the Bases, index.md, and the type folders; the LLM finds pages through the index, wikilinks, and grep (search `pages/` recursively). `scripts/wiki-type-folders.py` in the rekall repo moves misfiled pages, and `wiki-lint.py` warns about any page outside `pages/<type>/`.

`wiki/sessions/` holds the session digests the SessionEnd hook writes (one file per day). They are indexed for recall and graphed as `session` entities, and wiki pages cite them, but they are not compiled pages.

## Placement (mechanical, never a judgment call)

`type` in frontmatter is the taxonomy. Pick the type, then write the page to `pages/<type>/<slug>.md` (for example `pages/person/jane-doe.md`); create the folder if it doesn't exist yet:

- `type: person` — a human
- `type: project` — an initiative with state, members, decisions, next steps
- `type: system` — a named platform, service, or tool that other things run on or call: vendor SaaS, an internal application, a host
- `type: pipeline` — a scheduled or event-driven data flow with a source and a destination
- `type: entity` — anything else that exists: documents, orgs, places, products
- `type: concept` — ideas, patterns, methodologies, fundamentals
- `type: summary` — NON-MEETING sources only (long, raw, or external documents where the compiled summary is the artifact). Never create a per-meeting summary page: a meeting note is already Fathom's summary, so meeting content flows directly into entity/project/concept pages citing the meeting note.
- `type: meeting` → `meetings/`, the one folder split: meetings are the source layer.
- `type: plan` → `plans/`, the other folder split: a plan is a dated artifact of a session, not a compiled page. Frontmatter: `date`, `status: draft | approved | complete | abandoned`, `project: "[[project-page]]"`, `source`. The `/wiki` skill's "Mode: Plan" has the write recipe.
- Could be two types → `type: entity`.
- Changing a page's `type` means moving it to the matching folder.
- Basenames are unique across the whole wiki (wikilinks resolve by basename).
- Page names: lowercase, hyphen-separated, max 50 chars.

## Project catalog (curated)

Project pages (`type: project`) hold every initiative the wiki knows about, not only the owner's. Rules for writers:

- Match new content to an EXISTING project page first — check the projects Base or the index's Projects section (and page titles/aliases) before creating anything.
- When a genuinely new project page is unavoidable, add the tag `needs-review` to its frontmatter so the owner can bless, rename, merge, or retire it later.
- `repos:` (optional, project pages) lists the git repos the project's code lives in, as `owner/repo` or `owner/repo/path-prefix` when one repo hosts several projects. It is the owner's mapping: never remove or rewrite it, and add it only when the project page's own text names the repo.

## Page frontmatter

```yaml
type: entity|person|project|system|pipeline|concept|summary   # meetings: type: meeting; log.md: type: log
status: active           # active | retired | archive — see "Page lifecycle"; on every page and meeting note
title: "Human Readable Title"
description: "One sentence."   # always double-quoted, like title: an unquoted colon breaks the whole block
date: YYYY-MM-DD         # last updated
tags: [ ... ]
sources: [ ... ]         # source filenames feeding this page
repos: [ ... ]           # project pages only: owner/repo, or owner/repo/path-prefix when one repo hosts several projects
generated: {by: fathom-pipeline, at: ISO-8601}   # pipeline-written pages
owner: person-slug                              # optional, project|system|pipeline — see relation fields below
people: [person-slug, ...]                      # optional, project|system|pipeline — anyone involved
maintainers: [person-slug, ...]                 # optional, project|system|pipeline — who operates, supports, repairs it
depends_on: [page-slug, ...]                    # optional, project|system|pipeline
about: [page-slug, ...]        # optional, meeting notes | sessions | summaries | plans — the principal subject(s)
part_of: [page-slug, ...]      # optional, project|system|pipeline — the parent project, system, or pipeline
runs_on: [system-slug, ...]    # optional, pipeline — where it executes
reads_from: [page-slug, ...]   # optional, pipeline — data it consumes
writes_to: [page-slug, ...]    # optional, pipeline — data it produces
attendees: [Display Name, ...]                  # meeting notes only, written by the Fathom pipeline
```

Only `type` is required for OKF conformance; the rest is this wiki's convention. `type` is the single taxonomy field, so other vault note types (`note`, `decision`, `context`) join the wiki under it.

Quote every free-text value (`title`, `description`, any sentence) in double quotes. YAML reads `description: Sigma at Acme: Radar results` as a nested mapping, the whole frontmatter block fails to parse, and Obsidian shows it as raw body text. `wiki-index.py` quotes an unsafe `title` or `description` on its next run, but nothing repairs other fields.

`system` is a named platform, service, or tool that other things run on or call: vendor SaaS, an internal application, a homelab host. `pipeline` is a scheduled or event-driven data flow with a source and a destination. `entity` keeps everything else: a document, a plan, a guide, an organisation, a product line.

### Relation fields

Optional frontmatter fields the graph builder reads as typed edges:

| Field | On | Emits | Target |
|-------|-----|-------|--------|
| owner | project, system, pipeline | owns | one person slug |
| people | project, system, pipeline | member_of | person slugs |
| maintainers | project, system, pipeline | maintains | person slugs; who can fix it, not who is accountable (that is `owner`) |
| depends_on | project, system, pipeline | depends_on | page slugs |
| about | meeting notes, sessions, summaries, plans | about | any page |
| part_of | project, system, pipeline | part_of | project, system, or pipeline page (a DAG step inside a larger pipeline) |
| runs_on | pipeline | runs_on | system page |
| reads_from | pipeline | reads_from | system or dataset page |
| writes_to | pipeline | writes_to | system or dataset page |
| attendees | meeting notes | attended | display names as written by the Fathom pipeline |

Values are page slugs (the wikilink basename), written as YAML lists (`[a, b]` or block form) except `owner`, a single string.

Fill a relation only from evidence in the source you are ingesting, and cite that evidence in the body the way every other claim is cited. Never infer an owner. Never remove a relation value unless a source says it changed; add to lists, don't replace them. `about` on a note lists the pages the note was ingested into; the writer that creates or updates pages from a note sets it on that note in the same step. `depends_on` is for requirements the flow fields do not express. Reading from Snowflake is `reads_from: snowflake`, not also `depends_on: snowflake`.

Lint: unresolved relation targets and non-person `owner`/`people`/`maintainers` targets are lint errors; an active project with no `owner` is a lint warning. `part_of` targets must be project, system, or pipeline pages, `runs_on` targets must be system pages, a page may not be `part_of` itself.

## Page body format

`# Title`, then `**Summary**:` (1-2 sentences), `**Sources**:` (basename wikilinks), `**Last updated**:`, `---`, body with `[[wikilinks]]` throughout.

Section order (`scripts/wiki-reflow.py` in the rekall repo enforces it mechanically, lint check 9 reports drift):

1. `## State` — the current picture, REWRITTEN in place on every update, never appended to. One State section per page.
2. `## Next steps`, then `## Members` (project pages carry all three; other pages carry what applies).
3. `## Updates` — the dated log, NEWEST FIRST. Each entry is `### YYYY-MM-DD short title`; a new entry goes at the TOP of this section, directly under the heading. Dated headings never appear anywhere else on the page.
4. Reference sections (architecture, RCAs, specs, merged-in material), any order.
5. `## Related pages` last.

The reader question this answers is "what is true now?" — State answers it, Updates shows how it got there. Any section that carries dated sub-entries keeps them newest-first too.

## Markdown gotchas (Obsidian renderer)

- Never write raw angle-bracket placeholders (like a bare `<name>`) in page bodies — Obsidian parses them as unclosed HTML and silently swallows everything after them, including whole tables. Use backticks or ALL_CAPS placeholders.
- Tables: escape literal pipes in cells as `\|` (wikilink aliases in tables too: `[[page\|alias]]`), keep cells single-line, leave a blank line before the header row, and never let `**emphasis**` open in one cell and close in another.

## Page lifecycle (the only sanctioned removal path)

Every page and meeting note carries `status`, stamped explicitly, never implied by absence:

- `active` — normal.
- `retired` — the page stays where it is: links still resolve, it stays in the index (marked `(retired)`) and in search. Writers stop updating it; match new content elsewhere.
- `archive` — the mark for the nightly lifecycle job (`REKALL_REPO/scripts/wiki-cleanup.py`, runs after lint, dry-run by hand): it MOVES the file to `wiki/archive/` and drops its index entry. Nothing is deleted and no link is rewritten: Obsidian resolves `[[wikilinks]]` by basename vault-wide, so links to an archived page keep working. The index, lint, recall index and graph skip `archive/`. `raw/` files can be marked too (they need a frontmatter block to carry it).

The mark is the permission: Claude never moves or deletes an unmarked page, and never sets `archive` itself. The job reports would-be orphans (pages whose every inbound link came from what was archived) as candidates; it never cascades. Restore = drag the file back and set `status: active`. For a page the owner already deleted by hand, `wiki-cleanup.py --gone NAME` unlinks the dangling references.

## Hard rules

1. Never delete or move a wiki page yourself, and never set `status: archive`. Set `status: retired` when a page should stop changing; the owner marks `archive` for the lifecycle job.
2. Never modify `meetings/` notes or `raw/` files after creation. Two sanctioned writers are the exception. The lifecycle job (`wiki-cleanup.py`) may move marked files to `archive/`, and may rewrite wikilinks inside them when unlinking a hand-deleted page (`--gone`). The Granola sweep (`scripts/granola-sweep.py`) may APPEND one `## Granola notes` section to the end of a Fathom meeting note for the same meeting, once; it never modifies existing content or frontmatter, and re-queues the note for ingest. The ingest step that sets `about` on a note it just ingested is the only other frontmatter write.
3. Cite every factual claim: `(source: filename)`. Flag uncertainty `[unverified]`.
4. Note contradictions explicitly; never silently resolve them.
5. Every ingest/update: set the page's `title` and `description` frontmatter (the index hook IS the `description`), then regenerate the index with `python3 REKALL_REPO/scripts/wiki-index.py` — never hand-edit index entries. The Fathom pipeline regenerates automatically; interactive sessions run the script. Append to `log.md` at the END of the file — append-only, bare ISO heading, bold `**tag | name**` first line. The log is the audit trail.
6. Link with basename `[[wikilinks]]` only — never path-style links.
7. Updating a page: rewrite `## State` in place, insert the new `### YYYY-MM-DD` entry at the top of `## Updates`, and carry closed items out of `## Next steps`. Never append a dated section to the bottom of a page.
8. Interpersonal and organizational friction is documented professionally, on non-violent-communication principles: observations, not evaluations; process gaps, not personal failings; no attributed motives or frustration language. Keep the fact, drop the heat — pages may be read by the people they describe.
