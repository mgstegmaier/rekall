# Contextual retrieval for the memory leg

**Status:** closed 2026-09-14. Options 1, 2, 3 built and measured; none changed retrieval in a way the
eval can see at 300 prompts judged twice. Kept: option 1 (one line, free), the config key, numpy scan,
cached model load, and the eval harness. Parked: `contextualize.py`. Not kept: BGE-base (rebuild cost).
Next on retrieval is the measurement, not the retriever: a prompt set from outside the rekall repo and
a small human-labelled set to calibrate the judge. Option 4 (reranker) waits for that.

## Why

The memory leg's two search legs each score about 0.27 helpful on their own and 0.66 when they
agree (100-prompt eval, 2026-09-12, `graph-memory/eval/`). BGE-small is not the weak link: meaning-only
hits match keyword-only hits and beat them on prompts that name an entity (0.35 vs 0.28). The
weak link is chunk context. A chunk is embedded and full-text indexed as `[file § section]` plus
the section body, so a "Next steps" section from `pages/doc-extraction.md` carries no page title, no
description, and often no mention of the subject. Anthropic's contextual retrieval (raw note
"Contextual Retrieval in AI Systems", wiki page `contextual-retrieval`) reports a 35% cut in
retrieval failures from prepending a chunk-specific context sentence before embedding, 49% when
the same context also feeds BM25, 67% with a reranker on top.

## What the paper says that applies here

1. **Context goes into both indexes.** The gain from contextual BM25 (35% to 49%) comes from the
   context text being searchable by keyword too. `build_index.py` already inserts the same
   `embed_text` into `chunks_fts`, so any prefix we add reaches both legs with no extra code.
2. **Hybrid with rank fusion.** Already in place (`search.fuse`, reciprocal rank fusion).
3. **Rerank a wide candidate set.** The paper reranks the top 150 and passes the top 20 to the
   model. The hook has a 1,500-character budget and fires on every prompt, so a per-prompt Claude
   rerank is out. A local cross-encoder (fastembed ships `bge-reranker-base`) over the fused top 20
   is 100 to 200 ms and plausible; `/wiki` query mode has no such budget and could rerank with a
   model. Measured last, if options 1 to 3 leave headroom.
4. **Prompt caching makes contextualization cheap.** Whole document in the cached prefix, one call
   per chunk. Paper figure: about $1.02 per million document tokens. This corpus is 9,316 chunks,
   about 1.5M tokens, so roughly $2 once and cents per night after, since `build_index.py` already
   tracks file hashes and only re-chunks changed files.
5. **Domain-specific contextualizer prompts help.** Ours can hand the model what the wiki already
   knows: page title, type, description, owner, and the wikilink targets in the chunk. That is
   better than a generic "situate this chunk" prompt.
6. **Embedding model choice matters and the paper favours Gemini and Voyage.** Both are hosted,
   and this vault's text stays local, so the candidates are local: BGE-base as the next step up.
7. **Under about 200k tokens, skip retrieval and put it all in context.** Not us, at 1.5M.

## Options, in order

### Option 1. Deterministic context prefix (no model)

`file_docs()` in `build_index.py` prepends the page title and description to every chunk's
`embed_text`: `[rel § section]\nTitle: description\n<body>`. The stored `text` (what the hook
excerpts) is unchanged. Requires `build_index.py --full` (re-embed everything). This is also the
permanent fallback when Claude is unreachable in the nightly run: the index never blocks on a model.

### Option 2. Larger local embedding model

BGE-base-en-v1.5 (768 dims) via fastembed, same query prefix. `fetch_model.sh` pins the ONNX files;
`build_index.py --full` after the swap because stored vectors are model-specific. Expect embedding
to take about three times longer than BGE-small; recall latency is dominated by the dot products
over 9,316 rows, which double in cost at 768 dims. Measure the hook's `READ_TIMEOUT` (0.25 s) still holds.

### Option 3. Model-written context sentence per chunk

A new step `contextualize.py`, same shape as `distil.py`: for each file whose hash changed, one
`claude -p` call per chunk with the whole page as the cached prefix and a prompt that returns one or
two sentences situating the chunk (subject page, what the section is about, which entities it
concerns). Stored in a new `chunks.context` column; `embed_text` becomes
`[rel § section]\n<context>\n<body>`, replacing the option 1 prefix when a context exists.
Model from `digest/config.json` like distil, default Haiku. Runs in `reindex.sh` before
`build_index.py`. Failure of any call leaves that chunk on the option 1 prefix and logs it.

### Option 4 (conditional). Local reranker over the fused top 20

Only if the three above leave the both-legs row under about 0.8.

## Passing check

Same 100 frozen prompts and judge (`graph-memory/eval/sample_hits.py`, `judge.py`), memory rows
only. Baseline (2026-09-12): top 4 overall 0.38, keyword-only 0.26, meaning-only 0.27, both-legs 0.66.
The judge's noise floor is about 5 points (identical hits drifted 0.33 to 0.41 across runs), so an
option counts as a win at 10 points or more on top-4 overall, or on meaning-only plus both-legs
together. Each option is measured alone against the previous winner; nothing stacks unmeasured.

## Order

1 now. 2 next, on top of 1 if 1 wins, else on the baseline. 3 after 2. Record each result here and
on the wiki `rekall` page.

## Results

### Option 1 (2026-09-13): kept

