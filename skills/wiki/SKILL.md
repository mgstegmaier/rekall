---
name: wiki
description: LLM Wiki skill - ingest sources, query knowledge, lint for health (automated nightly). Maintains a persistent, interlinked wiki in the Obsidian vault from user-curated source documents. Based on Karpathy's LLM Wiki pattern.
---

# LLM Wiki Skill

## Purpose

Maintain a persistent, interlinked knowledge base in the Obsidian vault. Unlike RAG (re-derive every query), the wiki **compounds** -- each source enriches entity pages, concept pages, and cross-references. Claude does all the bookkeeping; the user curates sources and asks questions.

Based on Andrej Karpathy's LLM Wiki pattern. The wiki is a "codebase" maintained by AI: Obsidian is the IDE, Claude is the programmer, the wiki is the code.

**Vault path:** `~/obsidian-vault/heck-db/`

## When to Invoke

**Manually invoke with:** `/wiki`, `/wiki ingest`, `/wiki query`, `/wiki lint`

**Automatically triggered when user says:**
- "add to wiki", "wiki this", "ingest this"
- "what does the wiki say about...", "check the wiki"
- "wiki health", "lint the wiki", "check wiki"

---

## Architecture

```
heck-db/
└── wiki/                 # Claude-maintained knowledge base = one OKF-style bundle
    │                     # layout, placement, page format: see wiki/CLAUDE.md
    └── raw/              # User-curated sources (IMMUTABLE to Claude -- Mike adds/removes files himself)
        └── *.md, *.pdf   # Web clips, articles, notes, PDFs
```

**Three layers:**
1. Sources -- `wiki/raw/` (user drops files; Claude reads but NEVER modifies; Mike curates it himself, so files may appear and disappear) and `wiki/meetings/` (one note per meeting, written by the Fathom pipeline, then treated as immutable source material).
2. `wiki/` -- Claude creates/updates interlinked markdown pages in `wiki/pages/` (flat; `type` frontmatter is the taxonomy) per wiki/CLAUDE.md's placement rules.
3. Schema -- **`wiki/CLAUDE.md` in the vault is the source of truth for structure** (layout, placement, page format, hard rules); it loads automatically for any session touching wiki files. This skill file owns the workflows (ingest/query/lint). Layout follows Google's Open Knowledge Format idiom (see `docs/research/2026-08-22-okf-for-obsidian-wiki.md`); only `type` frontmatter is required for OKF conformance.

**Automated ingest:** the Fathom pipeline (see `docs/plans/2026-08-21-wiki-revival-fathom-pipeline.md`) runs unattended: it writes meeting notes to `wiki/meetings/`, ingests them and anything in `wiki/raw/` into the wiki, and logs everything. It has standing permission to create and update pages anywhere in `wiki/`, including `index.md` and `log.md`. Review happens after the fact -- by reading pages and `wiki/log.md` -- not by pre-approval.

---

## Bootstrap

On first invocation, check if `wiki/index.md` and `wiki/log.md` exist. If not, create them:

```bash
# Check if wiki directory exists
ls ~/obsidian-vault/heck-db/wiki/index.md 2>/dev/null

# If missing, bootstrap:
obsidian create vault="heck-db" path="wiki/index.md" content="# Wiki Index\n\nContent catalog for the LLM-maintained wiki.\n\n---\n\n## Entities\n\n_No entity pages yet._\n\n## Concepts\n\n_No concept pages yet._\n\n## Summaries\n\n_No summary pages yet._"
obsidian property:set vault="heck-db" path="wiki/index.md" name="okf_version" value="0.2" type=text

obsidian create vault="heck-db" path="wiki/log.md" content="# Wiki Log\n\nChronological record of all wiki operations.\n\n---"
obsidian property:set vault="heck-db" path="wiki/log.md" name="type" value="log" type=text
obsidian property:set vault="heck-db" path="wiki/log.md" name="date" value="{YYYY-MM-DD}" type=date
obsidian property:set vault="heck-db" path="wiki/log.md" name="tags" value="wiki,log" type=list
```

