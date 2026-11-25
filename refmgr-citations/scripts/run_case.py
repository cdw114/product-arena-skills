#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_case.py — entry point of the reference-management skill.

Reads the Harbor contract inputs (/input/case.json, /input/task.md, materials), detects what
the case asks for, runs the deterministic engines, and writes /app/output/result.json plus
editable artifacts. Also usable as a plain CLI on any manuscript + library pair.

    python run_case.py --input /input --output /app/output [--claim-matches claims.json]
    python run_case.py --manuscript m.md --library lib.bib --task "renumber+convert:gbt7714" --out out/

Exits 0 on success/partial (a result.json is always written), 2 on unrecoverable input error.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import re
import shutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engines as E  # noqa: E402
import refmgr as R  # noqa: E402

ACTION_KEYS = {  # task wording → action
    "insert": ["插入", "补引用", "添加引用", "insert", "add citation", "cite", "需要来源", "论断句"],
    "renumber": ["重排", "编号", "更新编号", "调序", "删除", "插入后", "renumber", "renumbering", "numbering", "reorder", "sync"],
    "dedup": ["去重", "归并", "合并", "重复", "dedup", "duplicate", "merge"],
    "convert": ["转换", "格式", "gb/t", "gbt", "apa", "bibtex", "ris", "cnki", "convert", "style"],
    "verify": ["核验", "真实性", "doi", "编造", "verify", "fabricat", "crossref", "元数据"],
    "consistency": ["一致性", "正文", "对应", "匹配", "论断", "consisten", "claim", "对应"],
}


def now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def find_inputs(inp: str) -> dict:
    """Discover case.json / task.md / manuscript / library files under `inp` (recursive, tolerant)."""
    files = [p for p in glob.glob(os.path.join(inp, "**", "*"), recursive=True) if os.path.isfile(p)]
    f = {"case": None, "task": None, "manuscripts": [], "libraries": [], "others": []}
    for p in files:
        b = os.path.basename(p).lower()
        ext = b.rsplit(".", 1)[-1] if "." in b else ""
        if b in ("case.json", "case.yml", "case.yaml"):
            f["case"] = p
        elif b in ("task.md", "task.txt", "task.json", "instructions.md", "说明.md"):
            f["task"] = p
        elif ext in ("bib", "ris", "enw"):
            f["libraries"].append(p)
        elif ext == "json":
            try:
                d = json.load(open(p, encoding="utf-8-sig"))
            except Exception:
                f["others"].append(p); continue
            if isinstance(d, dict) and any(k in d for k in ("output_contract", "materials", "case_id")):
                f["case"] = f["case"] or p
            elif isinstance(d, (list, dict)) and any(k in json.dumps(d)[:4000] for k in ('"title"', '"doi"', '"author"')):
                f["libraries"].append(p)
            else:
                f["others"].append(p)
        elif ext in ("md", "txt", "docx"):
            txt = _peek(p)
            if re.search(r"@\w+\s*\{|^TY  - ", txt, re.M):
                f["libraries"].append(p)
            elif re.search(r"参考文献|references", txt, re.I) or len(re.findall(r"\[\d{1,3}\]", txt)) >= 2:
                f["manuscripts"].append(p)
            elif f["task"] is None and re.search(r"任务|要求|task|请|需要", txt):
                f["task"] = p
            else:
                f["others"].append(p)
        else:
            f["others"].append(p)
    return f


def _peek(p: str, n: int = 4000) -> str:
    try:
        if p.lower().endswith(".docx"):
            return R.docx_to_text(p)[:n]
        with open(p, encoding="utf-8-sig", errors="replace") as fh:
            return fh.read(n)
    except Exception:
        return ""


def detect_actions(task_text: str, explicit: str = "") -> list:
    if explicit:
        return [a.strip() for a in re.split(r"[+,;\s]+", explicit) if a.strip()]
    t = task_text.lower()
    acts = [a for a, keys in ACTION_KEYS.items() if any(k.lower() in t for k in keys)]
    return acts or ["renumber", "dedup", "consistency"]


def detect_style(task_text: str, ms: R.Manuscript) -> tuple:
    t = task_text.lower()
    if re.search(r"apa|著者[-—]?出版年|author[- ]year", t):
        return "author-year", "apa7"
    if re.search(r"gb/t|gbt|7714|国标|顺序编码", t):
        return "numeric", "gbt"
    if re.search(r"ieee|vancouver", t):
        return "numeric", "ieee"
    if ms.marker_style == "author-year":
        return "author-year", "apa7"
    return "numeric", "bracket"


