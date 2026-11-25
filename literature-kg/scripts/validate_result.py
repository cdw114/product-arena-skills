#!/usr/bin/env python3
"""Validate result.json against the hard rules. Exit 0 = no errors (warnings allowed if explained).

Usage:
  python scripts/validate_result.py --result /app/output/result.json --paragraphs /app/work/paragraphs \
         [--manifest /input/corpus-manifest.json] [--case /input/case.json] [--min-queries 3]

Errors (exit 1)
  E01 output_contract key missing / case_id missing
  E02 evidence quote not an exact substring of the referenced paragraph
  E03 paragraph_id not found under the referenced source_id
  E04 node/edge without evidence (unless status placeholder)
  E05 source identity leak: node evidence all from source B but source_id field says A,
      or a node's `sources`/`first_seen` contradicts its evidence
  E06 dangling node/edge reference in queries[].result
  E07 merge decision without merge_basis
  E08 duplicate node/edge id
  E09 fabricated page number when the paragraph store has no page (page:1 labelled as PDF page)
Warnings (exit 0)
  W01 fewer than --min-queries executed queries
  W02 query without evidence
  W03 node with only cited/background evidence presented with confidence high
  W04 cross-paper node whose evidence is from one paper only
  W05 merged node still carrying two definitions/values in `definition`
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import read_json, load_paragraphs, quote_in_text, evidence_sources  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--paragraphs", required=True)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--case", default=None)
    ap.add_argument("--min-queries", type=int, default=3)
    a = ap.parse_args()
    R = read_json(a.result)
    paras = load_paragraphs(a.paragraphs)
    errors, warns = [], []
    E = errors.append; W = warns.append

    # E01 contract
    contract_keys = (R.get("_meta") or {}).get("output_contract_keys") or []
    if a.case:
        c = read_json(a.case)
        ck = c.get("output_contract") or []
        contract_keys = list(ck.keys()) if isinstance(ck, dict) else list(ck)
        cid = c.get("case_id") or c.get("id")
        if cid and R.get("case_id") != cid:
            E(f"E01 case_id mismatch: result={R.get('case_id')} case={cid}")
    for k in contract_keys:
        if k not in R:
            E(f"E01 output_contract key missing: {k}")
    if not R.get("case_id"):
        E("E01 case_id missing")
    if not R.get("status"):
        E("E01 status missing")
    for k in ("sources", "nodes", "edges", "queries", "uncertainties", "merge_conflicts", "change_log", "unreported"):
        if k not in R:
            E(f"E01 required field missing: {k}")

    src_ids = {s.get("source_id") for s in R.get("sources", [])}
    doiset = {s.get("doi") for s in R.get("sources", []) if s.get("doi")}
    all_src = src_ids | doiset

    def check_evidence(ev_list, where, owner_src=None):
        if not ev_list:
            E(f"E04 {where} has no evidence")
            return
        for e in ev_list:
            sid, pid = e.get("source_id"), e.get("paragraph_id")
            if not sid or not pid:
                E(f"E03 {where}: evidence without source_id/paragraph_id: {e}")
                continue
            p = paras.get((sid, pid))
            if p is None:
                E(f"E03 {where}: paragraph {sid}/{pid} not found in store")
                continue
            if not e.get("quote") or not quote_in_text(e["quote"], p["text"]):
                E(f"E02 {where}: quote not in {sid}/{pid}: {str(e.get('quote'))[:90]!r}")
            if p.get("page") is None and isinstance(e.get("page"), int):
                E(f"E09 {where}: evidence claims page {e['page']} but the paragraph store has no page (do not invent PDF pages)")

    ids = [n["id"] for n in R.get("nodes", [])]
    if len(ids) != len(set(ids)):
        E("E08 duplicate node ids")
    for n in R.get("nodes", []):
        check_evidence(n.get("evidence", []), f"node {n['id']}")
        evs = evidence_sources(n)
        if evs and n.get("sources") and set(n["sources"]) != set(evs):
            E(f"E05 node {n['id']}: sources {n['sources']} != evidence sources {evs}")
        if n.get("first_seen") and n["first_seen"] not in evs and n.get("first_seen") not in all_src:
            E(f"E05 node {n['id']}: first_seen {n['first_seen']} is not a known source")
        if n.get("first_seen") and evs and n["first_seen"] not in evs:
            E(f"E05 node {n['id']}: first_seen {n['first_seen']} not among its evidence sources {evs}")
        if len(evs) >= 2 and not n.get("merge_basis") and not n.get("merged_from"):
            W(f"W05 node {n['id']} has evidence from {evs} but no merge_basis/merged_from record")
        if n.get("attribution") in ("cited", "background") and n.get("confidence") == "high":
            W(f"W03 node {n['id']} rests on {n['attribution']} evidence but has confidence high")
        if n.get("sources") and len(n["sources"]) >= 2 and len(evs) < 2:
            E(f"E05 node {n['id']}: claims cross-paper sources {n['sources']} but evidence only from {evs}")
    eids = [e["id"] for e in R.get("edges", [])]
    if len(eids) != len(set(eids)):
        E("E08 duplicate edge ids")
    nset = set(ids)
    for e in R.get("edges", []):
        if e["src"] not in nset or e["dst"] not in nset:
            E(f"E06 edge {e['id']} references unknown node(s)")
        check_evidence(e.get("evidence", []), f"edge {e['id']}")
        if e.get("cross_paper") and len(evidence_sources(e)) < 2:
            W(f"W04 edge {e['id']} flagged cross_paper but evidence from one source")

    # E07 merge basis
    for p in R.get("cross_paper_alignment", {}).get("pairs", []):
        if p.get("decision") == "merge" and not p.get("merge_basis"):
            E(f"E07 merge {p.get('a')}/{p.get('b')} without merge_basis")

    # E06 queries
    qs = R.get("queries", [])
    executed = [q for q in qs if q.get("result") is not None]
    if len(executed) < a.min_queries:
        W(f"W01 only {len(executed)} executed queries (minimum {a.min_queries})")
    for q in qs:
        r = q.get("result") or {}
        for nid in r.get("nodes", []) or []:
            if nid not in nset:
                E(f"E06 query {q.get('id')} references unknown node {nid}")
        for eid in r.get("edges", []) or []:
            if eid not in set(eids):
                E(f"E06 query {q.get('id')} references unknown edge {eid}")
        if r and not q.get("evidence"):
            W(f"W02 query {q.get('id')} has no evidence")
        if r and not q.get("unresolvable") and q.get("status") == "ok":
            pass

    # sources vs manifest
    if a.manifest and Path(a.manifest).exists():
        m = read_json(a.manifest)
        recs = m if isinstance(m, list) else next((m[k] for k in ("papers", "items", "documents", "sources") if isinstance(m.get(k), list)), [])
        for r in recs:
            doi = r.get("doi")
            if doi and doi not in all_src:
                W(f"manifest DOI {doi} not present in result.sources")

    print(f"validate_result: {len(errors)} error(s), {len(warns)} warning(s)")
    for x in errors:
        print("  ERROR", x)
    for x in warns:
        print("  WARN ", x)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
