# Prior art

The working setup Rekall extracts from began as a mix of two designs: Karpathy's LLM Wiki pattern for the wiki layer, and Cerebras' knowledge-base architecture for the ingest side.

## Karpathy's LLM Wiki pattern

<https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>

Describes the pattern Rekall implements: an LLM incrementally maintains a persistent markdown wiki instead of doing RAG over raw documents. Knowledge compounds in the wiki; raw sources stay immutable underneath it.

His architecture maps to Rekall like this:

| Gist | Rekall |
|---|---|
| Raw sources (immutable) | `raw/` in the vault, meeting transcripts |
| The wiki (LLM-maintained markdown) | `wiki/` pages with `index.md` and `log.md` |
| Schema (config guiding the LLM) | vault conventions doc (to be formalized here) |
| Ingest operation | capture pipelines in `scripts/` (Fathom meeting pipeline) |
| Query operation | `graph-memory/` (RAG index + graph recall) and the wiki skill |
| Lint operation | `scripts/wiki-lint.py`, nightly via launchd, notifies on regressions |

All three operations exist. The schema layer is `docs/vault-conventions.md` in this repo, extracted from the working vault's schema file.

Upstream inspiration named in the gist: Vannevar Bush's Memex (1945).

## Cerebras' knowledge base

<https://www.cerebras.ai/blog/how-we-built-our-knowledge-base>

Cerebras built an internal knowledge base answering 15,000+ questions a day. Two pieces of it shaped Rekall's ingest design.

First, one shared store fed by many sources: every source (Slack threads, docs, even hardware netlists) lands in a single Postgres embeddings table with a common schema, and anything in the table is immediately queryable through one interface.

Second, connectors as plugin scripts: a team adds a source by opening a PR with a small Python module that reads its own system and emits rows in the shared schema. The rest of the stack never changes, and nobody is forced to move their data out of the platform where it already lives.

Rekall's translation: the vault is the shared store (markdown pages instead of embedding rows, the page schema instead of the table schema), and capture pipelines in `scripts/` are the plugin connectors. Adding a source means adding one script that emits conforming pages.
