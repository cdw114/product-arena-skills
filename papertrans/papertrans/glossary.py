#!/usr/bin/env python3
"""
papertrans.glossary — Deterministic term candidate extraction + locked glossary management.

Why: term consistency cannot be achieved by "please be consistent" prompts. We extract
candidate terms from the source deterministically, let the agent approve/edit the list once
(a tiny JSON), and then *enforce* it by masking every occurrence as a placeholder that the
translator must copy verbatim; after translation the placeholder is restored with the locked
target rendering. Consistency is therefore guaranteed by construction for every locked term.

Candidate scoring:
  - multi-word technical phrases (2–5 words), Capitalized or containing domain suffixes
    (-tion, -ment, -ity, -ness, -sis, -ose, -ase, -ity, -ance …) or hyphenated
  - weight: title ×5, abstract (first body block on page 1) ×3, headings ×3, captions ×2, body ×1
  - frequency across distinct roles (title/abstract/heading/caption/body) is what matters
  - stoplist of generic academic English; abbreviation pairing "long form (ABBR)" detected automatically

Glossary JSON format (glossary.json / glossary_reviewed.json):
  {"T001": {"source": "graph neural network", "target": "图神经网络", "abbr": "GNN",
            "pos": "noun", "domain": "ML", "note": "", "status": "approved"},
   ...}
  status ∈ approved | proposed | rejected | keep (do not translate, e.g., proper nouns)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

STOP = set("""
we our the a an of in on at to for from with without by as is are was were be been being this that these those
it its their there here which who whom whose what when where why how not no nor and or but if then than so such
can could may might must shall should will would has have had do does did using used use based via per
also both each either neither more most less least very much many few some any all other another others
same different new old first second third last next previous following above below between among within
into onto over under through during after before while until since about against among
results methods materials discussion conclusions introduction abstract references acknowledgements
study work paper report research analysis approach method model models data set dataset system systems
effect effects role roles impact impacts importance importance importance level levels value values
number numbers case cases part parts time times way ways fact facts point points issue issues
well known however thus therefore moreover furthermore additionally respectively
figure figures table tables equation equations scheme section supplementary appendix
high low higher lower large small larger smaller increase decrease increased decreased
shown show shows showing suggest suggests suggested demonstrate demonstrates demonstrated
propose proposed present presents presented provide provides provided report reports reported
observe observes observed found find finds found
""".split())

# Domain-bearing suffixes (English)
SUFFIX = re.compile(r"(tion|sion|ment|ness|ity|ise|ize|ase|ose|sis|ure|ance|ence|ship|age|ing|ism|ist)$")
BAD_EDGE = set("""is are was were be been of in on at to for from with by as and or only than then that this these those
its it their our we you they he she which who whom what when where why how also both each other more most less
such can could may might must shall should will would has have had do does did not no nor using used use based via per
into onto over under between among within during after before while until since about against including regarding
""".split())
ARTICLES = {"a", "an", "the"}
GENERIC_ING = set(("using", "based", "including", "regarding", "concerning", "according", "following",
                   "resulting", "corresponding", "underlying", "existing", "promising", "increasing",
                   "decreasing", "growing", "rising", "setting", "training", "testing", "scattering",
                   "imaging", "modeling", "modelling", "screening", "sampling", "annealing", "cooling",
                   "heating", "stirring", "mapping", "tracking", "pulsing", "yielding", "doping"))

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-’']*")
VERB_HEADS = set("""generalizes generalise generalize shows show achieve achieves achieved improves improve improves
outperforms outperform requires require requires enables enable enables contains contain contains
depends depend depends uses use used yields yield yields produces produce produces indicates indicate
suggests suggest suggests demonstrates demonstrate demonstrates represents represent represents includes
include includes involves involve involves forms form forms""".split())
ABBR_PAIR_RE = re.compile(r"\b((?:[A-Z][a-z]+[ \-]){1,4}[A-Z][a-z]+(?:[ \-][a-z]{2,5}){0,2})\s*\(([A-Z]{2,7})\)")
ABBR_PAIR_RE2 = re.compile(r"\b([a-z]+(?:[ \-][a-z]{2,8}){1,4})\s*\(([A-Z]{2,7})\)")

ROLE_WEIGHT = {"title": 5, "heading": 3, "caption": 2, "body": 1, "list": 1, "footnote": 1, "equation": 0, "abstract": 3}


def _is_candidate(phrase: str) -> bool:
    words = phrase.replace("-", " ").split()
    if not (2 <= len(words) <= 5):
        return False
    if any(w.lower() in STOP for w in words if len(w) > 2):
        return False
    if words[0].lower() in BAD_EDGE or words[-1].lower() in BAD_EDGE:
        return False
    if words[0].lower() in ARTICLES:
        return False
    if any(w.lower() in BAD_EDGE for w in words[1:-1] if len(w) <= 3 and not w.isupper()):
        return False
    # too generic: all common short words
    if all(len(w) < 4 for w in words):
        return False
    if words[-1].lower() in GENERIC_ING:
        return False
    has_domain = bool(SUFFIX.search(words[-1].lower())) or bool(SUFFIX.search(words[0].lower())) or ("-" in phrase)
    has_abbr = any(w.isupper() and len(w) >= 2 for w in words) or any(w.isdigit() for w in words)
    has_cap = all(w[0].isupper() for w in words if w[0].isalpha())
    long_word = any(len(w) >= 10 for w in words)
    # head noun must look like a noun: suffix, hyphen, capitalized, long, or a known noun ending
    head = words[-1].lower()
    head_ok = bool(SUFFIX.search(head)) or "-" in words[-1] or words[-1][0].isupper() or len(head) >= 8 or head.endswith(("er", "or", "ant", "cy", "ry", "ty"))
    if head in VERB_HEADS or head.endswith(("izes", "ises", "ates", "ifies", "generalizes")):
        head_ok = False
    if not head_ok:
        return False
    # Technical phrases: domain suffix, hyphenated, abbreviation, fully capitalized, or a long word
    return has_domain or has_abbr or has_cap or long_word


def _ngrams(text: str, n_max: int = 5) -> list[str]:
    toks = [(m.group(0), m.start()) for m in TOKEN_RE.finditer(text)]
    out = []
    for n in range(2, n_max + 1):
        for i in range(len(toks) - n + 1):
            # ensure tokens are adjacent (single space/hyphen) to avoid spanning punctuation
            ok = True
            for j in range(i, i + n - 1):
                gap = toks[j + 1][1] - (toks[j][1] + len(toks[j][0]))
                if gap > 1 or (text[toks[j][1] + len(toks[j][0]):toks[j + 1][1]] not in (" ", "-", " ")):
                    ok = False
                    break
            if not ok:
                continue
            phrase = " ".join(t[0] for t in toks[i:i + n])
            out.append(phrase)
    return out


def extract_candidates(segments: list[dict[str, Any]], top_k: int = 40, min_weight: int = 4,
                       min_count: int = 2) -> list[dict[str, Any]]:
    weighted: Counter = Counter()
    counts: Counter = Counter()
    roles: dict[str, set] = defaultdict(set)
    pages: dict[str, set] = defaultdict(set)
    abbrs: dict[str, str] = {}
    # first body block on page 1 = abstract proxy
    abstract_ids = [s["id"] for s in segments if s["page"] == 1 and s["role"] == "body"][:2]
    for s in segments:
        w = ROLE_WEIGHT.get(s["role"], 1)
        if s["id"] in abstract_ids:
            w = 3
        if w == 0:
            continue
        for ph in _ngrams(s["text"]):
            if not _is_candidate(ph):
                continue
            key = ph
            weighted[key] += w
            counts[key] += 1
            roles[key].add(s["role"])
            pages[key].add(s["page"])
        for m in ABBR_PAIR_RE.finditer(s["text"]):
            abbrs.setdefault(m.group(1).lower(), m.group(2))
        for m in ABBR_PAIR_RE2.finditer(s["text"]):
            k = m.group(1).lower()
            if k in abbrs or counts[k]:
                abbrs.setdefault(k, m.group(2))
    # collapse case variants: keep most frequent casing
    by_lower: dict[str, list[str]] = defaultdict(list)
    for k in weighted:
        by_lower[k.lower()].append(k)
    cands = []
    for low, variants in by_lower.items():
        best = max(variants, key=lambda v: (weighted[v], counts[v]))
        total_w = sum(weighted[v] for v in variants)
        total_c = sum(counts[v] for v in variants)
        if total_w < min_weight and total_c < min_count:
            continue
        if total_w < 2 and total_c < 3:
            continue
        rs: set = set()
        ps: set = set()
        for v in variants:
            rs |= roles[v]
            ps |= pages[v]
        cands.append({
            "source": best, "weight": total_w, "count": total_c,
            "roles": sorted(rs), "n_pages": len(ps), "pages": sorted(ps)[:6],
            "abbr": abbrs.get(low, ""),
        })
    cands.sort(key=lambda c: (-c["weight"], -c["count"], c["source"]))
    cands = _collapse_nested(cands)
    return cands[:top_k]


def _collapse_nested(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a candidate if it is a strict sub-phrase of a higher/equal-ranked candidate whose weight is
    ≥ 60% of the sum (nested n-grams like 'scaled dot-product' ⊂ 'scaled dot-product attention').
    Also merge simple plural variants ('training cost' ≡ 'training costs')."""
    # merge plural variants
    merged: dict[str, dict[str, Any]] = {}
    for c in cands:
        key = re.sub(r"(?:s|es)$", "", c["source"].lower().split()[-1]) + "|" + " ".join(c["source"].lower().split()[:-1])
        if key in merged:
            m = merged[key]
            m["weight"] += c["weight"]
            m["count"] += c["count"]
            m["roles"] = sorted(set(m["roles"]) | set(c["roles"]))
            m["pages"] = sorted(set(m["pages"]) | set(c["pages"]))
            if c["count"] > m["count"] or (c["count"] == m["count"] and not c["source"].endswith("s")):
                m["source"] = c["source"]
            if c.get("abbr") and not m.get("abbr"):
                m["abbr"] = c["abbr"]
        else:
            merged[key] = dict(c)
    cands = sorted(merged.values(), key=lambda c: (-c["weight"], -c["count"], c["source"]))
    kept: list[dict[str, Any]] = []
    for c in cands:
        low = " " + re.sub(r"\s+", " ", c["source"].lower()) + " "
        redundant = False
        for k in kept:
            klo = " " + re.sub(r"\s+", " ", k["source"].lower()) + " "
            if low.strip() != klo.strip() and low in klo and c["weight"] < 1.05 * k["weight"]:
                redundant = True
                break
        if not redundant:
            kept.append(c)
    return kept


