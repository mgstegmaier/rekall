#!/usr/bin/env python3
"""Nightly wiki lint: read-only checks over the vault's wiki, human-readable report.

Never writes to the vault. Structure/schema reference: wiki/CLAUDE.md.
Persists per-check issue counts to ~/.config/rekall/wiki-lint-state.json; if any
check's count goes up since the previous run, notify() fires (macOS notification,
same pattern as fathom-pipeline.py). First run (no state file) never notifies.
Always writes the full report to ~/.config/rekall/logs/wiki-lint-<timestamp>.log.

Flags: --verbose (list every offender, not just top 10) | --no-notify
Exit code is always 0 -- this is a reporter, not a gate.
"""

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from datetime import date, datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekall_config import ARCHIVE, STATE_DIR, VAULT, WIKI  # noqa: E402
RAW = WIKI / "raw"
RESEARCH = WIKI / "pages" / "research"
TYPED_DIRS = ["pages"]
REQUIRED_FIELDS = ["type", "title", "description", "date"]
PAGE_TYPES = {"person", "project", "entity", "concept", "summary", "system", "pipeline",
              "note", "decision", "context", "research"}  # `type` is the taxonomy; a page lives in pages/<type>/
STATUSES = {"active", "retired", "archive"}
STATE_FILE = STATE_DIR / "wiki-lint-state.json"
PIPELINE_STATE = STATE_DIR / "fathom-pipeline-state.json"
LOG_DIR = STATE_DIR / "logs"
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)  # [[...]] inside code is TOML/prose, not a link
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def page_type(path):
    m = FRONTMATTER_RE.match(path.read_text(encoding="utf-8", errors="replace"))
    t = re.search(r"(?m)^type:\s*(\S+)", m.group(1)) if m else None
    return t.group(1) if t else None


def dir_md(d):
    """pages/ nests by type (pages/<type>/x.md); meetings/ is flat and its distilled/ is source material."""
    return (WIKI / d).rglob("*.md") if d in TYPED_DIRS else (WIKI / d).glob("*.md")
LIMIT = 10
DRIFT_DAYS = 14  # Updates may outrun State by this much before check_state_drift complains


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def notify(msg, title="Wiki lint"):
    """macOS notification; never raises. Windows has no osascript, so the log line is it."""
    log(f"  NOTIFY: {msg}")
    if os.name == "nt":
        return
    try:
        subprocess.run(
            ["osascript", "-e", f"display notification {json.dumps(msg)} with title {json.dumps(title)}"],
            capture_output=True, timeout=10)
    except Exception:
        pass


def all_wiki_files():
    # CLAUDE.md excluded from link checks: its wikilinks are schema examples, not references
    # raw/ and meetings/distilled/ excluded: source material, not wiki pages
    # archive/ excluded: out of the wiki, but its basenames stay valid link targets (see main)
    return [p for p in WIKI.rglob("*.md")
            if ".obsidian" not in p.parts and p.name != "CLAUDE.md"
            and "raw" not in p.parts and "distilled" not in p.parts and ARCHIVE.name not in p.parts]


def parse_link_target(raw):
    """A raw [[...]] body -> the basename it resolves to (strip alias, heading, path)."""
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    # tables escape the alias pipe as \| — strip the leftover backslash, it's valid syntax
    return target.rsplit("/", 1)[-1].rstrip("\\")


def frontmatter_text(text):
    m = FRONTMATTER_RE.match(text)
    return m.group(1) if m else ""


def fm_field(fm, field):
    """Scalar frontmatter value: `field: value` on one line, quotes stripped."""
    m = re.search(rf"(?m)^{re.escape(field)}:[ \t]*(.+)$", fm)
    return m.group(1).strip().strip("\"'") if m else None


