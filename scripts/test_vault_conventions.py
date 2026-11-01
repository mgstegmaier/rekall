"""Docs match the enforced schema: the type list, the CLI doc's vault name and folder layout."""
import importlib.util
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp())
(TMP / "rekall.toml").write_text(f'[user]\nname = "T"\ntimezone = "America/Chicago"\n[vault]\npath = "{TMP}/vault"\n'
                                 f'[data]\npath = "{TMP}/data"\nstate = "{TMP}/state"\n')
os.environ.setdefault("REKALL_CONFIG", str(TMP / "rekall.toml"))


def test_documented_types_equal_page_types():
    spec = importlib.util.spec_from_file_location("wiki_lint", ROOT / "scripts" / "wiki-lint.py")
    wl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wl)
    line = next(l for l in (ROOT / "docs/vault-conventions.md").read_text().splitlines() if l.startswith("type: "))
    documented = set(re.match(r"type:\s*([a-z|]+)", line).group(1).split("|"))
    assert documented == wl.PAGE_TYPES, documented ^ wl.PAGE_TYPES


def test_cli_doc_is_generic_and_uses_type_folders():
    text = (ROOT / "docs/obsidian-vault-cli.md").read_text()
    assert not re.search(r"heck-db|people/|projects/", text)
    assert "pages/<type>/" in text or "pages/{type}/" in text
