#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engines.py — deterministic engines for the reference-management skill.

    dedupe(library)          → merge groups + explainable merge basis  (收得净)
    renumber(manuscript, lib)→ body/list/figure/appendix synced        (编得顺)
    convert(library, style)  → GB/T 7714-2015 | APA 7 | BibTeX | RIS    (格式转换)
    verify(...)              → field/DOI/claim-citation consistency     (对得上)

All engines are pure functions over refmgr objects; no model calls, no network.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from refmgr import (Citation, Entry, Library, Manuscript, author_keys, authors_equivalent, detect_language,
                    format_numeric_marker, has_cjk, normalise_title, split_authors, surname_equiv, TYPE_MAP)

# ============================================================================
# 1. DEDUPE — explainable merge criteria
# ============================================================================
# Each pair gets evidence signals; the decision is a rule table, so it is auditable.
SIGNAL_WEIGHTS = {
    "doi_exact": 5.0,          # same DOI (normalised) — decisive unless title conflicts
    "arxiv_exact": 4.5,        # same arXiv id
    "title_exact": 3.0,        # normalised title identical
    "title_similar": 1.5,      # title similarity ≥ 0.9 (cross-language / typo)
    "title_translated": 2.0,   # one title is a translation of the other (LLM-confirmed or dictionary)
    "authors_overlap": 1.0,    # ≥1 shared family-name key
    "authors_same_first": 1.0, # first author same
    "year_same": 0.5,
    "year_close": 0.3,         # |Δ| ≤ 1 (preprint→published)
    "venue_same": 0.5,
    "volume_pages_same": 1.0,
}
MERGE_THRESHOLD = 5.0        # ≥ → merge
REVIEW_THRESHOLD = 3.0       # [review, merge) → needs human confirmation
# Hard blockers: any of these forbids an automatic merge
BLOCK_DIFFERENT_DOI = True
BLOCK_TITLE_SIM_LOW = 0.6    # if both titles present and similarity < this → never merge on fuzzy


def _doi_norm(d: str) -> str:
    d = (d or "").lower().strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d.rstrip(".,;)")


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _title_tokens(t: str) -> set:
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", (t or "").lower()))


def pair_signals(a: Entry, b: Entry, title_translation_pairs: Optional[List[Tuple[str, str]]] = None) -> Dict[str, float]:
    s: Dict[str, float] = {}
    da, db = _doi_norm(a.doi), _doi_norm(b.doi)
    if da and db and da == db:
        s["doi_exact"] = 1
    if a.arxiv_id and b.arxiv_id and a.arxiv_id == b.arxiv_id:
        s["arxiv_exact"] = 1
    ta, tb = normalise_title(a.title), normalise_title(b.title)
    if ta and tb:
        if ta == tb:
            s["title_exact"] = 1
        else:
            r = _sim(ta, tb)
            if r >= 0.9:
                s["title_similar"] = r
            # cross-language: CJK vs Latin → check a supplied translation dictionary
            if (has_cjk(a.title) != has_cjk(b.title)) and title_translation_pairs:
                for x, y in title_translation_pairs:
                    nx, ny = normalise_title(x), normalise_title(y)
                    if {nx, ny} == {ta, tb} or (nx == ta and ny == tb) or (ny == ta and nx == tb):
                        s["title_translated"] = 1
                        break
    ka, kb = author_keys(a.authors), author_keys(b.authors)
    if ka and kb:
        if set(ka) & set(kb):
            s["authors_overlap"] = len(set(ka) & set(kb)) / max(1, min(len(set(ka)), len(set(kb))))
        elif authors_equivalent(ka, kb):
            s["authors_overlap"] = 0.5          # cross-script surname hint (张 vs Zhang) — half weight
        if ka[0] == kb[0] or surname_equiv(ka[0], kb[0]):
            s["authors_same_first"] = 1
    ya, yb = a.year or "", b.year or ""
    if ya and yb:
        if ya == yb:
            s["year_same"] = 1
        elif abs(int(ya) - int(yb)) <= 1:
            s["year_close"] = 1
    if a.journal and b.journal and normalise_title(a.journal) == normalise_title(b.journal):
        s["venue_same"] = 1
    if a.volume and a.volume == b.volume and (not a.pages or not b.pages or a.pages.split("-")[0] == b.pages.split("-")[0]):
        s["volume_pages_same"] = 1
    return s