def fm_list(fm, field):
    """List frontmatter value, either inline `field: [a, b]` or block `field:\\n  - a\\n  - b`."""
    m = re.search(rf"(?m)^{re.escape(field)}:[ \t]*\[(.*?)\]", fm)
    if m:
        return [v.strip().strip("\"'") for v in m.group(1).split(",") if v.strip()]
    m = re.search(rf"(?m)^{re.escape(field)}:[ \t]*$", fm)
    if not m:
        return []
    items = []
    for line in fm[m.end():].splitlines():
        if re.match(r"^\s*-\s+", line):
            items.append(re.sub(r"^\s*-\s+", "", line).strip().strip("\"'"))
        elif line.strip():
            break
    return items


class Report:
    def __init__(self, verbose):
        self.verbose = verbose
        self.lines = []
        self.warn_lines = []  # separate tier: printed under "Warnings", never counted or gated on
        self.counts = {}

    def out(self, line="", warn=False):
        (self.warn_lines if warn else self.lines).append(line)

    def section(self, key, title, entries, warn=False):
        """Generic check section: prints count + up to LIMIT (or all if verbose) entries.
        warn=True routes to the Warnings tier: not added to self.counts, so it never affects the
        issue total, the persisted state, or the regression notification."""
        if not warn:
            self.counts[key] = len(entries)
        self.out(f"\n== {title} ({len(entries)}) ==", warn=warn)
        if not entries:
            self.out("  none", warn=warn)
            return
        shown = entries if self.verbose else entries[:LIMIT]
        for e in shown:
            self.out(f"  {e}", warn=warn)
        if not self.verbose and len(entries) > LIMIT:
            self.out(f"  ... and {len(entries) - LIMIT} more", warn=warn)

    def text(self):
        out = "\n".join(self.lines)
        if self.warn_lines:
            out += "\n\n== Warnings ==\n" + "\n".join(self.warn_lines)
        return out


# ── Checks ──────────────────────────────────────────────────

def check_broken_links(r, files, known):
    broken = []  # (file_rel, target)
    for f in files:
        # sessions/ and daily-notes-archive/ are generated (SessionEnd digests, /today) and never
        # hand-edited, so their dangling links are not actionable here; they stay in `known`
        if f.name == "log.md" or "sessions" in f.parts or "daily-notes-archive" in f.parts:
            continue
        text = CODE_RE.sub("", f.read_text(encoding="utf-8", errors="replace"))
        for raw in LINK_RE.findall(text):
            target = parse_link_target(raw)
            if target and target not in known:
                broken.append((str(f.relative_to(WIKI)), target))

    r.counts["broken_links"] = len(broken)
    r.out(f"\n== 1. Broken wikilinks ({len(broken)}) ==")
    if not broken:
        r.out("  none")
        return
    by_file = Counter(f for f, _ in broken)
    r.out("  top offending files:")
    for fname, n in by_file.most_common(None if r.verbose else LIMIT):
        r.out(f"    {fname}  ({n}x)")
    if not r.verbose and len(by_file) > LIMIT:
        r.out(f"    ... and {len(by_file) - LIMIT} more files")
    if r.verbose:
        r.out("  every occurrence:")
        for fname, target in broken:
            r.out(f"    {fname} -> [[{target}]]")


def check_duplicates(r, basenames):
    dupes = [f"{name}: {', '.join(str(p.relative_to(WIKI)) for p in paths)}"
             for name, paths in basenames.items() if len(paths) > 1]
    r.section("duplicates", "2. Duplicate basenames", sorted(dupes))


