"""build_index.file_docs: every chunk's embed text carries the page title and
description in front of the body (contextual retrieval, deterministic form), and
the stored row text does not."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_index import file_docs  # noqa: E402

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

print("ok")
