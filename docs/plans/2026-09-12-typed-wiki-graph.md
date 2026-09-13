# Typed edges for the wiki graph

**Status:** phases 0 to 6 done 2026-09-13. Retest on the same 100 prompts: typed-triple precision
0.10 in the hook slice (positions 1 to 8) against 0.03 for `mentions`, below the 0.5 bar. The triples
were correct facts about the right entity; the prompts were rarely structural questions. Decision
(Michael, 2026-09-13): keep the graph block in the hook anyway, since the typed graph now carries
facts that exist nowhere in prose (ownership, dependencies) and the cost is about 8 lines on the
17% of prompts that seed an entity. `maintainers` (edge `maintains`) added 2026-09-13 at Michael's request: who operates, supports, or repairs
a thing, distinct from `owner` (accountable) and `people` (anyone involved); first values SignalsAI and
the rating platform. Michael wants the next pass to add, in this order: `about` on meeting notes,
sessions, and summaries (the writer already decides which pages a note updates, so it is a free
byproduct and gives the hook a passage-bearing typed edge); `part_of` for project hierarchy;
`runs_on`, `reads_from`, `writes_to` on the 14 pipeline pages, with `depends_on` reserved for
requirements those three do not express. Not adding: `stakeholders`, namespaced ids, derived
rollups, generated inverses, `creator`/`contributors`. Source: Codex vocabulary review, 2026-09-13. Graph after backfill: 731 entities, 5,940 edges, of which 2,440 typed
(attended 2,190, member_of 147, depends_on 73, owns 30). Two fixes found during phase 6: the walk cut
to `top_k` before dropping `mentions` (now filters first, and ranks owns, depends_on, member_of,
attended within a hop level), and attendee names resolve through a page's `aliases` list.

## Why

The recall hook injects up to 8 graph triples on most prompts. Measured on 2026-09-12 against 100
real prompts sampled from three weeks of Claude Code transcripts, with a Haiku judge labelling each
injected item as helpful or not:

| Leg | Items judged | Helpful |
|-----|--------------|---------|
| Memory, current top 4 | 400 | 38% |
| Memory, hits both search legs agreed on | 121 | 66% |
| Memory, single-leg hits | 879 | 27% |
| Graph triples, positions 1 to 20 | 845 | 2% |

The graph result is structural, not a volume problem. `build_graph.py` derives every edge from a
`[[wikilink]]` and labels it `mentions`. All 3,492 relations in the index carry that one predicate,
so a triple says "page A links to page B" and nothing about how they relate. The text index already
contains every wikilink in context, so the graph leg duplicates the memory leg with less
information. Adding pages adds more edges of the same kind. Two earlier reviews (session 2026-09-05)
reached the same diagnosis; the leg was kept on the theory that the wiki would grow into it. It
grew, and the number is 2%.

A graph earns its place by answering questions that span pages: who owns the system this pipeline
feeds, which projects does this person touch, what breaks if this changes. That needs typed edges,
and typed edges need a source. This plan gives them one.

## Goal

Relation fields in page frontmatter, filled by every writer that touches a page, emitted as typed
edges by the graph builder, and shown by the recall hook only when they exist. `mentions` edges stay
in the graph for the CLI and reindex checks but stop reaching the hook.

## Passing check

Rerun `sample_hits.py` and the judge over the same 100 prompts after phase 5. Pass when:

- typed-triple precision is 0.5 or better (against 0.02 today);
- every prompt that names an active project or system page returns at least one typed triple;
- `wiki-lint` is clean, with no unresolved relation targets and no active project page missing
  `owner`.

If typed precision stays under 0.5, the field set is wrong and phase 6 opens a schema discussion
before any further filling.

## Design decisions

**Three relation fields, one meaning each.** Two fields with a fuzzy boundary (`systems` versus
`depends_on`) is how frontmatter rots, so `systems` was dropped.

| Field | On page types | Emits | Target must be |
|-------|---------------|-------|----------------|
| `owner` | project, system, pipeline | `owns` (target → page) | one `person` page |
| `people` | project, system, pipeline | `member_of` (target → page) | `person` pages |
| `depends_on` | project, system, pipeline | `depends_on` (page → target) | any page |

Values are slugs, matching the wikilink basename rule already in force. Lists in YAML list form so
Obsidian shows them as list properties.

**`attendees` on meeting notes** is the one field the Fathom pipeline can fill without a model, from
the participants it already writes into the body. It emits `attended` (person → meeting). It is
cheap and gives the person pages their first typed edges.

**Split the `entity` type.** 132 pages are `type: entity`: vendors, internal systems, production
pipelines, homelab hosts, plans, guides, and four people. Typed edges need to know a `person` from a
`pipeline`, so `entity` gets two new siblings, `system` and `pipeline`, and misfiled people move to
`person`. `entity` stays for everything else (a vendor account, a document, a guide). Retagging is a
frontmatter edit, no file moves.

**`decided_in` is out of scope.** Decisions live in dated body sections and meeting notes already
link to the pages they touch. Typing that link needs a capture rule the writers do not have yet.
Revisit after phase 6.

**No LLM in the builder.** `build_graph.py` stays deterministic. The model work happens once, in the
backfill (phase 3), and then at write time inside the writers that already run a model.