def decide_pair(a: Entry, b: Entry, title_translation_pairs=None) -> dict:
    sig = pair_signals(a, b, title_translation_pairs)
    score = sum(SIGNAL_WEIGHTS.get(k, 0) * v for k, v in sig.items())
    blockers: List[str] = []
    if BLOCK_DIFFERENT_DOI and a.doi and b.doi and _doi_norm(a.doi) != _doi_norm(b.doi) and "doi_exact" not in sig:
        # different DOIs are a blocker only if titles are not near-identical (DOIs can be errata/versions)
        if "title_exact" not in sig and "title_similar" not in sig:
            blockers.append("different_doi")
    ta, tb = normalise_title(a.title), normalise_title(b.title)
    if ta and tb and "title_exact" not in sig and "title_similar" not in sig and "title_translated" not in sig:
        if not (has_cjk(a.title) != has_cjk(b.title)):
            blockers.append("title_differs")
    # same first author + same year + different title → likely two different papers (avoid over-merge)
    if "authors_same_first" in sig and "year_same" in sig and "title_differs" in blockers:
        blockers.append("same_author_same_year_different_title")
    if blockers:
        decision = "keep_separate"
    elif "title_translated" in sig and any(k in sig for k in ("authors_overlap", "authors_same_first", "year_same", "year_close", "venue_same", "volume_pages_same")):
        decision = "merge"                 # cross-language title match + corroborating signal
    elif "title_translated" in sig:
        decision = "review"                # translation alone: human confirms
    elif score >= MERGE_THRESHOLD:
        decision = "merge"
    elif score >= REVIEW_THRESHOLD:
        decision = "review"
    else:
        decision = "keep_separate"
    # preferred canonical record: published > preprint; more complete fields
    def quality(e: Entry) -> Tuple[int, int]:
        rank = 0 if e.type == "preprint" else 1
        return (rank, -len(e.is_incomplete()))
    preferred = a.ref_id if quality(a) >= quality(b) else b.ref_id
    return {"a": a.ref_id, "b": b.ref_id, "signals": sig, "score": round(score, 2),
            "decision": decision, "blockers": blockers, "preferred": preferred}


