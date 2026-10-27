# Vault conventions

The schema layer of a Rekall wiki: layout, placement rules, page format, and the hard rules that keep an LLM-maintained wiki trustworthy. Extracted from a personal vault that has run this way since early 2026; generalize the names, keep the mechanics.

Terminology: the **curator** is the human who owns the vault. The **writer** is any LLM session or pipeline that edits it.

## Layout

```
wiki/
├── index.md          # content catalog; GENERATED from page frontmatter, never hand-edit entries
├── log.md            # operations log; append-only, headings are bare ISO dates (## YYYY-MM-DD)
├── CLAUDE.md         # the schema file (this document, adapted to your vault)
├── pages/            # every compiled page, at pages/TYPE/SLUG.md; the folder name is the page's `type`
│   ├── person/       # people
│   ├── project/      # initiatives (state, members, decisions, next steps)
│   ├── system/       # platforms, services, and hosts other things run on or call
│   ├── pipeline/     # scheduled or event-driven data flows
│   ├── entity/       # other things that exist: documents, orgs, places, products
│   ├── concept/      # ideas, patterns, methodologies, fundamentals
│   └── summary/      # per-source summary pages
├── meetings/         # meeting notes; SOURCE layer, immutable once written
└── raw/              # curator-managed sources; writers never touch these
```

Three layers, per the LLM Wiki pattern: `raw/` and `meetings/` are immutable sources, `pages/` is the wiki, and the schema file governs the writers.

## Placement (mechanical, never a judgment call)

`type` in frontmatter is the taxonomy, and a page lives at `pages/TYPE/SLUG.md`, so its folder always equals its `type`. Pick the type and the path follows:

- Person → `type: person`, `pages/person/`
- Project → `type: project`, `pages/project/`
- Platform, service, or host → `type: system`, `pages/system/`
- Data flow with a source and a destination → `type: pipeline`, `pages/pipeline/`
- Any other entity → `type: entity`, `pages/entity/`
- Concept → `type: concept`, `pages/concept/`
- Summary → `type: summary`, `pages/summary/`, for NON-MEETING sources only (long, raw, or external documents where the compiled summary is the artifact). Never create a per-meeting summary page: a meeting note is already a summary, so meeting content flows directly into entity, project, and concept pages that cite the note.
- One level under `pages/`, never deeper. If a page could be two types, it is `type: entity`.
- Changing a page's `type` means moving it to the matching folder. The rekall script `scripts/wiki-type-folders.py` moves misfiled pages, and `wiki-lint.py` warns about them.
- Basenames are unique across the whole wiki, because wikilinks resolve by basename.
- Page names: lowercase, hyphen-separated, max 50 characters.

## Project catalog (curated)

`pages/project/` holds every initiative the wiki knows about, not only the curator's own. Rules for writers:

- Match new content to an EXISTING project page first. Check the `pages/project/` listing and page titles before creating anything.
- When a genuinely new project page is unavoidable, tag it `needs-review` in frontmatter so the curator's triage view surfaces it. The curator blesses, renames, merges, or retires it later.
- Frontmatter fields the curator maintains by hand (for example a `resource:` link to an external task board) are never removed or overwritten by a writer.

## Page frontmatter

```yaml
type: entity|person|project|system|pipeline|concept|summary   # meetings: type: meeting. The only taxonomy field (wiki-type retired 2026-09-04).
status: active           # active | retired | archive, on every page and meeting note
title: "Human Readable Title"
description: One sentence. This is the index hook.
date: YYYY-MM-DD         # last updated
tags: [ ... ]
sources: [ ... ]         # source filenames feeding this page
generated: {by: PIPELINE_NAME, at: ISO-8601}   # pipeline-written pages only
```

## Page body format

`# Title`, then `**Summary**:` (1-2 sentences), `**Sources**:` (basename wikilinks), `**Last updated**:`, a `---` rule, then the body with `[[wikilinks]]` throughout. Project pages carry `## State`, `## Members`, and `## Next steps` sections.

## Hard rules

1. A writer never deletes or moves a wiki page, and never sets `status: archive`. Set `status: retired` when a page should stop changing; the curator marks `archive` for the lifecycle job (below).
2. Never modify `meetings/` notes after creation, and never touch `raw/`. Sources are immutable; the wiki is where knowledge changes. The lifecycle job is the one exception: it moves marked files to `archive/`.
3. Cite every factual claim: `(source: filename)`. A source that is not a vault file names where it lives: `(source: filename, repo: <repo-name>)` for a file in a git repo, `(source: filename, external)` for anything else (a Confluence export, a vendor PDF, a document someone sent). The repo NAME, not a path — paths rot on refactors. An unmarked `(source: X.md)` therefore means a vault file, which is what makes the citation checkable (Mike, 2026-10-26). Flag uncertainty `[unverified]`.
4. Note contradictions explicitly; never silently resolve them.
5. Every ingest or update sets the page's `title` and `description` frontmatter, then regenerates `index.md` from frontmatter with the index script. Never hand-edit index entries. Append the operation to `log.md` at the end of the file: append-only, bare ISO heading, bold `**tag | name**` first line. The log is the audit trail.
6. Link with basename `[[wikilinks]]` only, never path-style links.

## Page lifecycle (the only sanctioned removal path)

Every page and meeting note carries `status`, stamped explicitly: `active`, `retired`, or `archive`. Retired pages stay in place, linkable and searchable, and writers stop updating them. `archive` is the curator's mark for the lifecycle job, which moves the file to `wiki/archive/` and drops its index entry. Nothing is deleted and no link is rewritten: Obsidian resolves wikilinks by basename vault-wide, so links to an archived page keep working, and the index, lint, and search skip `archive/`. The job reports would-be orphans as candidates and never cascades. The mark is the permission.

## Markdown gotchas (Obsidian renderer)

These matter for any vault opened in Obsidian:

- Never write raw angle-bracket placeholders (a bare `<name>`) in page bodies. The renderer parses them as unclosed HTML and silently swallows everything after them, including whole tables. Use backticks or ALL_CAPS placeholders.
- Tables: escape literal pipes in cells as `\|` (wikilink aliases in tables too: `[[page\|alias]]`), keep cells single-line, leave a blank line before the header row, and never let `**emphasis**` open in one cell and close in another.
- Callouts use `> [!note]` syntax; end them with a blank line, or the next bare `>` line continues the callout.

## Slugs

Lowercase, hyphen-separated, max 50 chars, no special characters, derived from the title ("React useEffect cleanup" becomes `react-useeffect-cleanup`).
