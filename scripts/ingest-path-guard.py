#!/usr/bin/env python3
"""PreToolUse guard for the pipeline's headless claude child.

The Fathom summary the agent ingests is LLM-generated from whatever people said in a
meeting, and anything dropped in wiki/raw/ rides the same path. A crafted line could
steer the agent into ~/.ssh, a .env, or an injected secret and write it into a wiki
page, which then replicates through Obsidian Sync. There is no Bash or network tool in
the child's allowlist, so a page is the exfiltration route, and this closes it.

Allowed roots arrive as REKALL_GUARD_ROOTS (os.pathsep-separated). Every path-carrying
tool input must resolve inside one of them or the call is denied.

Contract (Claude Code hooks): stdin is the tool call as JSON with `tool_name` and
`tool_input`; printing a hookSpecificOutput object with permissionDecision "deny" and
exiting 0 blocks the call and hands the reason back to the model.
"""
import json
import os
import sys
from pathlib import Path

# Every key a path can arrive under across Read, Write, Edit, Glob, and Grep. A tool
# input key that is not here is not a path, so it needs no check.
PATH_KEYS = ("file_path", "path", "notebook_path")


def roots():
    raw = os.environ.get("REKALL_GUARD_ROOTS", "")
    return [Path(p).resolve() for p in raw.split(os.pathsep) if p]


def outside(path, allowed):
    """True when path escapes every allowed root. Symlinks are resolved first, so a
    link planted inside the vault cannot point out of it."""
    try:
        real = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return True  # unresolvable is not provably inside
    return not any(real == root or root in real.parents for root in allowed)


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

    tool_input = call.get("tool_input") or {}
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value and outside(value, allowed):
            return deny(
                f"{call.get('tool_name', 'tool')} is restricted to "
                f"{os.pathsep.join(str(r) for r in allowed)} during automated ingest. "
                f"Refused: {value}. Work only from the sources named in the prompt."
            )
    sys.exit(0)  # no output, no decision, the call proceeds


def deny(reason):
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
