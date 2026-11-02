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

from paths import ARCHIVE, DB, WIKI  # noqa: E402
from recall_hook import graph_facts, hits  # noqa: E402

VAULT = WIKI.parent  # read_page covers the whole vault: wiki/, guide/, today.md, ...

READ_CAP = 20_000  # characters per read_page reply
SEARCH_CAP = 10_000  # characters per search_wiki reply, about 2,500 tokens

mcp = FastMCP("rekall")


@mcp.tool()
def search_wiki(query: str, section: str = "") -> str:
    """Search the user's wiki (projects, people, systems, meetings, past sessions).

    Call this BEFORE answering any question about a named project, person,
    system, tool, or past decision. Returns up to 5 matching chunks labeled
    [file § section] with their full text, then graph facts as
    "subject -[predicate]-> object (doc)" lines. Use read_page to open a whole
    page named in a label.

    section (optional) keeps only chunks under that heading, matched exactly,
    ignoring case: "Decisions" or "Open loops" for past sessions' decisions
    and open loops, or any page heading such as "Next steps". Graph facts
    are left out when it's set.
    """
    section = section.strip()  # headings are stored stripped
    try:
        found = hits(query, section or None)
    except Exception as e:
        if not DB.is_file():
            return "No index yet: run graph-memory/reindex.sh."
        return f"Search failed: {e}"
    parts = [f"{label}\n{text}" for label, text in found]
    facts = [] if section else [f"{s} -[{p}]-> {t} ({doc})" for s, p, t, doc in graph_facts(query)]
    if facts:
        parts.append("Wiki graph:\n" + "\n".join(facts))
    out = "\n\n".join(parts) or "No matches."
    if len(out) > SEARCH_CAP:
        out = out[:SEARCH_CAP - 40] + "\n[trimmed to fit the reply cap]"
    return out


@mcp.tool()
def read_page(name: str, offset: int = 0) -> str:
    """Read one note from the user's vault, by file name without .md or by vault-relative path.

    Covers every note in the vault, wiki pages and files outside wiki/ alike.
    Call this after search_wiki when a hit's label names a page you need. If a
    bare name is ambiguous, returns the candidate paths; call again with one
    of them (e.g. "wiki/pages/project/x.md"). The reply starts with the path
    read and is capped at READ_CAP characters; when the page is longer, the
    last line says where to resume: call again with that offset.
    """
    if not name or "\\" in name or ".." in name:
        return "Rejected: give a page name or a vault-relative .md path, no backslashes or '..'."
    root = VAULT.resolve()
    if "/" in name or name.endswith(".md"):
        if not name.endswith(".md") or name.startswith("/") or any(part.startswith(".") for part in name.split("/")):
            return "Rejected: a path must be vault-relative, end in .md, and have no hidden parts."
        found = [VAULT / name] if (VAULT / name).is_file() else []
    else:
        # ponytail: full vault walk per call (a few thousand files); cache stems if it gets slow
        found = [p for p in VAULT.rglob("*.md")  # compare stems, so glob characters in name match nothing
                 if p.stem == name and not any(part.startswith(".") for part in p.relative_to(VAULT).parts)]
        live = [p for p in found if ARCHIVE not in p.parents]
        found = live or found  # prefer non-archive; fall back to archive
    found = [p for p in found if p.resolve().is_relative_to(root)]  # a symlink may not leave the vault
    if not found:
        return f"Page not found: {name}"
    if len(found) > 1:
        return "Multiple pages match:\n" + "\n".join(str(p.relative_to(VAULT)) for p in sorted(found))
    text = found[0].read_text(encoding="utf-8")
    offset = max(offset, 0)
    head = f"[{found[0].relative_to(VAULT)}]\n"
    room = max(READ_CAP - len(head) - 120, 0)  # 120 leaves space for the trailer
    body = text[offset:offset + room]
    end = offset + len(body)
    trailer = f"\n[more: {len(text) - end} of {len(text)} characters left; call again with offset={end}]" if end < len(text) else ""
    return head + body + trailer


if __name__ == "__main__":
    mcp.run()
