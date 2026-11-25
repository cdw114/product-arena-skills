#!/usr/bin/env python3
"""prepare.py — read the case, find the paper, extract the skeleton.

This is the step-0/step-1 helper so the agent does not have to guess where the
PDF is or what the case wants. It is tolerant: case.json schemas differ per
challenge, so it searches for the first PDF among the fields cases actually use.

Usage:
    python scripts/prepare.py [--case /input/case.json] [--work /app/work] [--pdf PAPER.pdf]

Writes WORK/case_summary.json (case id, questions, output fields, materials) and
runs the extractor on the chosen PDF, writing WORK/skeleton.json + sections.md.
Prints a short JSON report.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

PDF_MAGIC = b"%PDF"


def _walk_strings(obj, path=""):
    """Yield (json_path, value) for every string in a nested structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def find_case_file(explicit: str | None) -> str | None:
    if explicit and os.path.exists(explicit):
        return explicit
    for cand in ("/input/case.json", "input/case.json", "case.json"):
        if os.path.exists(cand):
            return cand
    return None


def find_task_file(case_path: str | None) -> str | None:
    for cand in ("/input/task.md", "input/task.md", "task.md"):
        if os.path.exists(cand):
            return cand
    if case_path:
        beside = os.path.join(os.path.dirname(case_path), "task.md")
        if os.path.exists(beside):
            return beside
    return None


def is_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == PDF_MAGIC
    except OSError:
        return False


def candidate_pdfs(case: dict | None, case_path: str | None) -> list[str]:
    """Every plausible PDF path mentioned by the case, most specific first."""
    out: list[str] = []
    bases = []
    if case_path:
        bases.append(os.path.dirname(os.path.abspath(case_path)))
    bases += [os.getcwd(), "/input", os.path.abspath(".")]
    if case:
        for jp, val in _walk_strings(case):
            if not val.lower().endswith(".pdf"):
                continue
            if os.path.isabs(val) and os.path.exists(val):
                out.append(val)
                continue
            for base in bases:
                p = os.path.normpath(os.path.join(base, val))
                if os.path.exists(p):
                    out.append(p)
                    break
    # also anything pdf-ish sitting in the input dir
    for base in bases:
        if not os.path.isdir(base):
            continue
        try:
            for fn in sorted(os.listdir(base)):
                if fn.lower().endswith(".pdf"):
                    p = os.path.join(base, fn)
                    if p not in out and os.path.isfile(p):
                        out.append(p)
        except OSError:
            pass
    # keep only real PDFs, dedup preserving order
    seen, real = set(), []
    for p in out:
        rp = os.path.abspath(p)
        if rp in seen or not is_pdf(rp):
            continue
        seen.add(rp)
        real.append(rp)
    return real


def questions_from(case: dict | None, task_md: str | None) -> list[dict]:
    """Extract questions the case states, without assuming one schema."""
    qs: list[dict] = []
    if case:
        for key in ("questions", "question", "queries", "tasks", "items"):
            v = case.get(key)
            if isinstance(v, list):
                for i, item in enumerate(v, 1):
                    if isinstance(item, str):
                        qs.append({"qid": f"Q{i}", "question": item})
                    elif isinstance(item, dict):
                        qs.append({"qid": item.get("qid") or item.get("id") or f"Q{i}",
                                   "question": item.get("question") or item.get("text") or item.get("prompt") or ""})
            elif isinstance(v, str):
                qs.append({"qid": "Q1", "question": v})
    if not qs and task_md:
        import re
        for m in re.finditer(r"^\s*(?:\d+[.、)]|[-*])?\s*(.+\?)\s*$", task_md, re.M):
            q = m.group(1).strip()
            if 10 <= len(q) <= 300:
                qs.append({"qid": f"Q{len(qs) + 1}", "question": q})
    return qs[:20]


def read_json(path: str):
    """JSON load tolerant of a UTF-8 BOM (files written by Windows tools)."""
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default=None)
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--pdf", default=None, help="override: use this PDF")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--force-ocr", action="store_true")
    a = ap.parse_args(argv)

    os.makedirs(a.work, exist_ok=True)
    case_path = find_case_file(a.case)
    case = read_json(case_path) if case_path else None
    task_path = find_task_file(case_path)
    task_md = open(task_path, encoding="utf-8").read() if task_path else None

    pdfs = [os.path.abspath(a.pdf)] if a.pdf else candidate_pdfs(case, case_path)
    anomalies = []
    if not pdfs:
        anomalies.append({"kind": "NO_PDF_FOUND",
                          "detail": "No PDF found in the case materials or the input directory."})
    summary = {
        "case_path": case_path,
        "case": case,
        "task_path": task_path,
        "task_excerpt": (task_md or "")[:2000] or None,
        "questions": questions_from(case, task_md),
        "pdf_candidates": pdfs,
        "chosen_pdf": pdfs[0] if pdfs else None,
        "anomalies": anomalies,
    }
    if len(pdfs) > 1:
        summary["note"] = (f"{len(pdfs)} PDFs found; using the first. If another is the main paper, "
                           f"rerun with --pdf. Supplementary material can be extracted separately "
                           f"into its own work dir.")
    # expected output fields, if the case names them
    if isinstance(case, dict):
        oc = case.get("output_contract") or {}
        if isinstance(oc, dict):
            summary["output_contract_fields"] = list((oc.get("fields") or oc.get("required") or []) if isinstance(oc.get("fields") or oc.get("required"), (list, dict)) else [])
        for k in ("output_fields", "required_fields", "expected_fields"):
            if isinstance(case.get(k), list):
                summary["output_contract_fields"] = case[k]
                break

    with open(os.path.join(a.work, "case_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    if not pdfs:
        print(json.dumps({"status": "refused", "reason": "no PDF found", "work": a.work,
                          "anomalies": anomalies}, ensure_ascii=False, indent=1))
        return 2

    cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_extract.py"),
           pdfs[0], a.work]
    if a.max_pages:
        cmd += ["--max-pages", str(a.max_pages)]
    if a.force_ocr:
        cmd += ["--force-ocr"]
    rc = subprocess.call(cmd)
    ext = os.path.join(a.work, "extract_report.json")
    rep = read_json(ext) if os.path.exists(ext) else {}
    print(json.dumps({"status": rep.get("status", "unknown"), "chosen_pdf": pdfs[0],
                      "work": a.work, "sections": rep.get("sections"),
                      "heading_method": rep.get("heading_method"),
                      "questions_found": len(summary["questions"]),
                      "output_contract_fields": summary.get("output_contract_fields"),
                      "anomalies": rep.get("anomalies", [])}, ensure_ascii=False, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
