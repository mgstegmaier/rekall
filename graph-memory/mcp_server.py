"""MCP server (stdio): the recall hook's search and the wiki's pages, as tools.

Claude Desktop chat has no UserPromptSubmit hook, so the model calls these
itself. Read-only. All search logic lives in recall_hook.py; this file only
formats it and looks pages up by name.

Run: python mcp_server.py (a client launches it; see README "MCP server").
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from paths import ARCHIVE, WIKI  # noqa: E402
from recall_hook import graph_facts, hits  # noqa: E402

VAULT = WIKI.parent  # read_page covers the whole vault: wiki/, guide/, today.md, ...

mcp = FastMCP("rekall")


@mcp.tool()
def search_wiki(query: str) -> str:
    """Search the user's wiki (projects, people, systems, meetings, past sessions).

    Call this BEFORE answering any question about a named project, person,
    system, tool, or past decision. Returns up to 5 matching chunks labeled
    [file § section] with their full text, then graph facts as
    "subject -[predicate]-> object (doc)" lines. Use read_page to open a whole
    page named in a label.
    """
    try:
        found = hits(query)
    except Exception as e:  # no index yet, or a locked one
        return f"Search failed: {e}"
    parts = [f"{label}\n{text}" for label, text in found]
    facts = [f"{s} -[{p}]-> {t} ({doc})" for s, p, t, doc in graph_facts(query)]
    if facts:
        parts.append("Wiki graph:\n" + "\n".join(facts))
    return "\n\n".join(parts) or "No matches."


@mcp.tool()
def read_page(name: str) -> str:
    """Read one full note from the user's vault by its file name, without .md.

    Covers every note in the vault, wiki pages and files outside wiki/ alike
    (e.g. "index", "log"). Call this after
    search_wiki when a hit's label names a page you need in full. If the name
    is ambiguous, returns the candidate paths; call again with the exact name.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        return "Rejected: give a bare page name, no path separators or '..'."
    # ponytail: full vault walk per call (a few thousand files); cache stems if it gets slow
    found = [p for p in VAULT.rglob("*.md")  # compare stems, so glob characters in name match nothing
             if p.stem == name and not any(part.startswith(".") for part in p.relative_to(VAULT).parts)]
    live = [p for p in found if ARCHIVE not in p.parents]
    found = live or found  # prefer non-archive; fall back to archive
    if not found:
        return f"Page not found: {name}"
    if len(found) > 1:
        return "Multiple pages match:\n" + "\n".join(str(p.relative_to(VAULT)) for p in sorted(found))
    return found[0].read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()
