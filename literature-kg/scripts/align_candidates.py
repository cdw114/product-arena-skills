#!/usr/bin/env python3
"""Phase C3 step 1: propose cross-paper alignment candidates (deterministic, no LLM).

Usage:
  python scripts/align_candidates.py --graph graph.draft.json --out align_candidates.json [--min-jaccard 0.6]

Candidate signals:
  exact_alias        normalised alias/canonical match across two nodes from different sources
  containment       one name is a substring of the other (e.g. "RoBERTa" ⊂ "RoBERTa-large") → FLAG: may be different object
  jaccard           token Jaccard on canonical names >= threshold, same type
  same_type_token    same type + one shared distinctive token (len>=4) — weak, listed for completeness

Same-source pairs are never proposed. Each candidate lists the identity tests the LLM must
answer (T1..T4) and an initial hint (`class_instance_candidate` when the shared token is a
generic method/material term).
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import load_graph, norm, write_json  # noqa: E402

GENERIC_TERMS = {
    "cnn", "rnn", "lstm", "transformer", "bert", "gpt", "gnn", "svm", "random forest", "xgboost",
    "pla", "pva", "peg", "pet", "plga", "hydrogel", "serum", "plasma", "blood", "water", "saline",
    "_dataset", "corpus", "benchmark", "encoder", "decoder", "resnet", "vit", "mae", "mse", "rmse",
    "accuracy", "precision", "recall", "f1", "auc", "cross-validation", "k-fold",
}
STOP = {"the", "of", "a", "an", "and", "or", "in", "on", "for", "with", "by", "to", "via", "using", "based", "from", "at", "as"}


def toks(s):
    return {t for t in norm(s).split() if t not in STOP and len(t) > 1}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def names_of(n):
    return [n["canonical_name"]] + list(n.get("aliases", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-jaccard", type=float, default=0.6)
    a = ap.parse_args()
    g = load_graph(a.graph)

    def sources_of(n):
        return {e["source_id"] for e in n.get("evidence", [])}

    cands = []
    seen = set()

    def add(x, y, signal, hint, detail):
        key = (x["id"], y["id"], signal)
        if key in seen:
            return
        seen.add(key)
        cands.append({
            "a": x["id"], "b": y["id"], "type": x["type"], "signal": signal,
            "name_a": x["canonical_name"], "name_b": y["canonical_name"],
            "sources_a": sorted(sources_of(x)), "sources_b": sorted(sources_of(y)),
            "hint": hint, "detail": detail,
            "tests_to_answer": ["T1_same_real_world_object", "T2_conditions_samples_equivalent",
                                "T3_definitions_agree", "T4_value_conflict"],
        })

    for x, y in itertools.combinations(g["nodes"], 2):
        if sources_of(x) & sources_of(y):
            continue  # already co-sourced (already aligned or same paper)
        if x["type"] != y["type"]:
            continue
        nx = {norm(s) for s in names_of(x)}
        ny = {norm(s) for s in names_of(y)}
        # exact alias
        if nx & ny:
            add(x, y, "exact_alias", "likely_merge_if_T1_T2_pass", f"shared alias: {sorted(nx & ny)}")
            continue
        # containment
        for p, q in itertools.product(nx, ny):
            if len(p) >= 3 and len(q) >= 3 and (p in q or q in p):
                shared = p if len(p) <= len(q) else q
                generic = shared in GENERIC_TERMS or any(shared.startswith(gt) for gt in GENERIC_TERMS if gt.isalpha())
                add(x, y, "containment",
                    "FLAG_possible_different_object" if not generic else "FLAG_generic_term_class_instance_candidate",
                    f"'{shared}' is contained in both names" + (" (generic term)" if generic else ""))
                break
        # jaccard
        j = jaccard(toks(x["canonical_name"]), toks(y["canonical_name"]))
        if j >= a.min_jaccard:
            add(x, y, "jaccard", "check_T1", f"token jaccard={j:.2f}")
            continue
        # same type + shared distinctive token
        shared = toks(x["canonical_name"]) & toks(y["canonical_name"])
        distinctive = {t for t in shared if len(t) >= 4 and not t.startswith("_")}
        if distinctive:
            generic = {t for t in distinctive if t in GENERIC_TERMS}
            add(x, y, "same_type_token",
                "FLAG_generic_term_class_instance_candidate" if generic else "weak_check_T1",
                f"shared tokens: {sorted(distinctive)}" + (f" generic: {sorted(generic)}" if generic else ""))

    out = {"graph": a.graph, "n_candidates": len(cands), "candidates": cands,
           "note": "Candidates only. Decide each with the LLM using the quotes; not every alias must merge."}
    write_json(a.out, out)
    by = {}
    for c in cands:
        by[c["signal"]] = by.get(c["signal"], 0) + 1
    print(json.dumps({"n_candidates": len(cands), "by_signal": by}, ensure_ascii=False))
    for c in cands:
        print(f"  [{c['signal']:<15}] {c['name_a']!r}  <->  {c['name_b']!r}   ({c['hint']})")


if __name__ == "__main__":
    main()
