#!/usr/bin/env python3
"""Phase D: assemble /app/output/result.json from the work files.

Usage:
  python scripts/assemble_result.py --work /app/work --case-id ID --out /app/output/result.json \
         [--status success|partial|not_determinable|refused] [--status-reason "..."]
         [--queries queries/*.json ...] [--incremental incremental.json] [--scope scope.json]

Reads from <work>: graph.aligned.json (fallback graph.draft.json), sources.json, contract.json,
alignment summary (inside graph), queries/*.json, scope.json, incremental.json,
unreported.txt / uncertainties.json (optional, free-form lists written by the agent).

Every output_contract key from case.json is guaranteed present (filled with null + a note when missing),
so the result never fails on a missing field.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import read_json, write_json, evidence_sources  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=os.environ.get("KG_WORK", "/app/work"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--status", default="partial")
    ap.add_argument("--status-reason", default="")
    ap.add_argument("--queries", nargs="*", default=None, help="query json files (default: <work>/queries/*.json)")
    ap.add_argument("--incremental", default=None)
    ap.add_argument("--scope", default=None)
    a = ap.parse_args()
    W = Path(a.work)

    def load(p, default=None):
        p = Path(p)
        return read_json(p) if p.exists() else default

    graph = load(W / "graph.aligned.json") or load(W / "graph.draft.json") or {"nodes": [], "edges": []}
    sources = load(W / "sources.json", [])
    contract = load(W / "contract.json", {})
    inv = load(W / "input_inventory.json", {})
    scope = load(a.scope or W / "scope.json", {"focus": [], "out_of_scope": [], "assumptions": []})
    change_log = load(W / "change_log.json", [])
    unreported = load(W / "unreported.json", [])
    uncertainties_extra = load(W / "uncertainties.json", [])

    # queries
    qfiles = a.queries
    if qfiles is None:
        qfiles = sorted(glob.glob(str(W / "queries" / "*.json")))
    queries = []
    for i, qf in enumerate(qfiles, 1):
        q = load(qf)
        if not q:
            continue
        q.setdefault("id", f"Q{i}")
        queries.append(q)

    # alignment summary lives inside the aligned graph
    alsum = graph.get("alignment_summary", {"merged": [], "kept_separate": [], "uncertain": [], "conflicts": []})
    pairs = []
    for m in alsum["merged"]:
        pairs.append({"a": m["a"], "b": m["b"], "decision": "merge", "merge_basis": m["basis"], "conflict": m.get("conflict")})
    for k in alsum["kept_separate"]:
        pairs.append({"a": k["a"], "b": k["b"], "decision": "keep_separate", "reason": k.get("reason"), "relation": k.get("relation")})
    for u in alsum["uncertain"]:
        pairs.append({"a": u["a"], "b": u["b"], "decision": "uncertain", "reason": u.get("reason")})

    # merge_conflicts: from alignment + contradicts edges
    merge_conflicts = list(alsum["conflicts"])
    for e in graph["edges"]:
        if e["type"] in ("contradicts", "conflicts_with"):
            merge_conflicts.append({"a": e["src"], "b": e["dst"], "kind": "value_conflict", "description": e.get("conditions") or e.get("note") or "contradicts edge",
                                    "evidence_a": next((x for x in e["evidence"] if x["source_id"] == evidence_sources(e)[0] if evidence_sources(e)), None),
                                    "evidence_b": next((x for x in e["evidence"][1:]), None), "resolution": "both_values_kept"})

    # uncertainties from graph (low confidence nodes, cited-only nodes)
    unc = list(uncertainties_extra)
    for n in graph["nodes"]:
        if n.get("confidence") == "low" or n.get("attribution") in ("cited", "background"):
            ev = n["evidence"][0] if n.get("evidence") else {}
            unc.append({"item": n["id"], "reason": "third_party_report" if n.get("attribution") in ("cited", "background") else "low_confidence_extraction",
                        "location": {"source_id": ev.get("source_id"), "paragraph_id": ev.get("paragraph_id")},
                        "statement": f"node '{n['canonical_name']}' rests on {n.get('attribution')} evidence; treat as reported, not measured"})
    for e in graph["edges"]:
        if e.get("confidence") == "low" or e.get("evidence_strength") in ("indirect", "cooccurrence_only"):
            unc.append({"item": e["id"], "reason": "indirect_evidence",
                        "statement": f"edge {e['type']} ({e['src']} -> {e['dst']}) has evidence_strength={e.get('evidence_strength')}"})
    for w in inv.get("warnings", []):
        unc.append({"item": "input", "reason": "input_warning", "statement": w})

    stats = {
        "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
        "cross_paper_nodes": sum(1 for n in graph["nodes"] if len(evidence_sources(n)) >= 2),
        "cross_paper_edges": sum(1 for e in graph["edges"] if len(evidence_sources(e)) >= 2),
        "queries": len(queries), "merged": len(alsum["merged"]), "kept_separate": len(alsum["kept_separate"]),
        "uncertain_pairs": len(alsum["uncertain"]),
        "nodes_by_type": {}, "edges_by_type": {},
    }
    for n in graph["nodes"]:
        stats["nodes_by_type"][n["type"]] = stats["nodes_by_type"].get(n["type"], 0) + 1
    for e in graph["edges"]:
        stats["edges_by_type"][e["type"]] = stats["edges_by_type"].get(e["type"], 0) + 1

    result = {
        "case_id": a.case_id or contract.get("case_id") or "unknown",
        "status": a.status,
        "status_reason": a.status_reason or ("graph built from the provided corpus; see stats and uncertainties" if a.status != "partial" else "partial: see uncertainties and unreported"),
        "scope": scope,
        "sources": sources,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "cross_paper_alignment": {"pairs": pairs, "merged": [m["a"] for m in alsum["merged"]],
                                  "kept_separate": [k["a"] for k in alsum["kept_separate"]],
                                  "uncertain": [u["a"] for u in alsum["uncertain"]]},
        "queries": queries,
        "incremental_update": load(a.incremental or W / "incremental.json"),
        "merge_conflicts": merge_conflicts,
        "uncertainties": unc,
        "unreported": unreported,
        "change_log": change_log,
        "environment": {"python": platform.python_version(), "scripts": sorted(os.listdir(Path(__file__).resolve().parent)),
                        "graph_format": "json", "work_dir": str(W)},
        "stats": stats,
    }

    # guarantee every output_contract key
    contract_keys = contract.get("output_contract") or []
    if isinstance(contract_keys, dict):
        contract_keys = list(contract_keys.keys())
    missing = [k for k in contract_keys if k not in result]
    for k in missing:
        result[k] = None
        result.setdefault("uncertainties", []).append({"item": k, "reason": "contract_field_unfilled", "statement": f"output_contract field '{k}' not produced by the standard pipeline; left null"})
    result["_meta"] = {"output_contract_keys": contract_keys, "contract_keys_added_null": missing,
                       "assembled_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

    write_json(a.out, result)
    print(json.dumps({"written": str(a.out), "case_id": result["case_id"], "status": result["status"], **stats,
                      "contract_keys_added_null": missing}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
