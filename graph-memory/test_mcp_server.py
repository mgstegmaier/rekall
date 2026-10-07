#!/usr/bin/env python3
"""Self-check for mcp_server: search_wiki returns text for a real term,
read_page returns a guide page and a vault-root file, rejects path tricks, and reports a missing page.
Runs against the live index. Run: python3 graph-memory/test_mcp_server.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_server import read_page, search_wiki  # noqa: E402

# the tools are plain functions underneath the decorator
out = search_wiki("Doc Extraction")
assert out.strip() and out != "No matches." and not out.startswith("Search failed"), out[:200]

assert "Doc Extraction" in read_page("doc-extraction-guide")

for bad in ("../etc/passwd", "a/b", "a\\b", ".."):
    assert read_page(bad).startswith("Rejected"), bad

assert "not found" in read_page("no-such-page-xyz").lower()
assert "not found" in read_page("*").lower()  # glob characters are not patterns

# vault-root files are readable too (today.md is written daily by /today)
assert not read_page("today").startswith(("Page not found", "Rejected"))

print("ok")
