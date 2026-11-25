#!/usr/bin/env python3
"""Graph operations with built-in evidence verification.

Commands
  init                                           create empty graph
  add-node    --type T --name "..." --source S --paragraph P --quote "..."
              [--alias A ...] [--definition "..."] [--attribution author|cited|background]
              [--strength direct|indirect] [--confidence high|medium|low] [--id ID] [--file F]
  add-edge    --type T --src ID --dst ID --source S --paragraph P --quote "..."
              [--conditions "..."] [--strength ...] [--confidence ...] [--id ID] [--file F]
  add-evidence --node ID | --edge ID  --source S --paragraph P --quote "..."
  list        [--type T] [--source S]
  show        --node ID | --edge ID
  check                                          verify all quotes against the paragraph store

Every add/verify command refuses a quote that is not an exact (whitespace/quote-mark
tolerant) substring of the referenced paragraph. Work dir default: $KG_WORK or /app/work.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import (  # noqa: E402
    WORK, load_graph, load_paragraphs, node_index, edge_index, slug, norm, quote_in_text, write_json,
)

NODE_TYPES = {"researcher", "institution", "material", "method", "task", "model", "metric", "dataset",
              "conclusion", "condition", "other"}


def ev(source, paragraph, quote, attribution=None, strength=None):
    e = {"source_id": source, "paragraph_id": paragraph, "quote": quote}
    if attribution:
        e["attribution"] = attribution
    if strength:
        e["evidence_strength"] = strength
    return e


def verify(evidences, paras, where):
    bad = []
    for e in evidences:
        p = paras.get((e["source_id"], e["paragraph_id"]))
        if p is None:
            bad.append(f"{where}: paragraph {e['source_id']}/{e['paragraph_id']} not in store")
        elif not quote_in_text(e["quote"], p["text"]):
            bad.append(f"{where}: quote not found in {e['source_id']}/{e['paragraph_id']}: {e['quote'][:80]!r}")
    return bad


def cmd_init(a):
    g = {"nodes": [], "edges": []}
    write_json(a.graph, g)
    print(f"initialised {a.graph}")


def cmd_add_node(a):
    g = load_graph(a.graph)
    paras = load_paragraphs(a.para_dir)
    evidences = [ev(a.source, a.paragraph, a.quote, a.attribution, a.strength)]
    bad = verify(evidences, paras, "add-node")
    if bad:
        sys.exit("REFUSED (quote verification failed):\n  " + "\n  ".join(bad))
    nid = a.id or f"N:{a.type}:{slug(a.name)}"
    if nid in node_index(g):
        sys.exit(f"REFUSED: node id already exists: {nid}")
    g["nodes"].append({
        "id": nid, "type": a.type, "canonical_name": a.name,
        "aliases": a.alias or [], "definition": a.definition or "",
        "evidence": evidences, "first_seen": a.source,
        "attribution": a.attribution or "author",
        "confidence": a.confidence or ("high" if (a.attribution or "author") == "author" and (a.strength or "direct") == "direct" else "low"),
        "provenance": {"extraction": "llm", "verified_by": "scripts/graph_op.py"},
    })
    write_json(a.graph, g)
    print(f"added node {nid}")


def cmd_add_edge(a):
    g = load_graph(a.graph)
    paras = load_paragraphs(a.para_dir)
    ni = node_index(g)
    if a.src not in ni or a.dst not in ni:
        sys.exit(f"REFUSED: unknown node(s): {a.src not in ni and a.src} {a.dst not in ni and a.dst}")
    evidences = [ev(a.source, a.paragraph, a.quote, a.attribution, a.strength)]
    bad = verify(evidences, paras, "add-edge")
    if bad:
        sys.exit("REFUSED (quote verification failed):\n  " + "\n  ".join(bad))
    eid = a.id or f"E:{a.type}:{a.src.split(':', 2)[-1]}->{a.dst.split(':', 2)[-1]}"
    if eid in edge_index(g):
        sys.exit(f"REFUSED: edge id already exists: {eid}")
    g["edges"].append({
        "id": eid, "type": a.type, "src": a.src, "dst": a.dst, "evidence": evidences,
        "conditions": a.conditions or "", "confidence": a.confidence or "high",
        "evidence_strength": a.strength or "direct",
        "attribution": a.attribution or "author",
        "cross_paper": False,
    })
    write_json(a.graph, g)
    print(f"added edge {eid}")


def cmd_add_evidence(a):
    g = load_graph(a.graph)
    paras = load_paragraphs(a.para_dir)
    e_new = ev(a.source, a.paragraph, a.quote, a.attribution, a.strength)
    bad = verify([e_new], paras, "add-evidence")
    if bad:
        sys.exit("REFUSED (quote verification failed):\n  " + "\n  ".join(bad))
    if a.node:
        n = node_index(g).get(a.node) or sys.exit(f"no node {a.node}")
        n["evidence"].append(e_new)
        srcs = {x["source_id"] for x in n["evidence"]}
        n["sources"] = sorted(srcs)
        print(f"node {a.node} now has evidence from {sorted(srcs)}")
    else:
        ed = edge_index(g).get(a.edge) or sys.exit(f"no edge {a.edge}")
        ed["evidence"].append(e_new)
        ed["cross_paper"] = len({x["source_id"] for x in ed["evidence"]}) >= 2
        print(f"edge {a.edge} cross_paper={ed['cross_paper']}")
    write_json(a.graph, g)


def cmd_list(a):
    g = load_graph(a.graph)
    rows = []
    for n in g["nodes"]:
        if a.type and n["type"] != a.type:
            continue
        if a.source and a.source not in [e["source_id"] for e in n["evidence"]]:
            continue
        rows.append(f"{n['id']:<45} {n['type']:<12} src={sorted({e['source_id'] for e in n['evidence']})}")
    for e in g["edges"]:
        if a.type and e["type"] != a.type:
            continue
        rows.append(f"{e['id']:<45} {e['type']:<12} {e['src']} -> {e['dst']}")
    print("\n".join(rows) if rows else "(empty)")
    print(f"\n{len(g['nodes'])} nodes, {len(g['edges'])} edges")


def cmd_show(a):
    g = load_graph(a.graph)
    if a.node:
        print(json.dumps(node_index(g).get(a.node), ensure_ascii=False, indent=2))
    elif a.edge:
        print(json.dumps(edge_index(g).get(a.edge), ensure_ascii=False, indent=2))


def cmd_check(a):
    g = load_graph(a.graph)
    paras = load_paragraphs(a.para_dir)
    errs = []
    for n in g["nodes"]:
        errs += verify(n.get("evidence", []), paras, f"node {n['id']}")
        if not n.get("evidence"):
            errs.append(f"node {n['id']} has no evidence")
    for e in g["edges"]:
        errs += verify(e.get("evidence", []), paras, f"edge {e['id']}")
        if not e.get("evidence"):
            errs.append(f"edge {e['id']} has no evidence")
    ids = [n["id"] for n in g["nodes"]]
    dups = {i for i in ids if ids.count(i) > 1}
    if dups:
        errs.append(f"duplicate node ids: {sorted(dups)}")
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    print(f"OK: {len(g['nodes'])} nodes, {len(g['edges'])} edges, all quotes verified")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 parents=[common_parser()])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", parents=[common_parser()]).set_defaults(fn=cmd_init)

    p = sub.add_parser("add-node", parents=[common_parser()]); p.set_defaults(fn=cmd_add_node)
    for arg in ("--type", "--name", "--source", "--paragraph", "--quote"):
        p.add_argument(arg, required=True)
    p.add_argument("--alias", action="append")
    for arg in ("--definition", "--attribution", "--strength", "--confidence", "--id"):
        p.add_argument(arg)

    p = sub.add_parser("add-edge", parents=[common_parser()]); p.set_defaults(fn=cmd_add_edge)
    for arg in ("--type", "--src", "--dst", "--source", "--paragraph", "--quote"):
        p.add_argument(arg, required=True)
    for arg in ("--conditions", "--attribution", "--strength", "--confidence", "--id"):
        p.add_argument(arg)

    p = sub.add_parser("add-evidence", parents=[common_parser()]); p.set_defaults(fn=cmd_add_evidence)
    p.add_argument("--node"); p.add_argument("--edge")
    for arg in ("--source", "--paragraph", "--quote"):
        p.add_argument(arg, required=True)
    for arg in ("--attribution", "--strength"):
        p.add_argument(arg)

    p = sub.add_parser("list", parents=[common_parser()]); p.set_defaults(fn=cmd_list); p.add_argument("--type"); p.add_argument("--source")
    p = sub.add_parser("show", parents=[common_parser()]); p.set_defaults(fn=cmd_show); p.add_argument("--node"); p.add_argument("--edge")
    sub.add_parser("check", parents=[common_parser()]).set_defaults(fn=cmd_check)

    a = ap.parse_args()
    a.graph = a.graph or str(WORK / "graph.draft.json")
    a.para_dir = a.para_dir or str(WORK / "paragraphs")
    a.fn(a)


def common_parser():
    cp = argparse.ArgumentParser(add_help=False)
    cp.add_argument("--graph", default=None)
    cp.add_argument("--para-dir", default=None)
    return cp


if __name__ == "__main__":
    main()
