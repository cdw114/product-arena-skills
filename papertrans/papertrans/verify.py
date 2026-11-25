#!/usr/bin/env python3
"""
papertrans.verify — Deterministic post-translation checks (the "可核验" layer).

Checks per segment:
  coverage      : every segment id in the plan has a translation (missing / extra ids)
  placeholder   : every ⟦..⟧ present exactly once; none unexpected (protect.restore)
  digits        : multiset of numbers in source == numbers in restored translation
  unit          : unit tokens in source ⊆ units in translation (after restore)
  xref          : Fig./Table/Eq./Section references identical
  negation      : count of negation cues (not, no, never, neither, without, unlikely, fail to…)
                  vs target-language negation cues (不, 无, 未, 非, 没有, 否, 难以 …) — mismatch → flag
  hedging       : hedging cues (may, might, suggest, potentially, likely, possibly …) vs (可能, 或许, 似乎, 表明 …)
  glossary      : every TERM placeholder restored → the locked target string appears exactly once
                  (and no other approved target appears where a different term was expected)
  length_ratio  : len(target)/len(source) sanity band (zh: 0.25–1.2) → flag outliers as possible omission/padding
  unsure        : [待确认: …]/[UNSURE: …] markers are listed for human review

Output: verify.json with per-segment verdict (pass | warn | fail), issue list, and summary metrics.
A segment is `fail` if coverage/placeholder/digits/xref/glossary fail; `warn` for negation/hedge/length.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .protect import restore, marks_from_json, PLACEHOLDER_RE, CITE_AUTHOR_YEAR_RE as CITE_RE, CITE_BRACKET_RE

NEG_SRC = r"\b(?:not|no|never|neither|nor|without|unlikely|unable|cannot|can't|fail(?:s|ed)? to|lack(?:s|ed)? of|hardly|scarcely|rarely|absence of|free of|independent of)\b"
NEG_SRC_RE = re.compile(NEG_SRC, re.I)
NEG_TGT = {
    "zh": r"(?:不|无|未|非|没有|否|难以|无法|不能|缺少|缺乏|很少|几乎不|罕见|排除|独立于)",
    "en": NEG_SRC,
    "ja": r"(?:ない|ず|ません|未|非)",
}
HEDGE_SRC_RE = re.compile(r"\b(?:may|might|could|possibly|potentially|likely|unlikely|suggest(?:s|ed)?|appear(?:s|ed)? to|seem(?:s|ed)? to|putative|proposed|presumably|arguably|perhaps|probably)\b", re.I)
HEDGE_TGT = {"zh": r"(?:可能|或许|似乎|表明|提示|推测|也许|大概|潜在的|或许)", "en": r"\b(?:may|might|could|possibly|potentially|likely|suggest|appear|perhaps|probably)\b"}
UNSURE_RE = re.compile(r"\[(?:待确认|UNSURE)[:：][^\]]*\]")
NUM_RE = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?:[eE][-−+]?\d+)?(?![A-Za-z0-9])")   # sign-less, not embedded in identifiers
UNIT_AFTER_NUM = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?:\s*[–\-~±]\s*\d+(?:\.\d+)?)?\s?(mg|kg|μg|µg|ng|mol|mmol|km|cm|mm|μm|µm|nm|pm|mL|μL|µL|ms|hr|hrs|day|days|week|weeks|year|years|kDa|Da|eV|keV|MeV|J|kJ|W|mW|kW|V|mV|kV|mA|Hz|kHz|MHz|GHz|Pa|kPa|MPa|GPa|bar|atm|T|K|°C|N|ppm|ppb|M|mM|%)\b")
XREF_RE = re.compile(r"\b(?:(?:Fig(?:ure)?s?|Tables?|Eqs?\.?|Equations?|Sections?|Sec\.|Scheme|Algorithms?|Appendix|Supplementary|SI\s+Fig|SI\s+Table|Extended\s+Data)\s*\.?\s*S?\d+(?:\.\d+)*[a-zA-Z]?(?:[–\-][A-Z\d]+)?|§+\s*\d+(?:\.\d+)*)", re.I)
CITE_RE = re.compile(CITE_BRACKET_RE.pattern + r"|" + CITE_RE.pattern)
CITE_NUM_SUP_RE = re.compile(r"(?<![A-Za-z0-9\]])\^\s*\{\s*\d+(?:\s*[,–-]\s*\d+)*\s*\}")

LENGTH_BAND = {"zh": (0.22, 1.3), "ja": (0.3, 1.4), "en": (0.6, 1.6)}


def _nums(text: str) -> Counter:
    return Counter(NUM_RE.findall(text))


def _remask(src: str, marks: list) -> str:
    """Re-create the masked source from the original text + marks (start/end offsets)."""
    ms = marks_from_json(marks) if (marks and isinstance(marks[0], dict)) else marks
    out, last = [], 0
    for mk in sorted(ms, key=lambda m: m.start):
        out.append(src[last:mk.start])
        out.append(mk.surface)
        last = mk.end
    out.append(src[last:])
    return "".join(out)


def _ph_order(text: str, kinds: tuple[str, ...]) -> list[str]:
    out = []
    for m in PLACEHOLDER_RE.finditer(text):
        if m.group(1) in kinds:
            out.append(m.group(0))
    return out


def _order_inversions(src_seq: list[str], tgt_seq: list[str]) -> list[tuple[str, str]]:
    """Pairs (a, b) adjacent in source order but reversed in target order (only for ids present in both)."""
    tgt_pos = {ph: i for i, ph in enumerate(tgt_seq)}
    inv = []
    for i in range(len(src_seq)):
        for j in range(i + 1, len(src_seq)):
            a, b = src_seq[i], src_seq[j]
            if a in tgt_pos and b in tgt_pos and tgt_pos[a] > tgt_pos[b]:
                inv.append((a, b))
    return inv


def check_segment(sid: str, src: str, tgt_raw: str, marks_json: list[dict], glossary: dict[str, Any],
                  lang: str = "zh") -> dict[str, Any]:
    marks = marks_from_json(marks_json)
    masked_src = _remask(src, marks)
    restored, rep = restore(tgt_raw, marks)
    issues: list[dict[str, Any]] = []
    # 1 coverage / placeholders
    for m in rep["missing"]:
        issues.append({"type": "placeholder_missing", "severity": "fail", **m})
    for u in rep["unexpected"]:
        issues.append({"type": "placeholder_unexpected", "severity": "fail", "ph": u})
    for d in rep["duplicated"]:
        issues.append({"type": "placeholder_duplicated", "severity": "fail", **d})
    # 1b placeholder order: numeric/citation/xref/math spans that swap relative order → likely value attached
    #     to the wrong quantity (e.g. "trained for 41.8, scoring 3.5 days"). warn (word order can legitimately change).
    ORDER_KINDS = ("NUM", "CITE", "REF", "MATH", "TERM")
    src_seq = _ph_order(masked_src, ORDER_KINDS)
    tgt_seq = _ph_order(tgt_raw, ORDER_KINDS)
    inv = _order_inversions(src_seq, tgt_seq)
    if inv:
        by_ph = {m.surface: m for m in marks}
        pairs = [{"a": by_ph[a].original if a in by_ph else a, "b": by_ph[b].original if b in by_ph else b} for a, b in inv[:6]]
        sev = "warn"
        issues.append({"type": "placeholder_order_changed", "severity": sev, "n_inversions": len(inv), "pairs": pairs})
    # 2 numbers (compare on restored translation; ignore numbers inside restored spans since they are identical by construction)
    src_nums = _nums(src)
    tgt_nums = _nums(restored)
    missing_nums = list((src_nums - tgt_nums).elements())
    extra_nums = list((tgt_nums - src_nums).elements())
    if missing_nums:
        issues.append({"type": "numbers_missing", "severity": "fail", "values": missing_nums[:10]})
    if extra_nums:
        issues.append({"type": "numbers_added", "severity": "warn", "values": extra_nums[:10]})
    # 3 units
    su, tu = Counter(UNIT_AFTER_NUM.findall(src)), Counter(UNIT_AFTER_NUM.findall(restored))
    miss_u = list((su - tu).elements())
    if miss_u:
        issues.append({"type": "units_missing", "severity": "warn", "values": miss_u[:10]})
    # 4 cross-refs & citations
    sx, tx = Counter(XREF_RE.findall(src)), Counter(XREF_RE.findall(restored))
    if sx != tx:
        issues.append({"type": "xref_mismatch", "severity": "fail", "src": sorted(sx.elements())[:10], "tgt": sorted(tx.elements())[:10]})
    sc, tc = Counter(CITE_RE.findall(src) + CITE_NUM_SUP_RE.findall(src)), Counter(CITE_RE.findall(restored) + CITE_NUM_SUP_RE.findall(restored))
    if sc != tc:
        issues.append({"type": "citation_mismatch", "severity": "fail", "src": sorted(sc.elements())[:10], "tgt": sorted(tc.elements())[:10]})
    # 5 glossary enforcement: each TERM placeholder must be followed by its locked target (we restore → then check target present)
    for mk in marks:
        if mk.kind == "TERM":
            t = glossary.get(mk.term_id, {})
            target = t.get("target") or ""
            if t.get("status") == "keep" or not target:
                continue
            # restored text contains the SOURCE at that position; we require the translator to render the
            # target. We check the raw translation instead: the token was kept verbatim, so the target must
            # appear in the final assembled text — checked in assemble after back-fill. Here check no raw source leaked.
            if re.search(r"(?<![A-Za-z])" + re.escape(mk.original) + r"(?![A-Za-z])", tgt_raw.replace(mk.surface, "")):
                issues.append({"type": "term_source_leaked", "severity": "warn", "term": mk.original, "term_id": mk.term_id})
    # 6 negation / hedging
    ns, nt = len(NEG_SRC_RE.findall(src)), len(re.findall(NEG_TGT.get(lang, NEG_TGT["zh"]), restored))
    if ns > nt:
        issues.append({"type": "negation_possibly_dropped", "severity": "warn", "src_count": ns, "tgt_count": nt})
    hs, ht = len(HEDGE_SRC_RE.findall(src)), len(re.findall(HEDGE_TGT.get(lang, HEDGE_TGT["zh"]), restored))
    if hs >= 2 and ht == 0:
        issues.append({"type": "hedging_possibly_dropped", "severity": "warn", "src_count": hs, "tgt_count": ht})
    # 7 length ratio
    lo, hi = LENGTH_BAND.get(lang, (0.3, 2.0))
    if len(src) >= 40:
        ratio = len(restored) / len(src)
        if ratio < lo:
            issues.append({"type": "too_short_possible_omission", "severity": "warn", "ratio": round(ratio, 2)})
        elif ratio > hi:
            issues.append({"type": "too_long_possible_padding", "severity": "warn", "ratio": round(ratio, 2)})
    # 8 unsure markers
    unsure = UNSURE_RE.findall(restored)
    for u in unsure:
        issues.append({"type": "translator_unsure", "severity": "info", "marker": u})
    sev = {"fail": 0, "warn": 0, "info": 0}
    for i in issues:
        sev[i["severity"]] += 1
    verdict = "fail" if sev["fail"] else ("warn" if sev["warn"] else "pass")
    return {"id": sid, "verdict": verdict, "issues": issues, "placeholders": {"expected": rep["expected"], "found": rep["found"]},
            "restored": restored, "n_unsure": len(unsure)}


def verify(segments: list[dict], translations: dict[str, str], marks: dict[str, list], glossary: dict[str, Any],
           lang: str = "zh") -> dict[str, Any]:
    seg_ids = [s["id"] for s in segments]
    src_by_id = {s["id"]: s["text"] for s in segments}
    missing = [i for i in seg_ids if i not in translations or not str(translations.get(i, "")).strip()]
    extra = [i for i in translations if i not in src_by_id]
    results = []
    for s in segments:
        if s["id"] in missing:
            results.append({"id": s["id"], "verdict": "fail", "issues": [{"type": "missing_translation", "severity": "fail"}],
                            "placeholders": {"expected": len(marks.get(s["id"], [])), "found": 0}, "restored": "", "n_unsure": 0})
            continue
        results.append(check_segment(s["id"], s["text"], str(translations[s["id"]]), marks.get(s["id"], []), glossary, lang))
    # duplicates: same translation used for two different segments (copy-paste failure)
    by_text: dict[str, list[str]] = {}
    for r in results:
        if r["restored"] and len(r["restored"]) > 30:
            by_text.setdefault(r["restored"], []).append(r["id"])
    dup_groups = [v for v in by_text.values() if len(v) > 1]
    summary = {
        "n_segments": len(seg_ids),
        "n_translated": len(seg_ids) - len(missing),
        "missing": missing, "extra": extra,
        "verdicts": {"pass": sum(r["verdict"] == "pass" for r in results), "warn": sum(r["verdict"] == "warn" for r in results),
                     "fail": sum(r["verdict"] == "fail" for r in results)},
        "placeholder_integrity": _integrity(results),
        "duplicate_groups": dup_groups,
        "unsure_markers": sum(r["n_unsure"] for r in results),
        "issue_counts": dict(Counter(i["type"] for r in results for i in r["issues"])),
    }
    return {"summary": summary, "segments": results}


def _integrity(results):
    e = sum(r["placeholders"]["expected"] for r in results)
    f = sum(r["placeholders"]["found"] for r in results)
    return {"expected": e, "found": f, "ratio": round(f / e, 4) if e else 1.0}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="papertrans.verify")
    ap.add_argument("segments_json")
    ap.add_argument("translations_json")
    ap.add_argument("--marks", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    seg = json.loads(Path(a.segments_json).read_text(encoding="utf-8"))
    tr = json.loads(Path(a.translations_json).read_text(encoding="utf-8"))
    if isinstance(tr, dict) and "translations" in tr and isinstance(tr["translations"], dict):
        tr = tr["translations"]
    marks = json.loads(Path(a.marks).read_text(encoding="utf-8"))
    gl = json.loads(Path(a.glossary).read_text(encoding="utf-8"))
    res = verify(seg["segments"], tr, marks, gl, a.lang)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    s = res["summary"]
    print(f"[verify] segments={s['n_segments']} translated={s['n_translated']} verdicts={s['verdicts']} "
          f"placeholders={s['placeholder_integrity']['found']}/{s['placeholder_integrity']['expected']} "
          f"unsure={s['unsure_markers']} issues={s['issue_counts']}")
    return 0 if s["verdicts"]["fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
