#!/usr/bin/env python3
"""Self-check for mcp_server: search_wiki finds the wiki log, read_page returns
the wiki index, rejects path tricks, and reports a missing page. Both notes come
from vault-template/, so this passes on any installed vault. Runs against the
live index. Run: python3 graph-memory/test_mcp_server.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_server import read_page, search_wiki  # noqa: E402

# the tools are plain functions underneath the decorator
out = search_wiki("Wiki Log")
assert "log.md" in out and not out.startswith("Search failed"), out[:200]

assert "# Wiki Index" in read_page("index")

for bad in ("../etc/passwd", "a/b", "a\\b", ".."):
    assert read_page(bad).startswith("Rejected"), bad

assert "not found" in read_page("no-such-page-xyz").lower()
assert "not found" in read_page("*").lower()  # glob characters are not patterns

print("ok")