Same 100 prompts, memory rows. Top 4 overall 0.38 to 0.42 (+4, inside noise). Position 1 0.45 to 0.55
(+10). Keyword-only hits 0.26 to 0.35 (+9). Meaning-only 0.27 to 0.26 (flat). Both-legs 0.66 to 0.70,
and 55 prompts now have an agreed hit against 50. The strict bar (10 points on top 4, or on meaning
plus both-legs) was not met, but the two rows that moved are the paper's contextual-BM25 effect
exactly: the title and description words now match in FTS, while BGE-small's vectors did not change
in any measurable way. Kept because it costs one line and nothing at query time. The entity-prompt
subset is not comparable across the two runs (the sampler's seed count changed between them), so it
is not reported.

### Option 2 (2026-09-13): measured, not kept

BGE-base-en-v1.5 on top of option 1, same 100 prompts. Top 4 0.42 to 0.46 (+4). Position 1 0.55 to
0.59 (+4). Both-legs 0.70 to 0.75 (+5). Meaning-only flat at 0.25. Every delta is inside the 5-point
noise floor. The operational cost is not: the full rebuild took 1 h 54 min and held 13 GB of memory,
paging the machine, against about 15 min for BGE-small; the weekly Sunday self-heal rebuild and the
Windows install both rule that out. Query-side the model is fine once loaded from the local cache
(hook 0.66 s end to end). Kept from this option: the `[index] embedding_model` config key, the numpy
scan in `meaning_leg` (0.30 s to 0.07 s on the small model), `local_files_only` model loading, and
the model name recorded in `meta`. Config returns to BGE-small with the option 3 rebuild.

### Option 3 (2026-09-13): measured, no win

Backfill: 857 files, 8,096 contexts in 62 min at 8 workers, 570 chunks skipped on malformed JSON
replies (they keep the option 1 prefix). Same 100 prompts, BGE-small, contexts replacing the prefix
where present. Against option 1: top 4 0.42 to 0.43, position 1 0.55 to 0.52, keyword-only 0.35 to
0.34, meaning-only 0.26 to 0.21, both-legs 0.70 to 0.74. Every row inside the noise floor, and the
embedding leg moved the wrong way: a sentence that names three people and two projects pulls the
vector toward the names and away from the section's subject. The sentences read well (example on
`pages/doc-extraction.md § Next steps`: "Doc Extraction's remaining work includes ... Phase 2 POC
design and pilot plan ..."), but the title-and-description prefix already carried the part the
retriever needed. Cost of keeping it would be one headless call per changed page per night plus the
one-time hour. Decision pending Michael: disable (remove the `reindex.sh` line, leave `with_context`
inert by dropping the table), or keep running for `/wiki` query mode, which can show the sentence
as a chunk summary even if retrieval does not gain.

## Summary across the four runs

| Run | Top 4 | Pos 1 | Keyword-only | Meaning-only | Both legs | Cost |
|-----|-------|-------|--------------|--------------|-----------|------|
| baseline | 0.38 | 0.45 | 0.26 | 0.27 | 0.66 | |
| 1 title+description prefix | 0.42 | 0.55 | 0.35 | 0.26 | 0.70 | one line, kept |
| 2 BGE-base (on 1) | 0.46 | 0.59 | 0.30 | 0.25 | 0.75 | 1 h 54 min rebuild, 13 GB; not kept |
| 3 Haiku sentence (on 1) | 0.43 | 0.52 | 0.34 | 0.21 | 0.74 | 62 min once + nightly calls; pending |

What moved retrieval was cheap and deterministic. Both model-side options landed inside the judge's
noise. The remaining lever the paper offers is a reranker (option 4), and the both-legs row at 0.70
to 0.75 says the candidates are there; a cross-encoder over the fused top 20 is what would promote them.

## Measurement upgrade (2026-09-13, evening)

Michael's read of the four-run table: the numbers went up every time, so "inside the noise" undersold
three same-direction moves. Fair. The judge is too coarse for 4-point effects, so before deciding
option 3 or starting option 4 the measurement gets both fixes at once: the frozen prompt set grows
from 100 to 300 (the original 100 kept as the first 100), and every configuration is judged twice
with the two label sets averaged (`judge.py --score hits.csv judge_a judge_b`). Three
configurations, each rebuilt with the new `build_index.py --no-prefix / --no-context` knobs:
baseline, option 1, option 3. Option 2 stays out on rebuild cost regardless of its number. Option 3
stays in `reindex.sh` while this runs. Chain and logs: `~/.config/rekall/eval/2026-09-13-n300/`.

### Result at 300 prompts, judged twice (2026-09-14, 01:28)

| Configuration | Top 4 | Pos 1 | Keyword-only | Meaning-only | Both legs |
|---------------|-------|-------|--------------|--------------|-----------|
| baseline | 0.352 | 0.427 | 0.232 | 0.241 | 0.576 |
| option 1 | 0.343 | 0.408 | 0.239 | 0.243 | 0.574 |
| option 3 | 0.345 | 0.395 | 0.243 | 0.230 | 0.561 |

Flat. Every difference is under 2 points on 1,200 judged top-4 rows per configuration with two label
passes averaged. The 100-prompt single-pass runs that read 0.38, 0.42, 0.43 were the judge's own
variance; the "three same-direction moves" were not a trend. Neither the title/description prefix
nor the model-written context sentence changes what the memory leg returns in a way this judge can
see. Caveat on the prompt set: 200 of the 300 prompts come from the last 28 days, which include the
sessions that built this graph, so 84 of the 200 new prompts name rekall, the wiki, the graph, or the eval itself (7 of the
original 100 did). The comparison between configurations is still fair, since all three saw the same
prompts and judge, but the absolute numbers describe a week of building this tool more than normal
use, and the graph slice reads 0.03 here against 0.16 on the earlier 100 for the same reason. Next
prompt set should exclude sessions run inside the rekall repo.

### Decision (Michael, 2026-09-14)

Option 3 out of `reindex.sh`, `contexts` table dropped, `contextualize.py` kept in the repo as a
parked tool with a header saying so. Option 1 stays. Index rebuilt on the prefix alone.
