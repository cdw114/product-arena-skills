#!/usr/bin/env python3
"""audit.py — post-run audit of an output directory written by build_notes.py.

This is what `run.sh check` / `run.py check` runs. It reads result.json and
validation.json and reports whether the deliverable is trustworthy: required
files present, run status consistent with the checks, anchors verified, coverage
complete, no unrecorded placeholders.

Usage:
    python scripts/audit.py OUT_DIR
Exit code 0 = no blocking problems, 1 = blocking problems found.
"""
from __future__ import annotations

import json
import os
import sys

REQUIRED_CARD = {
    "research_question", "data", "method", "main_findings",
    "conclusion", "limitations", "scope_conditions", "open_questions",
}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 2
    out = argv[0]
    problems: list[str] = []
    warnings: list[str] = []

    rp = os.path.join(out, "result.json")
    if not os.path.exists(rp):
        print(f"FAIL missing {rp}")
        return 1
    r = json.load(open(rp, encoding="utf-8-sig"))

    # ---- required top-level blocks
    for key in ("case_id", "run_status", "result", "evidence", "uncertainty", "change_log"):
        if key not in r:
            problems.append(f"result.json missing top-level key '{key}'")
    st = (r.get("run_status") or {}).get("status")
    if st not in ("success", "partial", "cannot_determine", "refused"):
        problems.append(f"run_status.status is {st!r}, not one of the four allowed values")
    if st and st != "success" and not (r.get("run_status") or {}).get("reason"):
        problems.append(f"status {st!r} without a reason")

    # ---- refusal: nothing else to check
    if st == "refused":
        print(f"OK refused with reason: {(r.get('run_status') or {}).get('reason')}")
        print("(refusal is a valid deliverable; no notes expected)")
        return 0

    res = r.get("result") or {}
    ev = r.get("evidence") or {}
    ver = ev.get("verification") or {}
    cov = ev.get("coverage") or {}

    # ---- anchors
    failed = ver.get("anchors_failed", 0)
    checked = ver.get("anchors_checked", 0)
    if checked == 0:
        problems.append("no anchors were checked — notes are unverifiable")
    if failed:
        problems.append(f"{failed} anchor/quote verification failures")
        for f in (ver.get("failures") or [])[:5]:
            problems.append(f"  - {f.get('where')} {f.get('anchor')}: {', '.join(f.get('issues') or [])}")
    coarse = ver.get("anchors_coarse", 0)
    if checked and coarse / max(checked, 1) > 0.5:
        warnings.append(f"{coarse}/{checked} anchors are page/section-level only (coarse)")

    # ---- status must match the audit
    if st == "success" and failed:
        problems.append("status 'success' contradicts failed anchors — should be 'partial'")

    # ---- coverage
    total = cov.get("body_sections_total", 0)
    covered = cov.get("body_sections_covered", 0)
    if total and covered < total:
        warnings.append(f"{total - covered} of {total} body sections have no note: {cov.get('sections_missing')}")
    if cov.get("unknown_section_ids"):
        problems.append(f"section ids not in the skeleton: {cov.get('unknown_section_ids')}")

    # ---- paper card completeness
    card = {c.get("field") for c in (res.get("paper_card") or []) if c.get("status") == "filled"}
    missing_card = REQUIRED_CARD - card
    if missing_card:
        problems.append(f"paper card fields absent entirely (not even not_reported): {sorted(missing_card)}")
    nr = [c.get("field") for c in (res.get("paper_card") or []) if c.get("source") == "not_reported"]
    if nr:
        warnings.append(f"marked not_reported: {nr}")

    # ---- content sanity
    if not (res.get("sections") or []):
        problems.append("no section notes")
    if not (res.get("knowledge_points") or []):
        warnings.append("no knowledge points")
    for s in res.get("sections") or []:
        if not (s.get("purpose") or s.get("conclusion")):
            warnings.append(f"section {s.get('sid')} has neither purpose nor conclusion")
            break

    # ---- placeholder / fabrication smells
    blob = json.dumps(res, ensure_ascii=False).lower()
    for bad in ("todo", "tbd", "lorem ipsum", "xxx", "placeholder text"):
        if bad in blob:
            warnings.append(f"suspicious placeholder text found: {bad!r}")

    # ---- uncertainty recorded
    u = r.get("uncertainty") or {}
    if not (u.get("not_reported_fields") or u.get("uncertain_fields") or u.get("agent_declared")):
        warnings.append("uncertainty block is empty — confirm nothing was genuinely uncertain")

    for f in ("notes.md", "validation.json"):
        if not os.path.exists(os.path.join(out, f)):
            warnings.append(f"companion file missing: {f}")

    for w in warnings:
        print(f"WARN {w}")
    for p in problems:
        print(f"FAIL {p}")
    print(f"\nstatus={st} anchors={ver.get('anchors_ok')}/{checked} ok, {failed} failed; "
          f"sections={covered}/{total}; card={len(card)}/8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