def check_frontmatter(r):
    missing_by_field = {field: [] for field in REQUIRED_FIELDS}
    type_mismatch = []
    for d in TYPED_DIRS:
        for f in (WIKI / d).rglob("*.md"):
            fm = frontmatter_text(f.read_text(encoding="utf-8", errors="replace"))
            for field in REQUIRED_FIELDS:
                if not re.search(rf"(?m)^{re.escape(field)}:", fm):
                    missing_by_field[field].append(str(f.relative_to(WIKI)))
            tm = re.search(r"(?m)^type:\s*(\S+)", fm)
            if tm and tm.group(1) not in PAGE_TYPES:
                type_mismatch.append(f"{f.relative_to(WIKI)} (type: {tm.group(1)})")

    total = sum(len(v) for v in missing_by_field.values()) + len(type_mismatch)
    r.counts["frontmatter"] = total
    r.out(f"\n== 3. Frontmatter schema ({total} missing-field or type/folder mismatches) ==")
    if not total:
        r.out("  none")
        return
    if type_mismatch:
        r.out(f"  type outside the wiki page types {'/'.join(sorted(PAGE_TYPES))} ({len(type_mismatch)}):")
        for p in (type_mismatch if r.verbose else type_mismatch[:LIMIT]):
            r.out(f"    {p}")
    for field, paths in missing_by_field.items():
        r.out(f"  missing `{field}` ({len(paths)}):")
        shown = paths if r.verbose else paths[:LIMIT]
        for p in shown:
            r.out(f"    {p}")
        if not r.verbose and len(paths) > LIMIT:
            r.out(f"    ... and {len(paths) - LIMIT} more")


def check_naming(r):
    violations = []
    for d in TYPED_DIRS + ["meetings"]:
        for f in dir_md(d):
            if f.name == "CLAUDE.md":
                continue
            if " " in f.stem or f.stem != f.stem.lower():
                violations.append(str(f.relative_to(WIKI)))
    r.section("naming", "4. Naming violations (spaces/uppercase)", sorted(violations))


def check_index_sync(r, basenames):
    index_text = (WIKI / "index.md").read_text(encoding="utf-8", errors="replace")
    index_links = {parse_link_target(raw) for raw in LINK_RE.findall(index_text)}

    typed_pages = set()
    for d in TYPED_DIRS:
        typed_pages |= {p.stem for p in (WIKI / d).rglob("*.md")}
    meeting_stems = {p.stem for p in (WIKI / "meetings").glob("*.md")}

    missing_from_index = sorted(typed_pages - index_links)
    ghosts = sorted((index_links - typed_pages) - meeting_stems)

    r.out(f"\n== 5. Index sync ({len(missing_from_index) + len(ghosts)}) ==")
    r.counts["index_sync"] = len(missing_from_index) + len(ghosts)
    r.out(f"  pages not linked from index.md ({len(missing_from_index)}):")
    shown = missing_from_index if r.verbose else missing_from_index[:LIMIT]
    for p in shown:
        r.out(f"    {p}")
    if not r.verbose and len(missing_from_index) > LIMIT:
        r.out(f"    ... and {len(missing_from_index) - LIMIT} more")
    r.out(f"  ghost links in index.md (target in no folder, incl. meetings) ({len(ghosts)}):")
    shown = ghosts if r.verbose else ghosts[:LIMIT]
    for g in shown:
        r.out(f"    [[{g}]]")
    if not r.verbose and len(ghosts) > LIMIT:
        r.out(f"    ... and {len(ghosts) - LIMIT} more")


def check_project_sections(r):
    required = ["## State", "## Members", "## Next steps"]
    issues = []
    for f in sorted(f for f in (WIKI / "pages").rglob("*.md") if page_type(f) == "project"):
        lines = set(f.read_text(encoding="utf-8", errors="replace").splitlines())
        for heading in required:
            if heading not in lines:
                issues.append(f"{f.relative_to(WIKI)}: missing `{heading}`")
    r.section("project_sections", "6. Project-page sections", issues)


def check_log_order(r):
    dates = re.findall(r"(?m)^## (\d{4}-\d{2}-\d{2})$", (WIKI / "log.md").read_text(encoding="utf-8", errors="replace"))
    violations = [f"line pair #{i}: {dates[i]} -> {dates[i + 1]} (decreasing)"
                  for i in range(len(dates) - 1) if dates[i] > dates[i + 1]]
    r.section("log_order", "7. Log ordering (non-decreasing top to bottom)", violations)