def dedupe(lib: Library, title_translation_pairs=None) -> dict:
    """Union-find over merge decisions. Returns groups + full pair ledger + new Library."""
    ents = lib.entries
    parent = {e.ref_id: e.ref_id for e in ents}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ledger = []
    for i in range(len(ents)):
        for j in range(i + 1, len(ents)):
            d = decide_pair(ents[i], ents[j], title_translation_pairs)
            ledger.append(d)
            if d["decision"] == "merge":
                ra, rb = find(ents[i].ref_id), find(ents[j].ref_id)
                if ra != rb:
                    parent[rb] = ra
    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for e in ents:
        groups.setdefault(find(e.ref_id), []).append(e.ref_id)
    out = Library()
    merge_log = []
    for root, members in groups.items():
        base = next(e for e in ents if e.ref_id == root)
        if len(members) == 1:
            base.merged_from = []
            out.entries.append(base)
            continue
        # choose preferred by quality within the group, keeping the smallest ref_id stable for traceability
        cands = [next(e for e in ents if e.ref_id == m) for m in members]
        best = max(cands, key=lambda e: (0 if e.type == "preprint" else 1, -len(e.is_incomplete())))
        canon = Entry(**best.to_dict())
        canon.ref_id = min(members)                      # stable id = earliest
        canon.merged_from = [m for m in members if m != canon.ref_id]
        basis = []
        for m in canon.merged_from:
            other = next(e for e in ents if e.ref_id == m)
            d = next(x for x in ledger if {x["a"], x["b"]} == {canon.ref_id, m} or
                     (x["a"] in members and x["b"] in members and m in (x["a"], x["b"])))
            basis.append({"merged": m, "signals": d["signals"], "score": d["score"],
                          "title": other.title, "year": other.year, "doi": other.doi,
                          "type": other.type, "source_key": other.source_key})
        canon.merge_basis = basis
        # fill missing fields from the merged siblings (never overwrite non-empty)
        for m in canon.merged_from:
            other = next(e for e in ents if e.ref_id == m)
            for f in ("doi", "arxiv_id", "volume", "issue", "pages", "journal", "publisher", "address", "url", "isbn", "issn", "abstract", "note"):
                if not getattr(canon, f) and getattr(other, f):
                    setattr(canon, f, getattr(other, f))
            if not canon.year and other.year:
                canon.year = other.year
            for k in other.keywords:
                if k not in canon.keywords:
                    canon.keywords.append(k)
            canon.extra.update({k: v for k, v in other.extra.items() if k not in canon.extra})
        out.entries.append(canon)
        merge_log.append({"canonical": canon.ref_id, "merged": canon.merged_from, "basis": basis})
    # order preserved by original first-appearance
    order = {e.ref_id: i for i, e in enumerate(ents)}
    out.entries.sort(key=lambda e: order[min([e.ref_id] + e.merged_from)] if e.merged_from else order[e.ref_id])
    return {"library": out, "groups": groups, "ledger": ledger, "merge_log": merge_log,
            "reviews": [d for d in ledger if d["decision"] == "review"],
            "stats": {"input": len(ents), "output": len(out.entries), "merged": len(ents) - len(out.entries)}}


# ============================================================================
# 2. RENUMBER — first-appearance numbering with body/list/figure/appendix sync
# ============================================================================
CROSSREF_PATTERNS = [  # references to the bibliography from captions/appendix/footnotes
    r"(?:see|cf\.|from|in|data from|参见|见|据|数据来源)\s*\[(\d{1,3}(?:\s*[,，\-–]\s*\d{1,3})*)\]",
    r"\[(\d{1,3}(?:\s*[,，\-–]\s*\d{1,3})*)\]\s*(?:;|；)",  # trailing list refs
]


def renumber(ms: Manuscript, lib: Library, style: str = "numeric", label_fmt: str = "bracket") -> dict:
    """Assign numbers by first appearance in the BODY (excluding the reference list).
    Requires ms.citations[*].resolved to be filled (resolve_citations). Returns mapping and
    a new manuscript text + reference list text. Numbers are stable per run (deterministic)."""
    order: List[str] = []
    for c in sorted(ms.citations, key=lambda c: c.start):
        for rid in c.resolved:
            if rid not in order:
                order.append(rid)
    # cited-but-unresolved and uncited entries are appended (so the list is complete)
    for e in lib.entries:
        if e.ref_id not in order:
            order.append(e.ref_id)
    num = {rid: i + 1 for i, rid in enumerate(order)}
    uncited = [rid for rid in num if rid not in {r for c in ms.citations for r in c.resolved}]
    unresolved = [{"cid": c.cid, "keys": c.unresolved, "raw": c.raw} for c in ms.citations if c.unresolved]

    # rewrite body markers
    rs, re_ = ms.ref_section_range
    body = ms.text[:rs] if rs else ms.text
    edits = []
    for c in sorted(ms.citations, key=lambda c: -c.start):
        nums = [num[r] for r in c.resolved if r in num]
        if not nums:
            continue
        if style == "numeric":
            new = format_numeric_marker(nums, "gbt" if label_fmt == "gbt" else ("ieee" if label_fmt == "ieee" else "bracket"))
            if c.style == "superscript":
                new = "^" + new
        elif style == "author-year":
            new = "(" + "; ".join(_ay_label(lib.get(r)) for r in c.resolved) + ")"
        else:
            new = c.raw
        if new != c.raw:
            body = body[:c.start] + new + body[c.end:]
            edits.append({"cid": c.cid, "before": c.raw, "after": new, "ref_ids": c.resolved, "numbers": nums})
    # reference list
    lines = []
    for rid in order:
        e = lib.get(rid)
        if not e:
            continue
        txt = e.to_gbt7714() if label_fmt in ("gbt", "bracket", "ieee") else e.to_apa()
        lines.append(f"[{num[rid]}] {txt}")
    ref_text = "\n".join(lines)
    # re-assemble
    if rs:
        head = ms.text[:rs].rstrip("\n")
        # detect the heading line of the ref section to keep it
        heading = ms.text[rs:re_].split("\n", 1)[0]
        new_text = body.rstrip("\n") + "\n\n" + heading + "\n\n" + ref_text + "\n"
    else:
        new_text = body.rstrip("\n") + "\n\n## References\n\n" + ref_text + "\n"
    return {"numbering": num, "order": order, "edits": edits, "uncited": uncited,
            "unresolved": unresolved, "new_text": new_text, "ref_list": ref_text,
            "ref_entries": [{"n": num[rid], "ref_id": rid, "text": l} for rid, l in zip(order, lines)]}


