"""The one check for projects.py: frontmatter parsing, longest prefix, unique whole-repo, ambiguity.

Run: cd cos && python3 test_projects.py
"""
import projects as p

page = """---
type: project
repos:
  - Org/Repo.dbt
  - Org/Repo.Snow/perf_bench
---
# X
"""
assert p.parse_repos(page) == [("Org/Repo.dbt", ""), ("Org/Repo.Snow", "perf_bench")]
assert p.parse_repos('---\ntype: project\nrepos: [Org/A, "Org/B/x/y"]\n---\n') == [("Org/A", ""), ("Org/B", "x/y")]
assert p.parse_repos("no frontmatter") == []

mapping = {
    "dv2": [("Org/Repo.dbt", ""), ("Org/Repo.Snow", "perf_bench")],
    "signals": [("Org/Repo.Snow", "")],
    "dcm": [("Org/Repo.Snow", "")],
    "ingest": [("Org/Repo.Astro", "")],
}
# a PR touching only perf_bench/ in the shared repo -> the prefix owner
assert p.project_for("Org/Repo.Snow", ["perf_bench/run.py", "perf_bench/README.md"], mapping) == ("dv2", ["dv2"])
# housekeeping files at the repo root don't break the prefix match (17 of 19 files under perf_bench/)
assert p.project_for("Org/Repo.Snow", ["perf_bench/a.py"] * 17 + ["CLAUDE.md", ".claude/gate.sh"], mapping) == ("dv2", ["dv2"])
assert p.covers("perf_bench", ["perf_bench/a", "x", "y"]) is False  # one of three is not a majority
# a PR elsewhere in the shared repo: two whole-repo claimants -> unlabelled, both candidates
assert p.project_for("Org/Repo.Snow", ["signals/x.sql"], mapping) == (None, ["dcm", "signals"])
# a repo with one whole-repo claimant -> that page, files irrelevant
assert p.project_for("Org/Repo.Astro", [], mapping) == ("ingest", ["ingest"])
assert p.project_for("org/repo.dbt", ["models/a.sql"], mapping) == ("dv2", ["dv2"])  # case-insensitive
# unknown repo
assert p.project_for("Org/Nope", ["a"], mapping) == (None, [])

print("ok: repos parsing and PR-to-project mapping hold")