def check_pipeline_state(r):
    issues = []
    if PIPELINE_STATE.exists():
        state = json.loads(PIPELINE_STATE.read_text())
        for name in state.get("raw_ingested", []):
            # entries may be "name" (legacy) or "name:sha16" (content-hash keys)
            fname = name.rsplit(":", 1)[0] if re.fullmatch(r".+:[0-9a-f]{16}", name) else name
            if not (RAW / fname).exists() and not (ARCHIVE / fname).exists():
                issues.append(f"raw_ingested references missing file: wiki/raw/{fname}")
        for name in state.get("research_ingested", []):
            fname = name.rsplit(":", 1)[0] if re.fullmatch(r".+:[0-9a-f]{16}", name) else name
            if not (RESEARCH / fname).exists() and not (ARCHIVE / fname).exists():
                issues.append(f"research_ingested references missing file: wiki/pages/research/{fname}")
        for mid, entry in state.get("meetings", {}).items():
            if entry.get("retired"):
                continue  # deleted under the pre-2026-09-04 retire path; missing on disk is correct
            note = entry.get("note", "")
            if note and not (VAULT / note).exists() and not (ARCHIVE / Path(note).name).exists():
                issues.append(f"meeting {mid} ({entry.get('title', '?')}) note missing: {note}")
        for source, count in state.get("ingest_failures", {}).items():
            if count >= 2:
                issues.append(f"quarantined ({count}x failures): {source}")
    r.section("pipeline_state", "8. Fathom pipeline state cross-check", issues)


def check_page_order(r):
    """State first, one of each canonical section, dated updates newest-first (wiki/CLAUDE.md
    'Page body format'). Fix with scripts/wiki-reflow.py."""
    lead = re.compile(r"^#{2,3} +(\d{4}-\d{2}-\d{2})\b")
    trail = re.compile(r"^#{2,3} +.*\((\d{4}-\d{2}-\d{2})[^)]*\)\s*$")

    def dated(ln):
        m = lead.match(ln) or trail.match(ln)
        return m.group(1) if m else None

    issues = []
    for d in TYPED_DIRS:
        for f in sorted((WIKI / d).rglob("*.md")):
            rel = f.relative_to(WIKI)
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            h2 = [ln for ln in lines if ln.startswith("## ")]
            for name in ("## State", "## Next steps", "## Members", "## Research", "## Related pages"):
                if h2.count(name) > 1:
                    issues.append(f"{rel}: {h2.count(name)}x `{name}` (merge)")
            if "## State" in h2 and h2[0] != "## State":
                issues.append(f"{rel}: first section is `{h2[0]}`, not `## State`")
            dates = [dated(ln) for ln in lines if dated(ln)]
            if any(a < b for a, b in zip(dates, dates[1:])):
                issues.append(f"{rel}: dated headings not newest-first")
            if any(ln.startswith("## ") and dated(ln) for ln in lines):
                issues.append(f"{rel}: dated H2 outside `## Updates`")
    r.section("page_order", "9. Page order (State first, no duplicate sections, updates newest-first)", issues)


def check_lifecycle(r):
    """Every page and meeting note carries `status: active|retired|archive` (wiki/CLAUDE.md
    'Page lifecycle'). Fix missing ones with scripts/wiki-cleanup.py --stamp."""
    issues = []
    for d in TYPED_DIRS + ["meetings"]:
        for f in sorted(dir_md(d)):
            fm = frontmatter_text(f.read_text(encoding="utf-8", errors="replace"))
            m = re.search(r"(?m)^status:\s*(\S+)", fm)
            if not m:
                issues.append(f"{f.relative_to(WIKI)}: missing `status`")
            elif m.group(1) not in STATUSES:
                issues.append(f"{f.relative_to(WIKI)}: status `{m.group(1)}` not in active/retired/archive")
    r.section("lifecycle", "10. Lifecycle status (active/retired/archive on every page)", issues)


