#!/usr/bin/env python3
"""emit_outputs.py - step 7 of the methods-experiments-writer skill.

Turns the work directory into the deliverables a reviewer opens, and builds
result.json so that it carries EVERY field the case's output_contract names,
plus case_id, an honest status, sources, uncertainty and a change log.

    python3 scripts/emit_outputs.py --input /input --work /app/work --out /app/output

Automatic mapping from a contract field name to a deliverable, when
work/output_plan.json does not override it:

    methods/section/draft/manuscript/章节/方法/实验 -> the drafted section
    param/参数                                      -> parameter table
    evidence/source/provenance/证据/来源             -> fact -> source map
    coverage/checklist/覆盖                          -> six-element report
    question/gap/confirm/缺口/待确认                 -> author question list
    repro/复现                                       -> reproducibility checklist
    change/changelog/修改                            -> change log

A contract field with no deliverable behind it is written as null and named in
uncertainty. It is never filled with prose that looks finished.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mew_lib as L  # noqa: E402

SKILL_VERSION = "1.0.0"


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# deliverable builders
# ---------------------------------------------------------------------------

def load_work(work):
    g = lambda n: L.load_json(os.path.join(work, n))  # noqa: E731
    return {
        "contract": g("contract.json") or {},
        "inventory": g("inventory.json") or {"files": []},
        "evidence": g("evidence.json") or {"rows": []},
        "conflicts": g("conflicts.json") or {"conflicts": []},
        "gaps": g("gaps.json") or {"gaps": []},
        "audit": g("audit.json") or {},
        "plan": g("output_plan.json") or {},
    }


def read_draft(work, plan):
    path = None
    if isinstance(plan.get("draft"), str):
        path = plan["draft"]
    if not path:
        for cand in ("draft.md", "draft_final.md", "draft_audited.md"):
            p = os.path.join(work, cand)
            if os.path.isfile(p):
                path = p
                break
    if not path or not os.path.isfile(path):
        return None, None
    return path, (L.read_text(path) or "")


TABLE_KIND_PRIORITY = {"config_value": 0, "code_default": 1, "log_value": 2, "dataset_fact": 3,
                       "paper_statement": 4, "table_fact": 5, "raw_line": 6}
TABLE_SKIP_NAMES = {"column", "row", "prose_claim", "pdf_text_layer"}


VERSION_SUFFIXES = ("_version", "_steps", "_size", "_seed")


def _dedupe_key(name, display):
    """Collapse two spellings of one fact.

    A log line yields both `torch` and `torch_version` for the same 2.1.2, and
    the ledger keeps both because they came from different rules. The table is
    for the reader, so it keeps one row: the same value under a name that differs
    only by a trailing `_version` / `_steps` / `_size` / `_seed` is one fact.
    """
    leaf = L.param_leaf(name)
    for suf in VERSION_SUFFIXES:
        if leaf.endswith(suf) and len(leaf) > len(suf):
            leaf = leaf[: -len(suf)]
            break
    return (leaf, display)


def _cell(value):
    """Make a value safe inside a markdown table cell.

    A pipe splits a cell and a backtick opens a code span that the next backtick
    in a different row will close wrongly, so both are neutralised. The value is
    already wrapped in backticks by the caller.
    """
    s = str(value).replace("|", "\\|").replace("`", "'").replace("*", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _unit_for(row):
    if row.get("unit"):
        return row["unit"]
    leaf = L.param_leaf(row["name"])
    if leaf.endswith("_statement") or leaf == "statement":
        return "text"
    if "version" in leaf:
        return "version"
    return "1" if L.norm_number(row["value"]) is not None else "name"


def build_param_table(rows):
    """One row per parameter, most authoritative source first.

    The table is the section's numeric backbone, so it carries ordinary config
    keys too, not only the ones this skill has a name for: `model.hidden_dim`
    is a parameter a reader needs even though it is not in the vocabulary.
    """
    candidates = []
    for r in rows:
        if r["kind"] not in TABLE_KIND_PRIORITY:
            continue
        if str(r["name"]).lower() in TABLE_SKIP_NAMES:
            continue
        candidates.append(r)
    candidates.sort(key=lambda r: (TABLE_KIND_PRIORITY.get(r["kind"], 9),
                                  0 if L.canonical_param(r["name"])[0] else 1,
                                  r["eid"]))
    seen = set()
    kept = []
    for r in candidates:
        key = _dedupe_key(r["name"], r["display"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    lines = ["| eid | parameter | value | unit | applies to | source | status |",
             "|---|---|---|---|---|---|---|"]
    csv = ["eid,parameter,value,unit,applies_to,source_locator,status"]
    for r in kept:
        target = L.target_of(r["name"], r.get("applies_to") or "")
        unit = _unit_for(r)
        lines.append("| %s | `%s` | `%s` | %s | %s | `%s` | %s |" % (
            r["eid"], _cell(r["name"]), _cell(r["display"]), unit,
            target, r["source_locator"], r["status"]))
        csv.append('"%s","%s","%s","%s","%s","%s","%s"' % (
            r["eid"], r["name"], str(r["display"]).replace('"', "'"), unit,
            target, r["source_locator"], r["status"]))
    return "\n".join(lines) + "\n", "\n".join(csv) + "\n", len(kept)


def build_evidence_map(rows):
    lines = ["# Fact-to-source map", "",
             "Locator conventions: a text or log source is `<path>:<line>` (1-based); a JSON",
             "configuration is `<path>#/<json-pointer>`. Either one re-opens to the exact place",
             "the value came from.", "",
             "| eid | kind | fact | value | locator | method | confidence |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | `%s` | `%s` | `%s` | %s | %s |" % (
            r["eid"], r["kind"], r["name"], r["display"].replace("|", "\\|"),
            r["source_locator"], r["method"], r["confidence"]))
    lines.append("")
    lines.append("Rows with `status: conflict` carry two different values for one parameter;")
    lines.append("both are kept on purpose and neither is chosen silently.")
    return "\n".join(lines) + "\n"


def build_coverage(contract, coverage, open_gaps, resolved_gaps, conflicts, audit):
    zh = contract.get("deliverable_language") == "zh"
    T = (lambda a, b: a + " / " + b) if zh else (lambda a, b: b)
    o = ["# " + T("覆盖与缺口", "Coverage and gaps"), ""]
    o.append("## " + T("六要素", "Six elements"))
    o.append("")
    o.append("| " + T("要素", "element") + " | " + T("状态", "status") + " | " + T("缺口", "missing pieces") + " |")
    o.append("|---|---|---|")
    for k, v in coverage.items():
        o.append("| %s (`%s`) | %s | %s |" % (v["label"], k, v["status"], ", ".join(v.get("missing") or []) or "-"))
    o.append("")
    o.append("## " + T("仍然开放的缺口", "Gaps still open"))
    o.append("")
    if open_gaps:
        for g in open_gaps:
            o.append("- `%s` (%s) — %s" % (g.get("id"), g.get("severity", "important"), g.get("what", "")))
    elif not conflicts:
        o.append(T("无。", "None. Every element the checklist asks for is covered by the draft."))
    else:
        o.append(T("除下方来源冲突外无其他缺口。",
                   "None besides the source conflicts listed below."))
    o.append("")
    if resolved_gaps:
        o.append("## " + T("已被草稿回答的扫描缺口", "Scan gaps the draft answered"))
        o.append("")
        o.append(T("扫描阶段这些要素不完整；成稿通过写出步骤或标记 TO-CONFIRM 补上了它们，"
                   "因此不再列为待确认项。",
                   "These elements were incomplete at scan time. The draft covers them by "
                   "stating the missing piece or by marking it TO-CONFIRM, so they are no "
                   "longer open questions:"))
        o.append("")
        for g in resolved_gaps:
            o.append("- `%s` — %s" % (g.get("id"), g.get("what", "")))
        o.append("")
    o.append("## " + T("来源冲突", "Source conflicts"))
    o.append("")
    if conflicts:
        for c in conflicts:
            o.append("- **%s** — %s" % (c.get("parameter"), c.get("question")))
    else:
        o.append(T("无。", "None."))
    o.append("")
    if audit:
        o.append("## " + T("草稿审计摘要", "Draft audit summary"))
        o.append("")
        c = audit.get("counts", {})
        o.append("- " + T("审计结论", "verdict") + ": `%s`" % audit.get("verdict"))
        o.append("- " + T("无来源数字", "unsourced numbers") + ": %s" % c.get("unsourced_numbers"))
        o.append("- " + T("参数表不一致", "table mismatches") + ": %s" % c.get("table_mismatches"))
        o.append("- " + T("要素完成度", "elements complete") + ": %s/%s" % (
            c.get("elements_complete"), c.get("elements_total")))
        o.append("")
    return "\n".join(o) + "\n"


def build_questions(gaps, conflicts):
    o = ["# Questions for the author", "",
         "Each item names the exact file to open and what would settle it. Answer only what",
         "you know: an unanswered question stays open, and the section keeps a TO-CONFIRM",
         "marker where it matters.", ""]
    n = 0
    for c in conflicts:
        n += 1
        o.append("%d. **%s** (blocking — the materials disagree) — %s"
                 % (n, c.get("parameter"), c.get("question")))
    for g in gaps:
        n += 1
        o.append("%d. **%s** (%s) — %s" % (n, g.get("id"), g.get("severity", "important"), g.get("what", "")))
        if g.get("resolve_by"):
            o.append("   Resolve by: %s" % g["resolve_by"])
    if not n:
        o.append("None outstanding: every element the checklist asks for had evidence in the "
                 "materials, and no two sources disagreed.")
    o.append("")
    return "\n".join(o) + "\n"


def build_questions_machine(gaps, conflicts):
    items = []
    for c in conflicts:
        items.append({"id": "conflict_%s" % c.get("parameter"), "type": "conflict",
                      "question": c.get("question"), "eids": c.get("eids", [])})
    for g in gaps:
        items.append({"id": g.get("id"), "type": "gap", "severity": g.get("severity"),
                      "question": g.get("what"), "resolve_by": g.get("resolve_by")})
    return items


def build_repro(rows, audit):
    items = (audit or {}).get("repro", [])
    o = ["# Reproducibility checklist", "",
         "A checkbox is ticked only when the section states the item. A tick means a reader",
         "can act on it; it is not a claim that the item is globally correct.", ""]
    for it in items:
        o.append("- [%s] %s" % ("x" if it.get("present") else " ", it.get("item")))
    o.append("")
    cmds = [r for r in rows if r["kind"] == "code_fact" and r["name"] == "run_command"]
    if cmds:
        o.append("## Commands found in the materials")
        o.append("")
        for r in cmds:
            o.append("- `%s` — source `%s`" % (r["display"], r["source_locator"]))
        o.append("")
    else:
        o.append("## Commands found in the materials")
        o.append("")
        o.append("None. No run command could be recovered, so the section must not claim one.")
        o.append("")
    return "\n".join(o) + "\n"


def build_changelog(run_meta, audit, rows):
    o = ["# Change log", "",
         "What this run did, in order. Nothing here is inferred: each line was produced by a",
         "step that left a file behind.", ""]
    for step in run_meta["steps"]:
        o.append("- `%s` %s" % (step["at"], step["what"]))
    o.append("")
    o.append("## Counts")
    o.append("")
    o.append("| item | n |")
    o.append("|---|---|")
    for k, v in run_meta["counts"].items():
        o.append("| %s | %s |" % (k, v))
    o.append("")
    if audit:
        o.append("## Revisions the audit forced")
        o.append("")
        mf = audit.get("must_fix") or []
        if mf:
            for m in mf:
                o.append("- " + m)
        else:
            o.append("- none: the first audited draft already cleared every check")
        o.append("")
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------------------
# office preview (honest about what the image can actually do)
# ---------------------------------------------------------------------------

def try_docx(md_text, out_path):
    try:
        from docx import Document  # type: ignore
        from docx.shared import Pt  # type: ignore
    except Exception as exc:
        return False, "python-docx not importable (%s)" % exc.__class__.__name__
    try:
        doc = Document()
        for raw in md_text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                doc.add_heading(m.group(2).strip(), level=min(len(m.group(1)), 4))
                continue
            if line.strip().startswith("|") and set(line.strip()) - set("|-: "):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                p = doc.add_paragraph("  ·  ".join(cells))
                p.paragraph_format.space_after = Pt(2)
                continue
            if re.match(r"^\s*[-*]\s+", line):
                doc.add_paragraph(re.sub(r"^\s*[-*]\s+", "", line), style="List Bullet")
                continue
            if re.match(r"^\s*\d+\.\s+", line):
                doc.add_paragraph(re.sub(r"^\s*\d+\.\s+", "", line), style="List Number")
                continue
            if line.strip().startswith("```"):
                continue
            doc.add_paragraph(line.replace("**", "").replace("`", ""))
        doc.save(out_path)
        return True, "python-docx"
    except Exception as exc:
        return False, "%s: %s" % (exc.__class__.__name__, exc)


def try_pdf(docx_path, out_dir):
    for exe in ("soffice", "libreoffice", "soffice.bin"):
        path = shutil.which(exe)
        if not path:
            continue
        try:
            subprocess.run([path, "--headless", "--convert-to", "pdf", "--outdir", out_dir, docx_path],
                           check=True, timeout=240, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cand = os.path.join(out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
            if os.path.isfile(cand):
                return True, os.path.basename(path), cand
        except Exception:
            continue
    return False, None, None


def try_png(pdf_path, out_dir):
    try:
        import fitz  # type: ignore
    except Exception:
        return False, None
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            return False, None
        pix = doc[0].get_pixmap(dpi=110)
        out = os.path.join(out_dir, os.path.splitext(os.path.basename(pdf_path))[0] + "_p1.png")
        pix.save(out)
        return True, out
    except Exception:
        return False, None


# ---------------------------------------------------------------------------
# contract resolution
# ---------------------------------------------------------------------------

FIELD_RULES = [
    (r"method|experiment|section|draft|manuscript|章节|方法|实验|正文|正文草稿", "draft"),
    (r"param|parameter|参数", "params"),
    (r"evidence|source|provenance|mapping|trace|证据|来源|映射", "evidence"),
    (r"coverage|checklist|complete|integrity|覆盖|完整", "coverage"),
    (r"question|gap|confirm|uncertain|待确认|缺口|追问|不确定", "questions"),
    (r"repro|reproducib|复现", "repro"),
    (r"change|changelog|diff|修改|变更", "changelog"),
    (r"table|表格", "params"),
]


def resolve_field(key, spec):
    """Return the deliverable id that best matches a contract field key."""
    k = str(key).lower()
    for pattern, target in FIELD_RULES:
        if re.search(pattern, k):
            return target
    if isinstance(spec, str):
        s = spec.lower()
        for pattern, target in FIELD_RULES:
            if re.search(pattern, s):
                return target
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Emit the methods/experiments deliverables and result.json.")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--docx", default="auto", choices=["auto", "none"],
                    help="auto: build a .docx and a PDF/PNG preview when the image supports it")
    ap.add_argument("--only-contract", action="store_true",
                    help="write result.json fields only; do not create extra files")
    args = ap.parse_args(argv)

    L.ensure_dir(args.work)
    L.ensure_dir(args.out)
    w = load_work(args.work)
    contract = w["contract"]
    rows = w["evidence"].get("rows", [])
    audit = w["audit"]
    plan = w["plan"]
    case_id = contract.get("case_id") or (plan.get("case_id") if isinstance(plan.get("case_id"), str) else None)
    lang = contract.get("deliverable_language") or "en"
    started = utcnow()

    # A gap the finished draft already answers is not still open. This runs
    # before any report is written: doing it at the end left coverage_report.md
    # saying "7/7 complete" while the same file listed six open gaps, and
    # open_questions.md asking about things the draft had already stated.
    raw_gaps = w["gaps"].get("gaps", [])
    audit_cov = (audit or {}).get("coverage") or {}

    def answered_by_draft(gap):
        gid = str(gap.get("id") or "")
        if not gid.startswith("coverage_"):
            return False
        element = gid[len("coverage_"):]
        for suffix in ("_partial", "_missing"):
            if element.endswith(suffix):
                element = element[: -len(suffix)]
                break
        return (audit_cov.get(element) or {}).get("status") == "complete"

    resolved_gaps = [g for g in raw_gaps if answered_by_draft(g)]
    # A conflict reaches the reader through `conflicts`, which carries the eids
    # and both values. scan_case.py also writes the same conflict into the gap
    # list (so a bare scan is useful on its own), and keeping both would print
    # every contested parameter twice in open_questions.md.
    open_gaps = [
        g for g in raw_gaps
        if not answered_by_draft(g) and not str(g.get("id") or "").startswith("conflict_")
    ]
    gaps = open_gaps
    conflicts = w["conflicts"].get("conflicts", [])

    draft_path, draft_text = read_draft(args.work, plan)
    steps = [
        {"at": started, "what": "read the case contract from %s" % (contract.get("case_file") or "case.json")},
        {"at": started, "what": "scanned %d material file(s) into %d evidence rows" % (
            len(w["inventory"].get("files", [])), len(rows))},
    ]

    files = {}

    def put(name, text):
        p = os.path.join(args.out, name)
        L.write_text(p, text)
        files[name] = p
        return p

    if draft_text is not None:
        put("methods_and_experiments.md", draft_text)
        steps.append({"at": utcnow(), "what": "copied the audited draft to methods_and_experiments.md"})

    params_md, params_csv, n_params = build_param_table(rows)
    put("parameter_table.md", params_md)
    put("parameter_table.csv", params_csv)
    put("evidence_map.md", build_evidence_map(rows))
    put("coverage_report.md", build_coverage(contract, audit.get("coverage", {}),
                                             open_gaps, resolved_gaps, conflicts, audit))
    put("open_questions.md", build_questions(open_gaps, conflicts))
    put("reproducibility_checklist.md", build_repro(rows, audit))
    steps.append({"at": utcnow(), "what": "built parameter table, evidence map, coverage report and question list"})

    run_meta = {
        "steps": steps,
        "counts": {
            "materials": len(w["inventory"].get("files", [])),
            "evidence_rows": len(rows),
            "parameter_rows": n_params,
            "conflicts": len(conflicts),
            "gaps_open": len(open_gaps),
            "gaps_closed_by_draft": len(resolved_gaps),
        },
    }
    put("change_log.md", build_changelog(run_meta, audit, rows))

    previews = {"requested": args.docx, "docx": None, "pdf": None, "png": None, "notes": []}
    if args.docx == "auto" and draft_text:
        docx_path = os.path.join(args.out, "methods_and_experiments.docx")
        ok, how = try_docx(draft_text, docx_path)
        if ok:
            previews["docx"] = "methods_and_experiments.docx"
            okp, tool, pdf_path = try_pdf(docx_path, args.out)
            if okp:
                previews["pdf"] = os.path.basename(pdf_path)
                okg, png_path = try_png(pdf_path, args.out)
                if okg:
                    previews["png"] = os.path.basename(png_path)
            else:
                previews["notes"].append(
                    "no LibreOffice/soffice on PATH: the .docx is real but has no PDF preview")
        else:
            previews["notes"].append("docx not produced: %s" % how)

    # ---- result.json -----------------------------------------------------
    outputs = {
        "draft": {"text": draft_text, "path": files.get("methods_and_experiments.md"),
                  "name": "methods_and_experiments.md"} if draft_text else None,
        "params": {"text": params_md, "path": files["parameter_table.md"], "name": "parameter_table.md",
                   "csv": files["parameter_table.csv"]},
        "evidence": {"text": L.read_text(files["evidence_map.md"]),
                     "path": files["evidence_map.md"], "name": "evidence_map.md"},
        "coverage": {"text": L.read_text(files["coverage_report.md"]),
                     "path": files["coverage_report.md"], "name": "coverage_report.md"},
        "questions": {"text": L.read_text(files["open_questions.md"]),
                      "path": files["open_questions.md"], "name": "open_questions.md"},
        "repro": {"text": L.read_text(files["reproducibility_checklist.md"]),
                  "path": files["reproducibility_checklist.md"], "name": "reproducibility_checklist.md"},
        "changelog": {"text": L.read_text(files["change_log.md"]),
                      "path": files["change_log.md"], "name": "change_log.md"},
    }

    contract_fields = contract.get("output_contract") or {}
    plan_fields = plan.get("fields") if isinstance(plan.get("fields"), dict) else {}
    resolved, unresolved, field_manifest = {}, [], {}
    for key, spec in contract_fields.items():
        target = None
        override = plan_fields.get(key)
        if isinstance(override, str) and override in outputs:
            target = override
        elif isinstance(override, dict) and isinstance(override.get("deliverable"), str):
            target = override["deliverable"]
        if target is None:
            target = resolve_field(key, spec)
        if target and outputs.get(target):
            payload = outputs[target]
            if override and isinstance(override, dict) and isinstance(override.get("text"), str):
                resolved[key] = override["text"]
                field_manifest[key] = {"deliverable": target, "source": "output_plan.json"}
            else:
                resolved[key] = payload.get("text")
                field_manifest[key] = {"deliverable": target, "path": payload.get("path")}
        else:
            resolved[key] = None
            unresolved.append(key)
            field_manifest[key] = {"deliverable": None, "path": None}

    gaps = open_gaps
    # One entry per id: a conflicting parameter shows up twice otherwise, once as
    # a scan gap and once as a conflict, and the reader sees the same question
    # twice with two different labels.
    uncertainty_by_id = {}

    def note(item):
        prev = uncertainty_by_id.get(item["id"])
        if prev is None or (item["kind"] == "conflict" and prev["kind"] != "conflict"):
            uncertainty_by_id[item["id"]] = item

    for key in unresolved:
        note({
            "id": "unresolved_contract_field_%s" % key,
            "kind": "partial",
            "statement": "output_contract field '%s' has no deliverable behind it in this run" % key,
            "resolve_by": "read the field's requirement in case.json, then set work/output_plan.json fields.%s" % key,
        })
    for g in gaps:
        note({
            "id": g.get("id"), "kind": "gap",
            "statement": g.get("what"),
            "resolve_by": g.get("resolve_by") or "author confirmation required",
        })
    if resolved_gaps:
        note({
            "id": "gaps_closed_by_draft",
            "kind": "observation",
            "statement": ("%d scan-time gap(s) are answered by the finished draft and are no longer "
                          "open: %s" % (len(resolved_gaps), ", ".join(str(g.get("id")) for g in resolved_gaps))),
            "resolve_by": "nothing to confirm; recorded so the open list is not read as the scan list",
        })
    for c in conflicts:
        note({
            "id": "conflict_%s" % c.get("parameter"), "kind": "conflict",
            "statement": c.get("question"), "eids": c.get("eids", []),
            "resolve_by": "author names the authoritative source",
        })
    for i, text in enumerate(previews["notes"]):
        note({"id": "preview_note_%d" % i, "kind": "assumption", "statement": text,
              "resolve_by": "install the renderer in the image, or accept the markdown source"})
    uncertainty = list(uncertainty_by_id.values())

    audit_verdict = audit.get("verdict") or "not_run"
    if draft_text is None:
        status = "failed"
        status_detail = "no draft was written to work/draft.md, so there is no section to deliver"
    elif unresolved:
        status = "partial"
        status_detail = "%d of %d contract fields were filled; missing: %s" % (
            len(contract_fields) - len(unresolved), len(contract_fields), ", ".join(unresolved))
    elif audit_verdict == "blocked":
        status = "partial"
        status_detail = "the draft still has numbers the ledger cannot source; see audit.json must_fix"
    else:
        status = "success"
        status_detail = "every contract field was filled and the draft audit did not block"

    sources = []
    for it in w["inventory"].get("files", []):
        sources.append({
            "path": it.get("relpath"), "class": it.get("class"),
            "bytes": it.get("bytes"), "sha256": it.get("sha256"),
        })

    result = {
        "case_id": case_id,
        "skill": {"name": "methods-experiments-writer", "version": SKILL_VERSION},
        "status": status,
        "status_detail": status_detail,
        "language": lang,
        "generated_at": utcnow(),
        "outputs": resolved,
        "output_contract_source": contract.get("output_contract_source"),
        "field_manifest": field_manifest,
        "target_artifacts": {name: {"path": p, "sha256": L.sha256_file(p), "bytes": os.path.getsize(p)}
                             for name, p in files.items()},
        "fact_source_map": [
            {"eid": r["eid"], "fact": r["name"], "value": r["display"],
             "locator": r["source_locator"], "confidence": r["confidence"], "status": r["status"]}
            for r in rows
        ],
        "version_and_boundaries": {
            "materials_read": len(w["inventory"].get("files", [])),
            "evidence_rows": len(rows),
            "parameters_tabled": n_params,
            "open_questions": len(gaps) + len(conflicts),
            "audit_verdict": audit_verdict,
            "audit_counts": audit.get("counts", {}),
            "gaps_open": len(open_gaps),
            "gaps_closed_by_draft": [str(g.get("id")) for g in resolved_gaps],
            "conflicts": conflicts,
            "limitations": [
                "A value present in a config file is what the code would use by default; it is not "
                "proof the run used it. Where a log line disagrees, both values are kept as a conflict.",
                "Parameters that no file records are absent from the table and appear in "
                "open_questions.md. The section marks those spots TO-CONFIRM instead of filling them.",
                "Prose sentences extracted from a paper are evidence for wording, not for a "
                "machine-checked value; they carry confidence 'low'.",
            ],
        },
        "sources": sources,
        "uncertainty": uncertainty,
        "change_log": {
            "steps": [s["what"] for s in run_meta["steps"]],
            "artifact": files["change_log.md"],
            "revisions_forced_by_audit": audit.get("must_fix", []),
        },
        "previews": previews,
        "artifacts": {name: os.path.relpath(p, args.out).replace(os.sep, "/") for name, p in files.items()},
    }

    result_path = os.path.join(args.out, "result.json")
    L.write_json(result_path, result)

    # machine-readable companions
    L.write_json(os.path.join(args.out, "open_questions.json"),
                 {"questions": build_questions_machine(gaps, conflicts)})
    L.write_json(os.path.join(args.out, "evidence.json"), w["evidence"])
    if os.path.isfile(os.path.join(args.out, "parameter_table.csv")):
        pass
    manifest = {
        "schema": "mew-output-manifest/v1",
        "case_id": case_id,
        "generated_at": result["generated_at"],
        "files": [{"path": os.path.relpath(p, args.out).replace(os.sep, "/"),
                   "bytes": os.path.getsize(p), "sha256": L.sha256_file(p)}
                  for p in sorted(set(files.values()) | {result_path})],
    }
    L.write_json(os.path.join(args.out, "manifest.json"), manifest)

    print(json.dumps({
        "status": status,
        "case_id": case_id,
        "result_json": result_path,
        "contract_fields_filled": len(contract_fields) - len(unresolved),
        "contract_fields_total": len(contract_fields),
        "unresolved_fields": unresolved,
        "audit_verdict": audit_verdict,
        "files": sorted(os.path.relpath(p, args.out).replace(os.sep, "/")
                        for p in set(files.values()) | {result_path,
                                                        os.path.join(args.out, "open_questions.json"),
                                                        os.path.join(args.out, "evidence.json"),
                                                        os.path.join(args.out, "manifest.json")}),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
