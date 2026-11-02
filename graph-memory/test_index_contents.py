"""What the index holds: no transcripts (R-docs-4), no doubled session rows (R-recall-12).
Every test builds a temp corpus and a temp rag.db; the live index is never opened."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_index  # noqa: E402
import search  # noqa: E402

QUOTE = "the quarterly budget was cut in half"


def _run(monkeypatch, tmp, *extra):
    """One build_index.main() over tmp/wiki into tmp/rag.db, keyword-only (no model load)."""
    def no_model():
        raise ImportError
    monkeypatch.setattr(search, "embedding_model", no_model)
    monkeypatch.setattr(build_index, "DB", tmp / "rag.db")
    monkeypatch.setattr(build_index, "DISTILLED_DIR", tmp / "distilled")
    argv = ["build_index.py", "--corpus", str(tmp / "wiki")]
    for e in extra:
        argv += ["--extra", str(e)]
    monkeypatch.setattr(sys, "argv", argv)
    build_index.main()


def _rows(tmp):
    with sqlite3.connect(tmp / "rag.db") as db:
        return sorted(db.execute("SELECT file, section, start_line, end_line, text, kind FROM chunks"))


def _corpus(tmp):
    wiki = tmp / "wiki"
    (wiki / "pages").mkdir(parents=True)
    (wiki / "sessions").mkdir()
    (wiki / "meetings" / "transcripts").mkdir(parents=True)
    (wiki / "pages" / "a.md").write_text("# A\n\nbody of a\n")
    (wiki / "sessions" / "s1.md").write_text("# S1\n\nsession one\n\n## More\n\nmore of one\n")
    (wiki / "meetings" / "m.md").write_text("# M\n\nmeeting note\n")
    (wiki / "meetings" / "transcripts" / "t.md").write_text(f"# T\n\n{QUOTE}\n")
    return wiki


def _distillate(tmp, source):
    d = tmp / "distilled"
    d.mkdir(exist_ok=True)
    (d / "x.md").write_text(
        f"---\nsource: {source}\nquote: \"{QUOTE}\"\n---\n\n- What happened to the budget?\n")
    return d


def test_transcripts_and_their_distillates_are_not_indexed(tmp_path, monkeypatch):
    _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    with sqlite3.connect(tmp_path / "rag.db") as db:
        # seed what an older index held: a transcript file, its chunk, and a distillate of it
        for key, src, file in (("meetings/transcripts/t.md", None, "meetings/transcripts/t.md"),
                               ("distilled/x.md", "meetings/transcripts/t.md", "meetings/transcripts/t.md")):
            kind = "distilled" if src else "chunk"
            cur = db.execute("INSERT INTO chunks (file, section, start_line, end_line, text, kind) VALUES (?,?,?,?,?,?)",
                             (file, "T", 0, 1, QUOTE, kind))
            db.execute("INSERT INTO chunks_fts (rowid, text, file, section) VALUES (?,?,?,?)", (cur.lastrowid, QUOTE, file, "T"))
            db.execute("INSERT INTO files VALUES (?,?,?)", (key, "oldhash" if src else "oldhash2", src))
        db.commit()
    _distillate(tmp_path, "meetings/transcripts/t.md")
    _run(monkeypatch, tmp_path)
    with sqlite3.connect(tmp_path / "rag.db") as db:
        assert db.execute("SELECT count(*) FROM chunks WHERE file LIKE 'meetings/transcripts/%'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM files WHERE path LIKE 'meetings/transcripts/%'").fetchone()[0] == 0
    _run(monkeypatch, tmp_path)  # a second run stays clean
    assert not [r for r in _rows(tmp_path) if r[0].startswith("meetings/transcripts/")]
    assert any(r[0] == "meetings/m.md" for r in _rows(tmp_path))  # other meetings still indexed


def test_extra_inside_corpus_adds_nothing(tmp_path, monkeypatch):
    wiki = _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    want = _rows(tmp_path)
    (tmp_path / "rag.db").unlink()
    _run(monkeypatch, tmp_path, wiki / "sessions")
    assert _rows(tmp_path) == want
    assert sum(r[0] == "sessions/s1.md" for r in want) == 2


def test_incremental_run_repairs_duplicated_rows(tmp_path, monkeypatch):
    _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    want = _rows(tmp_path)
    with sqlite3.connect(tmp_path / "rag.db") as db:  # double one file's rows, as the old --extra did
        for r in db.execute("SELECT file, section, start_line, end_line, text, kind FROM chunks WHERE file='sessions/s1.md'").fetchall():
            cur = db.execute("INSERT INTO chunks (file, section, start_line, end_line, text, kind) VALUES (?,?,?,?,?,?)", r)
            db.execute("INSERT INTO chunks_fts (rowid, text, file, section) VALUES (?,?,?,?)", (cur.lastrowid, r[4], r[0], r[1]))
        db.commit()
    assert len(_rows(tmp_path)) == len(want) + 2
    _run(monkeypatch, tmp_path)
    assert _rows(tmp_path) == want
    _run(monkeypatch, tmp_path)  # idempotent
    assert _rows(tmp_path) == want


def test_two_distillates_of_one_source_are_stable_but_doubled_row_is_repaired(tmp_path, monkeypatch):
    _corpus(tmp_path)
    d = _distillate(tmp_path, "meetings/m.md")
    (tmp_path / "wiki" / "meetings" / "m.md").write_text(f"# M\n\n{QUOTE}\n")
    (d / "y.md").write_text((d / "x.md").read_text())  # same source, identical text
    _run(monkeypatch, tmp_path)
    want = _rows(tmp_path)
    assert sum(r[5] == "distilled" for r in want) == 2

    changed = []
    real = build_index.file_docs
    monkeypatch.setattr(build_index, "file_docs", lambda *a: changed.append(a[0]) or real(*a))
    orig = build_index.distilled_doc
    monkeypatch.setattr(build_index, "distilled_doc", lambda *a: changed.append(a[0]) or orig(*a))
    _run(monkeypatch, tmp_path)
    assert changed == [] and _rows(tmp_path) == want  # nothing forced

    with sqlite3.connect(tmp_path / "rag.db") as db:  # a genuinely doubled distilled row
        r = db.execute("SELECT file, section, start_line, end_line, text, kind FROM chunks WHERE kind='distilled'").fetchone()
        cur = db.execute("INSERT INTO chunks (file, section, start_line, end_line, text, kind) VALUES (?,?,?,?,?,?)", r)
        db.execute("INSERT INTO chunks_fts (rowid, text, file, section) VALUES (?,?,?,?)", (cur.lastrowid, r[4], r[0], r[1]))
        db.commit()
    _run(monkeypatch, tmp_path)
    assert _rows(tmp_path) == want
