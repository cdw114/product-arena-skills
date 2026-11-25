#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_case — entry point of the introduction / related-work writing skill.

    python3 scripts/run_case.py --input /input --out /app/output --work /app/work

Three stages, each safe to re-run and idempotent:

    plan      read every input file, build the reference library and the
              manuscript index, emit the ledgers' templates and the writing
              scaffold, and immediately write a `status: partial` result.json
              so that a run that is cut short still leaves something honest.
    audit     read work/draft.md + the four ledgers, run the 18 deterministic
              checks, write work/audit.json, /app/output/audit_report.{json,md}
    finalize  render the deliverables and the final result.json

`--stage auto` runs plan, then audit+finalize if a draft exists.

Exit codes: 0 result.json written (success or partial); 2 unrecoverable input
problem (a status=failed result.json is still written).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import introlib as L          # noqa: E402
import audit_rules as A       # noqa: E402
import render as R            # noqa: E402

SKILL_VERSION = "1.0.0"
NOW_YEAR = datetime.date.today().year

LOG = []


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    LOG.append(line)
    print(line, file=sys.stderr)


def write_json(path, obj):
    """Write UTF-8 with LF newlines on every platform: the bundle is diffed and
    shipped as text, so a CRLF-vs-LF difference between artifacts is noise."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# --------------------------------------------------------------------------- #
# case.json
# --------------------------------------------------------------------------- #

CASE_KEYS_KNOWN = {
    "case_id", "id", "task", "instruction", "prompt", "question", "request",
    "output_contract", "materials", "manuscript", "library", "bibliography",
    "references", "figures", "source", "documents", "target_genre", "target_lang",
    "citation_style", "length_limit", "audience", "notes", "inputs", "files",
}


def load_case(input_dir):
    """Read case.json with field-name tolerance. Never raises."""
    path = None
    for cand in ("case.json", "case.CASE.json", "case.yaml", "case.yml", "task.json"):
        p = os.path.join(input_dir, cand)
        if os.path.isfile(p):
            path = p
            break
    case = {}
    problems = []
    if path and path.endswith(".json"):
        try:
            obj = json.loads(L.read_text(path))
            if isinstance(obj, dict):
                case = obj
            else:
                problems.append("case.json is not an object")
        except Exception as exc:
            problems.append("case.json unreadable: %s" % exc)
    elif path:
        problems.append("case file %s is not JSON; fields ignored" % os.path.basename(path))

    def first(*names, default=None):
        for n in names:
            if n in case and case[n] not in (None, "", [], {}):
                return case[n]
        return default

    case_id = first("case_id", "id", "caseId", "slug", default=None)
    if not case_id:
        case_id = re.sub(r"[^A-Za-z0-9_.-]", "-", os.path.basename(input_dir.rstrip("/\\"))) or "unknown"
        problems.append("case_id absent; derived from directory name")
    task = first("task", "instruction", "prompt", "question", "request", "description", default="")
    if not isinstance(task, str):
        task = json.dumps(task, ensure_ascii=False)
    contract = case.get("output_contract")
    return {
        "case_id": str(case_id),
        "task": task,
        "output_contract": contract,
        "target_genre": first("target_genre", "genre", "audience", default=""),
        "target_lang": first("target_lang", "language", "lang", default=""),
        "citation_style": first("citation_style", "style", "citation", "reference_style", default=""),
        "length_limit": first("length_limit", "word_limit", "limit", default=None),
        "raw_keys": sorted(case.keys()),
        "declared_materials": first("materials", "inputs", "files", "documents", default=[]),
        "path": path,
        "problems": problems,
        "raw": case,
    }


def contract_field_names(contract):
    """The list of field names result.json must carry."""
    if not contract:
        return []
    if isinstance(contract, str):
        return [x.strip() for x in re.split(r"[,;，；\s]+", contract) if x.strip()]
    if isinstance(contract, list):
        return [str(x).strip() for x in contract if str(x).strip()]
    if isinstance(contract, dict):
        for k in ("required", "fields", "must_have", "required_fields", "keys"):
            v = contract.get(k)
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
        if all(isinstance(v, str) for v in contract.values()):
            return [str(k) for k in contract.keys()]
        for k in ("required", "fields"):
            if isinstance(contract.get(k), dict):
                return list(contract[k].keys())
        return [str(k) for k in contract.keys()]
    return []


FIELD_SYNONYMS = {
    "introduction": "introduction_related_work",
    "intro": "introduction_related_work",
    "section": "introduction_related_work",
    "manuscript_section": "introduction_related_work",
    "background": "background",
    "research_background": "background",
    "related_work": "related_work",
    "literature_review": "related_work",
    "gap": "research_gap",
    "research_gap": "research_gap",
    "contributions": "contributions",
    "contribution": "contributions",
    "citations": "citation_map",
    "citation_map": "citation_map",
    "references": "references_used",
    "references_used": "references_used",
    "bibliography": "references_used",
    "figures": "contribution_map",
    "tables": "contribution_map",
    "evidence": "evidence",
    "sources": "sources",
    "changes": "changes",
    "change_log": "changes",
    "audit": "audit",
    "checks": "audit",
    "status": "status",
    "uncertainty": "uncertainty",
    "limits": "uncertainty",
    "uncertainties": "uncertainty",
    "notes": "uncertainty",
    "case_id": "case_id",
    "result": "result",
    "text": "introduction_related_work",
    "markdown": "introduction_related_work",
    "outline": "result",
    "summary": "result",
}


# --------------------------------------------------------------------------- #
# task intent
# --------------------------------------------------------------------------- #

INTENT_PATTERNS = [
    ("revise", r"修改|改写|润色|校对|重写|修订|improve|revise|rewrite|polish|edit|proofread"),
    ("draft", r"撰写|写|起草|生成|补充|draft|write|compose|generate"),
    ("citations", r"引用|文献|citation|reference|引文"),
    ("bilingual", r"双语|中英|翻译|bilingual|translate"),
    ("format", r"格式|模板|latex|word|docx|markdown|GB/T|APA|IEEE|Vancouver"),
]


def detect_intent(task, manuscript, draft_exists):
    t = task or ""
    hits = [name for name, pat in INTENT_PATTERNS if re.search(pat, t, re.I)]
    if not hits:
        hits = ["draft"]
    mode = "revise" if ("revise" in hits and manuscript.get("intro_sections")) else "draft"
    if mode == "revise" and not manuscript.get("intro_sections"):
        mode = "draft"
    return {"intents": hits, "mode": mode, "has_existing_intro": bool(manuscript.get("intro_sections")),
            "draft_present": draft_exists}


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

def stage_plan(case, input_dir, work, out):
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    snaps = os.path.join(work, "snapshots")
    os.makedirs(snaps, exist_ok=True)

    materials = L.discover_materials(input_dir,
                                     exclude=[case.get("path"), os.path.join(input_dir, "task.md")])
    task_md = ""
    for n in ("task.md", "TASK.md", "task.txt"):
        p = os.path.join(input_dir, n)
        if os.path.isfile(p):
            task_md = L.read_text(p)
            break
    if task_md:
        materials.append({"path": os.path.join(input_dir, "task.md"), "name": "task.md",
                          "ext": ".md", "kind": "task", "size": len(task_md), "text": task_md,
                          "note": "task statement"})

    manus = [m for m in materials if m["kind"] == "manuscript"]
    if not manus:
        # last resort: the longest text that is not the task statement
        cand = [m for m in materials if m["kind"] != "task" and len(m["text"]) > 200]
        cand.sort(key=lambda m: -len(m["text"]))
        manus = cand[:1]
        for m in manus:
            m["kind"] = "manuscript"
            m["note"] = "classified as manuscript by size fallback"

    ms_path = (case.get("raw") or {}).get("manuscript") or (case.get("raw") or {}).get("source")
    if isinstance(ms_path, str) and os.path.isfile(os.path.join(input_dir, ms_path)):
        p = os.path.join(input_dir, ms_path)
        if not any(os.path.abspath(m["path"]) == os.path.abspath(p) for m in manus):
            manus.insert(0, {"path": p, "name": os.path.basename(p), "ext": os.path.splitext(p)[1],
                             "kind": "manuscript", "size": os.path.getsize(p),
                             "text": L.read_text(p), "note": "named by case.json"})

    if manus:
        manuscript = L.parse_manuscript(manus[0]["text"], manus[0]["path"])
        for m in manus[1:]:
            extra = L.parse_manuscript(m["text"], m["path"])
            manuscript["figures"] += extra["figures"]
            manuscript["tables"] += extra["tables"]
            manuscript["sections"] += extra["sections"]
            manuscript["numbers"] = sorted(set(manuscript["numbers"]) | set(extra["numbers"]))
            manuscript["text"] += "\n\n" + m["text"]
        manuscript["all_materials"] = [m["path"] for m in manus]
    else:
        manuscript = L.parse_manuscript("", "")

    library = L.build_library(materials)
    if not library["entries"] and manuscript.get("reflist"):
        lib, merge_log = L.dedupe_entries([dict(e, source="manuscript_reflist")
                                           for e in manuscript["reflist"]])
        for e in lib:
            e.setdefault("must_cite", False)
            e.setdefault("role", "")
            e.setdefault("cluster", "")
            e.setdefault("notes", "")
        library = {"entries": lib, "n_raw": len(manuscript["reflist"]), "sources": [
            {"path": manuscript["path"], "format": "manuscript_reflist", "n": len(lib)}],
            "formats": ["manuscript_reflist"], "merge_log": merge_log,
            "log": ["library fallback: built from the manuscript's own reference list"],
            "fallback": "manuscript_reflist"}

    for m in materials:
        try:
            if os.path.isfile(m["path"]) and m["kind"] in ("manuscript", "library"):
                dst = os.path.join(snaps, os.path.basename(m["path"]))
                if not os.path.exists(dst):
                    shutil.copy2(m["path"], dst)
        except OSError:
            pass

    library = L.link_reflist(manuscript, library)
    if library.get("reflist_links"):
        log("reflist links: %s" % json.dumps(library["reflist_links"]))

    draft_path = os.path.join(work, "draft.md")
    intent = detect_intent(case["task"] or task_md, manuscript, os.path.isfile(draft_path))
    lang = (case.get("target_lang") or "").strip() or manuscript.get("lang") or "zh"
    lang = "zh" if str(lang).lower().startswith("zh") or "chin" in str(lang).lower() else "en"
    style = (case.get("citation_style") or "").strip()
    if not style:
        style = L.citation_style_of(manuscript.get("text") or "")
    if style in ("", "none", "mixed"):
        # a manuscript with no citation markers yet cannot dictate a style
        style = "numeric" if lang == "zh" else "author-year"
    if str(style).lower() in ("gbt7714", "gb/t 7714", "gbt"):
        style = "numeric"

    intake = {
        "case_id": case["case_id"], "skill_version": SKILL_VERSION, "generated_at": _now_iso(),
        "task": (case["task"] or task_md)[:4000],
        "task_source": "case.json" if case["task"] else ("task.md" if task_md else "none"),
        "intent": intent, "lang": lang, "citation_style": style,
        "target_genre": case.get("target_genre") or "", "length_limit": case.get("length_limit"),
        "output_contract": case.get("output_contract"),
        "output_contract_fields": contract_field_names(case.get("output_contract")),
        "case_json_problems": case["problems"],
        "materials": [{"path": m["path"], "kind": m["kind"], "ext": m["ext"],
                       "bytes": m["size"], "note": m.get("note", "")} for m in materials],
        "manuscript": {k: manuscript[k] for k in
                       ("path", "chars", "words", "lang", "title", "abstract", "keywords",
                        "section_titles", "intro_sections", "reflist_n")},
        "manuscript_index_summary": {
            "figures": [f["label"] for f in manuscript["figures"]],
            "tables": [t["label"] for t in manuscript["tables"]],
            "equations": len(manuscript["equations"]),
        },
        "library": {"n": len(library["entries"]), "fallback": library["fallback"],
                    "sources": library["sources"], "log": library["log"]},
        "log": LOG[:],
    }
    write_json(os.path.join(work, "intake.json"), intake)
    write_json(os.path.join(work, "library.json"),
               {"entries": library["entries"], "n_raw": library["n_raw"], "merge_log": library["merge_log"],
                "sources": library["sources"], "fallback": library["fallback"]})
    write_json(os.path.join(work, "manuscript_index.json"),
               {k: v for k, v in manuscript.items() if k != "text"} | {"manuscript_text": manuscript.get("text") or ""})

    for kind, spec in L.LEDGER_SPEC.items():
        tpl = os.path.join(work, "ledgers", (spec["file"] or "").replace(".json", ".template.json"))
        os.makedirs(os.path.dirname(tpl), exist_ok=True)
        write_json(tpl, _ledger_template(kind, library, manuscript, lang))
        real = os.path.join(work, "ledgers", spec["file"])
        if not os.path.isfile(real):
            write_json(real, _ledger_template(kind, library, manuscript, lang, guidance=True))

    write_text(os.path.join(work, "scaffold.md"),
               _scaffold(library, manuscript, lang, style, intent, case))

    log("materials=%d manuscript=%dch library=%d refs figures=%d tables=%d lang=%s style=%s"
        % (len(materials), manuscript["chars"], len(library["entries"]),
           len(manuscript["figures"]), len(manuscript["tables"]), lang, style))

    state = {
        "case_id": case["case_id"], "lang": lang, "style": style, "intent": intent,
        "started_at": _now_iso(), "stage": "plan",
        "library_sha": L.sha256_text(json.dumps(library["entries"], ensure_ascii=False)),
        "manuscript_sha": L.sha256_text(manuscript.get("text") or ""),
        "warnings": list(case["problems"]),
    }
    if not library["entries"]:
        state["warnings"].append("library empty: citation checks cannot resolve anything")
    if not manuscript["chars"]:
        state["warnings"].append("no manuscript text found: contribution evidence cannot be resolved")
    if library["fallback"] == "manuscript_reflist":
        state["warnings"].append("library rebuilt from the manuscript reference list")
    write_json(os.path.join(work, "state.json"), state)

    ctx = _build_ctx(case, work, manuscript, library, lang, style, intent)
    res = _result_skeleton(case, ctx, work)
    _fill_contract(case, res)
    res["status"]["state"] = "partial"
    res["status"]["reason"] = ("规划完成，等待成稿与账本：%s 与 work/ledgers/*.json 写好后再跑 "
                               "--stage audit / --stage finalize" % os.path.join(work, "draft.md"))
    write_json(os.path.join(out, "result.json"), res)
    return ctx


def _now_iso():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _ledger_template(kind, library, manuscript, lang, guidance=False):
    zh = lang == "zh"
    if kind == "refs":
        rows = []
        for e in library["entries"]:
            rows.append({
                "ref_id": e["ref_id"],
                "title": e.get("title", "")[:160],
                "year": e.get("year"),
                "one_line": "",
                "role": "",
                "cluster": "",
                "must_cite": False,
            })
        obj = {"case_id": None,
               "note": ("每篇文献一行：role ∈ seminal/representative/recent/baseline/survey/application/other；"
                        "cluster 用你决定的分组名；must_cite=true 表示这篇必须进正文。one_line 用一句话写清这篇做了什么、"
                        "结论、适用条件。" if zh else
                        "One row per reference. role in seminal/representative/recent/baseline/survey/application/other; "
                        "cluster is your group name; must_cite=true forces a citation in the draft."),
               "entries": rows}
        return obj
    if kind == "groups":
        return {"case_id": None,
                "note": ("按问题/方法路线/评价方式分组，每组≥2 篇。works[].ref_id 必须来自 library.json；"
                         "method_route/data_setting/evaluation/conclusion/limitation 五个字段都要填；"
                         "comparison.dimension 写比较维度，comparison.tradeoff 写组内取舍结论。" if zh else
                         "Group by problem / method route / evaluation. At least 2 works per group; every work needs "
                         "method_route, data_setting, evaluation, conclusion, limitation; comparison.dimension and "
                         "comparison.tradeoff are mandatory."),
                "groups": [{"group_id": "G1", "label": "", "dimension": "",
                            "works": [{"ref_id": "", "method_route": "", "data_setting": "",
                                       "evaluation": "", "conclusion": "", "limitation": ""}],
                            "comparison": {"dimension": "", "tradeoff": "", "best_for": ""}}]}
    if kind == "gaps":
        return {"case_id": None,
                "note": ("每条空白都要 derived_from：至少一篇已引文献 + 缺口类型 + 证据；"
                         "limitation_kind ∈ shared_limitation/uncovered_scenario/conflicting_conclusions/"
                         "evaluation_gap/method_gap/data_gap；evidence.kind ∈ quote/paraphrase/author_judgment，"
                         "quote 必须能在该文献摘要里找到原文；how_filled.contribution_ids 指向贡献账本。" if zh else
                         "Every gap needs derived_from (cited ref + limitation_kind + evidence) and "
                         "how_filled.contribution_ids pointing at the contribution ledger. evidence.kind is "
                         "quote/paraphrase/author_judgment; a quote must appear verbatim in that reference's text."),
                "gaps": [{"gap_id": "PG1", "statement": "",
                          "derived_from": [{"ref_id": "", "limitation_kind": "shared_limitation",
                                            "evidence": {"kind": "quote", "text": ""}}],
                          "how_filled": {"contribution_ids": ["C1"], "mechanism": ""},
                          "confidence": "medium"}]}
    return {"case_id": None,
            "note": ("每条贡献都要 evidence：locator_type ∈ figure/table/section/result/equation，"
                     "locator 写正文里真实存在的定位（如 'Fig. 3'、'Table 2'、'4.2'），"
                     "result 类型必须给 claim_in_source 原文；scope 写不主张的范围。" if zh else
                     "Each contribution needs evidence: locator_type in figure/table/section/result/equation and a "
                     "locator that really exists in the manuscript; the result type needs claim_in_source; scope "
                     "records what is not claimed."),
            "contributions": [{"contribution_id": "C1", "text": "", "kind": "method",
                               "evidence": [{"locator_type": "section", "locator": "",
                                             "claim_in_source": ""}],
                               "scope": {"stated_limits": "", "not_claimed": ""}}]}


def _scaffold(library, manuscript, lang, style, intent, case):
    zh = lang == "zh"
    out = []
    out.append("# %s\n" % ("写作脚手架（示例结构，不是答案）" if zh else "Writing scaffold (structure only, not an answer)"))
    out.append("## %s\n" % ("已读取的材料" if zh else "Inputs read"))
    out.append("- case_id: `%s`" % case["case_id"])
    if zh:
        out.append("- 稿件：%d 字符，%d 图，%d 表，文末参考文献表 %d 条"
                   % (manuscript["chars"], len(manuscript["figures"]),
                      len(manuscript["tables"]), manuscript["reflist_n"]))
        out.append("- 文献库：%d 条（来源 %s）" % (len(library["entries"]), library["fallback"]))
        out.append("- 语言：%s ／ 引用格式：%s\n" % (lang, style))
    else:
        out.append("- manuscript: %d chars, %d figures, %d tables, %d reference-list entries"
                   % (manuscript["chars"], len(manuscript["figures"]),
                      len(manuscript["tables"]), manuscript["reflist_n"]))
        out.append("- library: %d entries (source: %s)" % (len(library["entries"]), library["fallback"]))
        out.append("- language: %s / citation style: %s\n" % (lang, style))

    out.append("## %s\n" % ("可引用的文献（只能用这些键）" if zh else "Available references (use only these)"))
    out.append("| ref_id | key | year | title |")
    out.append("|---|---|---|---|")
    for e in library["entries"][:200]:
        out.append("| %s | %s | %s | %s |" % (e["ref_id"], e.get("key") or "-", e.get("year") or "-",
                                              (e.get("title") or "")[:110].replace("|", "/")))
    out.append("")

    out.append("## %s\n" % ("可指向的证据定位" if zh else "Evidence locators that exist"))
    out.append("- figures: %s" % (", ".join(f["label"] for f in manuscript["figures"]) or "-"))
    out.append("- tables: %s" % (", ".join(t["label"] for t in manuscript["tables"]) or "-"))
    secs = ["%s %s" % (s.get("number") or "", s.get("title") or "") for s in manuscript["sections"][:30]]
    out.append("- sections: %s\n" % ("; ".join(x.strip() for x in secs) or "-"))

    out.append("## %s\n" % ("成稿骨架（把 <!-- part:... --> 之间填满，不要删标记）"
                            if zh else "Draft skeleton (fill between the markers, keep them)"))
    heads = {"background": ("## 1 研究背景", "## 1 Background"),
             "related_work": ("## 2 相关工作", "## 2 Related Work"),
             "gap": ("## 3 研究空白", "## 3 Research Gap"),
             "contributions": ("## 4 主要贡献", "## 4 Contributions")}
    hints = {
        "background": ("2–3 段。第 1 段：领域脉络 + 具体技术约束，禁止“近年来受到广泛关注”“随着……的快速发展”。"
                       "第 2 段：现有路线各自卡在哪一个具体环节。每段至少 1 个引用。",
                       "2-3 paragraphs. P1: the specific problem and technical constraint. No 'has attracted "
                       "widespread attention'. P2: where each existing route actually breaks. Every paragraph cites."),
        "related_work": ("按 G1/G2… 分组，每组 1 段。每组必须横向比较（而/相比之下/优于/代价），不能逐篇摘要。",
                         "One paragraph per group G1/G2..., each comparing works on the same dimension."),
        "gap": ("1 段：由 G 组共同的局限/未覆盖场景/相互冲突的结论推出空白，再用一句话说明本文如何填补"
                "（出现“本文/本研究/we/our work”）。至少 1 个引用。",
                "1 paragraph: derive the gap from the groups' shared limits, then say how this paper fills it. "
                "At least one citation."),
        "contributions": ("3–5 条要点。每条必须对应上面列出的图/表/章节/结果数值；拔高表述（首次/首个/最优）"
                          "必须在 scope 里写明适用范围。",
                          "3-5 bullets, each mapped to a figure/table/section/result above."),
    }
    for p in L.PART_ORDER:
        h = heads[p][0] if zh else heads[p][1]
        hint = hints[p][0] if zh else hints[p][1]
        out.append("<!-- part:%s -->" % p)
        out.append(h)
        out.append("")
        out.append("<!-- %s -->" % L.norm_ws(hint))
        out.append("")
        out.append("<!-- /part:%s -->" % p)
        out.append("")
    out.append("## %s\n" % ("写完后" if zh else "When done"))
    out.append("```bash\npython3 scripts/run_case.py --input /input --out /app/output --work /app/work --stage audit\n```\n")
    out.append("%s" % ("按 audit_report.md 里的 ERROR 逐条修 draft.md 与账本，再跑一次；gate=pass 后 --stage finalize。"
                       if zh else
                       "Fix every ERROR in audit_report.md, re-run audit, then finalize when gate=pass."))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# context
# --------------------------------------------------------------------------- #

def _build_ctx(case, work, manuscript, library, lang, style, intent):
    ledgers = {}
    problems = {}
    for kind, spec in L.LEDGER_SPEC.items():
        obj, probs = L.load_ledger(os.path.join(work, "ledgers", spec["file"]), kind)
        ledgers[kind] = obj
        problems[kind] = probs
    return {
        "case": case, "case_id": case["case_id"], "work": work,
        "manuscript": manuscript, "library": library, "lib_index": L.library_index(library),
        "reflist": manuscript.get("reflist") or [],
        "ledgers": ledgers, "ledger_problems": problems,
        "lang": lang, "target_citation_style": style, "intent": intent,
        "now_year": NOW_YEAR,
        "draft": L.parse_draft("", lang),
    }


def _load_draft(ctx):
    p = os.path.join(ctx["work"], "draft.md")
    if os.path.isfile(p):
        text = L.read_text(p)
    else:
        text = ""
    ctx["draft"] = L.parse_draft(text, ctx["lang"])
    ctx["draft"]["path"] = p
    return ctx["draft"]


# --------------------------------------------------------------------------- #
# result.json
# --------------------------------------------------------------------------- #

def _result_skeleton(case, ctx, work):
    return {
        "case_id": case["case_id"],
        "skill": {"name": "intrograph", "version": SKILL_VERSION},
        "generated_at": _now_iso(),
        "status": {"state": "partial", "gate": None, "reason": "", "limits": [], "notes": []},
        "task": {"text": (case["task"] or "")[:4000], "intent": ctx["intent"],
                 "lang": ctx["lang"], "citation_style": ctx["target_citation_style"],
                 "genre": case.get("target_genre") or "", "length_limit": case.get("length_limit")},
        "inputs": {
            "case_json": case.get("path"),
            "case_json_problems": case["problems"],
            "output_contract": case.get("output_contract"),
            "output_contract_fields": contract_field_names(case.get("output_contract")),
            "manuscript": {k: ctx["manuscript"].get(k) for k in
                           ("path", "chars", "words", "lang", "title", "section_titles",
                            "intro_sections", "reflist_n")},
            "library": {"n": len(ctx["library"]["entries"]), "sources": ctx["library"]["sources"],
                        "fallback": ctx["library"]["fallback"]},
        },
        "result": {},
        "introduction_related_work": None,
        "background": None,
        "related_work": None,
        "research_gap": None,
        "contributions": None,
        "citation_map": [],
        "contribution_map": [],
        "references_used": [],
        "evidence": {},
        "audit": None,
        "uncertainty": {"unresolved_citations": [], "ambiguous_citations": [],
                        "unchecked_quotes": [], "author_judgments": [],
                        "notes": [], "not_done": []},
        "changes": [],
        "sources": [],
        "artifacts": {},
        "environment": {"python": sys.version.split()[0], "skill_version": SKILL_VERSION,
                        "now_year": NOW_YEAR},
        "log": LOG[:],
    }


def _fill_contract(case, res):
    """Guarantee every contract field name exists at the top level."""
    names = contract_field_names(case.get("output_contract"))
    added, missing = [], []
    for n in names:
        if n in res:
            continue
        src = FIELD_SYNONYMS.get(n.lower().strip())
        if src and src in res:
            res[n] = res[src]
            added.append(n)
        else:
            res[n] = None
            missing.append(n)
    if names:
        # always present when a contract was declared, so a reviewer can see "nothing
        # was unfilled" rather than having to interpret a missing key
        res.setdefault("inputs", {})["contract_filling"] = {"aliased": added, "unfilled": missing}


def _assemble(case, ctx, work, out, audit=None):
    res = _result_skeleton(case, ctx, work)
    d = ctx["draft"]
    ms = ctx["manuscript"]
    entries = {e["ref_id"]: e for e in ctx["library"]["entries"]}
    lang = ctx["lang"]

    draft_path = os.path.join(work, "draft.md")
    clean, rnotes = (R.strip_slots(L.read_text(draft_path)) if os.path.isfile(draft_path) else ("", []))

    parts = {}
    for p in L.PART_ORDER:
        info = d["parts"][p]
        parts[p] = {"present": info["present"], "chars": info["chars"],
                    "paragraphs": len(info["paragraphs"]),
                    "text": info["text"].strip()}

    cited_ids, numbering = [], {}
    for _p, s in A.all_sentences(ctx):
        cited_ids.extend(s.get("ref_ids") or [])
        for rid, n in (s.get("ref_numbers") or {}).items():
            numbering[rid] = min(n, numbering.get(rid, 10 ** 6))
    cited_ids = list(dict.fromkeys(cited_ids))
    # a numeric manuscript numbers its bibliography by citation number, and any
    # reference cited only through a key marker continues after the highest number
    if numbering:
        nxt = max(numbering.values()) + 1
        for rid in cited_ids:
            if rid not in numbering:
                numbering[rid] = nxt
                nxt += 1
        cited_ids = sorted(cited_ids, key=lambda r: (numbering.get(r, 10 ** 6), r))
    else:
        # author-year / key styles have no numbers in the prose; the list position is
        # still recorded so references_used[].number stays meaningful
        numbering = {rid: i + 1 for i, rid in enumerate(cited_ids)}

    citation_map = []
    for para, s in A.all_sentences(ctx):
        if not s.get("citations"):
            continue
        citation_map.append({
            "part": para["part"], "para": para["index"], "sentence": s["text"][:300],
            "markers": [c["raw"] for c in s["citations"]],
            "ref_ids": s.get("ref_ids") or [],
            "unresolved": s.get("unresolved") or [],
            "resolution": s["citations"][0]["kind"],
        })

    groups = ctx["ledgers"]["groups"].get("groups") or []
    contribs = ctx["ledgers"]["contributions"].get("contributions") or []
    gaps = ctx["ledgers"]["gaps"].get("gaps") or []

    res["result"] = {
        "introduction_related_work_file": "introduction_related_work.md",
        "related_work_table_file": "related_work_table.md",
        "contribution_table_file": "contribution_table.md",
        "parts": parts,
        "part_order": L.PART_ORDER,
        "chars": d.get("char_count", 0),
        "n_citations": sum(1 for _p, _s in A.all_sentences(ctx) if _s.get("ref_ids")),
        "n_distinct_refs": len(cited_ids),
        "n_groups": len(groups),
        "n_gaps": len(gaps),
        "n_contributions": len(contribs),
    }
    res["introduction_related_work"] = clean
    res["background"] = parts["background"]["text"]
    res["related_work"] = {
        "text": parts["related_work"]["text"],
        "groups": [{"group_id": g.get("group_id"), "label": g.get("label"),
                    "dimension": g.get("dimension"),
                    "ref_ids": [w.get("ref_id") for w in (g.get("works") or []) if isinstance(w, dict)],
                    "comparison": g.get("comparison")} for g in groups if isinstance(g, dict)],
        "table_file": "related_work_table.md",
    }
    res["research_gap"] = {
        "text": parts["gap"]["text"],
        "gaps": [{"gap_id": g.get("gap_id"), "statement": g.get("statement"),
                  "derived_from": g.get("derived_from"), "how_filled": g.get("how_filled"),
                  "confidence": g.get("confidence")} for g in gaps if isinstance(g, dict)],
    }
    res["contributions"] = {
        "text": parts["contributions"]["text"],
        "items": [{"contribution_id": c.get("contribution_id"), "text": c.get("text"),
                   "kind": c.get("kind"), "evidence": c.get("evidence"), "scope": c.get("scope")}
                  for c in contribs if isinstance(c, dict)],
        "table_file": "contribution_table.md",
    }
    res["citation_map"] = citation_map
    res["contribution_map"] = [
        {"contribution_id": c.get("contribution_id"),
         "evidence": [{"locator_type": e.get("locator_type"), "locator": e.get("locator"),
                       "claim_in_source": e.get("claim_in_source")}
                      for e in (c.get("evidence") or []) if isinstance(e, dict)]}
        for c in contribs if isinstance(c, dict)]
    res["references_used"] = [
        {"ref_id": rid, "number": numbering.get(rid), "key": entries[rid].get("key"),
         "title": entries[rid].get("title"), "authors": entries[rid].get("authors"),
         "year": entries[rid].get("year"), "venue": entries[rid].get("venue"),
         "doi": entries[rid].get("doi"), "type": entries[rid].get("type"),
         "gbt7714": R.render_gbt7714(entries[rid], numbering.get(rid)),
         "ieee": R.render_ieee(entries[rid], numbering.get(rid)),
         "apa7": R.render_apa7(entries[rid])}
        for rid in cited_ids if rid in entries]
    res["result"]["reference_numbering"] = {rid: numbering[rid] for rid in cited_ids if rid in numbering}

    res["evidence"] = {
        "group_ledger": [{"group_id": g.get("group_id"), "dimension": g.get("dimension"),
                          "works": [w.get("ref_id") for w in (g.get("works") or []) if isinstance(w, dict)]}
                         for g in groups if isinstance(g, dict)],
        "gap_provenance": [{"gap_id": g.get("gap_id"),
                            "from": [x.get("ref_id") for x in (g.get("derived_from") or [])
                                     if isinstance(x, dict)],
                            "limitation_kinds": [x.get("limitation_kind") for x in (g.get("derived_from") or [])
                                                 if isinstance(x, dict)],
                            "evidence_kinds": [((x.get("evidence") or {}).get("kind")
                                               if isinstance(x.get("evidence"), dict) else None)
                                               for x in (g.get("derived_from") or []) if isinstance(x, dict)]}
                           for g in gaps if isinstance(g, dict)],
        "manuscript_locators": {"figures": [f["label"] for f in ms["figures"]],
                                "tables": [t["label"] for t in ms["tables"]],
                                "sections": [s.get("title") for s in ms["sections"]],
                                "n_numbers_indexed": len(ms["numbers"])},
    }

    unc = res["uncertainty"]
    unresolved, ambiguous = [], []
    for _, s in A.all_sentences(ctx):
        unresolved.extend(s.get("unresolved") or [])
        ambiguous.extend(s.get("ambiguous") or [])
    unc["unresolved_citations"] = list(dict.fromkeys(unresolved))
    unc["ambiguous_citations"] = list(dict.fromkeys(ambiguous))
    for g in gaps:
        if not isinstance(g, dict):
            continue
        for x in g.get("derived_from") or []:
            if isinstance(x, dict) and ((x.get("evidence") or {}).get("kind") == "author_judgment"):
                unc["author_judgments"].append({"gap": g.get("gap_id"), "ref_id": x.get("ref_id"),
                                                "text": (x.get("evidence") or {}).get("text", "")[:200]})
    for p, s in A.all_sentences(ctx):
        if A._has_judgment(s["text"]) and not s.get("ref_ids"):
            unc["author_judgments"].append({"part": p["part"], "sentence": s["text"][:200]})
    unc["notes"] = list(ctx["library"].get("log") or []) + list(LOG[:]) + rnotes
    if ctx["library"]["fallback"] == "manuscript_reflist":
        unc["notes"].append("文献库由稿件文末参考文献表反推，元数据完整度受原文排版限制。")
    if not ctx["library"]["entries"]:
        unc["not_done"].append("没有文献库：引用无法核验，覆盖度检查全部跳过。")
    if not ms.get("chars"):
        unc["not_done"].append("没有稿件正文：贡献证据无法定位。")
    for kind, probs in ctx["ledger_problems"].items():
        for pr in probs:
            unc["notes"].append("ledger %s: %s" % (kind, pr))

    # status
    gate = (audit or {}).get("gate")
    n_err = ((audit or {}).get("summary") or {}).get("errors", 0)
    n_warn = ((audit or {}).get("summary") or {}).get("warnings", 0)
    res["audit"] = {"gate": gate, "errors": n_err, "warnings": n_warn,
                    "report_file": "audit_report.md",
                    "summary_file": "audit_report.json",
                    "rules_failed": ((audit or {}).get("summary") or {}).get("rules_failed", [])}
    limits = []
    st = res["status"]
    if not clean:
        st["state"] = "failed"
        st["reason"] = "没有成稿：%s 不存在或为空。" % draft_path
        limits.append("no draft produced")
    elif gate == "pass":
        st["state"] = "success"
        st["reason"] = "18 项确定性核对全部通过（0 error，%d warning）。" % n_warn
    else:
        st["state"] = "partial"
        st["reason"] = ("成稿已产出，但核对仍有 %d 个 error（详见 audit_report.md）；"
                        "下面列出的 limits 是未解决项。" % n_err)
        limits.append("%d deterministic check error(s) remain" % n_err)
        for m in (audit or {}).get("must_fix", [])[:12]:
            limits.append("%s/%s: %s" % (m["rule"], m["code"], m["message"][:160]))
    if not ctx["library"]["entries"]:
        limits.append("library empty: citations unverifiable")
    if ctx["ledger_problems"] and any(ctx["ledger_problems"].values()):
        limits.append("one or more ledgers missing or malformed")
    st["limits"] = limits
    st["gate"] = gate

    res["sources"] = []
    for m in (ctx["manuscript"].get("all_materials") or [ctx["manuscript"].get("path")]) + \
              [s["path"] for s in ctx["library"]["sources"]]:
        if not m:
            continue
        res["sources"].append({"path": m, "sha256": L.sha256_file(m), "kind": "input"})
    seen = set()
    res["sources"] = [s for s in res["sources"] if not (s["path"] in seen or seen.add(s["path"]))]

    res["changes"] = [
        {"step": "plan", "what": "解析输入、建文献库与稿件索引、写脚手架与账本模板"},
        {"step": "draft", "what": "按账本写 background / related_work / gap / contributions 四部分"},
        {"step": "audit", "what": "运行 18 项确定性核对，逐条给出错误与警告"},
        {"step": "finalize", "what": "渲染成稿、比较表、贡献表、引用表与 result.json"},
    ]
    res["artifacts"] = {
        "introduction_related_work": "introduction_related_work.md",
        "related_work_table": "related_work_table.md",
        "contribution_table": "contribution_table.md",
        "audit_report_md": "audit_report.md",
        "audit_report_json": "audit_report.json",
        "citation_map": "citation_map.json",
        "refs_cited_bib": "refs_cited.bib",
        "refs_cited_txt": "refs_cited.txt",
    }
    res["log"] = LOG[:]
    res["generated_at"] = _now_iso()
    return res, clean, cited_ids, entries


# --------------------------------------------------------------------------- #
# audit / finalize
# --------------------------------------------------------------------------- #

def stage_audit(case, ctx, work, out):
    d = _load_draft(ctx)
    if not d["text"].strip():
        log("WARN no draft at %s" % d["path"])
    report = A.run_audit(ctx)
    report["draft_chars"] = len(d["text"])
    report["part_method"] = d.get("method")
    write_json(os.path.join(work, "audit.json"), report)
    write_json(os.path.join(out, "audit_report.json"), report)
    write_text(os.path.join(out, "audit_report.md"), R.render_audit_md(report, ctx["lang"]))
    log("audit gate=%s errors=%d warnings=%d"
        % (report["gate"], report["summary"]["errors"], report["summary"]["warnings"]))
    for m in report["must_fix"][:8]:
        log("  FIX %s/%s %s" % (m["rule"], m["code"], m["message"][:150]))
    return report


def stage_finalize(case, ctx, work, out, audit):
    res, clean, cited_ids, entries = _assemble(case, ctx, work, out, audit)
    _fill_contract(case, res)

    write_text(os.path.join(out, "introduction_related_work.md"), clean)
    write_text(os.path.join(out, "related_work_table.md"),
               R.render_group_table(ctx["ledgers"]["groups"].get("groups") or [], entries, ctx["lang"]))
    write_text(os.path.join(out, "contribution_table.md"),
               R.render_contribution_table(ctx["ledgers"]["contributions"].get("contributions") or [],
                                           ctx["lang"]))
    write_json(os.path.join(out, "citation_map.json"),
               {"case_id": case["case_id"], "items": res["citation_map"],
                "n_distinct_refs": len(cited_ids)})
    style = ctx["target_citation_style"]
    numbered = res["result"].get("reference_numbering") or {}
    if style in ("numeric", "gbt7714", "gbt") and ctx["lang"] == "en":
        render_style = "ieee"          # English numeric manuscripts read as IEEE
    elif style in ("numeric", "gbt7714", "gbt"):
        render_style = "gbt7714"
    elif style in ("apa", "apa7", "author-year"):
        render_style = "apa7"
    else:
        render_style = style or "gbt7714"
    if cited_ids:
        write_text(os.path.join(out, "refs_cited.bib"),
                   R.render_reference_block([entries[r] for r in cited_ids if r in entries], "bibtex"))
        write_text(os.path.join(out, "refs_cited.txt"),
                   R.render_reference_block([entries[r] for r in cited_ids if r in entries],
                                            render_style, numbered))
        res["artifacts"]["refs_cited_style"] = render_style
    else:
        write_text(os.path.join(out, "refs_cited.bib"), "")
        write_text(os.path.join(out, "refs_cited.txt"), "")
    for kind, spec in L.LEDGER_SPEC.items():
        p = os.path.join(work, "ledgers", spec["file"])
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(out, spec["file"]))
    write_json(os.path.join(out, "result.json"), res)
    st = res["status"]
    log("finalize state=%s gate=%s chars=%d refs=%d groups=%d gaps=%d contribs=%d"
        % (st["state"], st["gate"], res["result"]["chars"], res["result"]["n_distinct_refs"],
           res["result"]["n_groups"], res["result"]["n_gaps"], res["result"]["n_contributions"]))
    return res


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(description="introduction / related-work writing skill")
    ap.add_argument("--input", default="/input", help="input directory (case.json, task.md, materials)")
    ap.add_argument("--out", default="/app/output", help="output directory")
    ap.add_argument("--work", default="/app/work", help="work directory")
    ap.add_argument("--stage", default="auto", choices=["auto", "plan", "audit", "finalize"])
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args(argv)
    if a.version:
        print(SKILL_VERSION)
        return 0

    t0 = time.time()
    input_dir, out, work = a.input, a.out, a.work
    if not os.path.isdir(input_dir):
        for cand in ("/app/input", "./input", "."):
            if os.path.isdir(cand):
                input_dir = cand
                break
    os.makedirs(out, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    log("intrograph %s stage=%s input=%s out=%s work=%s"
        % (SKILL_VERSION, a.stage, input_dir, out, work))

    case = load_case(input_dir)
    log("case_id=%s task=%r" % (case["case_id"], (case["task"] or "")[:90]))
    for p in case["problems"]:
        log("WARN %s" % p)

    try:
        if a.stage in ("auto", "plan"):
            ctx = stage_plan(case, input_dir, work, out)
        else:
            # rebuild the context from what plan left on disk
            ctx = _rebuild_ctx(case, input_dir, work)
    except Exception:
        log("FATAL during plan:\n" + traceback.format_exc()[-1600:])
        res = {"case_id": case["case_id"], "status": {"state": "failed",
               "reason": "plan crashed: %s" % traceback.format_exc()[-400:], "limits": [], "gate": None},
               "skill": {"name": "intrograph", "version": SKILL_VERSION}, "log": LOG[:]}
        _fill_contract(case, res)
        write_json(os.path.join(out, "result.json"), res)
        return 2

    try:
        if a.stage == "plan":
            return 0
        audit = stage_audit(case, ctx, work, out)
        if a.stage in ("auto", "finalize"):
            if not (ctx["draft"]["text"] or "").strip():
                log("no draft yet; audit written, result.json left at the partial state written by plan")
                return 0
            stage_finalize(case, ctx, work, out, audit)
        return 0
    except Exception:
        log("FATAL:\n" + traceback.format_exc()[-1600:])
        p = os.path.join(out, "result.json")
        try:
            res = json.loads(L.read_text(p))
        except Exception:
            res = {"case_id": case["case_id"]}
        res.setdefault("status", {})
        res["status"]["state"] = "failed"
        res["status"]["reason"] = "crash during audit/finalize: %s" % traceback.format_exc()[-400:]
        write_json(p, res)
        return 2
    finally:
        log("done in %.1fs" % (time.time() - t0))


def _rebuild_ctx(case, input_dir, work):
    """Recreate the context for a later stage without redoing discovery."""
    intake_p = os.path.join(work, "intake.json")
    lib_p = os.path.join(work, "library.json")
    ms_p = os.path.join(work, "manuscript_index.json")
    if not (os.path.isfile(lib_p) and os.path.isfile(ms_p)):
        raise RuntimeError("no plan state under %s; run --stage plan first" % work)
    library = json.loads(L.read_text(lib_p))
    library.setdefault("sources", [])
    library.setdefault("fallback", "unknown")
    msj = json.loads(L.read_text(ms_p))
    text = msj.pop("manuscript_text", None) or msj.pop("text_head", "")
    manuscript = msj
    manuscript["text"] = text
    manuscript.setdefault("numbers", [])
    manuscript.setdefault("reflist", [])
    manuscript.setdefault("sections", [])
    manuscript.setdefault("figures", [])
    manuscript.setdefault("tables", [])
    manuscript.setdefault("equations", [])
    manuscript.setdefault("keywords", [])
    manuscript.setdefault("abstract", "")
    manuscript.setdefault("all_materials", [])
    # the full numbers index is rebuilt from the material's snapshot when available
    if not manuscript["numbers"]:
        for p in (manuscript.get("all_materials") or []):
            try:
                manuscript["numbers"] = sorted(set(manuscript["numbers"]) | set(
                    L.number_keys_of(L.read_text(p))))
            except OSError:
                pass
    state = {}
    sp = os.path.join(work, "state.json")
    if os.path.isfile(sp):
        try:
            state = json.loads(L.read_text(sp))
        except Exception:
            state = {}
    lang = state.get("lang") or manuscript.get("lang") or "zh"
    style = state.get("style") or "numeric"
    intent = state.get("intent") or {"intents": ["draft"], "mode": "draft"}
    return _build_ctx(case, work, manuscript, library, lang, style, intent)


if __name__ == "__main__":
    sys.exit(main())