def check_relations(r):
    """owner (string), people (list), depends_on/about/part_of/runs_on/reads_from/writes_to (list):
    every value must be an existing pages/ slug (11), owner/people/maintainers targets must be
    `type: person` pages (12), and part_of/runs_on targets must be the right page type with no
    self-reference (13). `attendees` on meeting notes is intentionally not validated here (plan
    phase 1: names may lack pages); `about` on meeting notes is checked below since meeting notes
    live in wiki/meetings/, not pages/."""
    page_type_by_slug = {p.stem: page_type(p) for p in (WIKI / "pages").rglob("*.md")}
    unresolved, wrong_type, structure = [], [], []
    for f in sorted((WIKI / "pages").rglob("*.md")):
        fm = frontmatter_text(f.read_text(encoding="utf-8", errors="replace"))
        rel = f.relative_to(WIKI)
        owner = fm_field(fm, "owner")
        fields = [("owner", [owner] if owner else []), ("people", fm_list(fm, "people")), ("maintainers", fm_list(fm, "maintainers"))]
        resolve_only = [("depends_on", fm_list(fm, "depends_on")), ("about", fm_list(fm, "about")),
                        ("part_of", fm_list(fm, "part_of")), ("runs_on", fm_list(fm, "runs_on")),
                        ("reads_from", fm_list(fm, "reads_from")), ("writes_to", fm_list(fm, "writes_to"))]
        for field, values in fields + resolve_only:
            for v in values:
                if v not in page_type_by_slug:
                    unresolved.append(f"{rel}: {field} -> {v} (no such page)")
        for field, values in fields:
            for v in values:
                if v in page_type_by_slug and page_type_by_slug[v] != "person":
                    wrong_type.append(f"{rel}: {field} -> {v} (type: {page_type_by_slug[v]}, not person)")
        for v in fm_list(fm, "part_of"):
            if v == f.stem:
                structure.append(f"{rel}: part_of -> itself")
            elif v in page_type_by_slug and page_type_by_slug[v] not in ("project", "system", "pipeline"):
                structure.append(f"{rel}: part_of -> {v} (type: {page_type_by_slug[v]}, not project/system/pipeline)")
        for v in fm_list(fm, "runs_on"):
            if v in page_type_by_slug and page_type_by_slug[v] != "system":
                structure.append(f"{rel}: runs_on -> {v} (type: {page_type_by_slug[v]}, not system)")
    for f in sorted((WIKI / "meetings").glob("*.md")):
        fm = frontmatter_text(f.read_text(encoding="utf-8", errors="replace"))
        rel = f.relative_to(WIKI)
        for v in fm_list(fm, "about"):
            if v not in page_type_by_slug:
                unresolved.append(f"{rel}: about -> {v} (no such page)")
    r.section("relations_unresolved",
              "11. Relation targets (owner/people/maintainers/depends_on/about/part_of/runs_on/reads_from/writes_to resolve to a page)",
              unresolved)
    r.section("relations_type", "12. Relation targets are person pages (owner/people/maintainers)", wrong_type)
    r.section("relations_structure", "13. part_of/runs_on structure (project/system/pipeline parent, system runtime, no self-reference)", structure)


def check_owner_warning(r):
    """Active project pages with no `owner` -- warning tier, not an error (plan phase 1)."""
    issues = []
    for f in sorted((WIKI / "pages").rglob("*.md")):
        fm = frontmatter_text(f.read_text(encoding="utf-8", errors="replace"))
        t = re.search(r"(?m)^type:\s*(\S+)", fm)
        s = re.search(r"(?m)^status:\s*(\S+)", fm)
        if t and t.group(1) == "project" and s and s.group(1) == "active" and not fm_field(fm, "owner"):
            issues.append(str(f.relative_to(WIKI)))
    r.section("owner_missing", "Active project pages missing `owner`", issues, warn=True)


