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


# --- full-or-incremental decision, bad bytes, weekly overdue (rekall-rebuild-safety design) ---
from datetime import date  # noqa: E402

import pytest  # noqa: E402


class FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 28)  # a Wednesday: no Sunday full


@pytest.fixture(autouse=True)
def _pin_date(monkeypatch):
    """Every run in this module, _run included, sees the same Wednesday."""
    monkeypatch.setattr(build_index, "date", FixedDate)


class CountingModel:
    def __init__(self, name):
        self.model_name, self.embedded = name, 0

    def embed(self, texts):
        texts = list(texts)
        self.embedded += len(texts)
        return [[1.0, 0.5, 0.25, 0.125] for _ in texts]


def _run_model(monkeypatch, tmp, name, *flags):
    """One build_index.main() with a fake embedding model configured as `name`. Returns the fake."""
    model = CountingModel(name)
    monkeypatch.setattr(search, "embedding_model", lambda: model)
    monkeypatch.setattr(build_index, "EMBEDDING_MODEL", name)
    monkeypatch.setattr(build_index, "DB", tmp / "rag.db")
    monkeypatch.setattr(build_index, "DISTILLED_DIR", tmp / "distilled")
    monkeypatch.setattr(sys, "argv", ["build_index.py", "--corpus", str(tmp / "wiki"), *flags])
    build_index.main()
    return model


def _count(tmp, table):
    with sqlite3.connect(tmp / "rag.db") as db:
        return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _meta(tmp, key):
    with sqlite3.connect(tmp / "rag.db") as db:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row and row[0]


def test_model_change_reembeds_every_row(tmp_path, monkeypatch, capsys):
    _corpus(tmp_path)
    _run_model(monkeypatch, tmp_path, "A")
    capsys.readouterr()
    model = _run_model(monkeypatch, tmp_path, "B")
    out = capsys.readouterr().out
    assert "full (model changed: A -> B)" in out, out
    assert model.embedded == _count(tmp_path, "chunks") > 0
    assert _meta(tmp_path, "model") == "B"


def test_keyword_only_stays_incremental(tmp_path, monkeypatch, capsys):
    _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    capsys.readouterr()
    _run(monkeypatch, tmp_path)
    assert any(l.startswith("incremental") for l in capsys.readouterr().out.splitlines())


def test_model_added_to_keyword_only_index_embeds_everything(tmp_path, monkeypatch, capsys):
    _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    assert _count(tmp_path, "vectors") == 0
    capsys.readouterr()
    _run_model(monkeypatch, tmp_path, "M")
    assert "full (model added)" in capsys.readouterr().out
    assert _count(tmp_path, "vectors") == _count(tmp_path, "chunks") > 0
    assert _meta(tmp_path, "model") == "M"


def test_model_unavailable_keeps_keyword_only(tmp_path, monkeypatch, capsys):
    wiki = _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    (wiki / "pages" / "new.md").write_text("# New\n\nfresh page\n")

    def offline():
        raise RuntimeError("offline")

    monkeypatch.setattr(search, "embedding_model", offline)
    capsys.readouterr()
    build_index.main()  # argv and DB still set by _run
    out = capsys.readouterr().out
    assert "model unavailable: offline" in out, out
    assert any(l.startswith("incremental") for l in out.splitlines()), out
    assert any(r[0] == "pages/new.md" for r in _rows(tmp_path))  # committed
    assert _count(tmp_path, "vectors") == 0 and _meta(tmp_path, "model") is None


def test_model_load_failure_on_vector_index_fails_the_run(tmp_path, monkeypatch):
    wiki = _corpus(tmp_path)
    _run_model(monkeypatch, tmp_path, "A")
    with sqlite3.connect(tmp_path / "rag.db") as db:
        vecs = sorted(db.execute("SELECT id, vec FROM vectors"))
    (wiki / "pages" / "a.md").write_text("# A\n\nbody of a, edited\n")

    def no_fastembed():
        raise ImportError("no fastembed")

    monkeypatch.setattr(search, "embedding_model", no_fastembed)
    with pytest.raises(ImportError):
        build_index.main()
    with sqlite3.connect(tmp_path / "rag.db") as db:
        assert sorted(db.execute("SELECT id, vec FROM vectors")) == vecs
    assert _meta(tmp_path, "model") == "A"


def test_bad_utf8_page_is_indexed(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    (wiki / "pages" / "a.md").write_text("# A\n\nbody of a\n")
    (wiki / "pages" / "b.md").write_text("# B\n\nbody of b\n")
    (wiki / "pages" / "bad.md").write_bytes(b"# Bad\n\nok \xff text\n")
    _run_model(monkeypatch, tmp_path, "M", "--full")
    with sqlite3.connect(tmp_path / "rag.db") as db:
        assert db.execute("SELECT count(*) FROM files WHERE path='pages/bad.md'").fetchone()[0] == 1
        texts = [t for (t,) in db.execute("SELECT text FROM chunks WHERE file='pages/bad.md'")]
    assert any("�" in t for t in texts), texts


def test_weekly_full_retries_when_overdue(tmp_path, monkeypatch, capsys):
    _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    with sqlite3.connect(tmp_path / "rag.db") as db:
        db.execute("UPDATE meta SET value='2026-10-20' WHERE key='last_full'")  # 8 days before the pin
    capsys.readouterr()
    _run(monkeypatch, tmp_path)
    assert "full (weekly overdue)" in capsys.readouterr().out


def test_missing_meta_table_rebuilds_full(tmp_path, monkeypatch, capsys):
    _corpus(tmp_path)
    _run(monkeypatch, tmp_path)
    with sqlite3.connect(tmp_path / "rag.db") as db:
        db.execute("DROP TABLE meta")
    capsys.readouterr()
    _run(monkeypatch, tmp_path)
    assert "full (corpus)" in capsys.readouterr().out
    assert _meta(tmp_path, "corpus")


def test_meta_model_is_the_configured_name(tmp_path, monkeypatch):
    """fastembed reports its own name for a pinned local model folder; meta.model must hold the
    configured name, or the next run would see a model change and re-embed everything."""
    _corpus(tmp_path)
    model = CountingModel("fastembed/own-name")
    monkeypatch.setattr(search, "embedding_model", lambda: model)
    monkeypatch.setattr(build_index, "EMBEDDING_MODEL", "configured/name")
    monkeypatch.setattr(build_index, "DB", tmp_path / "rag.db")
    monkeypatch.setattr(build_index, "DISTILLED_DIR", tmp_path / "distilled")
    monkeypatch.setattr(sys, "argv", ["build_index.py", "--corpus", str(tmp_path / "wiki")])
    build_index.main()
    assert _meta(tmp_path, "model") == "configured/name"
