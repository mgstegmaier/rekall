#!/usr/bin/env python3
"""PreToolUse guard for the pipeline's headless claude child.

The Fathom summary the agent ingests is LLM-generated from whatever people said in a
meeting, and anything dropped in wiki/raw/ rides the same path. A crafted line could
steer the agent into ~/.ssh, a .env, or an injected secret and write it into a wiki
page, which then replicates through Obsidian Sync. There is no Bash or network tool in
the child's allowlist, so a page is the exfiltration route, and this closes it.

Allowed roots arrive as REKALL_GUARD_ROOTS (os.pathsep-separated). Every path-carrying
tool input must resolve inside one of them or the call is denied. Write and Edit are held
tighter: only inside a write root (the command's arguments; the pipeline passes VAULT/wiki),
never a file named CLAUDE.md, which ingest's own rules come from. Any path with a dot-named
component inside its root (.obsidian/ plugin code, a planted .claude/settings.json) is
denied for every tool. A root that is not a write root is read-only.

Contract (Claude Code hooks): stdin is the tool call as JSON with `tool_name` and
`tool_input`; printing a hookSpecificOutput object with permissionDecision "deny" and
exiting 0 blocks the call and hands the reason back to the model.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Every key a path can arrive under across Read, Write, Edit, Glob, and Grep. A tool
# input key that is not here is not a path, so it needs no check.
PATH_KEYS = ("file_path", "path", "notebook_path")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def roots():
    raw = os.environ.get("REKALL_GUARD_ROOTS", "")
    return [Path(p).resolve() for p in raw.split(os.pathsep) if p]


def where(path, allowed):
    """(resolved path, the allowed root it sits in), or None when it escapes every root.
    Symlinks are resolved first, so a link planted inside the vault cannot point out of it."""
    try:
        real = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return None  # unresolvable is not provably inside
    for root in allowed:
        if real == root or root in real.parents:
            return real, root
    return None


def refusal(tool, value, allowed, writable):
    """Why this call is refused, or None when it may proceed."""
    hit = where(value, allowed)
    if hit is None:
        return (f"{tool} is restricted to {os.pathsep.join(str(r) for r in allowed)} during "
                f"automated ingest. Refused: {value}. Work only from the sources named in the prompt.")
    real, root = hit
    if any(part.startswith(".") for part in real.relative_to(root).parts):
        return f"hidden files and folders are off limits during automated ingest. Refused: {value}"
    if tool in WRITE_TOOLS:
        if real.name == "CLAUDE.md":
            return f"CLAUDE.md files are read-only during automated ingest. Refused: {value}"
        if where(real, writable) is None:
            return (f"{tool} is restricted to {os.pathsep.join(str(r) for r in writable)} during "
                    f"automated ingest. Refused: {value}")
    return None


def main():
    try:
        call = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return deny("guard could not parse the tool call")

    allowed = roots()
    if not allowed:
        # Fail closed. An empty allowlist means the caller forgot to set the variable,
        # and a guard that allows everything when misconfigured is not a guard.
        return deny("REKALL_GUARD_ROOTS is unset, so no path can be verified")

    writable = [Path(p).resolve() for p in sys.argv[1:]]
    tool_input = call.get("tool_input") or {}
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            reason = refusal(call.get("tool_name", "tool"), value, allowed, writable)
            if reason:
                return deny(reason)
    sys.exit(0)  # no output, no decision, the call proceeds


def deny(reason):
    # A control with no record can't be shown to anyone. Append-only, best effort: a
    # logging failure must never turn a denial into an allow.
    path = os.environ.get("REKALL_GUARD_LOG")
    if path:
        try:
            with open(path, "a") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')} DENY {reason}\n")
        except OSError:
            pass
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
