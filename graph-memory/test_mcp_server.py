#!/usr/bin/env python3
"""Self-check for mcp_server: search_wiki finds the wiki log, read_page returns
the wiki index, rejects path tricks, and reports a missing page. Both notes come
from vault-template/, copied to a temp vault and indexed (keyword leg only, no
model) into a temp rag.db, so it needs no install, no live index and no
particular vault. Run: python3 graph-memory/test_mcp_server.py"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_index  # noqa: E402
import mcp_server  # noqa: E402
import recall_hook  # noqa: E402
from test_ranking import make_db  # noqa: E402


def fixture(tmp):
    """Temp vault from vault-template/ and a keyword-only index over its wiki/ folder."""
    vault = tmp / "vault"
    shutil.copytree(HERE.parent / "vault-template", vault)
    wiki = vault / "wiki"
    rows = []
    for path in build_index.note_files(wiki):
        for _, row in build_index.file_docs(path.relative_to(wiki).as_posix(), path):
            rows.append((len(rows) + 1, row[0], row[1], row[4], row[4]))
    make_db(tmp / "rag.db", rows).close()
    return vault, tmp / "rag.db"


def test_tools():
    tmp = Path(tempfile.mkdtemp()).resolve()
    saved = mcp_server.VAULT, mcp_server.DB, recall_hook.DB
    try:
        vault, db = fixture(tmp)
        mcp_server.VAULT, mcp_server.DB, recall_hook.DB = vault, db, db

        # the tools are plain functions underneath the decorator
        out = mcp_server.search_wiki("Wiki Log")
        assert "log.md" in out and not out.startswith("Search failed"), out[:200]

        assert "# Wiki Index" in mcp_server.read_page("index")

        for bad in ("../etc/passwd", "a/b", "a\\b", ".."):
            assert mcp_server.read_page(bad).startswith("Rejected"), bad

        assert "not found" in mcp_server.read_page("no-such-page-xyz").lower()
        assert "not found" in mcp_server.read_page("*").lower()  # glob characters are not patterns
    finally:
        mcp_server.VAULT, mcp_server.DB, recall_hook.DB = saved
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_tools()
    print("ok")
