#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render — turn the ledgers and the accepted draft into the deliverables.

Three things are rendered from the same frozen state, so they cannot disagree:

    introduction_related_work.md   the clean manuscript section (part markers stripped)
    related_work_table.md          the comparison table derived from ledger_groups.json
    refs_cited.bib / .txt          only the works actually cited, in the target style

Rendering never invents a field. A missing year prints as `n.d.` in APA and is
left out of the GB/T string, and the omission is listed in `render_notes`.
"""

from __future__ import annotations

import re

import introlib as L


def strip_slots(text: str) -> tuple:
    """Remove the part markers and any leftover scaffold comment; keep the prose."""
    notes = []
    body = text or ""
    leftovers = re.findall(r"<!--(?!\s*/?part:)(.{0,80}?)-->", body, re.S)
    if leftovers:
        notes.append("removed %d scaffold comment(s) left in the draft" % len(leftovers))
    out = re.sub(r"<!--.*?-->\s*", "", body, flags=re.S)
    # a removed marker must not glue a heading onto the paragraph before it
    out = re.sub(r"([^\n])\n(#{1,6} )", r"\1\n\n\2", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"
    return out, notes


# --------------------------------------------------------------------------- #
# reference rendering
# --------------------------------------------------------------------------- #

def _authors_gbt(authors: list) -> str:
    if not authors:
        return "佚名"
    out = []
    for a in authors[:3]:
        a = L.norm_ws(a)
        if L.CJK_RE.search(a):
            out.append(a)
        else:
            # "Smith, John" -> "SMITH J"; "John Smith" -> "SMITH J"
            if "," in a:
                sur, given = a.split(",", 1)
            else:
                parts = a.split()
                sur, given = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (a, "")
            initials = "".join(x[0] for x in re.findall(r"[A-Za-z]+", given.upper()))
            out.append("%s %s" % (sur.upper().strip(), initials))
    s = ", ".join(x.strip() for x in out)
    if len(authors) > 3:
        s += ", 等" if L.CJK_RE.search(" ".join(authors[:1])) else ", et al"
    return s


def _authors_apa(authors: list) -> str:
    if not authors:
        return "Anon."
    out = []
    for a in authors[:20]:
        a = L.norm_ws(a)
        if L.CJK_RE.search(a):
            out.append(a)
            continue
        if "," in a:
            sur, given = a.split(",", 1)
        else:
            parts = a.split()
            sur, given = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (a, "")
        initials = " ".join("%s." % x[0].upper() for x in re.findall(r"[A-Za-z]+", given))
        out.append("%s%s" % (sur.strip().title() + ", ", initials) if initials else sur.strip().title())
    if len(out) == 1:
        return out[0]
    return ", ".join(out[:-1]) + ", & " + out[-1]


TYPE_TAG = {"journal": "J", "conference": "C", "book": "M", "thesis": "D",
            "report": "R", "web": "EB/OL", "chapter": "M", "preprint": "J/OL",
            "standard": "S", "misc": "Z"}


def render_gbt7714(e: dict, number: int = None) -> str:
    tag = TYPE_TAG.get((e.get("type") or "").lower(), "Z")
    parts = []
    au = _authors_gbt(e.get("authors") or [])
    parts.append(au + ".")
    if e.get("title"):
        parts.append("%s[%s]." % (e["title"], tag))
    if e.get("venue"):
        parts.append("%s," % e["venue"])
    ym = str(e.get("year") or "n.d.")
    vol = e.get("volume") or ""
    iss = e.get("issue") or ""
    if vol:
        ym += ", %s" % vol + ("(%s)" % iss if iss else "")
    elif iss:
        ym += ", (%s)" % iss
    if e.get("pages"):
        ym += ": %s" % e["pages"]
    parts.append(ym + ".")
    if e.get("doi"):
        parts.append("DOI: %s." % e["doi"])
    elif e.get("arxiv"):
        parts.append("arXiv: %s." % e["arxiv"])
    elif e.get("url"):
        parts.append(e["url"] + ".")
    s = " ".join(parts)
    s = re.sub(r"\s+([,.:])", r"\1", s)
    return ("[%d] " % number if number else "") + s


def render_apa7(e: dict) -> str:
    au = _authors_apa(e.get("authors") or [])
    yr = "(%s)." % (e.get("year") or "n.d.")
    ti = (e.get("title") or "Untitled") + "."
    ven = e.get("venue") or ""
    vol = e.get("volume") or ""
    iss = e.get("issue") or ""
    pg = e.get("pages") or ""
    tail = ""
    if vol:
        tail = ", %s" % vol + ("(%s)" % iss if iss else "")
    if pg:
        tail += ", %s" % pg
    s = "%s %s %s" % (au, yr, ti)
    if ven:
        s += " %s%s." % (ven, tail)
    if e.get("doi"):
        s += " https://doi.org/%s" % e["doi"]
    elif e.get("url"):
        s += " " + e["url"]
    return L.norm_ws(s)


def render_bibtex(e: dict) -> str:
    t = (e.get("type") or "misc").lower()
    kind = {"journal": "article", "conference": "inproceedings", "book": "book",
            "thesis": "phdthesis", "report": "techreport", "chapter": "incollection",
            "preprint": "misc", "web": "misc"}.get(t, "misc")
    key = e.get("key") or (L.surname_of((e.get("authors") or ["anon"])[0]).lower().replace(" ", "")
                           + str(e.get("year") or ""))
    fields = [("title", e.get("title")), ("author", " and ".join(e.get("authors") or [])),
              ("year", e.get("year")),
              ("journal" if kind == "article" else "booktitle", e.get("venue")),
              ("volume", e.get("volume")), ("number", e.get("issue")),
              ("pages", (e.get("pages") or "").replace("-", "--") or None),
              ("publisher", e.get("publisher")), ("doi", e.get("doi")),
              ("eprint", e.get("arxiv")), ("url", e.get("url"))]
    body = ",\n".join("  %s = {%s}" % (k, v) for k, v in fields if v not in (None, "", []))
    return "@%s{%s,\n%s\n}" % (kind, key, body)


def render_ieee(e: dict, number: int = None) -> str:
    """Numbered IEEE style — the natural rendering for an English numeric-citation
    manuscript, and the reason GB/T 7714 is not forced onto English references."""
    def au(a):
        a = L.norm_ws(a)
        if "," in a:
            sur, given = a.split(",", 1)
        else:
            parts = a.split()
            sur, given = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (a, "")
        ini = " ".join("%s." % x[0].upper() for x in re.findall(r"[A-Za-z]+", given))
        return ("%s %s" % (ini, sur)).strip() if ini else sur.strip()

    names = [au(a) for a in (e.get("authors") or []) if L.norm_ws(a)]
    if len(names) > 3:
        who = ", ".join(names[:3]) + ", et al."
    elif len(names) == 3:
        who = "%s, %s, and %s" % tuple(names)
    elif len(names) == 2:
        who = "%s and %s" % tuple(names)
    elif names:
        who = names[0]
    else:
        who = "Anon."

    s = who + ", "
    if e.get("title"):
        s += "\u201c%s,\u201d " % e["title"]
    ven = e.get("venue") or ""
    if ven:
        low = (e.get("type") or "").lower()
        prefix = "in Proc. " if low == "conference" else ("in " if low in ("book", "chapter") else "")
        s += prefix + ven + ", "
    if e.get("volume"):
        s += "vol. %s, " % e["volume"]
    if e.get("issue"):
        s += "no. %s, " % e["issue"]
    if e.get("pages"):
        s += "pp. %s, " % e["pages"]
    s += "%s." % (e.get("year") or "n.d.")
    if e.get("doi"):
        s += " doi: %s." % e["doi"]
    elif e.get("arxiv"):
        s += " arXiv:%s." % e["arxiv"]
    s = re.sub(r",\s*\.", ".", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return ("[%d] " % number if number else "") + s


def render_reference_block(entries: list, style: str, numbers: dict = None) -> str:
    """Render the cited subset.

    `numbers` maps ref_id -> the citation number the draft actually uses. For a
    numeric manuscript the list must follow those numbers, not the order the
    references happen to be discovered: a bibliography whose [1] is not the
    draft's [1] is a defect, not a formatting choice.
    """
    style = (style or "").lower()
    entries = [e for e in entries if e]
    if numbers and style in ("numeric", "numeric-en", "ieee", "gbt7714", "gbt"):
        entries = sorted(entries, key=lambda e: (numbers.get(e.get("ref_id"), 10 ** 6),
                                                 e.get("ref_id") or ""))
    lines = []
    for i, e in enumerate(entries, 1):
        n = (numbers or {}).get(e.get("ref_id"), i)
        if style in ("ieee", "numeric-en"):
            lines.append(render_ieee(e, n))
        elif style in ("apa7", "apa", "author-year"):
            lines.append(render_apa7(e))
        elif style in ("bibtex", "bib"):
            lines.append(render_bibtex(e))
        else:
            lines.append(render_gbt7714(e, n))
    return "\n\n".join(lines) + ("\n" if lines else "")


# --------------------------------------------------------------------------- #
# comparison table
# --------------------------------------------------------------------------- #

def render_group_table(groups: list, entries_by_id: dict, lang: str = "zh") -> str:
    zh = lang == "zh"
    out = []
    hdr = ("| 代表工作 | 方法路线 | 数据/场景 | 评价方式 | 结论 | 局限 |"
           if zh else
           "| Work | Method route | Data / setting | Evaluation | Conclusion | Limitation |")
    sep = "|---|---|---|---|---|---|"
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        gid = g.get("label") or g.get("group_id") or "?"
        dim = g.get("dimension") or ""
        if not g.get("works"):
            out.append("### %s\n\n%s\n\n%s\n" % (gid, dim, hdr + "\n" + sep))
            continue
        out.append("### %s\n" % gid)
        if dim:
            out.append("%s: %s\n" % ("比较维度" if zh else "Dimension", dim))
        rows = [hdr, sep]
        for w in g["works"]:
            if not isinstance(w, dict):
                continue
            e = entries_by_id.get(w.get("ref_id") or "") or {}
            name = L.norm_ws(str(w.get("label") or e.get("key") or w.get("ref_id") or ""))
            yr = e.get("year") or ""
            who = ("%s %s" % (L.surname_of((e.get("authors") or [""])[0]), yr)).strip()
            cells = [who or name, w.get("method_route") or "", w.get("data_setting") or "",
                     w.get("evaluation") or "", w.get("conclusion") or "", w.get("limitation") or ""]
            cells = [re.sub(r"\s*\n\s*", " ", str(c)).replace("|", "/") for c in cells]
            rows.append("| " + " | ".join(cells) + " |")
        out.append("\n".join(rows) + "\n")
        cmp_ = g.get("comparison") or {}
        if cmp_.get("tradeoff"):
            out.append("**%s**: %s\n" % ("取舍" if zh else "Trade-off", cmp_["tradeoff"]))
        if cmp_.get("best_for"):
            out.append("**%s**: %s\n" % ("适用条件" if zh else "Best for", cmp_["best_for"]))
    return "\n".join(out).strip() + "\n"


def render_contribution_table(contribs: list, lang: str = "zh") -> str:
    zh = lang == "zh"
    hdr = ("| 贡献 | 类型 | 证据定位 | 原文依据 | 不主张 |" if zh
           else "| Contribution | Kind | Evidence | Source claim | Not claimed |")
    rows = [hdr, "|---|---|---|---|---|"]
    for c in contribs or []:
        if not isinstance(c, dict):
            continue
        ev = "; ".join("%s:%s" % (x.get("locator_type"), x.get("locator"))
                       for x in (c.get("evidence") or []) if isinstance(x, dict))
        sc = c.get("scope") or {}
        limits = sc.get("stated_limits") or sc.get("not_claimed") or ""
        if isinstance(limits, list):
            limits = "; ".join(str(x) for x in limits)
        rows.append("| %s | %s | %s | %s | %s |" % (
            str(c.get("text") or "").replace("|", "/").replace("\n", " "),
            c.get("kind") or "", ev.replace("|", "/"),
            str((c.get("evidence") or [{}])[0].get("claim_in_source") or "").replace("|", "/")[:120]
            if c.get("evidence") else "",
            str(limits).replace("|", "/")))
    return "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- #
# audit report (markdown, for humans)
# --------------------------------------------------------------------------- #

def render_audit_md(report: dict, lang: str = "zh") -> str:
    zh = lang == "zh"
    s = report.get("summary") or {}
    out = []
    out.append("# %s\n" % ("引言与相关工作 核对报告" if zh else "Introduction & Related Work audit report"))
    out.append("**case_id**: `%s`  |  **gate**: **%s**  |  **errors**: %d  |  **warnings**: %d\n"
               % (report.get("case_id"), report.get("gate"), s.get("errors", 0), s.get("warnings", 0)))
    if report.get("must_fix"):
        out.append("\n## %s\n" % ("必须先修的问题" if zh else "Must fix"))
        for m in report["must_fix"]:
            out.append("- **%s/%s** %s" % (m["rule"], m["code"], m["message"]))
    out.append("\n## %s\n" % ("按四个问题汇总" if zh else "By question"))
    out.append("| %s | checks | errors | warnings |" % ("问题" if zh else "Question"))
    out.append("|---|---|---|---|")
    for q, agg in (report.get("by_question") or {}).items():
        out.append("| %s | %d | %d | %d |" % (q, len(agg["checks"]), agg["error"], agg["warn"]))
    out.append("\n## %s\n" % ("逐条检查" if zh else "Checks"))
    out.append("| rule | title | status | checked | errors | warnings |")
    out.append("|---|---|---|---|---|---|")
    for c in report.get("checks") or []:
        out.append("| %s | %s | **%s** | %d | %d | %d |"
                   % (c["id"], c["title"], c["status"], c["checked"], c["n_error"], c["n_warn"]))
    out.append("")
    for c in report.get("checks") or []:
        fs = [f for f in c.get("findings") or [] if f["severity"] in ("error", "warn")]
        if not fs:
            continue
        out.append("### %s %s (%s)" % (c["id"], c["title"], c["question"]))
        for f in fs[:12]:
            mark = "ERROR" if f["severity"] == "error" else "warn"
            out.append("- `%s` **%s** — %s" % (mark, f["code"], f["message"]))
        if len(fs) > 12:
            out.append("- … %d more" % (len(fs) - 12))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
