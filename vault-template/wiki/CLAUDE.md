---
type: schema
title: "Wiki structure rules"
description: Source of truth for this wiki's layout, placement rules, page format, and hard rules.
date: 2026-09-03
---

# Wiki Structure Rules (source of truth)

This directory is an LLM-maintained knowledge wiki: Karpathy's LLM Wiki pattern in Google's OKF-style layout (Open Knowledge Format v0.2). This file is the schema layer. Workflows (ingest/query/lint) live in the `/wiki` skill. If the skill and this file disagree on *structure*, this file wins.

## Layout

```
wiki/
├── index.md          # content catalog; GENERATED from page frontmatter — never hand-edit entries; frontmatter is okf_version ONLY
├── log.md            # operations log; headings are bare ISO dates (## YYYY-MM-DD)
├── CLAUDE.md         # this file
├── people/           # person entity pages
├── projects/         # project entity pages (state, members, decisions, next steps)
├── entities/         # other entities: servers, tools, orgs, places, products
├── concepts/         # ideas, patterns, methodologies, fundamentals
├── summaries/        # per-source summary pages
├── meetings/         # meeting notes written by the Fathom pipeline — SOURCE layer, immutable once written
└── raw/              # user-curated sources — IMMUTABLE to Claude; the wiki owner adds and removes files
```

Beside `wiki/`, `memory/sessions/` holds the session digests the SessionEnd hook writes. They are indexed for recall and cited by wiki pages, but they are not wiki pages and never get edited.

## Placement (mechanical, never a judgment call)

- Person (tagged `people`) → `people/`
- Project → `projects/`
- Any other entity → `entities/`
- `wiki-type: concept` → `concepts/`
- `wiki-type: summary` → `summaries/` — NON-MEETING sources only (long, raw, or external documents where the compiled summary is the artifact). Never create a per-meeting summary page: a meeting note is already Fathom's summary, so meeting content flows directly into entity/project/concept pages citing the meeting note.
- One level deep, never deeper. Could go two places → `entities/`.
- Basenames are unique across the whole wiki (wikilinks resolve by basename).
- Page names: lowercase, hyphen-separated, max 50 chars.

## Project catalog (curated)

`projects/` holds every initiative the wiki knows about, not only the owner's. Rules for writers:

- Match new content to an EXISTING project page first — check the `projects/` listing (and page titles/aliases) before creating anything.
- When a genuinely new project page is unavoidable, add the tag `needs-review` to its frontmatter so the owner can bless, rename, merge, or retire it later.

## Page frontmatter

```yaml
type: wiki-page          # meetings use: type: meeting
wiki-type: entity|project|concept|summary
title: "Human Readable Title"
description: One sentence.
date: YYYY-MM-DD         # last updated
tags: [ ... ]
sources: [ ... ]         # source filenames feeding this page
generated: {by: fathom-pipeline, at: ISO-8601}   # pipeline-written pages
```

Only `type` is required for OKF conformance; the rest is this wiki's convention.

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

## Retiring pages (the only sanctioned delete path)

The owner marks a page `status: retired` in its frontmatter; the cleanup job (`scripts/wiki-cleanup.py` in the rekall repo, dry-run by default) then unlinks references vault-wide, removes the index entry, deletes the file, and logs an audit entry. The mark is the permission — Claude never deletes an unmarked page. For pages the owner already deleted by hand, run the job with `--gone NAME` to clean up the orphaned references. Retired meeting-note citations are annotated `— retired`, never removed; the claims they supported stay, flagged by the annotation.

## Hard rules

1. Never delete a wiki page yourself — mark `[deprecated]` in its Summary, or let the owner mark `status: retired` for the cleanup job.
2. Never modify `meetings/` notes or `raw/` files after creation. Sole exception: the retire-cleanup job may rewrite wikilinks and annotate citations inside them while unlinking a retired page.
3. Cite every factual claim: `(source: filename)`. Flag uncertainty `[unverified]`.
4. Note contradictions explicitly; never silently resolve them.
5. Every ingest/update: set the page's `title` and `description` frontmatter (the index hook IS the `description`), then regenerate the index with `python3 REKALL_REPO/scripts/wiki-index.py` — never hand-edit index entries. The Fathom pipeline regenerates automatically; interactive sessions run the script. Append to `log.md` at the END of the file — append-only, bare ISO heading, bold `**tag | name**` first line. The log is the audit trail.
6. Link with basename `[[wikilinks]]` only — never path-style links.
7. Updating a page: rewrite `## State` in place, insert the new `### YYYY-MM-DD` entry at the top of `## Updates`, and carry closed items out of `## Next steps`. Never append a dated section to the bottom of a page.
8. Interpersonal and organizational friction is documented professionally, on non-violent-communication principles: observations, not evaluations; process gaps, not personal failings; no attributed motives or frustration language. Keep the fact, drop the heat — pages may be read by the people they describe.