Also check that `wiki/raw/` exists:
```bash
mkdir -p ~/obsidian-vault/heck-db/wiki/raw
```

---

## Mode: Ingest

Runs when the Fathom pipeline finds a new meeting note or `wiki/raw/` file, or when the user asks to ingest something. Same workflow either way -- ingest writes directly, with citations, and the log is the audit trail. There is no discuss-before-writing step; that ceremony starved the wiki (five ingests in April 2026, then four months of silence).

### Workflow

1. **Read the source** via `obsidian read vault="heck-db" path="wiki/raw/{filename}"` (or Read tool for PDFs/images; meeting notes live in `wiki/meetings/`)
2. **Check for existing pages** via `obsidian search vault="heck-db" query="{concept}"` -- update existing pages rather than creating duplicates
3. **Create or update wiki pages** for each major entity, concept, or topic:
   - Entity pages: people, places, organizations, tools, systems, projects
   - Concept pages: ideas, patterns, methodologies, principles
   - Summary pages: source-specific summaries -- for NON-MEETING sources only (long/raw/external docs where the compiled summary is the artifact). NEVER create a per-meeting summary page: the meeting note is already Fathom's summary; merge meeting content into entity/project/concept pages citing the meeting note (Mike, 2026-08-25)
   - Project entity pages capture: current state, members, decisions, next steps