def build_glossary(cands: list[dict[str, Any]], target_lang: str = "zh") -> dict[str, Any]:
    gl: dict[str, Any] = {}
    for i, c in enumerate(cands, 1):
        tid = f"T{i:03d}"
        gl[tid] = {
            "source": c["source"], "target": "", "abbr": c["abbr"], "pos": "noun",
            "domain": "", "note": f"weight={c['weight']} count={c['count']} roles={','.join(c['roles'])} pages={c['pages']}",
            "status": "proposed",
        }
    return gl


def load_glossary(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, list):  # tolerate list form
        return {f"T{i+1:03d}": x for i, x in enumerate(data)}
    return data


def active_terms(glossary: dict[str, Any]) -> list[tuple[str, str]]:
    """[(source_surface, term_id)] for approved/keep terms, longest first."""
    out = []
    for tid, t in glossary.items():
        if t.get("status") in ("approved", "keep") and t.get("source"):
            out.append((t["source"].strip(), tid))
    return sorted(out, key=lambda x: -len(x[0]))


def validate_glossary(glossary: dict[str, Any]) -> list[str]:
    errs = []
    seen_targets: dict[str, str] = {}
    for tid, t in glossary.items():
        if t.get("status") == "approved":
            if not t.get("target"):
                errs.append(f"{tid} approved but target is empty")
            src = t.get("source", "").lower()
            tgt = t.get("target", "").strip()
            if tgt and tgt in seen_targets and seen_targets[tgt] != src:
                errs.append(f"{tid} target '{tgt}' already used for '{seen_targets[tgt]}' (one-to-one violated)")
            if tgt:
                seen_targets[tgt] = src
            if t.get("abbr") and t["abbr"].lower() == tgt.lower():
                errs.append(f"{tid} target equals abbreviation")
        if t.get("status") not in ("approved", "keep", "proposed", "rejected"):
            errs.append(f"{tid} unknown status {t.get('status')}")
    return errs


