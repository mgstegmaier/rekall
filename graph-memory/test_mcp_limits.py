"""MCP tool caps (R-cost-3), vault-relative read_page (R-recall-9), and the chunker's
line bound. Temp vault only; hits and graph_facts are stubbed, so no index is needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_index  # noqa: E402
import mcp_server  # noqa: E402


def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    for rel in ("wiki/pages/a/x.md", "wiki/pages/b/x.md", "guide/only.md", "today.md"):
        (v / rel).parent.mkdir(parents=True, exist_ok=True)
        (v / rel).write_text(f"body of {rel}", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "VAULT", v)
    return v


def test_read_page_cap_and_offset(tmp_path, monkeypatch):
    v = vault(tmp_path, monkeypatch)
    text = "".join(f"line {i:06d}\n" for i in range(50_000))  # about 600 KB
    (v / "big.md").write_text(text, encoding="utf-8")
    got, offset = "", 0
    first = mcp_server.read_page("big")
    assert len(first) <= mcp_server.READ_CAP and "offset=" in first
    while True:
        out = mcp_server.read_page("big", offset)
        assert len(out) <= mcp_server.READ_CAP
        body = out.split("\n", 1)[1]
        if "\n[more:" not in body:
            got += body
            break
        body, trailer = body.rsplit("\n[more:", 1)
        got += body
        offset += len(body)
        assert f"offset={offset}" in trailer
    assert got == text


def test_search_wiki_cap(monkeypatch):
    found = [(f"[f{i}.md § s]", "x" * 1600) for i in range(5)]
    monkeypatch.setattr(mcp_server, "hits", lambda q, s=None: found)
    monkeypatch.setattr(mcp_server, "graph_facts", lambda q: [("a", "p", "b" * 300, "d")] * 20)
    assert len(mcp_server.search_wiki("q")) <= mcp_server.SEARCH_CAP


def test_read_page_relative_path(tmp_path, monkeypatch):
    vault(tmp_path, monkeypatch)
    amb = mcp_server.read_page("x")
    assert amb.startswith("Multiple")
    paths = amb.splitlines()[1:]
    assert paths == ["wiki/pages/a/x.md", "wiki/pages/b/x.md"]
    for p in paths:
        out = mcp_server.read_page(p)
        assert out.startswith(f"[{p}]") and f"body of {p}" in out
    assert mcp_server.read_page("only").startswith("[guide/only.md]")
    assert "body of today.md" in mcp_server.read_page("today")
    assert "body of today.md" in mcp_server.read_page("today.md")


def test_read_page_stays_in_vault(tmp_path, monkeypatch):
    v = vault(tmp_path, monkeypatch)
    (v / "wiki/.hidden").mkdir()
    (v / "wiki/.hidden/x.md").write_text("secret", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (v / "link.md").symlink_to(outside)
    (v / "dirlink").symlink_to(tmp_path)
    for bad in ("../outside.md", "wiki/.hidden/x.md", "/etc/passwd.md", str(outside), "dirlink/outside.md", "wiki/pages/a/x.txt"):
        assert mcp_server.read_page(bad).startswith(("Rejected", "Page not found")), bad
    assert "outside" not in mcp_server.read_page("link")
    assert "outside" not in mcp_server.read_page("link.md")


def test_chunks_never_exceed_budget(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("# H\n" + "a" * 1000 + "\n" + "b" * 1000 + "\n" + "c" * 5000 + "\n", encoding="utf-8")
    _, chunks = build_index.chunk_file(f)
    assert chunks and all(len(c[3]) <= build_index.CHUNK_BUDGET for c in chunks)
    joined = "".join(c[3] for c in chunks)
    assert joined.count("a") == 1000 and joined.count("b") == 1000 and joined.count("c") == 5000
