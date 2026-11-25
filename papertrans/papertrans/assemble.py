#!/usr/bin/env python3
"""
papertrans.assemble — Restore placeholders (TERM → locked target), emit bilingual deliverables.

Outputs (under --out-dir):
  bilingual.md        — 段落级中英对照，每段带 [Sxxx | role | p.N | bbox | verdict] 定位头
  bilingual.json      — [{id, page, bbox, role, source, target, verdict, issues, marks:[{ph,kind,src,tgt}]}]
  result.json         — 平台要求的结构化结果（status/sources/uncertainty/change_records…）
  glossary_used.json  — 术语表 + 每术语出现次数与一致性结果
  references.md       — 未翻译的参考文献块（原样保留）
Term back-fill: a TERM placeholder restored by `restore()` yields the SOURCE string; here we instead
replace it with the locked TARGET (or keep source if status=keep). After back-fill we assert that
no locked source surface remains in the target text → term consistency is checked, not assumed.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .protect import marks_from_json, PLACEHOLDER_RE

ROLE_ZH = {"title": "标题", "heading": "小标题", "body": "正文", "caption": "图表题注", "equation": "公式",
           "list": "列表", "footnote": "脚注", "table": "表格", "reference": "参考文献"}


def backfill(target_raw: str, marks_json: list[dict], glossary: dict[str, Any]) -> tuple[str, list[dict], list[dict]]:
    """Replace placeholders in the raw translation: TERM → locked target; others → original span."""
    marks = marks_from_json(marks_json)
    by_ph = {m.surface: m for m in marks}
    log: list[dict] = []
    issues: list[dict] = []

    def sub(m: re.Match) -> str:
        mk = by_ph.get(m.group(0))
        if mk is None:
            return m.group(0)
        if mk.kind == "TERM":
            t = glossary.get(mk.term_id, {})
            tgt = (t.get("target") or "").strip()
            if t.get("status") == "keep" or not tgt:
                log.append({"ph": mk.surface, "kind": "TERM", "src": mk.original, "tgt": mk.original, "action": "keep"})
                return mk.original
            log.append({"ph": mk.surface, "kind": "TERM", "src": mk.original, "tgt": tgt, "action": "backfill"})
            return tgt
        log.append({"ph": mk.surface, "kind": mk.kind, "src": mk.original, "tgt": mk.original, "action": "restore"})
        return mk.original

    out = PLACEHOLDER_RE.sub(sub, target_raw)
    leftover = PLACEHOLDER_RE.findall(out)
    if leftover:
        issues.append({"type": "placeholder_leftover", "severity": "fail", "tokens": sorted(set(leftover))[:5]})
    return out, log, issues


def term_consistency(targets: list[str], glossary: dict[str, Any]) -> dict[str, Any]:
    """For each active term: occurrences of locked target vs. leaked source surfaces in the whole output."""
    from .protect import term_pattern

    report = {}
    for tid, t in glossary.items():
        if t.get("status") not in ("approved", "keep") or not t.get("source"):
            continue
        src_re = re.compile(r"(?<![A-Za-z])(?:" + term_pattern(t["source"]) + r")(?![A-Za-z])", re.I)
        tgt = (t.get("target") or t["source"]).strip()
        n_src_leak = sum(len(src_re.findall(x)) for x in targets)
        n_tgt = sum(x.count(tgt) for x in targets) if t.get("status") == "approved" else n_src_leak
        consistent = (n_src_leak == 0) if t.get("status") == "approved" else True
        report[tid] = {"source": t["source"], "target": tgt, "status": t["status"],
                       "n_target": n_tgt, "n_source_leak": n_src_leak, "consistent": consistent}
    n_terms = len(report)
    return {"n_terms": n_terms, "n_consistent": sum(1 for v in report.values() if v["consistent"]),
            "consistency_rate": round(sum(1 for v in report.values() if v["consistent"]) / n_terms, 4) if n_terms else 1.0,
            "terms": report}


def assemble(seg: dict[str, Any], translations: dict[str, str], verify_res: dict[str, Any], marks: dict[str, list],
              glossary: dict[str, Any], doc_meta: dict[str, Any], out_dir: Path, case: dict[str, Any],
              lang: str = "zh", refs_md: str = "") -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    verdict_by_id = {r["id"]: r for r in verify_res["segments"]}
    verbatim = [v for v in seg.get("verbatim_blocks", []) if v.get("role") == "author"]
    author_lines = [v["text"] for v in verbatim]
    rows = []
    for s in seg["segments"]:
        raw = translations.get(s["id"], "")
        v = verdict_by_id.get(s["id"], {})
        if not raw.strip():
            rows.append({"id": s["id"], "page": s["page"], "pages": s.get("pages"), "bbox": s["bbox"], "role": s["role"],
                         "source": s["text"], "target": "", "verdict": "fail", "issues": [{"type": "missing_translation"}],
                         "marks": [], "backfill": []})
            continue
        final, log, extra_issues = backfill(raw, marks.get(s["id"], []), glossary)
        issues = list(v.get("issues", [])) + extra_issues
        verdict = v.get("verdict", "fail")
        if extra_issues and verdict != "fail":
            verdict = "fail"
        rows.append({"id": s["id"], "page": s["page"], "pages": s.get("pages"), "bbox": s["bbox"], "role": s["role"],
                     "source": s["text"], "target": final, "verdict": verdict, "issues": issues,
                     "marks": [{k: m[k] for k in ("ph", "kind", "src", "tgt", "action")} for m in log],
                     "backfill": [m["tgt"] for m in log if m["kind"] == "TERM"]})
    # term consistency over final targets
    tcons = term_consistency([r["target"] for r in rows], glossary)
    s = verify_res["summary"]
    status = "success" if s["verdicts"]["fail"] == 0 and not s["missing"] else ("partial" if s["n_translated"] else "failed")
    # ---- bilingual.md
    lines = [f"# {doc_meta.get('title') or case.get('title') or 'Bilingual translation'}"]
    if author_lines:
        lines.append("")
        lines.append("> 作者（按原文保留，不翻译）：" + " · ".join(a.strip() for a in author_lines if a.strip()))
    lines += [
             f"- 源文件: `{doc_meta.get('source')}` · 页数 {doc_meta.get('n_pages')} · 解析后端 {doc_meta.get('backend')}",
             f"- 目标语言: {lang} · 段落 {s['n_segments']} · 已译 {s['n_translated']} · 结论 pass/warn/fail = {s['verdicts']['pass']}/{s['verdicts']['warn']}/{s['verdicts']['fail']}",
             f"- 占位符完整性: {s['placeholder_integrity']['found']}/{s['placeholder_integrity']['expected']} · 术语一致率: {tcons['consistency_rate']:.0%} ({tcons['n_consistent']}/{tcons['n_terms']}) · 译者标注不确定: {s['unsure_markers']}",
             "", "每段格式：`[段号 | 角色 | 页 | 位置 | 核验]`，原文在前，译文在后。`⟦..⟧` 为保护标记（数字/引用/交叉引用/公式/锁定术语），译文中原样还原。", ""]
    for r in rows:
        pages = ",".join(str(p) for p in (r.get("pages") or [r["page"]]))
        bbox = ",".join(str(x) for x in r["bbox"]) if r["bbox"] else "-"
        flag = {"pass": "✓", "warn": "⚠", "fail": "✗"}[r["verdict"]]
        lines.append(f"### [{r['id']} | {ROLE_ZH.get(r['role'], r['role'])} | p.{pages} | {bbox} | {flag}]")
        lines.append("")
        lines.append(r["source"])
        lines.append("")
        lines.append(r["target"] or "（未翻译）")
        if r["issues"]:
            iss = "; ".join(f"{i['type']}" + (f"({','.join(map(str, i.get('values', [])))})" if i.get("values") else "") for i in r["issues"])
            lines.append("")
            lines.append(f"> 核验: {iss}")
        lines.append("")
    (out_dir / "bilingual.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "bilingual.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    gl_out = {"terms": glossary, "consistency": tcons["terms"], "consistency_rate": tcons["consistency_rate"]}
    (out_dir / "glossary_used.json").write_text(json.dumps(gl_out, ensure_ascii=False, indent=1), encoding="utf-8")
    # ---- result.json (contract)
    result = {
        "case_id": case.get("case_id"),
        "task": case.get("task"),
        "status": status,
        "target_lang": lang,
        "summary": {
            "segments_total": s["n_segments"], "segments_translated": s["n_translated"],
            "coverage": round(s["n_translated"] / s["n_segments"], 4) if s["n_segments"] else 0,
            "verdicts": s["verdicts"], "placeholder_integrity": s["placeholder_integrity"],
            "term_consistency_rate": tcons["consistency_rate"], "term_count": tcons["n_terms"],
            "unsure_markers": s["unsure_markers"], "issue_counts": s["issue_counts"],
            "duplicate_groups": s["duplicate_groups"],
        },
        "result": {"bilingual": "bilingual.md", "bilingual_json": "bilingual.json", "glossary": "glossary_used.json",
                   "references": "references.md" if refs_md else None},
        "evidence": {
            "source_file": doc_meta.get("source"), "n_pages": doc_meta.get("n_pages"), "parser": doc_meta.get("backend"),
            "title_source": doc_meta.get("title"),
            "authors_verbatim": [{"page": v["page"], "block": v["block"], "text": v["text"]} for v in verbatim],
            "segment_locator": "bilingual.json[].{page,pages,bbox,source_blocks}",
            "per_segment_verdicts": "verify.json", "per_segment_marks": "bilingual.json[].marks",
        },
        "uncertainty": {
            "missing_segments": s["missing"], "translator_unsure_markers": s["unsure_markers"],
            "warn_segments": [r["id"] for r in rows if r["verdict"] == "warn"],
            "fail_segments": [r["id"] for r in rows if r["verdict"] == "fail"],
            "term_inconsistencies": [k for k, v in tcons["terms"].items() if not v["consistent"]],
            "excluded_blocks_not_translated": [{"page": e["page"], "block": e["block"], "role": e["role"]} for e in seg.get("excluded_blocks", [])][:200],
            "parser_warnings": doc_meta.get("warnings", []),
        },
        "change_records": case.get("change_records", []),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if refs_md:
        (out_dir / "references.md").write_text(refs_md, encoding="utf-8")
    return result


def references_markdown(excluded: list[dict]) -> str:
    refs = [e for e in excluded if e["role"] == "reference"]
    if not refs:
        return ""
    lines = ["# References（按原文保留，不翻译）", ""]
    for e in refs:
        lines.append(f"- [p.{e['page']} | {e['block']}] {e['text']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="papertrans.assemble")
    ap.add_argument("segments_json")
    ap.add_argument("translations_json")
    ap.add_argument("verify_json")
    ap.add_argument("--marks", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--doc", required=True, help="parsed doc.json for metadata")
    ap.add_argument("--case", help="case.json for case_id/task")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--lang", default="zh")
    a = ap.parse_args(argv)
    seg = json.loads(Path(a.segments_json).read_text(encoding="utf-8"))
    tr = json.loads(Path(a.translations_json).read_text(encoding="utf-8"))
    if isinstance(tr, dict) and "translations" in tr and isinstance(tr["translations"], dict):
        tr = tr["translations"]
    ver = json.loads(Path(a.verify_json).read_text(encoding="utf-8"))
    marks = json.loads(Path(a.marks).read_text(encoding="utf-8"))
    gl = json.loads(Path(a.glossary).read_text(encoding="utf-8"))
    doc = json.loads(Path(a.doc).read_text(encoding="utf-8"))
    case = json.loads(Path(a.case).read_text(encoding="utf-8")) if a.case and Path(a.case).exists() else {}
    if isinstance(case, dict) and "content" in case and isinstance(case["content"], dict):
        case = case["content"]
    res = assemble(seg, tr, ver, marks, gl, doc, Path(a.out_dir), case, a.lang, references_markdown(seg.get("excluded_blocks", [])))
    print(f"[assemble] status={res['status']} coverage={res['summary']['coverage']} term_consistency={res['summary']['term_consistency_rate']} → {a.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
