# Obsidian vault CLI reference

Full command syntax and conventions for the `heck-db` vault. Load this before writing to the
vault. The always-on rule (`identity/obsidian-vault.md`, deployed to
`~/.claude/rules/familiar-obsidian-vault.md`) carries only the vault path, the write
restrictions, and a pointer here — this file is canonical for everything else.

**Vault:** `~/obsidian-vault/heck-db/` · **Requirement:** Obsidian must be running, or the CLI
fails and you fall back to the Write/Read tools.

**PATH note:** the Bash tool may not have `obsidian` in PATH. On `command not found`, use the
full path. Mac: `/Applications/Obsidian.app/Contents/MacOS/obsidian`. Windows:
`%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe` (verify, the installer location varies).
Always pass `vault="heck-db"` to target the right vault.

## Creating notes

Two steps, in this order. Do not hand-write YAML frontmatter; Obsidian manages it.

```bash
# 1. Body content
obsidian create vault="heck-db" path="memory/learnings/coding/2026-02-28-slug.md" content="# Title\n\nBody content"

# 2. Typed properties, one call each
obsidian property:set vault="heck-db" path="memory/learnings/coding/2026-02-28-slug.md" name="type" value="learning" type=text
obsidian property:set vault="heck-db" path="memory/learnings/coding/2026-02-28-slug.md" name="date" value="2026-02-28" type=date
obsidian property:set vault="heck-db" path="memory/learnings/coding/2026-02-28-slug.md" name="tags" value="coding,relevant-tag" type=list
```

## Reading and searching

```bash
obsidian search vault="heck-db" query="topic" format=json             # vault-indexed search
obsidian search:context vault="heck-db" query="topic" format=json     # search with matching lines
obsidian read vault="heck-db" path="memory/learnings/coding/file.md"  # note content
obsidian backlinks vault="heck-db" path="file.md" format=json         # incoming links
obsidian tags vault="heck-db" format=json                             # all vault tags
obsidian orphans vault="heck-db"                                      # notes with no incoming links
```

## Appending, prepending, moving

```bash
obsidian append vault="heck-db" path="file.md" content="New content"
obsidian prepend vault="heck-db" path="file.md" content="New content"
obsidian daily:append vault="heck-db" content="- Quick note"          # today's daily note
obsidian move vault="heck-db" path="old/path.md" to="new/path.md"      # auto-updates wikilinks
```

## CLI conventions

1. Use the CLI for all vault operations, not the Write/Read tools. It talks to the running app,
   so indexing, backlinks, typed properties, and the graph update immediately.
2. Use `path=` (exact path from vault root), never `file=` — wikilink resolution is ambiguous.
3. Create the body first, then set each property.
4. Use `\n` for newlines inside content values.
5. If Obsidian is not running and the CLI fails, fall back to Write/Read.

## Write locations and naming

| Directory | Purpose | Naming |
|-----------|---------|--------|
| `memory/sessions/{YYYY-MM-DD}/` | Active work sessions | `session-{slug}.md` |
| `memory/context/` | Cross-conversation context | `context-{slug}.md` |
| `inbox/` | Quick capture | `{YYYY-MM-DD}-{source}-{slug}.md` |
| `inbox/proposed-learnings/` | Tier 3 learning proposals | `{YYYY-MM-DD}-{slug}.md` |
| `memory/learnings/{category}/` | Validated learnings | `{YYYY-MM-DD}-{slug}.md` |
| `memory/decisions/` | Architectural decisions | `{YYYY-MM-DD}-{slug}.md` |
| `wiki/daily-notes-archive/` | Archived daily notes | `{YYYY-MM-DD}.md` |
| `wiki/meetings/` | Fathom meeting notes (pipeline + `/today`) | `{YYYY-MM-DD}-{slug}.md` |
| `recipes/` | Recipes (`/recipe`) | `{slug}.md` |
| `wiki/{people\|projects\|entities\|concepts\|summaries}/` | Wiki pages (`/wiki`), one level deep per type — see `wiki/CLAUDE.md` for placement rules | `{slug}.md` |

Notes with no specified home go in `notes/`, never the vault root.

**System-managed files** (read and write, mutated by the `/today` skill): `today.md` (daily
worksheet, archived and overwritten each day; its `<!-- fathom-digest -->` Meeting Digest block
is owned by the Fathom pipeline, which also performs the daily rollover on its first sweep), `recurring.md` (templates, `next:` dates
advanced), `ideas.md` (backlog, parking-lot items appended), `therapy-reflections.md`
(mood/energy entries appended).

## File format

Every file gets typed properties via `property:set`:

| Property | Type | Values |
|----------|------|--------|
| `type` | text | `learning`, `decision`, `session`, `context`, `inbox`, `proposed-learning`, `daily`, `meeting`, `recipe`, `person`, `project`, `entity`, `concept`, `summary`, `log`, `schema` |
| `date` | date | `YYYY-MM-DD` |
| `tags` | list | comma-separated |

Additional properties vary by type; see the individual skill docs.

## Markdown gotchas in Obsidian (apply to every vault write)

- **Never write raw angle-bracket placeholders** like `<name>` or `<value>` in note bodies.
  Obsidian's renderer treats them as unclosed HTML tags and silently swallows everything after
  them — including whole tables. Use backticks (`` `name` ``) or ALL_CAPS placeholders instead.
- **Tables**: escape any literal `|` inside a cell as `\|`; keep cells single-line; leave a
  blank line before the header row; don't let `**emphasis**` open in one cell and close in
  another (strip emphasis from generated cell text).
- **Wikilinks in tables** are fine (`[[page]]`, `[[page\|alias]]` — note the escaped pipe for
  aliases inside tables).
- Callouts use `> [!note]` syntax; a bare `>` line after one continues the callout, which is
  usually not what generated content wants — end callouts with a blank line.

## Slugs and categories

Slugs: lowercase, hyphen-separated, max 50 chars, no special characters, derived from the
title ("React useEffect cleanup" becomes `react-useeffect-cleanup`).

Learning categories: `coding`, `workflow`, `debugging`, `architecture`.
