"""build_index.file_docs: every chunk's embed text carries the page title and
description in front of the body (contextual retrieval, deterministic form), and
the stored row text does not."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sqlite3

from build_index import SCHEMA, file_docs, note_files, old_vectors, purge  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "widget-project.md"
    p.write_text(
        "---\ntitle: Widget Project\ndescription: Builds widgets for the shop floor.\n---\n"
        "# Widget Project\n\nIntro line.\n\n## Next steps\n\n- ship the thing\n"
    )
    docs = file_docs("pages/widget-project.md", p)
    by_section = {row[1]: (embed, row) for embed, row in docs}
    embed, row = by_section["Next steps"]
    assert embed.startswith("[pages/widget-project.md § Next steps]\nWidget Project: Builds widgets for the shop floor.\n"), embed
    assert row[4].startswith("## Next steps"), row[4]  # stored text is the body only
    assert "Builds widgets" not in row[4]
    assert by_section["description"][1][5] == "description"

    q = Path(tmp) / "bare.md"
    q.write_text("# Bare\n\nno frontmatter here\n")
    (embed, row), = file_docs("pages/bare.md", q)
    assert embed == "[pages/bare.md § Bare]\n# Bare\n\nno frontmatter here", embed

# note_files: a root-level index.md (wiki-index.py's generated page listing) is
# excluded -- it just duplicates every page's own description row -- but a
# nested index.md (a page that happens to be named that) is indexed normally.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp).resolve()  # note_files resolves its root; macOS /var is a symlink to /private/var
    (root / "index.md").write_text("# Index\n\n- [[a]]\n")
    (root / "pages").mkdir()
    (root / "pages" / "a.md").write_text("# A\n\nbody\n")
    (root / "pages" / "index.md").write_text("# Not the root index\n\nbody\n")
    got = {p.relative_to(root).as_posix() for p in note_files(root)}
    assert got == {"pages/a.md", "pages/index.md"}, got

# old_vectors: recovers a key's (embed-text hash -> vector blob) before purge()
# deletes it, so an unchanged chunk skips re-embedding on the next build. A
# non-distilled key sees only its own chunk rows, a distilled/ key only the
# matching source's distilled row.
with sqlite3.connect(":memory:") as db:
    db.executescript(SCHEMA)
    db.execute("INSERT INTO chunks (id, file, section, start_line, end_line, text, kind) "
               "VALUES (1, 'a.md', 'Intro', 1, 2, 'body one', 'chunk')")
    db.execute("INSERT INTO chunks_fts (rowid, text, file, section) VALUES (1, 'EMBED ONE', 'a.md', 'Intro')")
    db.execute("INSERT INTO vectors (id, vec) VALUES (1, ?)", (b"\x01\x02\x03\x04",))
    db.execute("INSERT INTO chunks (id, file, section, start_line, end_line, text, kind) "
               "VALUES (2, 'a.md', 'distilled', 0, 0, 'quote body', 'distilled')")
    db.execute("INSERT INTO chunks_fts (rowid, text, file, section) VALUES (2, 'EMBED TWO', 'a.md', 'distilled')")
    db.execute("INSERT INTO vectors (id, vec) VALUES (2, ?)", (b"\x05\x06\x07\x08",))

    assert list(old_vectors(db, "a.md", None).values()) == [b"\x01\x02\x03\x04"]
    assert list(old_vectors(db, "distilled/a.md", "a.md").values()) == [b"\x05\x06\x07\x08"]

    purge(db, "a.md", None)
    assert db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1  # the distilled row survives
    assert old_vectors(db, "a.md", None) == {}  # gone with the purged row

print("ok")