def apply_insertions(text: str, ins: list) -> tuple:
    """Place \\cite{key} placeholders. Anchor rules (挂得对):
      - the marker goes at the END of the sentence that makes the claim, before the terminal punctuation
        (numeric styles) — never at paragraph end unless anchor says so;
      - 'after-claim' → right after the matched sentence text (mid-sentence, for a specific clause);
      - footnote → inline '[^fnN]' marker; the footnote body is appended at the end of the paragraph.
    Returns (new_text, applied_records). Unmatched sentences are skipped and reported by caller."""
    applied = []
    # work from the end so offsets stay valid
    pending = []
    for k, j in enumerate(ins):
        sent = (j.get("sentence") or "").strip()
        if not sent:
            continue
        idx = text.find(sent)
        if idx < 0:
            # tolerate whitespace / punctuation drift: try a prefix
            head = sent[: min(24, len(sent))]
            idx = text.find(head)
        if idx < 0:
            continue
        sent_end = idx + len(sent)
        anchor = (j.get("anchor") or "sentence-end").lower()
        keys = ",".join(j.get("ref_keys") or [])
        if not keys:
            continue
        form = (j.get("form") or "numeric").lower()
        if form == "footnote":
            fid = k + 1
            marker, pos = f"[^fn{fid}]", sent_end
            body = f"\n\n[^fn{fid}]: {j.get('footnote_text') or ('; '.join(keys))}\n"
            pending.append((pos, marker, body, j, sent))
        else:
            # GB/T / IEEE / Vancouver: the bracket goes BEFORE the terminal punctuation (论断[1]。下一句)
            pos = sent_end - 1 if (anchor == "sentence-end" and sent[-1] in (".", "。", "!", "！", "?", "？", ";", "；")) else sent_end
            marker = "\\cite{" + keys + "}"
            pending.append((pos, marker, "", j, sent))
    # apply from the end
    pending.sort(key=lambda x: -x[0])
    for pos, marker, body, j, sent in pending:
        text = text[:pos] + marker + text[pos:]
        if body:
            # append footnote body after the paragraph containing pos
            pe = text.find("\n\n", pos)
            pe = len(text) if pe == -1 else pe
            text = text[:pe] + body + text[pe:]
        applied.append({"sentence": sent, "anchor": j.get("anchor"), "ref_keys": j.get("ref_keys"),
                        "form": j.get("form"), "why": j.get("why"), "confidence": j.get("confidence"),
                        "placeholder": marker, "position": pos})
    applied.reverse()
    return text, applied


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="case input dir (Harbor: /input)")
    ap.add_argument("--manuscript"); ap.add_argument("--library", action="append", default=[])
    ap.add_argument("--task", default=None, help="task text OR action list like renumber+convert:gbt7714")
    ap.add_argument("--claim-matches", help="JSON [{cid,ref_id,verdict,basis}] from the LLM claim-matching step")
    ap.add_argument("--insertions", help="JSON [{paragraph,sentence,anchor,ref_keys,form,why,confidence}] from the LLM insertion step")
    ap.add_argument("--translations", help="JSON list of [zh_title, en_title] pairs for cross-language dedup")
    ap.add_argument("--online", action="store_true", help="allow DOI lookup via api.crossref.org")
    ap.add_argument("--out", default=None); ap.add_argument("--work", default=None)
    a = ap.parse_args(argv)
    out = a.out or os.environ.get("OUTPUT_DIR") or "/app/output"
    work = a.work or os.environ.get("WORK_DIR") or ("/app/work" if os.path.isdir("/app") else os.path.join(out, "..", "work"))
    os.makedirs(out, exist_ok=True); os.makedirs(work, exist_ok=True)
    log = []

    def L(msg):
        log.append(f"[{now()}] {msg}"); print(msg, file=sys.stderr)

    # ---------------- locate inputs
    case = {}
    task_text = ""
    man_path = lib_paths = None, []
    try:
        if a.input:
            f = find_inputs(a.input)
            if f["case"]:
                case = json.load(open(f["case"], encoding="utf-8-sig")); L(f"case.json: {f['case']}")
            if f["task"]:
                task_text = _peek(f["task"], 100000); L(f"task: {f['task']}")
            man_path = f["manuscripts"][0] if f["manuscripts"] else None
            lib_paths = f["libraries"]
        if a.manuscript:
            man_path = a.manuscript
        if a.library:
            lib_paths = list(a.library)
        # task text may also live inside case.json
        if not task_text and isinstance(case, dict):
            task_text = "\n".join(str(case.get(k, "")) for k in ("task", "instruction", "prompt", "description"))
        for p in glob.glob(os.path.join(a.input or ".", "**", "*"), recursive=True):
            if os.path.basename(p).lower() in ("task.md",) and not task_text:
                task_text = _peek(p, 100000)
        if not man_path:
            raise FileNotFoundError("no manuscript (.md/.txt/.docx) found")
        if not lib_paths:
            L("WARN: no library file found; building library from the manuscript's own reference list")
    except Exception as ex:
        L(f"input error: {ex}")
        _write(os.path.join(out, "result.json"), {"case_id": case.get("case_id", case.get("id", "unknown")), "status": "failed",
                                                   "status_reason": f"input error: {ex}", "log": log})
        return 2

    # ---------------- parse
    text = R.docx_to_text(man_path) if man_path.lower().endswith(".docx") else R.read_text(man_path)
    # ---- LLM-decided insertions: place \cite{key} placeholders at the anchor sentence (model picks the spot,
    #      the renumber pass later turns them into target-style markers). Keys may be library keys or ref_ids.
    insertions_applied = []
    if a.insertions and os.path.exists(a.insertions):
        try:
            ins = json.load(open(a.insertions, encoding="utf-8"))
            text, insertions_applied = apply_insertions(text, ins)
            L(f"insertions: {len(insertions_applied)} placed, {len(ins) - len(insertions_applied)} skipped")
        except Exception as ex:
            L(f"insertions unreadable: {ex}")
    ms = R.parse_manuscript(text, man_path)
    L(f"manuscript: {len(text)} chars, sections={len(ms.sections)}, citations={len(ms.citations)}, style={ms.marker_style}")
    lib_entries, lib_sources = [], []
    for p in lib_paths:
        ents, fmt = R.parse_library_file(p)
        L(f"library {p}: {len(ents)} entries ({fmt})")
        for e in ents:
            e.source_file = os.path.basename(p)
        lib_entries += ents; lib_sources.append({"path": p, "format": fmt, "n": len(ents)})
    if not lib_entries:
        # fall back: parse manuscript's own reference list as a tagged text library (title-first)
        for it in ms.ref_list_items:
            t = it["text"]
            m = re.search(r"10\.\d{4,9}/\S+", t)
            e = R.Entry(ref_id="", type="other", title=t[:120], doi=m.group(0).rstrip(".") if m else "")
            e.source_file = os.path.basename(man_path) + "#reflist"; e.source_key = f"n{it['n']}"
            e.extra["reflist_n"] = str(it["n"])
            lib_entries.append(e)
        lib_sources.append({"path": man_path + "#reflist", "format": "fallback-reflist", "n": len(lib_entries)})
    # numeric reflist fallback: match each to real library via resolve
    lib = R.Library(lib_entries)
    for i, e in enumerate(lib.entries, 1):
        if not e.ref_id:
            e.ref_id = f"R{i:03d}"
    if not any(e.ref_id.startswith("R") for e in lib.entries):
        for i, e in enumerate(lib.entries, 1):
            e.ref_id = f"R{i:03d}"
    R.resolve_citations(ms, lib)
    # Manuscript's own list items that match NO library entry are kept as 'unverified' entries so the
    # output list stays complete and the fabrication risk is explicit (对得上). They get ids U001…
    n_next = len(lib.entries) + 1
    for it in ms.ref_list_items:
        if not R._match_ref_text_to_library(it["text"], lib) and not any(e.extra.get("reflist_n") == str(it["n"]) for e in lib.entries):
            t = it["text"]
            m = re.search(r"10\.\d{4,9}/\S+", t)
            e = R.Entry(ref_id=f"U{n_next:03d}", type="other", title=t[:160], doi=m.group(0).rstrip(".") if m else "")
            e.source_file = os.path.basename(man_path) + "#reflist"; e.source_key = f"n{it['n']}"
            e.extra["reflist_n"] = str(it["n"]); e.verification = {"status": "no_library_match", "fabrication_risk": "high"}
            ym = re.search(r"(1[5-9]|20)\d{2}", t)
            e.year = ym.group(0) if ym else ""
            lib.entries.append(e); n_next += 1
            L(f"reflist item [{it['n']}] has no library match → {e.ref_id} (flagged)")
    R.resolve_citations(ms, lib)
    n_res = sum(len(c.resolved) for c in ms.citations); n_unres = sum(len(c.unresolved) for c in ms.citations)
    L(f"resolved {n_res} refs, unresolved {n_unres}")

    # ---------------- actions
    actions = detect_actions(task_text or "", a.task or "")
    style, label_fmt = detect_style(task_text or "", ms)
    m = re.search(r"(?:convert|转换)[:\s]*([a-z0-9/\-]+)", (a.task or "").lower())
    if m:
        label_fmt = {"gbt7714": "gbt", "gbt": "gbt", "apa": "apa7", "apa7": "apa7", "bibtex": "bibtex", "ris": "ris"}.get(m.group(1).replace("-", "").replace("/", ""), label_fmt)
    L(f"actions={actions} style={style}/{label_fmt}")

    result = {"case_id": case.get("case_id") or case.get("id") or os.path.basename(os.path.dirname(man_path)) or "unknown",
              "generated_at": now(), "status": "partial", "inputs": {"manuscript": man_path, "libraries": lib_sources,
              "task_excerpt": task_text[:800]}, "actions": actions, "target_style": {"citation": style, "label": label_fmt},
              "stats": {}, "log": log}
    snapshots = os.path.join(work, "snapshots"); os.makedirs(snapshots, exist_ok=True)
    shutil.copy(man_path, os.path.join(snapshots, "manuscript." + man_path.rsplit(".", 1)[-1]))
    for p in lib_paths:
        shutil.copy(p, os.path.join(snapshots, os.path.basename(p)))

    # snapshot BEFORE any change (for traceability)
    _write(os.path.join(out, "result.json"), {**result, "status": "partial", "status_reason": "pipeline started; saved early"})  # early save

    # --- dedup
    trans = json.load(open(a.translations, encoding="utf-8")) if a.translations else None
    dd = E.dedupe(lib, trans)
    lib2 = dd["library"]
    # remap citation resolutions to canonical ids
    remap = {}
    for e in lib2.entries:
        for m_ in e.merged_from:
            remap[m_] = e.ref_id
    for c in ms.citations:
        c.resolved = sorted({remap.get(r, r) for r in c.resolved})
    R.resolve_citations(ms, lib2)
    result["dedup"] = {"stats": dd["stats"], "merge_log": dd["merge_log"], "needs_review": dd["reviews"]}
    L(f"dedup: {dd['stats']}")

    # --- renumber + consistency
    rn = E.renumber(ms, lib2, style=style, label_fmt=label_fmt)
    cons = E.consistency_check(ms, lib2, rn)
    result["renumber"] = {"order": rn["order"], "numbering": rn["numbering"], "edits": rn["edits"], "uncited": rn["uncited"], "unresolved": rn["unresolved"]}
    result["consistency"] = cons
    L(f"renumber: {len(rn['edits'])} marker edits, uncited={len(rn['uncited'])}, unresolved={len(rn['unresolved'])}, issues={len(cons['issues'])}")

    # --- convert
    conv = E.convert(lib2, label_fmt if label_fmt in ("gbt", "apa7", "bibtex", "ris") else "gbt7714")
    conv_style = {"gbt": "gbt7714", "apa7": "apa7"}.get(label_fmt, label_fmt)
    conv = E.convert(lib2, conv_style)
    result["conversion"] = {"style": conv["style"], "items": conv["items"], "field_report": conv["field_report"]}
    L(f"convert → {conv['style']}")

    # --- verify
    crossref = None
    if a.online:
        crossref = {}
        for d in {e.doi for e in lib2.entries if e.doi}:
            got = E.fetch_crossref([d])
            if got:
                crossref.update(got)
        by_ref = {}
        for e in lib2.entries:
            if e.doi in crossref:
                by_ref[e.ref_id] = crossref[e.doi]
        ver = E.verify_entries(lib2, by_ref, offline=False)
    else:
        ver = E.verify_entries(lib2, None, offline=True)
    result["verification"] = ver
    L(f"verify: {ver['summary']}")

    # --- claim ↔ citation (LLM judgments supplied via --claim-matches, else left as pending pairs)
    pairs = E.claim_citation_pairs(ms, lib2)
    cm = {}
    if a.claim_matches and os.path.exists(a.claim_matches):
        try:
            for j in json.load(open(a.claim_matches, encoding="utf-8")):
                cm[(j["cid"], j["ref_id"])] = j
        except Exception as ex:
            L(f"claim-matches unreadable: {ex}")
    for p_ in pairs:
        j = cm.get((p_["cid"], p_["ref_id"]))
        p_["verdict"] = j.get("verdict", "pending") if j else "pending"
        p_["basis"] = j.get("basis", "") if j else ""
        p_["sentence"] = p_["claim"]
    result["claim_citation"] = {"pairs": pairs, "pending": sum(1 for p_ in pairs if p_["verdict"] == "pending"),
                                "supported": sum(1 for p_ in pairs if p_["verdict"] == "supports"),
                                "mismatch": sum(1 for p_ in pairs if p_["verdict"] == "mismatch"),
                                "insufficient_evidence": sum(1 for p_ in pairs if p_["verdict"] == "insufficient")}

    # ---------------- artifacts
    result["insertions"] = insertions_applied
    ext = man_path.rsplit(".", 1)[-1].lower()
    man_out = os.path.join(out, "manuscript_revised." + ("md" if ext == "docx" else ext))
    _write(man_out, rn["new_text"])
    ref_out = os.path.join(out, "references_" + conv["style"] + (".bib" if conv["style"] == "bibtex" else ".ris" if conv["style"] == "ris" else ".txt"))
    _write(ref_out, conv["full_text"])
    _write(os.path.join(out, "library_canonical.json"), lib2.to_json())
    _write(os.path.join(out, "citation_map.json"), json.dumps([c.__dict__ for c in ms.citations], ensure_ascii=False, indent=2))
    diff = R.diff_summary(text, rn["new_text"])
    _write(os.path.join(out, "changes.json"), json.dumps({"diff": diff, "marker_edits": rn["edits"], "merges": dd["merge_log"]}, ensure_ascii=False, indent=2))
    result["artifacts"] = {"manuscript_revised": os.path.basename(man_out), "reference_list": os.path.basename(ref_out),
                           "library_canonical": "library_canonical.json", "citation_map": "citation_map.json", "changes": "changes.json",
                           "snapshots": snapshots}
    result["stats"] = {"citations": len(ms.citations), "library_in": dd["stats"]["input"], "library_out": dd["stats"]["output"],
                       "merged": dd["stats"]["merged"], "review_pairs": len(dd["reviews"]), "edits": len(rn["edits"]),
                       "uncited": len(rn["uncited"]), "unresolved": len(rn["unresolved"]), "consistency_issues": len(cons["issues"]),
                       "verify_errors": ver["summary"]["errors"], "claim_pairs": len(pairs), "claim_pending": result["claim_citation"]["pending"]}
    # ---------------- status
    reasons = []
    if rn["unresolved"] or ver["summary"]["errors"]:
        result["status"] = "partial"; reasons.append("unresolved citations or verification errors need human confirmation")
    elif result["claim_citation"]["pending"]:
        result["status"] = "partial"; reasons.append("claim↔citation judgments pending (LLM step not supplied)")
    else:
        result["status"] = "success"
    result["status_reason"] = "; ".join(reasons) or "all requested actions completed"
    result["human_review"] = [{"item": r["a"] + " ~ " + r["b"], "why": "dedup score in review band", "signals": r["signals"]} for r in dd["reviews"]] + \
                              cons["issues"]
    result["change_log"] = [{"step": "parse", "what": f"{len(ms.citations)} citations, {len(lib.entries)} library entries"},
                            {"step": "dedup", "what": dd["stats"]}, {"step": "renumber", "what": f"{len(rn['edits'])} markers rewritten, list rebuilt ({len(rn['order'])} entries)"},
                            {"step": "convert", "what": conv["style"]}, {"step": "verify", "what": ver["summary"]}]
    result["uncertainties"] = [u for u in result["human_review"]]
    result["environment"] = {"python": sys.version.split()[0], "refmgr": R.__version__, "dependencies": "stdlib only", "online": bool(a.online)}
    _write(os.path.join(out, "result.json"), result)
    L(f"DONE status={result['status']} → {out}")
    return 0


def _write(p: str, data) -> None:
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        tb = traceback.format_exc()
        out = os.environ.get("OUTPUT_DIR") or "/app/output"
        try:
            _write(os.path.join(out, "result.json"), {"status": "failed", "status_reason": tb[-1500:], "case_id": "unknown"})
        except Exception:
            pass
        print(tb, file=sys.stderr)
        sys.exit(2)