def _ay_label(e: Optional[Entry]) -> str:
    if not e:
        return "UNKNOWN"
    ka = author_keys(e.authors)
    a = ka[0].capitalize() if ka else "Anon."
    if len(e.authors) >= 3:
        a += " et al."
    elif len(e.authors) == 2:
        a += " & " + (ka[1].capitalize() if len(ka) > 1 else "")
    return f"{a}, {e.year or 'n.d.'}"


def consistency_check(ms: Manuscript, lib: Library, renum: dict) -> dict:
    """Body ↔ list consistency: continuity, orphans, duplicates, style uniformity, caption/appendix refs."""
    issues: List[dict] = []
    nums_used = sorted({n for c in ms.citations for n in [renum["numbering"].get(r) for r in c.resolved if r in renum["numbering"]]})
    expected = list(range(1, len(renum["order"]) + 1))
    if nums_used and nums_used != expected[:len(nums_used)] and nums_used != list(range(1, max(nums_used) + 1)):
        missing = sorted(set(range(1, max(nums_used) + 1)) - set(nums_used))
        issues.append({"kind": "numbering_gap", "detail": f"numbers {missing} never cited in body", "severity": "warn"})
    if renum["uncited"]:
        issues.append({"kind": "uncited_entries", "detail": renum["uncited"], "severity": "warn"})
    if renum["unresolved"]:
        issues.append({"kind": "unresolved_citations", "detail": renum["unresolved"], "severity": "error"})
    styles = {c.style for c in ms.citations}
    if len(styles) > 1:
        issues.append({"kind": "mixed_marker_styles", "detail": sorted(styles), "severity": "warn"})
    # citation position heuristics (挂得对)
    pos = {"sentence-end": 0, "mid-sentence": 0, "paragraph-end": 0, "caption": 0, "unknown": 0}
    for c in ms.citations:
        pos[c.anchor_status or "unknown"] = pos.get(c.anchor_status or "unknown", 0) + 1
        if c.anchor_status == "paragraph-end" and not re.search(r"[.。;；]\s*$", c.claim):
            issues.append({"kind": "citation_at_paragraph_end", "cid": c.cid, "detail": c.claim[-80:], "severity": "review"})
        if c.anchor_status == "caption":
            issues.append({"kind": "citation_in_caption_only", "cid": c.cid, "detail": c.claim[-80:], "severity": "review"})
    # figure/appendix cross-refs to bibliography numbers
    body = ms.text[:ms.ref_section_range[0]] if ms.ref_section_range[0] else ms.text
    cross = []
    for pat in CROSSREF_PATTERNS:
        for m in re.finditer(pat, body):
            cross.append({"text": m.group(0)[:80], "numbers": re.findall(r"\d+", m.group(1))})
    multi = [c.cid for c in ms.citations if len(c.resolved) > 1]
    return {"issues": issues, "anchor_positions": pos, "crossrefs_in_captions": cross,
            "multi_citation_count": len(multi), "n_citations": len(ms.citations)}


