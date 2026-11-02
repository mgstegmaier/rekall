"""The recall hook's injected text, parsed back into items.

Two callers: eval/hook_output.items() and digest/recall_use.scan(). The hook writes this
format (recall_hook.block() labels, graph_block() triples); eval/test_eval_harness.py runs
the real hook output through items(), so a reworded label or triple fails there.
"""
import re

MEMORY = re.compile(r"^\[(.+?) § (.*?)\]\n(.*)$", re.S)
GRAPH = re.compile(r"^(.*) -\[(.*?)\]-> (.*)  \((.*)\)$")
GRAPH_PREFIX = "Wiki graph:"


def parse(context):
    """(kind, label, excerpt, predicate) per injected item; kind is "memory" or "graph".
    Notices and the header parse to nothing."""
    found = []
    for part in context.split("\n\n"):
        if part.startswith(GRAPH_PREFIX):
            for line in part.splitlines()[1:]:
                m = GRAPH.match(line)
                if m:
                    s, p, t, doc = m.groups()
                    found.append(("graph", doc, f"{s} -[{p}]-> {t}", p))
        else:
            m = MEMORY.match(part)
            if m:
                found.append(("memory", f"{m[1]} § {m[2]}", m[3], ""))
    return found
