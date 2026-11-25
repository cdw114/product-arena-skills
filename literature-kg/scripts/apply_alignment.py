#!/usr/bin/env python3
"""Phase C3 step 2: apply alignment decisions to the graph.

Usage:
  python scripts/apply_alignment.py --graph graph.draft.json --alignment alignment.json \
         --out graph.aligned.json [--allow-conflict]

alignment.json:
  {"pairs": [{"a": "N:..", "b": "N:..", "decision": "merge|keep_separate|uncertain",
              "merge_basis": ["same_explicit_name", ...],   # required when decision == merge
              "conflict": "free text",                       # optional
              "evidence_a": {...}, "evidence_b": {...},      # optional, used in merge_conflicts
              "relation": "related_to|instance_of|contradicts"  # for keep_separate (optional)
             }]}

merge          → keep node `a` (first in pair), union aliases/evidence, set merged_from, first_seen = earliest
keep_separate  → no merge; optionally add `relation` edge (default related_to) with confidence low and
                 evidence from both nodes (copied, not retyped)
uncertain      → no merge, no edge; recorded only
Refuses a merge between two nodes that have conflicting `reports_value` edges unless --allow-conflict.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import load_graph, write_json, evidence_sources  # noqa: E402


def reports_values(g, nid):
    return [(e.get("metric"), e.get("value"), e.get("conditions")) for e in g["edges"]
            if e["type"] == "reports_value" and e["src"] == nid]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--alignment", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-conflict", action="store_true")
    a = ap.parse_args()
    g = load_graph(a.graph)
    al = json.load(open(a.alignment, encoding="utf-8"))
    pairs = al.get("pairs", al if isinstance(al, list) else [])

    nodes = {n["id"]: n for n in g["nodes"]}
    merged, kept, uncertain, conflicts = [], [], [], []

    for p in pairs:
        A, B = nodes.get(p["a"]), nodes.get(p["b"])
        if not A or not B:
            print(f"skip: unknown node in pair {p['a']} / {p['b']}", file=sys.stderr)
            continue
        if A is B:
            continue
        d = p.get("decision")
        if d == "merge":
            if not p.get("merge_basis"):
                sys.exit(f"REFUSED: merge of {A['id']} and {B['id']} has no merge_basis")
            va, vb = reports_values(g, A["id"]), reports_values(g, B["id"])
            if va and vb and va != vb and not a.allow_conflict:
                sys.exit(f"REFUSED: {A['id']} and {B['id']} have conflicting reports_value edges "
                         f"({va} vs {vb}). Use --allow-conflict only if the conflict is listed in merge_conflicts.")
            # union
            for al_ in B.get("aliases", []):
                if al_ not in A["aliases"]:
                    A["aliases"].append(al_)
            if B["canonical_name"] != A["canonical_name"] and B["canonical_name"] not in A["aliases"]:
                A["aliases"].append(B["canonical_name"])
            have = {(e["source_id"], e["paragraph_id"], e["quote"]) for e in A["evidence"]}
            for e in B["evidence"]:
                if (e["source_id"], e["paragraph_id"], e["quote"]) not in have:
                    A["evidence"].append(e)
            A["merged_from"] = sorted(set(A.get("merged_from", []) + [A["id"], B["id"]] + B.get("merged_from", [])))
            A["merge_basis"] = sorted(set(A.get("merge_basis", []) + list(p["merge_basis"])))
            A["sources"] = evidence_sources(A)
            A["first_seen"] = min(A["first_seen"], B["first_seen"])
            A.setdefault("merge_notes", []).append({"merged": B["id"], "basis": p["merge_basis"],
                                                    "conflict": p.get("conflict"), "at": "alignment"})
            # redirect edges
            for e in g["edges"]:
                if e["src"] == B["id"]:
                    e["src"] = A["id"]
                if e["dst"] == B["id"]:
                    e["dst"] = A["id"]
            g["nodes"] = [n for n in g["nodes"] if n is not B]
            nodes = {n["id"]: n for n in g["nodes"]}
            merged.append({"a": A["id"], "b": B["id"], "basis": p["merge_basis"], "conflict": p.get("conflict")})
            if p.get("conflict"):
                conflicts.append({"a": A["id"], "b": B["id"], "kind": p.get("conflict_kind", "value_conflict"),
                                  "description": p["conflict"], "evidence_a": p.get("evidence_a"),
                                  "evidence_b": p.get("evidence_b"), "resolution": "merged_with_conditions_recorded"})
        elif d == "keep_separate":
            rel = p.get("relation", "related_to")
            eid = f"E:{rel}:{A['id'].split(':', 1)[-1]}->{B['id'].split(':', 1)[-1]}"
            if eid not in {e["id"] for e in g["edges"]}:
                ev = []
                for e in A["evidence"][:1] + B["evidence"][:1]:
                    ev.append(dict(e))
                g["edges"].append({"id": eid, "type": rel, "src": A["id"], "dst": B["id"], "evidence": ev,
                                   "conditions": "", "confidence": "low", "evidence_strength": "indirect",
                                   "attribution": "alignment", "cross_paper": True,
                                   "note": p.get("conflict") or p.get("reason") or "kept separate by alignment decision"})
            kept.append({"a": A["id"], "b": B["id"], "reason": p.get("conflict") or p.get("reason"), "relation": rel})
            if p.get("conflict"):
                conflicts.append({"a": A["id"], "b": B["id"], "kind": p.get("conflict_kind", "different_object"),
                                  "description": p["conflict"], "evidence_a": p.get("evidence_a"),
                                  "evidence_b": p.get("evidence_b"), "resolution": "kept_separate"})
        else:
            uncertain.append({"a": A["id"], "b": B["id"], "reason": p.get("conflict") or p.get("reason")})

    # drop exact duplicate edges created by redirect
    seen, edges = set(), []
    for e in g["edges"]:
        k = (e["type"], e["src"], e["dst"], e.get("conditions"))
        if k in seen:
            continue
        seen.add(k)
        edges.append(e)
    g["edges"] = edges
    # keep evidence ids unique & mark cross_paper
    for e in g["edges"]:
        e["cross_paper"] = len(evidence_sources(e)) >= 2
    g["alignment_summary"] = {"merged": merged, "kept_separate": kept, "uncertain": uncertain, "conflicts": conflicts}
    write_json(a.out, g)
    print(json.dumps({"merged": len(merged), "kept_separate": len(kept), "uncertain": len(uncertain),
                      "conflicts": len(conflicts), "nodes": len(g["nodes"]), "edges": len(g["edges"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