# ============================================================================
# 3. CONVERT — field mapping across BibTeX / RIS / GB/T 7714-2015 / APA 7 / CNKI
# ============================================================================
STYLES = ("gbt7714", "apa7", "bibtex", "ris", "json", "cnki")


def convert(lib: Library, style: str, lang_order: str = "zh-first") -> dict:
    style = style.lower().replace("/", "").replace("-", "").replace(" ", "")
    if style in ("gbt", "gbt7714", "gbt77142015", "gb/t7714", "gbt7714-2015"):
        style = "gbt7714"
    if style in ("apa", "apa7", "apa7th"):
        style = "apa7"
    items = []
    entries = list(lib.entries)
    if lang_order == "zh-first" and style == "gbt7714":
        entries.sort(key=lambda e: 0 if e.language == "zh" else 1)  # stable: keeps numbering within groups
    for i, e in enumerate(entries, 1):
        if style == "gbt7714":
            txt = f"[{i}] {e.to_gbt7714()}"
        elif style == "apa7":
            txt = e.to_apa()
        elif style == "bibtex":
            txt = e.to_bibtex().rstrip("\n")
        elif style == "ris":
            txt = e.to_ris().rstrip("\n")
        else:
            txt = None
        items.append({"n": i, "ref_id": e.ref_id, "text": txt, "entry": e.to_dict()})
    field_report = [{"ref_id": e.ref_id, "missing": e.is_incomplete(), "type": e.type,
                     "language": e.language} for e in entries]
    return {"style": style, "items": items, "field_report": field_report,
            "full_text": ("\n".join(it["text"] for it in items) if style not in ("json",) else lib.to_json()),
            "supported_styles": list(STYLES)}


# ============================================================================
# 4. VERIFY — metadata + DOI + claim↔citation consistency
# ============================================================================
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def verify_entries(lib: Library, crossref: Optional[Dict[str, dict]] = None, offline: bool = True) -> dict:
    """Structural checks always run offline; `crossref` (ref_id → fetched metadata) enables online comparison."""
    report = []
    for e in lib.entries:
        problems: List[dict] = []
        if e.doi and not DOI_RE.match(e.doi):
            problems.append({"field": "doi", "issue": "malformed_doi", "value": e.doi, "severity": "error"})
        for f in e.is_incomplete():
            problems.append({"field": f, "issue": "missing_field", "severity": "warn"})
        if e.type == "journal-article" and e.pages and not re.search(r"\d", e.pages):
            problems.append({"field": "pages", "issue": "pages_without_number", "severity": "warn"})
        if e.year and not re.match(r"^(1[5-9]|20)\d{2}$", str(e.year)[:4]):
            problems.append({"field": "year", "issue": "year_out_of_range", "value": e.year, "severity": "warn"})
        if e.title and len(e.title) < 6:
            problems.append({"field": "title", "issue": "title_too_short", "severity": "warn"})
        if e.url and not e.url.startswith(("http://", "https://")):
            problems.append({"field": "url", "issue": "url_without_scheme", "value": e.url, "severity": "warn"})
        if has_cjk(e.title) and e.language != "zh":
            problems.append({"field": "language", "issue": "language_mismatch", "severity": "info"})
        status = "unverified_offline" if offline and not crossref else "unverified"
        online = None
        if e.verification.get("status") == "no_library_match":
            problems.append({"field": "entry", "issue": "not_in_library", "detail": "cited in manuscript but absent from the supplied library — possible fabricated or mis-transcribed reference",
                             "severity": "error"})
            status = "not_in_library"
        if crossref and e.ref_id in crossref:
            online = _compare_crossref(e, crossref[e.ref_id])
            status = "verified" if online["mismatches"] == [] else "mismatch"
            for m in online["mismatches"]:
                problems.append({"field": m["field"], "issue": "crossref_mismatch", "local": m["local"],
                                 "remote": m["remote"], "severity": m["severity"]})
        elif crossref:
            status = "not_found_remote"
            problems.append({"field": "doi", "issue": "not_found_remote", "severity": "error" if e.doi else "warn"})
        report.append({"ref_id": e.ref_id, "status": status, "problems": problems, "online": online,
                       "fabrication_risk": "high" if (not e.doi and not e.url and not e.isbn and not e.issn and e.type != "other") else "low"})
    n_err = sum(1 for r in report for p in r["problems"] if p["severity"] == "error")
    n_warn = sum(1 for r in report for p in r["problems"] if p["severity"] == "warn")
    return {"entries": report, "summary": {"n": len(report), "errors": n_err, "warnings": n_warn,
                                           "verified": sum(1 for r in report if r["status"] == "verified"),
                                           "mismatch": sum(1 for r in report if r["status"] == "mismatch"),
                                           "unverified": sum(1 for r in report if r["status"].startswith("unverified"))}}