4. **Cite every factual claim** with `(source: filename)` after the claim
5. **Note contradictions** explicitly when new source disagrees with existing wiki pages
6. **Flag unverified claims** with `[unverified]` when source reliability is uncertain
7. **Regenerate `wiki/index.md`** -- the index is generated from page frontmatter (each page's `description` is its index hook). Run `python3 ~/github_repos/personal_projects/rekall/scripts/wiki-index.py`; never hand-edit index entries
8. **Append to `wiki/log.md`** with entry: `## [YYYY-MM-DD] ingest | {source-name}\n\nPages created/updated: [[page-1]], [[page-2]], ...` -- ALWAYS at the END of the file, dated with today's date, even when the source material is older. The log is append-only run order, not subject-date order; inserting a backdated block mid-file breaks the ordering contract (lint check 7 catches it)

### Example Ingest

User drops `wiki/raw/karpathy-llm-wiki.md` and says "ingest this" (or the pipeline picks it up):

1. Read the source
2. Create pages:
   - `wiki/pages/llm-wiki-pattern.md`
   - `wiki/pages/rag-vs-compiled-knowledge.md`
   - `wiki/pages/andrej-karpathy.md`
   - `wiki/pages/karpathy-llm-wiki-summary.md`
3. Regenerate index.md (wiki-index.py) and append to log.md (append-only, at the END)

---

## Mode: Query

When the user asks a question about topics covered by the wiki.

### Workflow

1. **For cross-cutting questions**, run `obsidian search vault="heck-db" query="{topic}"` (or Grep over `wiki/`) before walking index links -- it catches pages the index's category grouping can miss
2. **Read `wiki/index.md`** to find relevant pages
3. **Read relevant wiki pages** via `obsidian read`
4. **Synthesize an answer** with citations to both wiki pages and raw sources
5. **If answer is valuable**, offer: "This answer could be filed as a new wiki page. Want me to save it?"
6. **If not in wiki**, say so clearly: "The wiki doesn't cover this topic yet. Would you like to add a source about it?"

### Citation Format in Answers

```
The LLM Wiki pattern uses three layers (wiki: [[llm-wiki-pattern]]) -- raw sources,
wiki pages, and a schema document (source: karpathy-llm-wiki.md).
```

---

## Mode: Lint

Lint is automated: `rekall/scripts/wiki-lint.py` runs nightly via launchd (`com.heckatron.wiki-lint`) and notifies on regressions. To run it manually:

```bash
python3 ~/github_repos/personal_projects/rekall/scripts/wiki-lint.py --verbose
```

---

## Wiki Page Format

Every wiki page (except index.md and log.md) follows this structure:

```markdown
# Page Title

**Summary**: One to two sentences describing what this page covers.

**Sources**: [[source-1]], [[source-2]]

**Last updated**: YYYY-MM-DD

---

Main content goes here. Use clear headings and short paragraphs.

Link to related concepts using [[wiki-links]] throughout the text.
Every factual claim references its source: claim text (source: filename).

If two sources disagree, note the contradiction explicitly:
> **Contradiction**: Source A says X, but Source B says Y. [needs resolution]

If a claim has no source, mark it: claim text [unverified]

## Related pages

- [[related-concept-1]]
- [[related-concept-2]]
```

---

## Properties

Set via `obsidian property:set` after creating each wiki page. See wiki/CLAUDE.md "Page frontmatter" for the required and optional properties -- this section just shows the CLI mechanics.

### Example Property Commands

```bash
# After creating wiki/pages/llm-wiki-pattern.md
obsidian property:set vault="heck-db" path="wiki/pages/llm-wiki-pattern.md" name="type" value="concept" type=text
obsidian property:set vault="heck-db" path="wiki/pages/llm-wiki-pattern.md" name="date" value="2026-04-14" type=date
obsidian property:set vault="heck-db" path="wiki/pages/llm-wiki-pattern.md" name="tags" value="knowledge-management,ai,patterns" type=list
obsidian property:set vault="heck-db" path="wiki/pages/llm-wiki-pattern.md" name="sources" value="karpathy-llm-wiki.md" type=list
```

---

## Updating Existing Pages

When a new source adds information to an existing wiki page:

1. Read the existing page via `obsidian read vault="heck-db" path="wiki/{slug}.md"`
2. Merge new information with existing content -- never silently drop existing claims; note contradictions instead
3. Write the updated page via Write tool (Obsidian CLI `create` overwrites; use Write tool for targeted edits to preserve properties)
4. Update the `sources` property to include the new source
5. Update the `date` property to today
6. Append update entry to `wiki/log.md`

---

## Naming Rules

See wiki/CLAUDE.md "Placement" for type and naming rules (lowercase, hyphen-separated, max 50 chars, unique basenames across the wiki). In practice: derive the slug from the topic ("Machine Learning" -> `machine-learning.md`), entity pages use the entity name ("Andrej Karpathy" -> `andrej-karpathy.md`), summary pages include a source reference (`karpathy-llm-wiki-summary.md`). `wiki/daily-notes-archive/` is `/today`-owned machinery, not wiki pages -- never ingest from it, never write to it.

---

## Rules

Hard structural rules (deletion, citations, index/log updates, contradictions, wikilinks) are defined in wiki/CLAUDE.md -- see "Hard rules". The one exception worth restating here because it's easy to miss mid-workflow: NEVER modify `wiki/raw/` or `wiki/meetings/` -- both are immutable source layers (Mike curates `wiki/raw/` himself), except the retire-cleanup job (`wiki-cleanup.py`), which may rewrite wikilinks and annotate citations in both while unlinking a retired page.

This skill adds two workflow rules on top of wiki/CLAUDE.md's hard rules:

1. **Keep pages focused** -- one concept/entity per page; split large pages
2. **Good answers compound** -- when a query produces a valuable synthesis, offer to file it as a wiki page

---

## Relationship to Other Systems

| System | Purpose | Interaction |
|--------|---------|-------------|
| `memory/` (knowledge-capture) | Conversation continuity, point-in-time learnings | Wiki pages may `[[link]]` to memory notes; separate lifecycle |
| `ideas.md` | Quick idea capture | Ideas about wiki topics can be ingested as sources |
| `/knowledge-recall` | Search the vault | Can search wiki pages alongside memory |
| `/upgrade` | Extract learnings from work | Learnings from wiki work captured normally |

The wiki is for **cumulative, interlinked understanding**. Memory is for **conversation context and quick captures**. They complement each other.