def apply_glossary(segments: list[dict[str, Any]], glossary: dict[str, Any]) -> dict[str, Any]:
    """Attach glossary hits to each segment and compute per-batch relevant term subsets."""
    from .protect import term_pattern

    terms = active_terms(glossary)
    by_id = {tid: glossary[tid] for _, tid in terms}
    pats = {tid: re.compile(r"(?<![A-Za-z])(?:" + term_pattern(surface) + r")(?![A-Za-z])", re.I) for surface, tid in terms}
    hits_per_seg: dict[str, list[str]] = {}
    for s in segments:
        hits = [tid for tid, pat in pats.items() if pat.search(s["text"])]
        s["glossary_hits"] = hits
        hits_per_seg[s["id"]] = hits
    total_occ = Counter()
    for s in segments:
        for tid, pat in pats.items():
            total_occ[tid] += len(pat.findall(s["text"]))
    return {"hits_per_segment": hits_per_seg, "total_occurrences": dict(total_occ),
            "terms": {tid: by_id[tid] for _, tid in terms}}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="papertrans.glossary", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("segments_json")
    ap.add_argument("--out", required=True, help="output glossary.json (proposed)")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--min-weight", type=int, default=4)
    ap.add_argument("--apply", action="store_true", help="annotate segments with hits (needs --reviewed)")
    ap.add_argument("--reviewed", help="reviewed glossary to apply/validate")
    a = ap.parse_args(argv)
    seg = json.loads(Path(a.segments_json).read_text(encoding="utf-8-sig"))
    segments = seg["segments"] if isinstance(seg, dict) else seg
    if a.apply:
        gl = load_glossary(Path(a.reviewed))
        errs = validate_glossary(gl)
        info = apply_glossary(segments, gl)
        seg["glossary_hits"] = info["hits_per_segment"]
        Path(a.out).write_text(json.dumps(seg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[glossary] validated errors={len(errs)} active_terms={len(info['terms'])} "
              f"occurrences={sum(info['total_occurrences'].values())}")
        for e in errs:
            print("  !", e)
        return 1 if errs else 0
    cands = extract_candidates(segments, a.top, a.min_weight)
    gl = build_glossary(cands)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(gl, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[glossary] candidates={len(gl)} → {a.out}")
    for tid, t in list(gl.items())[:15]:
        print(f"  {tid} {t['source']!r} w={t['note'].split()[0]} {t['abbr'] and ('ABBR=' + t['abbr'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
