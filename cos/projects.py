"""Which wiki project a repo path belongs to, from the `repos:` frontmatter on project pages.

    repos:
      - your-org/data-warehouse            # the whole repo
      - your-org/platform/perf_bench       # one folder of a shared repo

A PR maps to the page with the longest prefix that covers at least half its changed files. A whole-repo entry
wins only when it is the sole page claiming that repo AND no page names a folder of it. In a repo
split by folders, or when two pages claim it whole, the PR keeps its repo label and the whole-repo
pages come back as candidates, so the rigor check can say "cite on one of ...". Read-only, stdlib only.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rekall_config import WIKI  # noqa: E402

PAGES = WIKI / "pages"


def parse_repos(text):
    """The `repos:` list from a page's frontmatter, as (owner/repo, prefix) tuples; prefix '' = whole repo."""
    if not text.startswith("---"):
        return []
    fm = text.split("---", 2)[1]
    m = re.search(r"^repos:\s*\n((?:[ \t]+-\s+.+\n?)+)", fm, re.M)
    items = re.findall(r"-\s+(\S+)", m.group(1)) if m else []
    m2 = re.search(r"^repos:\s*\[(.+?)\]", fm, re.M)
    if m2:
        items += [x.strip().strip("\"'") for x in m2.group(1).split(",")]
    out = []
    for it in items:
        parts = it.strip().strip("\"'").split("/")
        if len(parts) < 2:
            continue
        out.append(("/".join(parts[:2]), "/".join(parts[2:]).strip("/")))
    return out


def project_repos(pages_dir=None):
    """{page stem: [(owner/repo, prefix), ...]} for every project page that declares repos."""
    out = {}
    for p in (pages_dir or PAGES).glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^type:\s*project\s*$", text[:2000], re.M):
            continue
        repos = parse_repos(text)
        if repos:
            out[p.stem] = repos
    return out


def covers(prefix, files):
    """A prefix covers a PR when at least half its changed files sit under it. PR #28 (perf_bench) also
    touched CLAUDE.md and .claude/gate.sh at the repo root; housekeeping files must not break the match."""
    if not files:
        return False
    root = prefix.rstrip("/") + "/"
    under = sum(1 for f in files if f.startswith(root) or f == prefix)
    return under * 2 >= len(files)


def project_for(full_repo, files, mapping):
    """(page stem or None, candidate stems). Longest covering prefix wins; whole-repo wins only if unique."""
    full_repo = full_repo.lower()
    best, best_len, whole, split = None, -1, [], False
    for stem, repos in mapping.items():
        for repo, prefix in repos:
            if repo.lower() != full_repo:
                continue
            if not prefix:
                whole.append(stem)
                continue
            split = True  # at least one page names a folder of this repo
            if covers(prefix, files) and len(prefix) > best_len:
                best, best_len = stem, len(prefix)
    if best:
        return best, [best]
    if len(whole) == 1 and not split:
        return whole[0], whole
    # a repo split by folders: a page that names no folder can be a candidate, never the label
    return None, sorted(set(whole))


if __name__ == "__main__":
    for stem, repos in sorted(project_repos().items()):
        print(stem, "->", ", ".join(r + ("/" + x if x else "") for r, x in repos))
