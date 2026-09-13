#!/usr/bin/env python3
"""Self-check for build_graph's frontmatter relation reader and edge builder.
Run: python3 graph-memory/test_build_graph.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_graph import page_meta, relation_edges  # noqa: E402

# page_meta: type, an inline list, a block list, and a bare scalar (owner)
fm = [
    "type: project",
    "owner: alice",
    "people: [alice, bob]",
    "depends_on:",
    "- widget-service",
    "- other-thing",
]
kind, relations = page_meta(fm)
assert kind == "project", kind
assert relations["owner"] == ["alice"], relations["owner"]
assert relations["people"] == ["alice", "bob"], relations["people"]
assert relations["depends_on"] == ["widget-service", "other-thing"], relations["depends_on"]

# relation_edges: owner/people/depends_on resolve through by_slug (same lookup
# as a wikilink target); an unresolved target is skipped, not an error.
by_slug = {
    "alice": "id-alice",
    "bob": "id-bob",
    "widget-service": "id-widget",
    "widget-project": "id-page",
}
ident_by_rel = {"pages/widget-project.md": "id-page"}
rows = [
    (
        "pages/widget-project.md",
        "widget-project",
        "project",
        {},
        "",
        {"owner": ["alice"], "people": ["alice", "bob"], "maintainers": ["bob"], "depends_on": ["widget-service", "ghost"]},
    )
]
by_name = {}
aliases = {}
edges = relation_edges(rows, by_slug, by_name, aliases, ident_by_rel)
assert edges == {
    ("id-alice", "id-page", "owns", "pages/widget-project.md"),
    ("id-alice", "id-page", "member_of", "pages/widget-project.md"),
    ("id-bob", "id-page", "member_of", "pages/widget-project.md"),
    ("id-bob", "id-page", "maintains", "pages/widget-project.md"),
    ("id-page", "id-widget", "depends_on", "pages/widget-project.md"),
}, edges  # "ghost" is unresolved and skipped, no edge for it

# attendees only apply to meeting pages
meeting_rows = [
    (
        "meetings/2026-09-01.md",
        "2026-09-01",
        "meeting",
        {},
        "",
        {"attendees": ["alice", "ghost"]},
    )
]
ident_by_rel["meetings/2026-09-01.md"] = "id-meeting"
by_slug["2026-09-01"] = "id-meeting"
edges = relation_edges(meeting_rows, by_slug, by_name, aliases, ident_by_rel)
assert edges == {("id-alice", "id-meeting", "attended", "meetings/2026-09-01.md")}, edges

# an attendee given as a display name (not a slug) resolves through the name
# column (frontmatter title) or the aliases table, case-insensitively
by_name_named = {"alice cooper": "id-alice"}
aliases_named = {"al cooper": "id-alice"}
name_rows = [
    (
        "meetings/2026-09-02.md",
        "2026-09-02",
        "meeting",
        {},
        "",
        {"attendees": ["Alice Cooper", "Al Cooper"]},
    )
]
ident_by_rel["meetings/2026-09-02.md"] = "id-meeting-2"
edges = relation_edges(name_rows, by_slug, by_name_named, aliases_named, ident_by_rel)
assert edges == {("id-alice", "id-meeting-2", "attended", "meetings/2026-09-02.md")}, edges

print("ok")