def check_type_folder(r):
    """A page sits in pages/<its type>/ (wiki/CLAUDE.md 'Placement'). Move with scripts/wiki-type-folders.py."""
    issues = []
    for f in sorted((WIKI / "pages").rglob("*.md")):
        t = page_type(f)
        if f.parent != WIKI / "pages" / str(t):
            issues.append(f"{f.relative_to(WIKI)} (type: {t})")
    r.section("type_folder", "Pages outside pages/<type>/", issues, warn=True)


def check_state_drift(r):
    """Warn when a page's newest `## Updates` date is more than DRIFT_DAYS past the newest date in a
    `(source: ...)` citation in `## State`. The mail and Teams ingest writes only to Updates by
    design, so facts land there and never reach State, which is what the recall hook surfaces; a
    page can drift until its State says one thing and its latest Update says the opposite.
    Skips pages without both sections and pages whose status is retired/archive."""
    def section(text, name):
        ms = [m.group(1) for m in re.finditer(rf"(?ms)^## {name}[ \t]*$(.*?)(?=^## |\Z)", text)]
        return "\n".join(ms) if ms else None  # every section of that name: some pages carry duplicates

    issues = []
    for f in sorted((WIKI / "pages").rglob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if fm_field(frontmatter_text(text), "status") in ("retired", "archive"):
            continue
        state, updates = section(text, "State"), section(text, "Updates")
        if state is None or updates is None:
            continue
        # ponytail: Updates dates are heading/bullet leads only; State dates only inside `(source: ...)`
        upd = re.findall(r"(?m)^(?:#{2,4}|[-*])[ \t]+(\d{4}-\d{2}-\d{2})\b", updates)
        cited = [d for c in re.findall(r"\(source:[^)]*\)", state) for d in re.findall(r"\d{4}-\d{2}-\d{2}", c)]
        if not upd or not cited:
            continue
        try:
            gap = (date.fromisoformat(max(upd)) - date.fromisoformat(max(cited))).days
        except ValueError:  # a typo'd date like 2026-13-45 is not drift
            continue
        if gap > DRIFT_DAYS:
            issues.append(f"{f.relative_to(WIKI)}: newest Update {max(upd)}, newest State citation {max(cited)} ({gap} days)")
    r.section("state_drift", f"State drift (newest Update >{DRIFT_DAYS} days past newest State citation)", issues, warn=True)


# ── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()

    r = Report(args.verbose)
    r.out(f"Wiki lint report -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    files = all_wiki_files()
    basenames = {}
    for f in files:
        basenames.setdefault(f.stem, []).append(f)

    # raw/ and distilled/ are not linted, but summary pages cite them in Sources lines;
    # attachments keep their extension because embeds do: ![[x.png]]
    known = (set(basenames) | {p.stem for p in ARCHIVE.glob("*.md")}
             | {p.stem for p in RAW.glob("*.md")} | {p.stem for p in (WIKI / "distilled").glob("*.md")}
             | {p.name for p in (VAULT / "attachments").glob("*")})
    check_broken_links(r, files, known)
    check_duplicates(r, basenames)
    check_frontmatter(r)
    check_naming(r)
    check_index_sync(r, basenames)
    check_project_sections(r)
    check_log_order(r)
    check_pipeline_state(r)
    check_page_order(r)
    check_lifecycle(r)
    check_relations(r)
    check_owner_warning(r)
    check_type_folder(r)
    check_state_drift(r)

    total = sum(r.counts.values())
    r.out(f"\nLINT: {total} issues across {len(r.counts)} checks")
    print(r.text())

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"wiki-lint-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    logfile.write_text(r.text() + "\n")

    prev = {}
    if STATE_FILE.exists():
        prev = json.loads(STATE_FILE.read_text())
    regressed = [k for k, v in r.counts.items() if k in prev and v > prev[k]]
    if regressed and not args.no_notify:
        notify(f"regressed: {', '.join(f'{k} {prev[k]}->{r.counts[k]}' for k in regressed)}")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(r.counts, indent=2))


if __name__ == "__main__":
    main()