## Phases

### Phase 0. Hook stops showing `mentions`

`graph-memory/recall_hook.py`, `graph_facts()`: drop triples whose predicate is `mentions`. The
graph leg, `graph_recall.py`, the CLI, and the label logic are untouched. Until phase 5 lands the
hook shows no graph block, and the label reads `memory: N hits`. Approved by Michael on 2026-09-12.

### Phase 1. Schema and lint

- Vault `wiki/CLAUDE.md`, "Page frontmatter": add `system` and `pipeline` to the type list; add
  `owner`, `people`, `depends_on` with the table above; add `attendees` to the meeting-note schema.
  State the rule for writers: fill a relation only from evidence in the source being ingested, cite
  it in the body as usual, and never infer an owner.
- `scripts/wiki-lint.py`: extend `PAGE_TYPES`; every relation value must resolve to an existing page
  slug; `owner` and `people` targets must be `person`; an active `project` page without `owner` is a
  warning (not an error, so the nightly run reports instead of blocking).
- `graph-memory/build_graph.py` `TYPE_BY_FOLDER` and any type checks: accept the new types so
  phase 2 does not drop pages from the entity table.

### Phase 2. Retag `entity` pages

A subagent reads each of the 132 `entity` pages and proposes `system`, `pipeline`, `person`, or
keep `entity`, one line per page with the sentence that justifies it. Michael approves the list.
Apply with the `obsidian` CLI so properties stay typed. Run lint and `reindex.sh`; the entity count
must not drop.

### Phase 3. Backfill relations on existing pages

Same pattern for the 34 `project` pages and the new `system` and `pipeline` pages: a subagent
proposes `owner`, `people`, and `depends_on` from body text and cited sources, quoting the
supporting line for each value. Unsupported fields stay empty. Michael approves; apply via the CLI.
Meeting notes: a one-off script fills `attendees` from the participants line the pipeline already
writes. That one is deterministic and needs no review beyond a spot check.

### Phase 4. Writers keep the fields current

This is the part that decides whether the graph is still useful in a month.

| Writer | What changes |
|--------|--------------|
| `/wiki` skill, ingest mode (`skills/wiki/SKILL.md`) | Instructions for creating or updating a `project`, `system`, or `pipeline` page: set or extend `owner`, `people`, `depends_on` when the source supports it; never remove a value without a source that says it changed. The Fathom sweep's headless ingest and the raw sweep both run these instructions, so this one edit covers both. |
| `scripts/fathom-pipeline.py` | Write `attendees:` into meeting-note frontmatter from the participant list, deterministically, next to `type`/`status`/`title`/`date`. |
| `wrap-up` skill | When it promotes a session digest into a project page, same rule as `/wiki`. |
| `graph-memory/digest/session_end.py` | No change. Session files carry no frontmatter and stay wikilink-only. |
| cos-desk `status.py`, `scripts/wins-sweep.py` | No change. They append bullets and never touch frontmatter. |

Each writer change ships with one check: ingest a fixture source that names an owner and a
dependency, and assert the fields land. The live `skills/wiki` is Michael's symlink; the repo copy
changes first and the live one follows the usual sync.

### Phase 5. Builder emits typed edges

`build_graph.py`: after the wikilink pass, read the four relation fields from each page's frontmatter
and emit edges with the predicates in the table. Targets resolve through the same slug and alias
table wikilinks use; an unresolved target is logged and skipped (lint will already have flagged it).
`graph_recall.WALK` needs no change. `recall_hook.graph_facts()` already filters `mentions` from
phase 0, so typed edges start appearing in the hook as soon as the hourly reindex runs. Extend
`test_recall_hook.py` with one case: a fixture graph with one `owns` edge and one `mentions` edge
shows exactly the first.

### Phase 6. Measure

Rerun the sample and judge (scripts from the 2026-09-12 scratchpad, to be checked into
`graph-memory/eval/` at this phase). Compare against the table at the top. Record the result on the
wiki `rekall` page and in `wiki/log.md`, and decide there whether `decided_in` is worth a capture
rule.

## Risks

- **Fields rot.** Mitigation is phase 4 plus the lint warning on ownerless active projects, which
  the nightly lint run surfaces. If the warning list grows for two weeks, the writers are not doing
  their job and phase 4 reopens.
- **Retag breaks a consumer.** `build_graph.py`, `wiki-lint.py`, the `/wiki` skill's type list, and
  `wiki/index.md` generation all read `type`. Phase 1 touches the first three; phase 2 checks the
  index regenerates.
- **Judge bias.** The 2% baseline came from one Haiku pass. Phase 6 uses the same judge and prompt
  so the comparison holds, and Michael spot-checks 30 labels each side.
- **Public repo.** Fixtures and eval scripts must not carry employer names, people, or ids. The
  sampled prompts stay in the scratchpad and out of git; the eval script regenerates them locally.

## Order and dependencies

0 is independent and ships first. 1 before 2 and 3 (lint must accept the new types and fields).
2 before 3 (backfill targets need correct types). 4 can run in parallel with 2 and 3. 5 after 1.
6 after everything, once the hourly reindex has picked up the backfilled pages.
