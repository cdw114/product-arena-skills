#!/usr/bin/env python3
"""Phase C4: execute graph queries. Every result carries evidence copied from the graph.

Usage:
  python scripts/query_kg.py --graph graph.aligned.json --query NAME [args] --out queries/NAME.json

  neighbors   --node ID [--edge-type T] [--hops 1|2]
  path        --src ID --dst ID
  by_source   --source SOURCE_ID
  cross_paper
  compare     --a ID --b ID
  conflicts
  used_by     --node METHOD_ID           (reverse traversal: what uses this method)
  reports     --node ID                   (reports_value edges with values+conditions, per paper)
  type        --type T                    (all nodes of a type with their sources)

Output: {"query": {...}, "result": {"nodes": [...], "edges": [...]}, "evidence": [...], "unresolvable": [...]}
The evidence array is the union of evidence over returned nodes/edges (each item keeps its own source_id).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import load_graph, write_json, evidence_sources  # noqa: E402


def subgraph(g, node_ids, edge_ids):
    ns = [n for n in g["nodes"] if n["id"] in node_ids]
    es = [e for e in g["edges"] if e["id"] in edge_ids]
    return {"nodes": ns, "edges": es}


def collect_evidence(nodes, edges):
    out, seen = [], set()
    for item in list(nodes) + list(edges):
        for e in item.get("evidence", []):
            k = (e.get("source_id"), e.get("paragraph_id"), e.get("quote"))
            if k in seen:
                continue
            seen.add(k)
            out.append({"source_id": e.get("source_id"), "paragraph_id": e.get("paragraph_id"), "quote": e.get("quote"),
                        "attribution": e.get("attribution", "author"), "evidence_strength": e.get("evidence_strength", "direct"),
                        "attached_to": item["id"]})
    return out


def result(g, nodes, edges, unresolvable=None):
    return {"nodes": [n["id"] for n in nodes], "edges": [e["id"] for e in edges],
            "node_details": [{"id": n["id"], "type": n["type"], "canonical_name": n["canonical_name"],
                              "sources": evidence_sources(n)} for n in nodes],
            "edge_details": [{"id": e["id"], "type": e["type"], "src": e["src"], "dst": e["dst"],
                              "conditions": e.get("conditions", ""), "sources": evidence_sources(e)} for e in edges],
            "evidence": collect_evidence(nodes, edges),
            "unresolvable": unresolvable or []}


def q_neighbors(g, a):
    ni = {n["id"]: n for n in g["nodes"]}
    if a.node not in ni:
        return None, [f"node {a.node} not in graph"]
    frontier = {a.node}
    visited = set()
    hops = a.hops or 1
    picked_edges = set()
    for _ in range(hops):
        nxt = set()
        for e in g["edges"]:
            if a.edge_type and e["type"] != a.edge_type:
                continue
            if e["src"] in frontier and e["dst"] not in visited:
                nxt.add(e["dst"]); picked_edges.add(e["id"])
            if e["dst"] in frontier and e["src"] not in visited:
                nxt.add(e["src"]); picked_edges.add(e["id"])
        visited |= frontier
        frontier = nxt
        if not frontier:
            break
    visited |= frontier
    return subgraph(g, visited, picked_edges), []


def q_path(g, a):
    ni = {n["id"]: n for n in g["nodes"]}
    if a.src not in ni or a.dst not in ni:
        return None, [f"node(s) not in graph: {a.src if a.src not in ni else ''} {a.dst if a.dst not in ni else ''}"]
    adj = {}
    for e in g["edges"]:
        adj.setdefault(e["src"], []).append((e["dst"], e["id"]))
    prev = {a.src: (None, None)}
    dq = deque([a.src])
    while dq:
        u = dq.popleft()
        if u == a.dst:
            break
        for v, eid in adj.get(u, []):
            if v not in prev:
                prev[v] = (u, eid)
                dq.append(v)
    if a.dst not in prev:
        return subgraph(g, {a.src, a.dst}, set()), [f"no directed path from {a.src} to {a.dst}"]
    path_e, cur = [], a.dst
    while prev[cur][0] is not None:
        u, eid = prev[cur]
        path_e.append(eid); cur = u
    path_e = set(path_e)
    return subgraph(g, {a.src, a.dst} | {e["src"] for e in g["edges"] if e["id"] in path_e} | {e["dst"] for e in g["edges"] if e["id"] in path_e}, path_e), []


def q_by_source(g, a):
    ns = [n for n in g["nodes"] if a.source in evidence_sources(n)]
    es = [e for e in g["edges"] if a.source in evidence_sources(e)]
    if not ns and not es:
        return subgraph(g, set(), set()), [f"no node/edge with source {a.source}"]
    return subgraph(g, {n["id"] for n in ns}, {e["id"] for e in es}), []


def q_cross_paper(g, a):
    ns = [n for n in g["nodes"] if len(evidence_sources(n)) >= 2]
    es = [e for e in g["edges"] if len(evidence_sources(e)) >= 2]
    return subgraph(g, {n["id"] for n in ns}, {e["id"] for e in es}), []


def q_compare(g, a):
    ni = {n["id"]: n for n in g["nodes"]}
    unres = [f"node {x} not in graph" for x in (a.a, a.b) if x not in ni]
    if unres:
        return None, unres
    ids = {a.a, a.b}
    es = [e for e in g["edges"] if (e["src"] in ids and e["dst"] in ids) or e["src"] in ids or e["dst"] in ids]
    sg = subgraph(g, ids, {e["id"] for e in es})
    # per-source evidence table
    table = {}
    for n in sg["nodes"]:
        for ev in n["evidence"]:
            table.setdefault(ev["source_id"], {}).setdefault(n["id"], []).append(ev["quote"][:160])
    sg["compare_table"] = table
    return sg, []


def q_conflicts(g, a):
    es = [e for e in g["edges"] if e["type"] in ("contradicts", "conflicts_with")]
    ns = [n for n in g["nodes"] if n["id"] in {x for e in es for x in (e["src"], e["dst"])}]
    unres = [] if es else ["no contradicts edge in graph"]
    return subgraph(g, {n["id"] for n in ns}, {e["id"] for e in es}), unres


def q_used_by(g, a):
    ni = {n["id"]: n for n in g["nodes"]}
    if a.node not in ni:
        return None, [f"node {a.node} not in graph"]
    es = [e for e in g["edges"] if e["dst"] == a.node and e["type"] in ("uses", "evaluated_on", "proposed_by", "measures", "part_of", "instance_of")]
    ns = [n for n in g["nodes"] if n["id"] == a.node or n["id"] in {e["src"] for e in es}]
    return subgraph(g, {n["id"] for n in ns}, {e["id"] for e in es}), []


def q_reports(g, a):
    ni = {n["id"]: n for n in g["nodes"]}
    if a.node not in ni:
        return None, [f"node {a.node} not in graph"]
    es = [e for e in g["edges"] if (e["src"] == a.node or e["dst"] == a.node) and e["type"] == "reports_value"]
    ids = {a.node} | {x for e in es for x in (e["src"], e["dst"])}
    sg = subgraph(g, ids, {e["id"] for e in es})
    sg["per_source_values"] = [
        {"source_id": s, "edge": e["id"], "metric": e.get("metric"), "value": e.get("value"), "conditions": e.get("conditions", "")}
        for e in es for s in evidence_sources(e)]
    return sg, [] if es else [f"no reports_value edge for {a.node}"]


def q_type(g, a):
    ns = [n for n in g["nodes"] if n["type"] == a.type]
    return subgraph(g, {n["id"] for n in ns}, set()), [] if ns else [f"no node of type {a.type}"]


Q = {"neighbors": q_neighbors, "path": q_path, "by_source": q_by_source, "cross_paper": q_cross_paper,
     "compare": q_compare, "conflicts": q_conflicts, "used_by": q_used_by, "reports": q_reports, "type": q_type}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--query", required=True, choices=sorted(Q))
    ap.add_argument("--out", required=True)
    ap.add_argument("--question", default="", help="natural-language question, copied to output")
    ap.add_argument("--unresolvable", default="", help="semicolon-separated extra unresolvable notes")
    ap.add_argument("--node"); ap.add_argument("--src"); ap.add_argument("--dst"); ap.add_argument("--source")
    ap.add_argument("--a"); ap.add_argument("--b"); ap.add_argument("--type"); ap.add_argument("--edge-type")
    ap.add_argument("--hops", type=int, default=1)
    a = ap.parse_args()
    g = load_graph(a.graph)
    sg, unres = Q[a.query](g, a)
    if sg is None:
        out = {"query": {"name": a.query, "args": vars(a)}, "question": a.question, "result": None,
               "evidence": [], "unresolvable": unres, "status": "unresolvable"}
        write_json(a.out, out)
        print(json.dumps({"status": "unresolvable", "unresolvable": unres}, ensure_ascii=False))
        return
    extra = [x.strip() for x in a.unresolvable.split(";") if x.strip()]
    r = result(g, sg["nodes"], sg["edges"], unres + extra)
    r.update({k: v for k, v in sg.items() if k not in ("nodes", "edges")})
    status = "ok" if not (unres) else "partial"
    out = {"query": {"name": a.query, "args": {k: v for k, v in vars(a).items() if k not in ("graph", "out", "unresolvable", "question") and v}},
           "question": a.question, "result": r, "evidence": r["evidence"], "unresolvable": r["unresolvable"], "status": status}
    write_json(a.out, out)
    print(json.dumps({"status": status, "nodes": len(sg["nodes"]), "edges": len(sg["edges"]),
                      "evidence_items": len(r["evidence"]), "unresolvable": r["unresolvable"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
