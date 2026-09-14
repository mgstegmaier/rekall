"""contextualize.run: one context row per chunk, keyed by the chunk's hash, so a
second run calls nothing, an edited section costs exactly one call, and a reply
that is not JSON drops that page instead of raising."""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contextualize  # noqa: E402
from contextualize import text_hash  # noqa: E402

ALPHA = (
    "---\ntitle: Alpha Page\ntype: project\ndescription: Keeps the alphas.\nowner: the desk\n---\n"
    "# Overview\n\nAlpha is a thing, linked to [[Beta Page]].\n\n"
    "## Next steps\n\n- ship the thing\n"
)
BETA = "---\ntitle: Beta Page\ntype: system\ndescription: Runs the betas.\n---\n# Status\n\nGreen.\n"
REPLY = ('{"Overview": "Alpha Page is a project page. Its overview says what Alpha is and links Beta Page.",'
         ' "Next steps": "Alpha Page is a project page. Its next steps list the shipping work.",'
         ' "Status": "Beta Page is a system page. Its status section reports the system as green."}')


def rows(db_path):
    with sqlite3.connect(db_path) as db:
        return db.execute("SELECT file, section, text_hash, context, model FROM contexts").fetchall()


with tempfile.TemporaryDirectory() as tmp:
    corpus = Path(tmp) / "wiki"
    corpus.mkdir()
    alpha, beta = corpus / "alpha.md", corpus / "beta.md"
    alpha.write_text(ALPHA)
    beta.write_text(BETA)
    contextualize.DB = str(Path(tmp) / "rag.db")

    calls = []

    def fake_ask(model, prompt_text, payload):
        calls.append(payload)
        return "```json\n" + REPLY + "\n```"

    contextualize.ask = fake_ask

    counts = contextualize.run(corpus, dry_run=True)
    assert counts == {"files": 2, "chunks": 3, "skipped": 0}, counts
    assert calls == []

    counts = contextualize.run(corpus)
    assert counts["chunks"] == 3 and counts["skipped"] == 0, counts
    assert len(calls) == 2, calls  # one call per file, not per chunk
    assert "Alpha Page" in calls[0] and "Keeps the alphas." in calls[0] and "the desk" in calls[0]
    assert "Beta Page" in calls[0]  # the wikilink target is named beside its section

    got = rows(contextualize.DB)
    assert len(got) == 3, got
    by_section = {(r[0], r[1]): r for r in got}
    assert by_section[("alpha.md", "Next steps")][2] == text_hash("## Next steps\n\n- ship the thing")
    assert by_section[("beta.md", "Status")][3].startswith("Beta Page is a system page")
    assert all(r[4] == contextualize.model_name() for r in got)

    calls.clear()
    assert contextualize.run(corpus)["chunks"] == 0  # every hash is known
    assert calls == []
    assert len(rows(contextualize.DB)) == 3

    alpha.write_text(ALPHA.replace("- ship the thing", "- ship the other thing"))
    counts = contextualize.run(corpus)
    assert len(calls) == 1 and "alpha.md" in calls[0], calls
    assert counts == {"files": 1, "chunks": 1, "skipped": 0}, counts
    assert len(rows(contextualize.DB)) == 4  # the old hash keeps its row

    calls.clear()
    contextualize.ask = lambda *_a: "sorry, I cannot do that"
    beta.write_text(BETA.replace("Green.", "Amber."))
    counts = contextualize.run(corpus)
    assert counts == {"files": 1, "chunks": 0, "skipped": 1}, counts  # dropped, not raised
    assert len(rows(contextualize.DB)) == 4

with tempfile.TemporaryDirectory() as tmp:
    # six pages, one worker then three: same table either way
    corpus = Path(tmp) / "wiki"
    corpus.mkdir()
    for i in range(6):
        (corpus / f"page{i}.md").write_text(
            f"---\ntitle: Page {i}\ntype: project\ndescription: Page number {i}.\n---\n"
            f"# Overview\n\nPage {i} exists.\n\n## Status\n\nGreen.\n")
    reply = '{"Overview": "an overview context", "Status": "a status context"}'
    contextualize.ask = lambda *_a: reply

    def table(workers):
        contextualize.DB = str(Path(tmp) / f"w{workers}.db")
        counts = contextualize.run(corpus, workers=workers)
        assert counts == {"files": 6, "chunks": 12, "skipped": 0}, counts
        return sorted(rows(contextualize.DB))

    assert table(3) == table(1)

print("ok")
