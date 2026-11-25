#!/usr/bin/env python3
"""run_case.py — I/O skeleton for one academic-polishing case.

It does the deterministic parts so the editor (the model) spends its budget on
the actual rewriting:

  init     Read the case, write the work tree, extract a baseline of protected
           spans from the source text, and print a compact "edit brief" that
           lists every hedge / number / citation the revision must keep.
  verify   Re-run the audit on source vs revised, merge the edit ledger, write
           result.json with all output_contract fields, and exit non-zero if a
           protected span changed without a ledger entry explaining it.

The polishing itself is NOT done here. `init` prepares; the model edits; `verify`
checks. Nothing is invented: if a field is unknown it is reported as unknown.

Usage:
  python run_case.py init   --case /input/case.json [--task-md /input/task.md] [--work /app/work]
  python run_case.py verify --case /input/case.json --work /app/work --out /app/output \
                            [--revised FILE] [--ledger FILE] [--status complete|partial]

Exit code (verify): 0 = consistent; 2 = unexplained protected-span change; 1 = error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE / "polish_audit.py"

EDIT_TYPES = ["grammar", "syntax", "punctuation", "long_sentence_split", "word_choice", "terminology",
              "register", "hedge_adjust", "connective", "translationese", "redundancy", "citation_format",
              "structure", "format", "other"]
LEDGER_VERSION = "edit-ledger/v1"
ZH_NEG_WORDS = {"不", "未", "无", "非", "没有", "无法", "不能", "并非", "不是", "尚未", "并不", "从未"}
EN_NEG_WORDS = {"not", "no", "never", "neither", "nor", "without", "cannot", "n't", "unable", "fails to"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_text_any(path: Path) -> str:
    """Read txt/md/tex/docx. docx is parsed with zipfile+xml (stdlib) if python-docx is absent."""
    suf = path.suffix.lower()
    if suf == ".docx":
        try:
            import docx  # type: ignore
            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        except ImportError:
            import zipfile
            from xml.etree import ElementTree as ET
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml")
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            root = ET.fromstring(xml)
            paras = []
            for p in root.iter("{%s}p" % ns["w"]):
                paras.append("".join(t.text or "" for t in p.iter("{%s}t" % ns["w"])))
            return "\n".join(paras)
    return path.read_text(encoding="utf-8", errors="replace")


def _source_format(path: Path) -> str:
    return {".tex": "tex", ".latex": "tex", ".md": "md", ".markdown": "md"}.get(path.suffix.lower(), "txt")


def _audit(args: list[str]) -> dict:
    cmd = [sys.executable, str(AUDIT), *args, "--json", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if not r.stdout:
        raise RuntimeError(f"polish_audit failed (rc={r.returncode}): {r.stderr[-1200:]}")
    return json.loads(r.stdout)


def _find_case_field(case: dict, *names: str, default=None):
    """Look up the first present key among `names`, case-insensitively, at top level or under 'input'."""
    containers = [case]
    for sub in ("input", "data", "payload", "case"):
        if isinstance(case.get(sub), dict):
            containers.append(case[sub])
    for c in containers:
        keys = {k.lower(): k for k in c.keys()}
        for n in names:
            if n.lower() in keys:
                return c[keys[n.lower()]]
    return default


def _resolve_material(case: dict, value, base_dir: Path) -> Path | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("path") or value.get("file") or value.get("name")
    if not isinstance(value, str):
        return None
    p = Path(value)
    if p.is_absolute() and p.exists():
        return p
    for cand in (base_dir / p, base_dir / "materials" / p, base_dir / "input" / p, base_dir.parent / p):
        if cand.exists():
            return cand
    return None


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

def cmd_init(a: argparse.Namespace) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    case = json.loads(Path(a.case).read_text(encoding="utf-8"))
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    base_dir = Path(a.case).resolve().parent

    case_id = _find_case_field(case, "case_id", "id", default=Path(a.case).parent.name)
    task_md = a.task_md or _find_case_field(case, "task_md", "task", "instructions", "instruction")
    task_text = ""
    if task_md and Path(task_md).exists():
        task_text = Path(task_md).read_text(encoding="utf-8", errors="replace")
    elif isinstance(task_md, str):
        task_text = task_md
    if not task_text and isinstance(case.get("task"), str):
        task_text = case["task"]

    # source material: file path(s) or inline text
    src_ref = _find_case_field(case, "source", "source_file", "material", "materials", "input_file", "text", "draft")
    inline = _find_case_field(case, "text", "source_text", "content")
    source_path: Path | None = None
    if isinstance(src_ref, str) and "\n" not in src_ref and len(src_ref) < 500:
        source_path = _resolve_material(case, src_ref, base_dir)
    if source_path is None and isinstance(inline, str) and inline.strip():
        source_path = work / "source_inline.txt"
        source_path.write_text(inline, encoding="utf-8")
    if source_path is None:
        # last resort: any doc-looking file next to the case file
        for pat in ("*.md", "*.txt", "*.tex", "*.docx"):
            hits = sorted(p for p in base_dir.glob(pat) if p.name not in ("task.md", "case.json"))
            if hits:
                source_path = hits[0]
                break
    if source_path is None:
        print(json.dumps({"status": "error", "reason": "no source material found next to case.json",
                          "case_id": case_id}, ensure_ascii=False, indent=2))
        return 1

    src_text = _read_text_any(source_path)
    src_copy = work / ("source" + source_path.suffix.lower())
    if src_copy.resolve() != source_path.resolve():
        src_copy.write_text(src_text, encoding="utf-8")
    fmt = _source_format(source_path)

    # baseline audit
    ex = _audit(["extract", "--text", str(source_path), "--source-format", fmt])

    # glossary skeleton (editor fills 'preferred' / 'variants')
    glossary = {
        "version": "glossary/v1", "lang": ex["lang"],
        "terms": [{"preferred": {"zh": t["term"], "en": ""}, "variants": [], "count": t["count"], "status": "candidate"}
                  for t in ex["candidate_terms"][:25]],
    }
    (work / "glossary.json").write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")

    # constraints from the task text (best effort; editor confirms)
    constraints = {
        "target_genre": _find_case_field(case, "genre", "target_genre", "document_type", default=None),
        "target_lang": _find_case_field(case, "target_lang", "lang", "output_lang", default=ex["lang"]),
        "length_limit": _find_case_field(case, "length_limit", "word_limit", "max_words", default=None),
        "explicit_do_not": _find_case_field(case, "do_not", "constraints", "forbidden", default=None),
        "style_guide": _find_case_field(case, "style_guide", "journal", "format", default=None),
        "notes": "Values read from case.json only; null means the case did not state it. Confirm from task.md.",
    }

    state = {
        "schema": "polish-case-state/v1", "case_id": case_id, "created_at": _now(),
        "case_path": str(Path(a.case).resolve()), "source_path": str(src_copy.resolve()),
        "source_format": fmt, "lang": ex["lang"], "source_sha256": _sha(src_copy),
        "constraints": constraints,
        "baseline": {"hedges": len(ex["hedges"]), "numbers": len(ex["numbers"]), "citations": sum(len(v) for v in ex["citations"].values()),
                     "author_year": len(ex["author_year"]), "bracket_numbers": len(ex["bracket_numbers"]),
                     "sentences": ex["counts"]["sentences"], "chars": ex["counts"]["chars"]},
    }
    (work / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "baseline_extract.json").write_text(json.dumps(ex, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "revised.md").write_text(src_text + "\n\n<!-- EDIT BELOW THIS LINE; delete this comment when done -->\n", encoding="utf-8")
    (work / "ledger.json").write_text(json.dumps({"version": LEDGER_VERSION, "case_id": case_id, "edits": []}, ensure_ascii=False, indent=2), encoding="utf-8")

    # Edit brief: the one screen the editor needs before touching the text
    brief = {
        "status": "ready", "case_id": case_id, "lang": ex["lang"], "work_dir": str(work),
        "edit_target": str(work / "revised.md"), "ledger": str(work / "ledger.json"), "glossary": str(work / "glossary.json"),
        "task_excerpt": task_text[:1500] if task_text else "(task.md not found — read /input/task.md yourself)",
        "constraints": constraints,
        "protected_spans_baseline": state["baseline"],
        "hedges_to_preserve": ex["hedges"],
        "numbers_to_preserve": ex["numbers"],
        "citations_to_preserve": ex["citations"],
        "author_year_to_preserve": ex["author_year"],
        "bracket_refs_to_preserve": ex["bracket_numbers"],
        "candidate_terms": [t["term"] for t in ex["candidate_terms"][:25]],
        "style_hints_in_source": ex["style_hints"][:40],
        "edit_types_allowed": EDIT_TYPES,
        "next": "1) read task_excerpt + full /input/task.md; 2) fill glossary.json preferred/variants; "
                "3) edit revised.md sentence-by-sentence; 4) append one ledger entry per changed sentence; "
                "5) run: python run_case.py verify --case CASE --work WORK --out OUT",
    }
    (work / "edit_brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def _load_ledger(path: Path) -> dict:
    if not path.exists():
        return {"version": LEDGER_VERSION, "edits": []}
    led = json.loads(path.read_text(encoding="utf-8"))
    led.setdefault("edits", [])
    return led


def _validate_ledger(led: dict) -> list[str]:
    errs = []
    for i, e in enumerate(led.get("edits", [])):
        for f in ("edit_id", "edit_type", "source_excerpt", "revised_excerpt", "reason"):
            if not e.get(f):
                errs.append(f"edits[{i}].{f} missing")
        if e.get("edit_type") and e["edit_type"] not in EDIT_TYPES:
            errs.append(f"edits[{i}].edit_type '{e['edit_type']}' not in {EDIT_TYPES}")
        if e.get("source_excerpt") and e.get("revised_excerpt") and e["source_excerpt"] == e["revised_excerpt"]:
            errs.append(f"edits[{i}] source_excerpt == revised_excerpt (no change recorded)")
    return errs


def _classify_blocking(report: dict, ledger: dict) -> tuple[list[dict], list[dict]]:
    """Split blocking findings into explained / unexplained using ledger hedge_adjust entries."""
    explained, unexplained = [], []
    hedge_notes = " ".join(e.get("reason", "") + " " + e.get("source_excerpt", "") + " " + e.get("revised_excerpt", "")
                          for e in ledger["edits"] if e.get("edit_type") in ("hedge_adjust", "terminology", "other"))
    for b in report["blocking"]:
        dropped = b.get("dropped", [])
        # a dropped hedge/number/citation is "explained" only if a ledger entry mentions it verbatim
        if dropped and all(str(d) in hedge_notes for d in dropped):
            explained.append(b)
        else:
            unexplained.append(b)
    return explained, unexplained


def cmd_verify(a: argparse.Namespace) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    case = json.loads(Path(a.case).read_text(encoding="utf-8"))
    work = Path(a.work)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state = json.loads((work / "state.json").read_text(encoding="utf-8")) if (work / "state.json").exists() else {}
    case_id = state.get("case_id") or _find_case_field(case, "case_id", "id", default="unknown")

    src = Path(state.get("source_path", "")) if state else None
    if not src or not src.exists():
        src = _resolve_material(case, _find_case_field(case, "source", "source_file", "material", "text"), Path(a.case).resolve().parent)
    revised = Path(a.revised) if a.revised else work / "revised.md"
    ledger_path = Path(a.ledger) if a.ledger else work / "ledger.json"
    missing = [n for n, p in (("source", src), ("revised", revised), ("ledger", ledger_path)) if not p or not Path(p).exists()]
    if missing:
        print(json.dumps({"status": "error", "reason": f"missing: {missing}"}, ensure_ascii=False))
        return 1

    fmt = state.get("source_format") or _source_format(src)
    gl = work / "glossary.json"
    args = ["compare", "--source", str(src), "--revised", str(revised), "--lang", state.get("lang", "auto"), "--source-format", fmt]
    if gl.exists():
        args += ["--glossary", str(gl)]
    report = _audit(args)

    led = _load_ledger(ledger_path)
    ledger_errors = _validate_ledger(led)
    explained, unexplained = _classify_blocking(report, led)

    revised_text = revised.read_text(encoding="utf-8", errors="replace")
    revised_text_clean = re.sub(r"<!--.*?-->", "", revised_text, flags=re.S).rstrip() + "\n"
    (out / "revised.md").write_text(revised_text_clean, encoding="utf-8")
    (out / "edit_ledger.json").write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "edit_ledger.md").write_text(_ledger_md(led, case_id), encoding="utf-8")
    (out / "audit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if gl.exists():
        (out / "glossary.json").write_text(gl.read_text(encoding="utf-8"), encoding="utf-8")

    status = a.status
    if unexplained and status == "complete":
        status = "partial"
    if report["lang"] == "unknown":
        status = "partial"

    result = {
        "schema": "polish-result/v1",
        "case_id": case_id,
        "status": status,
        "generated_at": _now(),
        "input": {
            "case_path": str(Path(a.case).resolve()),
            "source_path": str(src.resolve()), "source_sha256": _sha(src), "source_format": fmt,
            "lang": state.get("lang", report["lang"]),
        },
        "outputs": {
            "revised_text": str((out / "revised.md").resolve()), "revised_sha256": _sha(out / "revised.md"),
            "edit_ledger": str((out / "edit_ledger.json").resolve()), "edit_ledger_md": str((out / "edit_ledger.md").resolve()),
            "glossary": str((out / "glossary.json").resolve()) if gl.exists() else None,
            "audit_report": str((out / "audit_report.json").resolve()),
        },
        "main_result": {
            "chars": {"source": report["counts"]["chars"]["source"], "revised": report["counts"]["chars"]["revised"]},
            "sentences": {"source": report["counts"]["sentences"]["source"], "revised": report["counts"]["sentences"]["revised"]},
            "hedges": {"source": report["hedge_strength"]["by_class"]["hedge"]["source"], "revised": report["hedge_strength"]["by_class"]["hedge"]["revised"]},
            "negation": report["hedge_strength"]["by_class"]["negation"],
            "absolute": report["hedge_strength"]["by_class"]["absolute"],
            "edits_recorded": len(led["edits"]),
            "edits_by_type": {t: sum(1 for e in led["edits"] if e.get("edit_type") == t) for t in EDIT_TYPES if any(e.get("edit_type") == t for e in led["edits"])},
        },
        "fact_and_source_mapping": {
            "numbers_changed": {"dropped": report["numbers"]["dropped"], "added": report["numbers"]["added"]},
            "citations_changed": {"dropped": report["citations"]["dropped"], "added": report["citations"]["added"]},
            "author_year_changed": {"dropped": report["author_year"]["dropped"], "added": report["author_year"]["added"]},
            "bracket_refs_changed": {"dropped": report["bracket_numbers"]["dropped"], "added": report["bracket_numbers"]["added"]},
            "hedge_words_dropped": report["hedge_strength"]["hedge_words_dropped"],
            "hedge_words_added": report["hedge_strength"]["hedge_words_added"],
            "glossary_violations_in_revised": report["glossary_violations_revised"],
            "explanation": "Each change above must map to an edit_ledger entry (edit_type, reason). Unexplained items are listed in version_and_boundaries.unexplained_changes.",
        },
        "version_and_boundaries": {
            "ledger_errors": ledger_errors,
            "unexplained_changes": unexplained,
            "explained_changes": explained,
            "style_hints_remaining_in_revised": report["style_hints_revised"][:60],
            "human_confirmation_needed": _human_flags(case, report, led),
            "limits": [
                "Audit is lexical (regex + rule tables); it cannot judge whether a rewritten clause still carries the author's intended meaning.",
                "Protected-span lists are the spans the audit could detect; a hedge phrased unusually may be missed.",
                "No external style guide was consulted unless its text was supplied in the case materials.",
            ],
        },
    }
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "case_id": case_id, "edits": len(led["edits"]),
                      "unexplained": len(unexplained), "ledger_errors": len(ledger_errors),
                      "hedges": result["main_result"]["hedges"], "result": str((out / "result.json").resolve())},
                     ensure_ascii=False, indent=2))
    return 2 if unexplained else 0


def _human_flags(case: dict, report: dict, led: dict) -> list[str]:
    flags = []
    if report["numbers"]["dropped"] or report["numbers"]["added"]:
        flags.append("Numbers or units differ between source and revision; confirm every change against the source data.")
    if report["citations"]["dropped"] or report["author_year"]["dropped"] or report["bracket_numbers"]["dropped"]:
        flags.append("At least one citation is missing from the revision.")
    dropped_hedges = report["hedge_strength"]["hedge_words_dropped"]
    if any(w in ZH_NEG_WORDS or w.lower() in EN_NEG_WORDS for w in dropped_hedges):
        flags.append("At least one negation word was dropped; confirm the polarity of each affected clause.")
    if report["hedge_strength"]["by_class"]["absolute"]["source"] != report["hedge_strength"]["by_class"]["absolute"]["revised"]:
        flags.append("Absolute quantifier count changed; confirm claim strength is intended.")
    if report["lang"] == "unknown":
        flags.append("Language could not be detected from the text; register rules may not apply.")
    return flags


def _ledger_md(led: dict, case_id: str) -> str:
    lines = [f"# Edit ledger — {case_id}", "", f"Version: `{led.get('version', LEDGER_VERSION)}` · {len(led.get('edits', []))} edits", "",
             "| # | type | source | revised | reason |", "|---|---|---|---|---|"]
    for i, e in enumerate(led.get("edits", []), 1):
        s = (e.get("source_excerpt") or "").replace("|", "\\|").replace("\n", " ")
        r = (e.get("revised_excerpt") or "").replace("|", "\\|").replace("\n", " ")
        why = (e.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | {e.get('edit_type', '')} | {s} | {r} | {why} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--case", required=True)
    i.add_argument("--task-md")
    i.add_argument("--work", default=os.environ.get("WORK_DIR", "/app/work"))
    i.set_defaults(fn=cmd_init)
    v = sub.add_parser("verify")
    v.add_argument("--case", required=True)
    v.add_argument("--work", default=os.environ.get("WORK_DIR", "/app/work"))
    v.add_argument("--out", default=os.environ.get("OUT_DIR", "/app/output"))
    v.add_argument("--revised")
    v.add_argument("--ledger")
    v.add_argument("--status", default="complete", choices=["complete", "partial"])
    v.set_defaults(fn=cmd_verify)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
