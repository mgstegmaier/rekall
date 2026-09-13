"""Apply approved frontmatter changes to vault pages.
Input: JSON {"pages/slug.md": {"type": "system", "owner": "x", "people": ["a","b"]}, ...}
Tries the obsidian CLI (property:set) per property; if the CLI fails, falls back to an in-place
frontmatter edit. Every touched file is backed up first to ./backup/<same relative path>.
Used for the typed-graph backfills (docs/plans/2026-09-12-typed-wiki-graph.md). Dry run without --apply."""
import json, shutil, subprocess, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rekall_config  # noqa

VAULT = rekall_config.VAULT
WIKI = rekall_config.WIKI
OBS = "/Applications/Obsidian.app/Contents/MacOS/obsidian"
BACKUP = Path(__file__).parent / "backup"

def cli_set(rel, name, value):
    if isinstance(value, list):
        args = [f"value={','.join(value)}", "type=list"]
    else:
        args = [f"value={value}", "type=text"]
    r = subprocess.run([OBS, "property:set", 'vault=heck-db', f"path=wiki/{rel}", f"name={name}", *args],
                       capture_output=True, text=True, timeout=20)
    return r.returncode == 0

def file_set(path, name, value):
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit(f"no frontmatter: {path}")
    fm = m.group(1)
    if isinstance(value, list):
        line = f"{name}:\n" + "".join(f"  - {v}\n" for v in value)
    else:
        line = f"{name}: {value}\n"
    # replace existing key (scalar or block list) or append
    pat = re.compile(rf"^{re.escape(name)}:.*?(?=^\S|\Z)", re.S | re.M)
    fm2 = pat.sub(line, fm + "\n", count=1).rstrip("\n") if pat.search(fm + "\n") else fm + "\n" + line.rstrip("\n")
    path.write_text(f"---\n{fm2}\n---\n" + text[m.end():])

def main(spec, apply):
    changes = json.load(open(spec))
    use_cli = None
    for rel, props in changes.items():
        path = WIKI / rel
        if not path.is_file():
            print("MISSING", rel); continue
        if not apply:
            print(rel, props); continue
        b = BACKUP / rel; b.parent.mkdir(parents=True, exist_ok=True)
        if not b.exists(): shutil.copy2(path, b)
        for name, value in props.items():
            if use_cli is None:
                try: use_cli = cli_set(rel, name, value)
                except Exception: use_cli = False
                if use_cli: continue
            if use_cli and cli_set(rel, name, value): continue
            file_set(path, name, value)
        print("ok", rel, list(props))
    print("via", "obsidian CLI" if use_cli else "direct file edit")

if __name__ == "__main__":
    main(sys.argv[1], "--apply" in sys.argv)
