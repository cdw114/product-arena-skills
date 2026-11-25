#!/usr/bin/env python3
"""selftest.py — offline self-test for the paper-structured-notes scripts.

Runs without a network, without a real paper, and (for the validate stage)
without PyMuPDF. It builds a tiny synthetic skeleton, feeds a draft with known
good and known bad anchors, and asserts the validator's verdicts.

Usage:
    python scripts/selftest.py [OUT_DIR]     # default: ./_selftest
Exit code 0 = all checks passed, 1 = a check failed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def make_skeleton() -> dict:
    """A minimal two-section skeleton shaped exactly like pdf_extract output."""
    blocks = [
        {"bid": "p1:b0", "page": 1, "idx": 0, "kind": "heading", "text": "1 Introduction",
         "bbox": [], "font_size": 12.0, "font": "X", "bold": True, "section_path": [], "column": 0},
        {"bid": "p1:b1", "page": 1, "idx": 1, "kind": "paragraph",
         "text": "Most sequence models rely on recurrence, which prevents parallel training within a sequence.",
         "bbox": [], "font_size": 10.0, "font": "X", "bold": False, "section_path": ["1"], "column": 0},
        {"bid": "p1:b2", "page": 1, "idx": 2, "kind": "paragraph",
         "text": "We propose a network architecture based solely on attention mechanisms.",
         "bbox": [], "font_size": 10.0, "font": "X", "bold": False, "section_path": ["1"], "column": 0},
        {"bid": "p2:b0", "page": 2, "idx": 0, "kind": "heading", "text": "2 Method",
         "bbox": [], "font_size": 12.0, "font": "X", "bold": True, "section_path": [], "column": 0},
        {"bid": "p2:b1", "page": 2, "idx": 1, "kind": "paragraph",
         "text": "Attention is computed as a softmax over scaled dot products of queries and keys.",
         "bbox": [], "font_size": 10.0, "font": "X", "bold": False, "section_path": ["2"], "column": 0},
        {"bid": "p2:b2", "page": 2, "idx": 2, "kind": "caption",
         "text": "Figure 1: The overall architecture.", "bbox": [], "font_size": 8.5,
         "font": "X", "bold": False, "section_path": ["2"], "column": 0},
    ]
    sections = [
        {"sid": "s0", "number": "", "title": "Preamble", "level": 0, "anchor": "p1:b0",
         "page_start": 1, "page_end": 1, "block_ids": ["p1:b0"], "parent": ""},
        {"sid": "s1", "number": "1", "title": "Introduction", "level": 1, "anchor": "p1:b0",
         "page_start": 1, "page_end": 1, "block_ids": ["p1:b0", "p1:b1", "p1:b2"], "parent": "s0"},
        {"sid": "s2", "number": "2", "title": "Method", "level": 1, "anchor": "p2:b0",
         "page_start": 2, "page_end": 2, "block_ids": ["p2:b0", "p2:b1", "p2:b2"], "parent": "s0"},
    ]
    return {
        "source": "synthetic-selftest.pdf",
        "metadata": {},
        "pages": 2,
        "body_font_size": 10.0,
        "heading_method": "synthetic",
        "sections": sections,
        "section_stats": [{"sid": s["sid"], "title": s["title"], "chars": 100, "blocks": 2,
                           "pages": [s["page_start"], s["page_end"]], "equations": False,
                           "images_nearby": False} for s in sections],
        "blocks": blocks,
        "figures": [{"fid": "F1", "kind": "figure", "number": "1",
                     "caption": "Figure 1: The overall architecture.", "anchor": "p2:b2", "page": 2}],
        "page_meta": {},
    }


GOOD_CARD = {
    "research_question": {"value": "Whether attention alone suffices without recurrence.",
                          "source": "reported",
                          "evidence": [{"anchor": "p1:b1", "quote": "Most sequence models rely on recurrence"}]},
    "data": {"value": None, "source": "not_reported"},
    "method": {"value": "Attention over scaled dot products.",
               "source": "reported",
               "evidence": [{"anchor": "p2:b1", "quote": "softmax over scaled dot products"}]},
    "main_findings": {"value": "Architecture needs no recurrence.",
                      "source": "reported",
                      "evidence": [{"anchor": "p1:b2", "quote": "based solely on attention mechanisms"}]},
    "conclusion": {"value": "Attention is sufficient.", "source": "reported",
                   "evidence": [{"anchor": "p1:b2", "quote": "based solely on attention mechanisms"}]},
    "limitations": {"value": None, "source": "not_reported"},
    "scope_conditions": {"value": "Sequence transduction setting.", "source": "uncertain",
                         "evidence": [{"anchor": "p1:b1", "quote": "within a sequence"}]},
    "open_questions": {"value": None, "source": "not_reported"},
}


def run_validate(tmp: str, draft: dict) -> tuple[int, dict]:
    sk = os.path.join(tmp, "skeleton.json")
    dp = os.path.join(tmp, "notes_draft.json")
    out = os.path.join(tmp, "out")
    json.dump(make_skeleton(), open(sk, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(draft, open(dp, "w", encoding="utf-8"), ensure_ascii=False)
    p = subprocess.run([sys.executable, os.path.join(HERE, "build_notes.py"),
                        "--skeleton", sk, "--draft", dp, "--out", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        txt = (p.stdout or "").strip()
        start = txt.find("{")
        summary = json.loads(txt[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        summary = {"_raw": (p.stdout or "")[-500:], "_err": (p.stderr or "")[-500:]}
    return p.returncode, summary


def main(argv: list[str] | None = None) -> int:
    out_dir = (argv or sys.argv[1:] or ["_selftest"])[0]
    checks: list[tuple[str, bool, str]] = []
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(os.path.abspath(out_dir), "_tmp")
    os.makedirs(tmp, exist_ok=True)

    # ---- 1. healthy draft verifies
    draft = {
        "run_status": {"status": "success"},
        "paper_card": GOOD_CARD,
        "sections": [
            {"sid": "s1", "purpose": "Motivate dropping recurrence.",
             "conclusion": "Recurrence blocks parallelism.", "link_to_previous": "opening section",
             "evidence": [{"anchor": "p1:b1", "quote": "prevents parallel training"}]},
            {"sid": "s2", "purpose": "Define attention.",
             "evidence": [{"anchor": "p2:b1", "quote": "softmax over scaled dot products"},
                          {"anchor": "F1", "quote": None}]},
        ],
        "knowledge_points": [
            {"id": "KP-001", "term": "Self-attention", "aliases": ["intra-attention"], "type": "concept",
             "statement": "Attention within one sequence.", "evidence": [{"anchor": "p1:b2", "quote": "solely on attention"}]},
            {"id": "KP-002", "term": "Scaled dot-product attention", "type": "method",
             "statement": "Softmax over scaled dot products.", "evidence": [{"anchor": "p2:b1", "quote": "scaled dot products"}]},
        ],
        "answers": [{"qid": "Q1", "question": "What replaces recurrence?",
                     "answer": "Attention.", "evidence": [{"anchor": "p1:b2", "quote": "attention mechanisms"}]}],
        "change_log": ["selftest"],
    }
    rc, s = run_validate(tmp, draft)
    checks.append(("healthy draft -> success", s.get("status") == "success", f"status={s.get('status')} problems={s.get('problems')}"))
    checks.append(("healthy draft no failed anchors", s.get("anchors_failed") == 0, f"failed={s.get('anchors_failed')} {s.get('failures')}"))
    checks.append(("healthy draft full section coverage", s.get("coverage", {}).get("body_sections_covered") == 2, str(s.get("coverage", {}).get("body_sections_covered"))))
    checks.append(("healthy draft card complete", s.get("coverage", {}).get("card_fields_filled", 0) + 3 == 8 or s.get("coverage", {}).get("card_fields_filled") == 8, f"filled={s.get('coverage', {}).get('card_fields_filled')}"))

    # ---- 2. a wrong quote is caught
    bad = json.loads(json.dumps(draft))
    bad["sections"][0]["evidence"] = [{"anchor": "p1:b1", "quote": "this sentence is nowhere in the paper"}]
    rc2, s2 = run_validate(tmp, bad)
    checks.append(("wrong quote detected", s2.get("anchors_failed") == 1, f"failed={s2.get('anchors_failed')}"))
    checks.append(("wrong quote downgrades to partial", s2.get("status") == "partial", f"status={s2.get('status')}"))

    # ---- 3. out-of-range page is caught
    bad3 = json.loads(json.dumps(draft))
    bad3["sections"][0]["evidence"] = [{"anchor": "p99:b1", "quote": "anything"}]
    rc3, s3 = run_validate(tmp, bad3)
    checks.append(("out-of-range page detected", s3.get("anchors_failed") == 1, f"failed={s3.get('anchors_failed')}"))

    # ---- 4. duplicate knowledge point terms are flagged
    bad4 = json.loads(json.dumps(draft))
    bad4["knowledge_points"].append({"id": "KP-003", "term": "self-attention", "type": "concept",
                                     "statement": "dup", "evidence": [{"anchor": "p1:b2", "quote": "attention"}]})
    rc4, s4 = run_validate(tmp, bad4)
    checks.append(("duplicate kp term flagged", bool(s4.get("dup_kp_terms")), str(s4.get("dup_kp_terms"))))

    # ---- 5. a refusal is honoured and still emits result.json
    ref = {"run_status": {"status": "refused", "reason": "PDF is a scan and OCR is unavailable"}}
    rc5, s5 = run_validate(tmp, ref)
    out_result = os.path.join(tmp, "out", "result.json")
    emitted = os.path.exists(out_result)
    checks.append(("refusal exits 2", rc5 == 2, f"rc={rc5}"))
    checks.append(("refusal still writes result.json", emitted, f"exists={emitted}"))
    if emitted:
        rj = json.load(open(out_result, encoding="utf-8"))
        checks.append(("refusal reason recorded", (rj.get("run_status", {}).get("reason") or "").startswith("PDF is a scan"), str(rj.get("run_status", {}).get("reason"))[:60]))

    # ---- 6. coverage gap is reported, not hidden
    part = json.loads(json.dumps(draft))
    part["sections"] = part["sections"][:1]
    rc6, s6 = run_validate(tmp, part)
    checks.append(("missing section reported", "s2" in (s6.get("coverage", {}).get("sections_missing") or []), str(s6.get("coverage", {}).get("sections_missing"))))

    # ---- report
    os.makedirs(out_dir, exist_ok=True)
    lines = []
    ok = 0
    for name, passed, detail in checks:
        ok += bool(passed)
        lines.append(f"[{'PASS' if passed else 'FAIL'}] {name}" + ("" if passed else f"  ({detail})"))
    report = {"passed": ok, "total": len(checks), "checks": [{"name": n, "passed": bool(p), "detail": d} for n, p, d in checks]}
    with open(os.path.join(out_dir, "selftest_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n".join(lines))
    print(f"\n{ok}/{len(checks)} checks passed")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
