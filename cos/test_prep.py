"""The one check for prep.py's matching rules. No network: the calendar is never called here.

Run: cd cos && python3 test_prep.py
"""
import tempfile
from datetime import date
from pathlib import Path

import prep as p

# title matching: half the event's significant words, at least two when it has two or more
assert p.title_match(p.sig_words("CCL AI Weekly Project"), p.sig_words("CCL AI Weekly Project"))
assert p.title_match(p.sig_words("1:1 Gottlieb / Stegmaier"), p.sig_words("1:1 Gottlieb / Stegmaier"))
assert not p.title_match(p.sig_words("Claude wiki setup"), p.sig_words("Claude Code risk assessment readout"))
assert p.title_match(p.sig_words("Claude wiki setup"), p.sig_words("Claude wiki setup with Jeff"))
assert not p.title_match(set(), p.sig_words("anything"))

# names: "(host)" stripped, first+last collapses middle names
assert p.name_keys("Natalie Akers") == {"natalie akers"}
assert "michael stegmaier" in p.name_keys("Michael J Stegmaier")

# note parsing: participants without parentheticals, summary skips sub-headings and strips links
with tempfile.TemporaryDirectory() as d:
    n = Path(d) / "2026-09-04-ccl-ai-weekly-project.md"
    n.write_text('---\ntype: meeting\ntitle: "CCL AI Weekly Project"\ndate: 2026-09-04\n---\n# CCL\n\n'
                 "**Participants:** Natalie Akers (host), Kiki Wang, Michael Stegmaier\n\n## Summary\n\n"
                 "## Meeting Purpose\n[Align on AI project scope.](https://fathom.video/x)\n")
    meta = p.note_meta(n)
assert meta["participants"] == ["Natalie Akers", "Kiki Wang", "Michael Stegmaier"]
assert meta["summary"] == "Align on AI project scope."
assert meta["date"] == date(2026, 9, 4)

# spawning lines need a spawn verb and a title word
assert p.SPAWN_RE.search("- Schedule three-way alignment meeting with Blaisdell")
assert not p.SPAWN_RE.search("- Draft the one-pager")

print("ok: title matching, names, note parsing, spawn regex hold")