def _compare_crossref(e: Entry, m: dict) -> dict:
    mism = []
    def cmp(field, local, remote, sev="warn", thr=0.85):
        if local and remote and normalise_title(str(local)) != normalise_title(str(remote)):
            if _sim(normalise_title(str(local)), normalise_title(str(remote))) < thr:
                mism.append({"field": field, "local": str(local), "remote": str(remote), "severity": sev})
    cmp("title", e.title, m.get("title"))
    cmp("journal", e.journal, m.get("container_title") or m.get("journal"))
    ry = str(m.get("year") or m.get("issued") or "")[:4]
    if e.year and ry and e.year != ry:
        mism.append({"field": "year", "local": e.year, "remote": ry, "severity": "warn"})
    if e.volume and m.get("volume") and e.volume != str(m.get("volume")):
        mism.append({"field": "volume", "local": e.volume, "remote": m["volume"], "severity": "warn"})
    ra = author_keys(split_authors("; ".join(m.get("authors", []))) if isinstance(m.get("authors"), list) else split_authors(str(m.get("authors", ""))))
    if ra and e.author_keys() and not (set(ra) & set(e.author_keys())):
        mism.append({"field": "authors", "local": e.authors, "remote": m.get("authors"), "severity": "error"})
    return {"mismatches": mism}


def fetch_crossref(dois: List[str], timeout: int = 8) -> Dict[str, dict]:
    """Optional online check via api.crossref.org. Any failure → {} (offline-safe)."""
    out = {}
    try:
        import json, urllib.request, urllib.parse
    except Exception:
        return out
    for d in dois:
        if not d:
            continue
        try:
            url = "https://api.crossref.org/works/" + urllib.parse.quote(d, safe="")
            req = urllib.request.Request(url, headers={"User-Agent": "refmgr-skill/1.0 (mailto:none@example.org)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                msg = json.loads(r.read().decode("utf-8"))["message"]
            out[d] = {"title": (msg.get("title") or [""])[0], "container_title": (msg.get("container-title") or [""])[0],
                      "year": str((msg.get("issued") or msg.get("published-print") or msg.get("published-online") or {}).get("date-parts", [[""]])[0][0]),
                      "volume": msg.get("volume", ""), "authors": [f"{a.get('family','')}, {a.get('given','')}" for a in msg.get("author", [])]}
        except Exception:
            continue
    return out


# claim↔citation consistency is LLM work; this packages the inputs so the model answers per sentence.
def claim_citation_pairs(ms: Manuscript, lib: Library) -> List[dict]:
    out = []
    for c in ms.citations:
        for rid in c.resolved:
            e = lib.get(rid)
            out.append({"cid": c.cid, "ref_id": rid, "claim": c.claim, "anchor": c.anchor_status,
                        "ref_title": e.title if e else None, "ref_year": e.year if e else None,
                        "ref_abstract": (e.abstract[:600] if e and e.abstract else None),
                        "ref_keywords": (e.keywords if e else [])})
    return out
