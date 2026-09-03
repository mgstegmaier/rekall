# Vault conventions

The schema layer of a Rekall wiki: layout, placement rules, page format, and the hard rules that keep an LLM-maintained wiki trustworthy. Extracted from a personal vault that has run this way since early 2026; generalize the names, keep the mechanics.

Terminology: the **curator** is the human who owns the vault. The **writer** is any LLM session or pipeline that edits it.

## Layout

```
wiki/
├── index.md          # content catalog; GENERATED from page frontmatter, never hand-edit entries
├── log.md            # operations log; append-only, headings are bare ISO dates (## YYYY-MM-DD)
├── CLAUDE.md         # the schema file (this document, adapted to your vault)
├── people/           # person entity pages
├── projects/         # project pages (state, members, decisions, next steps)
├── entities/         # other entities: servers, tools, orgs, places, products
├── concepts/         # ideas, patterns, methodologies, fundamentals
├── summaries/        # per-source summary pages
├── meetings/         # meeting notes; SOURCE layer, immutable once written
└── raw/              # curator-managed sources; writers never touch these
```

Three layers, per the LLM Wiki pattern: `raw/` and `meetings/` are immutable sources, the type directories are the wiki, and the schema file governs the writers.

## Placement (mechanical, never a judgment call)

- Person → `people/`
- Project → `projects/`
- Any other entity → `entities/`
- Concept → `concepts/`
- Summary → `summaries/`, for NON-MEETING sources only (long, raw, or external documents where the compiled summary is the artifact). Never create a per-meeting summary page: a meeting note is already a summary, so meeting content flows directly into entity, project, and concept pages that cite the note.
- One level deep, never deeper. If a page could go two places, it goes in `entities/`.
- Basenames are unique across the whole wiki, because wikilinks resolve by basename.
- Page names: lowercase, hyphen-separated, max 50 characters.

## Project catalog (curated)

`projects/` holds every initiative the wiki knows about, not only the curator's own. Rules for writers:

- Match new content to an EXISTING project page first. Check the `projects/` listing and page titles before creating anything.
- When a genuinely new project page is unavoidable, tag it `needs-review` in frontmatter so the curator's triage view surfaces it. The curator blesses, renames, merges, or retires it later.
- Frontmatter fields the curator maintains by hand (for example a `resource:` link to an external task board) are never removed or overwritten by a writer.

## Page frontmatter

```yaml
type: wiki-page          # meetings use: type: meeting
wiki-type: entity|project|concept|summary
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

1. A writer never deletes a wiki page. Mark `[deprecated]` in its Summary, or let the curator mark `status: retired` for the cleanup job (below).
2. Never modify `meetings/` notes after creation, and never touch `raw/`. Sources are immutable; the wiki is where knowledge changes.
3. Cite every factual claim: `(source: filename)`. Flag uncertainty `[unverified]`.
4. Note contradictions explicitly; never silently resolve them.
5. Every ingest or update sets the page's `title` and `description` frontmatter, then regenerates `index.md` from frontmatter with the index script. Never hand-edit index entries. Append the operation to `log.md` at the end of the file: append-only, bare ISO heading, bold `**tag | name**` first line. The log is the audit trail.
6. Link with basename `[[wikilinks]]` only, never path-style links.

## Retiring pages (the only sanctioned delete path)

The curator marks a page `status: retired` in its frontmatter; a cleanup job (dry-run by default) then unlinks references vault-wide, removes the index entry, deletes the file, and logs an audit entry. The mark is the permission: a writer never deletes an unmarked page. Citations pointing at a retired source are annotated `— retired`, never removed; the claims they supported stay, flagged by the annotation.

## Markdown gotchas (Obsidian renderer)

These matter for any vault opened in Obsidian:

- Never write raw angle-bracket placeholders (a bare `<name>`) in page bodies. The renderer parses them as unclosed HTML and silently swallows everything after them, including whole tables. Use backticks or ALL_CAPS placeholders.
- Tables: escape literal pipes in cells as `\|` (wikilink aliases in tables too: `[[page\|alias]]`), keep cells single-line, leave a blank line before the header row, and never let `**emphasis**` open in one cell and close in another.
- Callouts use `> [!note]` syntax; end them with a blank line, or the next bare `>` line continues the callout.

## Slugs

Lowercase, hyphen-separated, max 50 chars, no special characters, derived from the title ("React useEffect cleanup" becomes `react-useeffect-cleanup`).
