#!/usr/bin/env python3
"""
papertrans.cli — single entry point for the whole workflow.

  python -m papertrans.cli run  INPUT.pdf --out OUT_DIR [--lang zh] [--max-pages N] [--case case.json]
      Phase 1 only: parse → segment → glossary candidates → (optional reviewed glossary) → batches
  python -m papertrans.cli verify OUT_DIR   (after translations.json exists)
  python -m papertrans.cli assemble OUT_DIR
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import assemble as A
from . import glossary as G
from . import parse as P
from . import segment as S
from . import translate as T
from . import verify as V


def phase_prepare(pdf: Path, out: Path, lang: str = "zh", max_pages: int | None = None, case: Path | None = None,
                  budget_tokens: int = 3000, glossary_top: int = 40, reviewed: Path | None = None,
                  include_references: bool = False, ocr_dir: Path | None = None) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    doc = P.parse_pdf(pdf, max_pages=max_pages, ocr_dir=ocr_dir)
    (out / "doc.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    seg = S.segment_document(doc, include_references=include_references)
    seg["batches"] = S.make_batches(seg["segments"], budget_tokens)
    (out / "segments.json").write_text(json.dumps(seg, ensure_ascii=False, indent=1), encoding="utf-8")
    cands = G.extract_candidates(seg["segments"], glossary_top)
    gl = G.build_glossary(cands)
    (out / "glossary_candidates.json").write_text(json.dumps(gl, ensure_ascii=False, indent=1), encoding="utf-8")
    # glossary to enforce: reviewed file wins; else the proposed one (no approved terms → no TERM masks)
    gl_notes: list[str] = []
    if reviewed and not Path(reviewed).exists():
        gl_notes.append(f"reviewed glossary not found: {reviewed} — using candidates (no locked terms)")
    gl_used = G.load_glossary(reviewed) if reviewed and Path(reviewed).exists() else gl
    errs = G.validate_glossary(gl_used)
    if not G.active_terms(gl_used):
        gl_notes.append("no approved/keep terms in glossary — term locking is OFF for this run (translate still protects NUM/CITE/REF/MATH)")
    info = G.apply_glossary(seg["segments"], gl_used)
    seg["glossary_hits"] = info["hits_per_segment"]
    (out / "segments.json").write_text(json.dumps(seg, ensure_ascii=False, indent=1), encoding="utf-8")
    tb = T.build_batches(seg, gl_used, out / "batches", lang)
    # per-batch request skeleton for the agent to fill
    for b in seg["batches"]:
        req = {"batch_id": b["id"], "input": f"batches/{b['id']}.json", "output": "translations.json",
               "segment_ids": b["segment_ids"], "status": "pending"}
        (out / "batches" / f"{b['id']}.status.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    plan = {
        "source": str(pdf), "out_dir": str(out), "lang": lang, "n_pages": doc["n_pages"], "parser": doc["backend"],
        "warnings": doc["warnings"], "title": doc.get("title"), "ocr_pages": doc.get("ocr_pages", []),
        "n_segments": seg["n_segments"], "role_counts": seg["role_counts"], "n_batches": len(seg["batches"]),
        "n_placeholders": tb["total_placeholders"], "glossary_candidates": len(gl), "glossary_active": len(info["terms"]),
        "glossary_errors": errs, "excluded_blocks": len(seg["excluded_blocks"]),
        "glossary_notes": gl_notes,
        "request_budget_estimate": 1 + 2 * len(seg["batches"]) + 1,
        "elapsed_s": round(time.time() - t0, 2),
    }
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return plan


def phase_verify(out: Path, lang: str, translations: Path | None = None) -> dict:
    seg = json.loads((out / "segments.json").read_text(encoding="utf-8-sig"))
    tr_path = translations or (out / "translations.json")
    tr = json.loads(tr_path.read_text(encoding="utf-8-sig"))
    if isinstance(tr, dict) and "translations" in tr and isinstance(tr["translations"], dict):
        tr = tr["translations"]
    marks = json.loads((out / "batches" / "marks.json").read_text(encoding="utf-8-sig"))
    reviewed = out / "glossary_reviewed.json"
    gl = G.load_glossary(reviewed if reviewed.exists() else out / "glossary_candidates.json")
    res = V.verify(seg["segments"], tr, marks, gl, lang)
    (out / "verify.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res["summary"]


def phase_assemble(out: Path, lang: str, case: Path | None = None) -> dict:
    seg = json.loads((out / "segments.json").read_text(encoding="utf-8-sig"))
    tr = json.loads((out / "translations.json").read_text(encoding="utf-8-sig"))
    if isinstance(tr, dict) and "translations" in tr and isinstance(tr["translations"], dict):
        tr = tr["translations"]
    ver = json.loads((out / "verify.json").read_text(encoding="utf-8-sig"))
    marks = json.loads((out / "batches" / "marks.json").read_text(encoding="utf-8-sig"))
    reviewed = out / "glossary_reviewed.json"
    gl = G.load_glossary(reviewed if reviewed.exists() else out / "glossary_candidates.json")
    doc = json.loads((out / "doc.json").read_text(encoding="utf-8-sig"))
    case_d = json.loads(Path(case).read_text(encoding="utf-8-sig")) if case and Path(case).exists() else {}
    res = A.assemble(seg, tr, ver, marks, gl, doc, out, case_d, lang, A.references_markdown(seg.get("excluded_blocks", [])))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="papertrans.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("prepare", help="parse → segment → glossary → batches")
    r.add_argument("pdf")
    r.add_argument("--out", required=True)
    r.add_argument("--lang", default="zh")
    r.add_argument("--max-pages", type=int, default=None)
    r.add_argument("--case", default=None)
    r.add_argument("--budget-tokens", type=int, default=3000)
    r.add_argument("--glossary-top", type=int, default=40)
    r.add_argument("--reviewed", default=None, help="reviewed glossary json to enforce")
    r.add_argument("--include-references", action="store_true")
    r.add_argument("--ocr-dir", default=None, help="dir with P{n}.txt OCR text for text-less pages")
    v = sub.add_parser("verify", help="run deterministic checks on translations.json")
    v.add_argument("out")
    v.add_argument("--lang", default="zh")
    v.add_argument("--translations", default=None)
    a = sub.add_parser("assemble", help="back-fill terms and write bilingual.md / result.json")
    a.add_argument("out")
    a.add_argument("--lang", default="zh")
    a.add_argument("--case", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        plan = phase_prepare(Path(args.pdf), Path(args.out), args.lang, args.max_pages,
                             Path(args.case) if args.case else None, args.budget_tokens, args.glossary_top,
                             Path(args.reviewed) if args.reviewed else None, args.include_references,
                             Path(args.ocr_dir) if args.ocr_dir else None)
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "verify":
        s = phase_verify(Path(args.out), args.lang, Path(args.translations) if args.translations else None)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        return 0 if s["verdicts"]["fail"] == 0 else 2
    if args.cmd == "assemble":
        res = phase_assemble(Path(args.out), args.lang, Path(args.case) if args.case else None)
        print(json.dumps({"status": res["status"], "summary": res["summary"]}, ensure_ascii=False, indent=1))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
