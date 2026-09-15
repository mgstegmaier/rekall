#!/usr/bin/env python3
"""Match and append-once checks for granola-sweep.py. Run directly: python3 scripts/test_granola_match.py"""
import importlib.util
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location("granola_sweep", Path(__file__).parent / "granola-sweep.py")
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)
CT = gs.fp.CT


def fathom_note(d, name, title, when, attendees, source=None):
    att = "".join(f'  - "{a}"\n' for a in attendees)
    src = f"source: {source}\n" if source else ""
    (d / name).write_text(f'---\ntype: meeting\nstatus: active\ntitle: "{title}"\ndate: {when[:10]}\n'
                          f"attendees:\n{att}{src}---\n# {title}\n\n**Date:** {when}\n\n## Summary\n\nbody\n")
    return d / name


def main():
    d = Path(tempfile.mkdtemp())
    g = {"id": "not_abc", "title": "Jeff / Mike weekly", "dt": datetime(2026, 9, 8, 9, 5, tzinfo=CT),
         "participants": ["Jeffrey Gottlieb", "Michael Stegmaier"], "summary": "- talked", "url": "https://notes.granola.ai/d/x"}
    right = fathom_note(d, "2026-09-08-1-1-gottlieb-stegmaier.md", "1:1 Gottlieb / Stegmaier", "2026-09-08 at 9:00 AM",
                        ["Jeffrey Gottlieb", "Michael Stegmaier"])
    fathom_note(d, "2026-09-08-rad-management-call.md", "RAD Management Call", "2026-09-08 at 3:00 PM",
                ["Mark Jones", "Michael Stegmaier"])                                   # same day, wrong time
    fathom_note(d, "2026-09-08-standup.md", "Standup", "2026-09-08 at 9:00 AM", ["Kiki Wang", "Liam McGrath"])  # right time, disjoint
    fathom_note(d, "2026-09-09-1-1-gottlieb-stegmaier.md", "1:1 Gottlieb / Stegmaier", "2026-09-09 at 9:00 AM",
                ["Jeffrey Gottlieb", "Michael Stegmaier"])                            # different day
    fathom_note(d, "2026-09-08-granola-paste.md", "1:1 Gottlieb / Stegmaier", "2026-09-08 at 9:00 AM",
                ["Jeffrey Gottlieb", "Michael Stegmaier"], source="granola")           # Granola-origin, never a target

    assert gs.find_fathom_match(g, d) == right, gs.find_fathom_match(g, d)
    assert gs.find_fathom_match({**g, "dt": datetime(2026, 9, 10, 9, 0, tzinfo=CT)}, d) is None
    assert gs.find_fathom_match({**g, "participants": ["Nobody Here", "Someone Else"]}, d) is None

    before = right.read_text()
    now = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)
    assert gs.append_granola_section(right, g, now) is True
    after = right.read_text()
    assert after.startswith(before.rstrip("\n") + "\n"), "existing content changed"
    assert after.count(gs.SECTION) == 1 and "not_abc" in after and "- talked" in after
    assert gs.append_granola_section(right, g, now) is False
    assert right.read_text() == after, "second run changed the note"
    print("ok")


if __name__ == "__main__":
    main()
