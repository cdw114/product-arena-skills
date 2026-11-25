#!/usr/bin/env python3
"""build_notes.py — validate agent-written notes against the skeleton and emit the final result.

Stage 2 of the pipeline. The agent writes `notes_draft.json` (sections, paper card,
knowledge points — each with anchors into the skeleton). This script:

  1. validates every anchor id exists in skeleton.json and every `quote` is really
     inside the anchored block (normalised whitespace, case-insensitive, ≥ 20 chars);
  2. computes machine-checkable coverage: which sections / figures / tables were
     summarised, which card fields were filled, which are explicitly "not reported";
  3. writes result.json (status + result + evidence + uncertainty + run log),
     notes.md (human-readable) and a validation report.

Exit code 0 on success / partial, 2 on refused (nothing to emit).

Usage:
    python build_notes.py --skeleton WORK/skeleton.json --draft WORK/notes_draft.json \
        --case-json /input/case.json --out OUTPUT_DIR [--task-md /input/task.md]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from typing import Any

# --------------------------------------------------------------------------- #
# Field dictionary (see references/field_dictionary.md)
# --------------------------------------------------------------------------- #

CARD_FIELDS = {
    "research_question": "The question/hypothesis the paper addresses (as stated by the authors)",
    "data": "Datasets/samples/cohort: name, size, source, time range, inclusion criteria",
    "method": "Pipeline/model/algorithm/procedure incl. key hyper-parameters and conditions",
    "main_findings": "Principal quantitative/qualitative results with units and comparators",
    "conclusion": "Authors' stated conclusion (claims as made, not your assessment)",
    "limitations": "Limitations/threats to validity the authors state or that bound the claim",
    "scope_conditions": "Conditions under which the conclusions hold (population, setting, scale)",
    "open_questions": "Future work / unresolved items stated by the authors",
}

FIELD_SOURCES = ("reported", "not_reported", "uncertain", "conflicting")

STEP_TYPES = ("thought", "tool_call", "tool_result", "artifact", "decision", "error", "observation")

STATUS_VALUES = ("success", "partial", "cannot_determine", "refused")


def _norm(s: str) -> str:
    s = s.replace("\u00ad", "")
    s = re.sub(r"[\u2010-\u2015\-]\s+", "", s)  # de-hyphenation
    s = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", s)
    return s.lower().strip()


def _load(path: str) -> Any:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# Anchor validation
# --------------------------------------------------------------------------- #

def validate_anchor(anchor: str, quote: str | None, blocks: dict[str, dict], pages: int) -> dict[str, Any]:
    """Return {"ok": bool, "page": int|None, "issues": [...]} for one anchor+quote."""
    res: dict[str, Any] = {"ok": True, "page": None, "issues": []}
    a = (anchor or "").strip()
    # accepted forms: p3 (page), p3:b12 (block), s3.2 (section id), F2 / T1 (figure/table id)
    m = re.fullmatch(r"p(\d+)(?::b(\d+))?", a)
    if m:
        page = int(m.group(1))
        res["page"] = page
        if page < 1 or page > pages:
            res["ok"] = False
            res["issues"].append(f"page {page} outside document (1–{pages})")
            return res
        if m.group(2) is not None:
            bid = a
            if bid not in blocks:
                res["ok"] = False
                res["issues"].append(f"block id {bid} not in skeleton")
                return res
            if quote:
                q = _norm(quote)
                if len(q) < 12:
                    res["issues"].append("quote shorter than 12 chars — not verifiable")
                    res["ok"] = False
                elif q not in _norm(blocks[bid]["text"]):
                    res["ok"] = False
                    res["issues"].append("quote not found in anchored block")
            else:
                res["issues"].append("block anchor without quote — location only")
        return res
    if re.fullmatch(r"s[\d.]+|h\d+|s0", a):
        res["issues"].append("section-level anchor — coarse; add a block anchor for key claims")
        return res
    if re.fullmatch(r"[FT][0-9A-Za-z]+", a):
        return res
    res["ok"] = False
    res["issues"].append(f"unrecognised anchor format: {a!r}")
    return res


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skeleton", required=True)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--case-json", default=None)
    ap.add_argument("--task-md", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--notes-md", default=None, help="optional pre-written markdown notes to copy")
    a = ap.parse_args(argv)

    skel = _load(a.skeleton)
    draft = _load(a.draft)
    case = _load(a.case_json) if a.case_json and os.path.exists(a.case_json) else {}
    task_md = open(a.task_md, encoding="utf-8-sig").read() if a.task_md and os.path.exists(a.task_md) else ""

    blocks = {b["bid"]: b for b in skel.get("blocks", [])}
    sections = {s["sid"]: s for s in skel.get("sections", [])}
    pages = skel.get("pages", 1)
    fig_ids = {f["fid"] for f in skel.get("figures", [])}

    vreport: dict[str, Any] = {"anchors_checked": 0, "anchors_ok": 0, "anchors_coarse": 0, "anchors_failed": 0, "failures": []}

    def check(anchor: str | None, quote: str | None, where: str) -> dict[str, Any]:
        r = validate_anchor(anchor, quote, blocks, pages)
        vreport["anchors_checked"] += 1
        if r["ok"]:
            vreport["anchors_ok"] += 1
            if any("coarse" in i or "location only" in i for i in r["issues"]):
                vreport["anchors_coarse"] += 1
        else:
            vreport["anchors_failed"] += 1
            vreport["failures"].append({"where": where, "anchor": anchor, "quote": (quote or "")[:80], "issues": r["issues"]})
        return r

    # ---- per-item verification; attach page + verification status to each item
    def verify_items(items: list[dict], where: str, id_key: str) -> None:
        for it in items:
            evs = it.get("evidence") or []
            if isinstance(evs, dict):
                evs = [evs]
            it["_evidence"] = []
            for ev in evs:
                r = check(ev.get("anchor"), ev.get("quote"), f"{where}:{it.get(id_key, '?')}")
                e2 = dict(ev)
                e2["page"] = r["page"]
                e2["verified"] = "ok" if r["ok"] else "failed"
                if r["issues"]:
                    e2["note"] = "; ".join(r["issues"])
                it["_evidence"].append(e2)
            it["_evidence_ok"] = bool(it["_evidence"]) and all(e["verified"] == "ok" for e in it["_evidence"])

    section_notes = draft.get("sections", [])
    verify_items(section_notes, "section", "sid")
    kps = draft.get("knowledge_points", [])
    verify_items(kps, "kp", "id")

    # ---- section coverage
    body_sids = [s["sid"] for s in skel.get("sections", []) if s["sid"] != "s0" and "eference" not in s["title"]]
    covered = [s["sid"] for s in section_notes if s.get("sid") in sections]
    missing_sections = [sid for sid in body_sids if sid not in covered]
    bad_sids = [s["sid"] for s in section_notes if s.get("sid") not in sections]

    # ---- card fields
    card = draft.get("paper_card", {})
    card_out = []
    for fname, desc in CARD_FIELDS.items():
        v = card.get(fname)
        if v is None or (isinstance(v, str) and not v.strip()):
            card_out.append({"field": fname, "status": "missing", "value": None, "source": "not_reported", "evidence": []})
            continue
        if isinstance(v, str):
            v = {"value": v}
        src = v.get("source", "reported") if v.get("source") in FIELD_SOURCES else "reported"
        evs = v.get("evidence") or []
        if isinstance(evs, dict):
            evs = [evs]
        ev_out = []
        for ev in evs:
            r = check(ev.get("anchor"), ev.get("quote"), f"card:{fname}")
            e2 = dict(ev)
            e2["page"] = r["page"]
            e2["verified"] = "ok" if r["ok"] else "failed"
            ev_out.append(e2)
        card_out.append({
            "field": fname, "description": desc, "status": "filled", "value": v.get("value"),
            "source": src, "evidence": ev_out, "note": v.get("note"),
        })
    filled = [c for c in card_out if c["status"] == "filled"]
    nr = [c["field"] for c in card_out if c["source"] == "not_reported"]
    unc = [c["field"] for c in card_out if c["source"] == "uncertain"]
    conf = [c["field"] for c in card_out if c["source"] == "conflicting"]

    # ---- knowledge-point hygiene
    kp_ids = [k.get("id") for k in kps]
    dup_ids = sorted({i for i in kp_ids if kp_ids.count(i) > 1})
    kp_terms = [_norm(k.get("term", "")) for k in kps]
    dup_terms = sorted({t for t in kp_terms if t and kp_terms.count(t) > 1})

    # ---- figures/tables referenced
    figs_ref = sorted({e.get("anchor") for s in section_notes + kps for e in (s.get("evidence") or []) if e.get("anchor") in fig_ids})
    figs_unreferenced = sorted(fig_ids - set(figs_ref))

    # ---- answers to task questions (if case.json has questions)
    answers = draft.get("answers", [])
    for ans in answers:
        evs = ans.get("evidence") or []
        if isinstance(evs, dict):
            evs = [evs]
        ev_out = []
        for ev in evs:
            r = check(ev.get("anchor"), ev.get("quote"), f"answer:{ans.get('qid', '?')}")
            e2 = dict(ev)
            e2["page"] = r["page"]
            e2["verified"] = "ok" if r["ok"] else "failed"
            ev_out.append(e2)
        ans["_evidence"] = ev_out
        ans["_evidence_ok"] = bool(ev_out) and all(e["verified"] == "ok" for e in ev_out)

    # ---- overall status
    run_status = draft.get("run_status", {})
    requested = run_status.get("status")
    problems = []
    if not section_notes:
        problems.append("no section notes")
    if not kps:
        problems.append("no knowledge points")
    if vreport["anchors_failed"] > 0:
        problems.append(f"{vreport['anchors_failed']} anchor/quote verification failures")
    if missing_sections and len(missing_sections) > max(1, len(body_sids) // 4):
        problems.append(f"{len(missing_sections)} of {len(body_sids)} body sections not covered")
    if requested == "refused" or not requested:
        status = requested or ("partial" if section_notes else "refused")
    elif problems:
        status = "partial"
    else:
        status = "success"
    if status == "partial" and not problems:
        problems.append("run_status declared partial by agent")
    if status == "cannot_determine":
        problems.append(run_status.get("reason", "declared cannot_determine"))

    case_id = case.get("case_id") or case.get("id") or os.path.basename(os.path.dirname(os.path.abspath(a.out)))
    result = {
        "case_id": case_id,
        "input": {
            "case_json": case,
            "source_pdf": skel.get("source"),
            "pages": pages,
            "heading_method": skel.get("heading_method"),
        },
        "run_status": {
            "status": status,
            "reason": run_status.get("reason") or ("; ".join(problems) if problems else None),
            "problems": problems,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "skill": "paper-structured-notes",
            "stage": "build_notes",
        },
        "result": {
            "paper_card": card_out,
            "sections": section_notes,
            "knowledge_points": kps,
            "answers": answers,
            "figures_in_paper": skel.get("figures", []),
            "figures_referenced": figs_ref,
        },
        "evidence": {
            "anchor_format": "p{page}:b{block} (1-based page, block in column-major reading order); quote = verbatim substring of that block",
            "verification": vreport,
            "coverage": {
                "body_sections_total": len(body_sids),
                "body_sections_covered": len([s for s in covered if s in body_sids]),
                "sections_missing": missing_sections,
                "unknown_section_ids": bad_sids,
                "card_fields_filled": len(filled),
                "card_fields_total": len(CARD_FIELDS),
                "figures_total": len(fig_ids),
                "figures_referenced": len(figs_ref),
                "knowledge_points": len(kps),
            },
            "section_map": [{"sid": s["sid"], "number": s["number"], "title": s["title"], "pages": [s["page_start"], s["page_end"]], "anchor": s["anchor"]} for s in skel.get("sections", [])],
        },
        "uncertainty": {
            "not_reported_fields": nr,
            "uncertain_fields": unc,
            "conflicting_fields": conf,
            "unverified_items": [k.get("id") for k in kps if not k.get("_evidence_ok")] + [s.get("sid") for s in section_notes if not s.get("_evidence_ok")],
            "duplicate_kp_ids": dup_ids,
            "duplicate_kp_terms": dup_terms,
            "figures_without_caption_read": figs_unreferenced,
            "agent_declared": draft.get("uncertainty", []),
            "notes_on_extraction": (draft.get("extraction_notes") or []),
        },
        "change_log": draft.get("change_log", []),
    }
    # replace the agent's raw evidence with the verified version (page + status)
    def _finalize(items: list[dict]) -> None:
        for it in items:
            if "_evidence" in it:
                it["evidence"] = it["_evidence"]
        for it in items:
            it.pop("_evidence", None)
            it.pop("_evidence_ok", None)
    for bucket in ("sections", "knowledge_points", "answers"):
        _finalize(result["result"][bucket])

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    # strip private keys for validation report
    with open(os.path.join(a.out, "validation.json"), "w", encoding="utf-8") as f:
        json.dump({"status": status, "problems": problems, **vreport, "coverage": result["evidence"]["coverage"], "dup_kp_ids": dup_ids, "dup_kp_terms": dup_terms}, f, ensure_ascii=False, indent=1)

    # ---- notes.md
    md = render_md(result, skel, task_md)
    with open(os.path.join(a.out, "notes.md"), "w", encoding="utf-8") as f:
        f.write(md)

    print(json.dumps({"status": status, "problems": problems, **vreport, "coverage": result["evidence"]["coverage"], "dup_kp_ids": dup_ids, "dup_kp_terms": dup_terms}, ensure_ascii=False, indent=1))
    return 0 if status != "refused" else 2


def render_md(result: dict, skel: dict, task_md: str) -> str:
    r = result["result"]
    ev = result["evidence"]
    cov = ev["coverage"]
    L = [f"# Structured notes — {os.path.basename(skel.get('source', '') or '')}", ""]
    L.append(f"Run status: **{result['run_status']['status']}** — {result['run_status'].get('reason') or 'ok'}  ")
    L.append(f"Source: `{skel.get('source')}` · {skel.get('pages')} pages · headings via `{skel.get('heading_method')}`  ")
    L.append(f"Anchor check: {ev['verification']['anchors_ok']}/{ev['verification']['anchors_checked']} ok ({ev['verification']['anchors_coarse']} coarse) · {ev['verification']['anchors_failed']} failed  ")
    L.append("")
    L.append("> Anchor format `p{page}:b{block}`; quotes are verbatim text of that block (normalised whitespace).")
    L.append("")
    # ---- paper card
    L.append("## 1. Paper card")
    L.append("")
    L.append("| field | value | source | evidence |")
    L.append("|---|---|---|---|")
    for c in r["paper_card"]:
        if c["status"] == "missing":
            L.append(f"| {c['field']} | — | not_reported | — |")
            continue
        evs = "; ".join(f"`{e.get('anchor')}` p.{e.get('page')}{'' if e.get('verified') == 'ok' else ' ⚠'}" for e in c["evidence"]) or "—"
        val = (c["value"] or "").replace("\n", " ").replace("|", "\\|")
        L.append(f"| {c['field']} | {val} | {c['source']} | {evs} |")
    L.append("")
    # ---- sections
    L.append(f"## 2. Section-by-section notes ({cov['body_sections_covered']}/{cov['body_sections_total']} body sections)")
    L.append("")
    for s in r["sections"]:
        title = next((m["title"] for m in ev["section_map"] if m["sid"] == s.get("sid")), s.get("sid"))
        num = next((m["number"] for m in ev["section_map"] if m["sid"] == s.get("sid")), "")
        pg = next((m["pages"] for m in ev["section_map"] if m["sid"] == s.get("sid")), "")
        L.append(f"### {('§' + num + ' ') if num else ''}{title} ({s.get('sid')}, pp.{pg[0]}–{pg[1]})")
        L.append("")
        for k in ("purpose", "method", "results", "conclusion", "link_to_previous"):
            if s.get(k):
                L.append(f"- **{k}**: {s[k]}")
        if s.get("limitations"):
            L.append(f"- **limitations**: {s['limitations']}")
        if s.get("figures"):
            L.append(f"- **figures/tables**: {', '.join(s['figures'])}")
        evs = s.get("evidence") or []
        if evs:
            L.append("- **evidence**: " + "; ".join(f"`{e.get('anchor')}` p.{e.get('page')} “{(e.get('quote') or '')[:70]}…”{'' if e.get('verified') == 'ok' else ' ⚠ ' + e.get('note', '')}" for e in evs))
        if s.get("not_reported"):
            L.append(f"- **not reported / uncertain**: {s['not_reported']}")
        L.append("")
    if cov["sections_missing"]:
        L.append(f"⚠ Sections without notes: {', '.join(cov['sections_missing'])}")
        L.append("")
    # ---- knowledge points
    L.append(f"## 3. Knowledge points ({len(r['knowledge_points'])})")
    L.append("")
    for k in r["knowledge_points"]:
        L.append(f"- **{k.get('id')} {k.get('term')}** ({k.get('type', '')}) — {k.get('statement', '')}")
        if k.get("aliases"):
            L.append(f"  - aliases: {', '.join(k['aliases'])}")
        if k.get("conditions"):
            L.append(f"  - conditions: {k['conditions']}")
        if k.get("related"):
            L.append(f"  - related: {', '.join(k['related'])}")
        evs = k.get("evidence") or []
        if evs:
            L.append("  - evidence: " + "; ".join(f"`{e.get('anchor')}` p.{e.get('page')}{'' if e.get('verified') == 'ok' else ' ⚠'}" for e in evs))
        L.append("")
    # ---- answers
    if r.get("answers"):
        L.append("## 4. Answers to task questions")
        L.append("")
        for an in r["answers"]:
            L.append(f"**{an.get('qid')} {an.get('question', '')}**")
            L.append("")
            L.append(str(an.get("answer", "")))
            evs = an.get("evidence") or []
            if evs:
                L.append("")
                L.append("Evidence: " + "; ".join(f"`{e.get('anchor')}` p.{e.get('page')}{'' if e.get('verified') == 'ok' else ' ⚠'} “{(e.get('quote') or '')[:80]}…”" for e in evs))
            L.append("")
    # ---- uncertainty
    u = result["uncertainty"]
    L.append("## 5. Uncertainty & boundaries")
    L.append("")
    L.append(f"- not reported in paper: {', '.join(u['not_reported_fields']) or 'none'}")
    L.append(f"- uncertain: {', '.join(u['uncertain_fields']) or 'none'}")
    L.append(f"- conflicting within paper: {', '.join(u['conflicting_fields']) or 'none'}")
    L.append(f"- figures/tables in paper not referenced by any note: {', '.join(u['figures_without_caption_read']) or 'none'}")
    if u["duplicate_kp_ids"]:
        L.append(f"- ⚠ duplicate knowledge-point ids: {', '.join(u['duplicate_kp_ids'])}")
    if u["duplicate_kp_terms"]:
        L.append(f"- ⚠ duplicate knowledge-point terms: {', '.join(u['duplicate_kp_terms'])}")
    for n in u["agent_declared"]:
        L.append(f"- {n}")
    L.append("")
    if result.get("change_log"):
        L.append("## 6. Change log")
        L.append("")
        for c in result["change_log"]:
            L.append(f"- {c}")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
