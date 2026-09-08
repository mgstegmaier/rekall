"""GitHub facts through the `gh` CLI, read-only: PRs you merged, PRs you have open, reviews you owe.

Repos are filtered to the orgs in rekall.toml `[cos] github_orgs`; an empty list means every repo
the account can see. Every item carries `number`, `url`, and `repo` (the short name after the last
dot, so `UCG.DataEngineering.Astronomer` reads "Astronomer"). All failures raise RuntimeError with a
one-line reason; callers turn that into an errors[] entry, never a crash.
"""
import json
import subprocess
from datetime import date, datetime

PR_WAIT_BDAYS = 3  # an open PR with no approval for this many business days is waiting on someone


def run(args, timeout=60):
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("gh is not installed")
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh timed out")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1][:160] if (r.stderr or r.stdout).strip() else f"gh exit {r.returncode}")
    return json.loads(r.stdout or "[]")


def short_repo(name_with_owner):
    return name_with_owner.split("/", 1)[1].rsplit(".", 1)[-1]


def in_orgs(name_with_owner, orgs):
    return not orgs or name_with_owner.split("/", 1)[0].lower() in {o.lower() for o in orgs}


def _item(pr, **extra):
    return {"number": pr["number"], "title": pr["title"], "url": pr["url"],
            "repo": short_repo(pr["repository"]["nameWithOwner"]), "full_repo": pr["repository"]["nameWithOwner"], **extra}


def merged_prs(since, orgs):
    """PRs you authored that merged on or after `since` (a date), newest first."""
    rows = run(["search", "prs", "--author=@me", "--merged", f"--merged-at=>={since.isoformat()}", "--limit", "100",
                "--json", "repository,title,number,url,closedAt"])
    out = [_item(p, date=p["closedAt"][:10]) for p in rows if in_orgs(p["repository"]["nameWithOwner"], orgs)]
    return sorted(out, key=lambda i: i["date"], reverse=True)


def open_prs(orgs, today=None):
    """PRs you authored that are open and not drafts, with review state and business days waiting."""
    from followups import bdays_between  # same folder; keeps one definition of a business day
    today = today or date.today()
    rows = run(["search", "prs", "--author=@me", "--state=open", "--limit", "50",
                "--json", "repository,title,number,url,isDraft,createdAt,updatedAt"])
    out = []
    for p in rows:
        if p.get("isDraft") or not in_orgs(p["repository"]["nameWithOwner"], orgs):
            continue
        decision = ""
        try:
            decision = run(["pr", "view", p["url"], "--json", "reviewDecision"], timeout=30).get("reviewDecision") or ""
        except RuntimeError:
            pass
        opened = date.fromisoformat(p["createdAt"][:10])
        out.append(_item(p, opened=opened.isoformat(), review=decision or "NO_REVIEW",
                         wait_bdays=bdays_between(opened, today)))
    return sorted(out, key=lambda i: i["opened"])


def review_requests(orgs):
    """Open PRs where your review is requested."""
    rows = run(["search", "prs", "--review-requested=@me", "--state=open", "--limit", "50",
                "--json", "repository,title,number,url,author,updatedAt"])
    return [_item(p, author=(p.get("author") or {}).get("login", ""), updated=p["updatedAt"][:10])
            for p in rows if in_orgs(p["repository"]["nameWithOwner"], orgs)]


def pr_files(url):
    """Changed file paths of one PR; [] when gh can't say."""
    try:
        return [f["path"] for f in run(["pr", "view", url, "--json", "files"], timeout=30).get("files", [])]
    except RuntimeError:
        return []


def repo_prs(full_repo, since=None, state="merged", limit=20):
    """PRs by anyone in one repo: merged on/after `since`, or open. Newest first."""
    args = ["search", "prs", f"--repo={full_repo}", "--limit", str(limit),
            "--json", "repository,title,number,url,closedAt,createdAt,author,isDraft"]
    args += ["--merged", f"--merged-at=>={since.isoformat()}"] if state == "merged" else ["--state=open"]
    rows = run(args)
    out = []
    for r in rows:
        if state == "open" and r.get("isDraft"):
            continue
        out.append(_item(r, author=(r.get("author") or {}).get("login", ""),
                         date=(r.get("closedAt") if state == "merged" else r.get("createdAt"))[:10]))
    return sorted(out, key=lambda i: i["date"], reverse=True)


def waiting(prs):
    """The open PRs that count as waiting on someone: no approval after PR_WAIT_BDAYS business days."""
    return [p for p in prs if p["review"] != "APPROVED" and p["wait_bdays"] >= PR_WAIT_BDAYS]


if __name__ == "__main__":  # smoke: python3 gh.py -> counts for the last 7 days
    from datetime import timedelta
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from rekall_config import COS_GITHUB_ORGS
    since = date.today() - timedelta(days=7)
    m, o, r = merged_prs(since, COS_GITHUB_ORGS), open_prs(COS_GITHUB_ORGS), review_requests(COS_GITHUB_ORGS)
    print(f"merged since {since}: {len(m)} · open: {len(o)} (waiting: {len(waiting(o))}) · reviews owed: {len(r)}")
    for p in m:
        print(f"  {p['date']} {p['repo']} #{p['number']} {p['title'][:70]}")
    for p in waiting(o):
        print(f"  waiting {p['wait_bdays']}bd {p['repo']} #{p['number']} {p['title'][:60]} ({p['review']})")
