#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refmgr.py ’canonical reference & citation model for the reference-management skill.

Design principle
----------------
Everything downstream works on *stable* keys, never on numbers:

    library entry  --(ref_id)-->  manuscript citation marker
                                        |
                                   numbering pass (derived, deterministic)
                                        |
                              body labels == list order == figure/appendix labels

So inserting / deleting / reordering never leaves the body and the reference list
out of sync: numbers are *computed* from first-appearance order every time.

No third-party dependencies. Python >= 3.8. All text I/O is UTF-8.

Public API (used by run_case.py and the agent-facing commands):
    Entry                 canonical record for one bibliographic item
    Library               list of Entry + parse/serialise helpers
    Manuscript            text + section model + citation markers
    Citation              one in-text citation occurrence (set of ref_ids)
    parse_library()       .bib / .ris / .json / .csv / CNKI .txt / free text -> Library
    parse_manuscript()    .md / .txt / plain text (from docx) -> Manuscript
    normalise_title()     for dedup
    author_keys()         for dedup
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Tuple

__version__ = "1.0.0"

# --------------------------------------------------------------------------------------
# Bibliographic types
# --------------------------------------------------------------------------------------
# Canonical type keys and how they map to/from BibTeX / RIS / GB/T 7714 / APA
BIBTEX_TYPES = {
    "article", "inproceedings", "conference", "proceedings", "book", "inbook",
    "incollection", "phdthesis", "mastersthesis", "techreport", "misc", "unpublished",
    "online", "preprint", "dataset", "software", "chapter", "booklet", "manual",
}
TYPE_MAP = {
    # canonical: (bibtex, ris[TY], gbt_type_code, apa_kind)
    "journal-article":   ("article",         "JOUR", "J", "journal"),
    "conference-paper":  ("inproceedings",   "CPAPER", "C", "proceedings"),
    "book":              ("book",            "BOOK", "M", "book"),
    "book-chapter":      ("incollection",    "CHAP", "M", "chapter"),
    "thesis-phd":        ("phdthesis",       "THES", "D", "thesis"),
    "thesis-masters":    ("mastersthesis",   "THES", "D", "thesis"),
    "tech-report":       ("techreport",      "RPRT", "R", "report"),
    "preprint":          ("misc",            "UNPB", "Z", "preprint"),
    "webpage":           ("online",          "ELEC", "EB/OL", "webpage"),
    "dataset":           ("dataset",         "DATA", "DS", "dataset"),
    "software":          ("software",        "COMP", "CP", "software"),
    "other":             ("misc",            "GEN", "Z", "other"),
}
RIS_TO_CANONICAL = {v[1]: k for k, v in TYPE_MAP.items()}
BIBTEX_TO_CANONICAL = {
    "article": "journal-article", "inproceedings": "conference-paper", "conference": "conference-paper",
    "proceedings": "conference-paper", "book": "book", "inbook": "book-chapter",
    "incollection": "book-chapter", "chapter": "book-chapter", "phdthesis": "thesis-phd",
    "mastersthesis": "thesis-masters", "techreport": "tech-report", "misc": "other",
    "unpublished": "preprint", "online": "webpage", "electronic": "webpage",
    "dataset": "dataset", "software": "software", "manual": "other", "booklet": "other",
}


def infer_type(e: dict) -> str:
    """Infer canonical type from a loosely-typed record (BibTeX/RIS/JSON/CNKI fields)."""
    t = (e.get("type") or e.get("entry_type") or e.get("document_type") or "").lower().strip()
    if t in TYPE_MAP:
        return t
    if t in BIBTEX_TO_CANONICAL:
        return BIBTEX_TO_CANONICAL[t]
    if t in RIS_TO_CANONICAL:
        return RIS_TO_CANONICAL[t]
    tt = t.upper()
    if tt in RIS_TO_CANONICAL:
        return RIS_TO_CANONICAL[tt]
    # heuristics
    if e.get("journal") or e.get("container_title") or e.get("source") and not e.get("publisher"):
        return "journal-article"
    if any(k in e for k in ("booktitle", "proceedings_title", "conference")):
        return "conference-paper"
    if "publisher" in e and not e.get("journal"):
        return "book"
    if "thesis" in json.dumps(e, ensure_ascii=False).lower():
        return "thesis-phd"
    if "arxiv" in json.dumps(e, ensure_ascii=False).lower() or "preprint" in t:
        return "preprint"
    return "other"


@dataclass
class Entry:
    """One bibliographic item in canonical form. Extra fields are kept in `extra`."""
    ref_id: str                                   # stable key, e.g. R001
    type: str = "other"                           # canonical type key
    title: str = ""
    authors: List[str] = field(default_factory=list)   # "Family, Given" or full name as given
    year: Optional[str] = None
    journal: str = ""                             # journal / container / proceedings title
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    address: str = ""
    doi: str = ""
    url: str = ""
    isbn: str = ""
    issn: str = ""
    language: str = ""                            # 'zh' | 'en' | '' (unknown)
    arxiv_id: str = ""
    note: str = ""
    abstract: str = ""
    keywords: List[str] = field(default_factory=list)
    source_file: str = ""                         # which input file / record it came from
    source_key: str = ""                          # original key in that file (BibTeX key, RIS ID ...)
    extra: Dict[str, str] = field(default_factory=dict)
    # provenance / merge bookkeeping
    merged_from: List[str] = field(default_factory=list)
    merge_basis: List[str] = field(default_factory=list)
    verification: Dict[str, object] = field(default_factory=dict)

    # ----------------------------------------------------------------- helpers
    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def sort_title(self) -> str:
        return normalise_title(self.title)

    def author_keys(self) -> List[str]:
        return author_keys(self.authors)

    def fingerprint(self) -> str:
        """Cheap identity fingerprint used for exact-duplicate detection."""
        return "|".join([
            self.doi.lower().strip(), self.sort_title, ",".join(self.author_keys()[:3]),
            (self.year or "")[:4], self.volume, self.issue, self.pages,
        ])

    def is_incomplete(self) -> List[str]:
        """Fields that the target styles normally require (missing → warn, not error)."""
        missing = []
        if not self.title:
            missing.append("title")
        if not self.authors:
            missing.append("authors")
        if not self.year:
            missing.append("year")
        if self.type == "journal-article":
            if not self.journal:
                missing.append("journal")
            if not self.volume and not self.issue:
                missing.append("volume/issue")
            if not self.pages:
                missing.append("pages")
        if self.type == "conference-paper" and not self.journal:
            missing.append("proceedings")
        if self.type in ("book", "book-chapter") and not self.publisher:
            missing.append("publisher")
        return missing

    # ----------------------------------------------------------------- BibTeX
    def to_bibtex(self, key: Optional[str] = None) -> str:
        key = key or self.source_key or self.ref_id
        bt = TYPE_MAP.get(self.type, TYPE_MAP["other"])[0]
        fields: List[Tuple[str, str]] = []
        if self.authors:
            fields.append(("author", " and ".join(_bib_author(a) for a in self.authors)))
        fields.append(("title", "{" + self.title + "}"))
        if self.type in ("journal-article",):
            fields.append(("journal", self.journal))
        elif self.type == "conference-paper":
            fields.append(("booktitle", self.journal))
        elif self.type in ("book", "book-chapter"):
            fields.append(("publisher", self.publisher)) if self.publisher else None
            if self.type == "book-chapter":
                fields.append(("booktitle", self.journal)) if self.journal else None
        if self.year:
            fields.append(("year", str(self.year)))
        if self.volume:
            fields.append(("volume", self.volume))
        if self.issue:
            fields.append(("number", self.issue))
        if self.pages:
            fields.append(("pages", self.pages.replace("-", "--") if "--" not in self.pages else self.pages))
        if self.publisher and self.type not in ("book", "book-chapter"):
            fields.append(("publisher", self.publisher))
        if self.address:
            fields.append(("address", self.address))
        if self.doi:
            fields.append(("doi", self.doi))
        if self.url:
            fields.append(("url", self.url))
        if self.isbn:
            fields.append(("isbn", self.isbn))
        if self.issn:
            fields.append(("issn", self.issn))
        if self.arxiv_id:
            fields.append(("eprint", self.arxiv_id))
            fields.append(("archiveprefix", "arXiv"))
        if self.keywords:
            fields.append(("keywords", "; ".join(self.keywords)))
        if self.note:
            fields.append(("note", self.note))
        if self.language == "zh":
            fields.append(("language", "zh"))
        body = ",\n".join(f"  {k} = {{{_bib_escape(v)}}}" for k, v in fields)
        return f"@{bt}{{{key},\n{body}\n}}\n"

    # ----------------------------------------------------------------- RIS
    def to_ris(self) -> str:
        ris_ty = TYPE_MAP.get(self.type, TYPE_MAP["other"])[1]
        lines = [f"TY  - {ris_ty}"]
        for a in self.authors:
            lines.append(f"AU  - {_ris_author(a)}")
        if self.title:
            lines.append(f"TI  - {self.title}")
        if self.journal:
            tag = "T2" if self.type in ("journal-article", "book-chapter") else (
                "T2" if self.type == "conference-paper" else "T2")
            lines.append(f"{tag}  - {self.journal}")
        if self.year:
            lines.append(f"PY  - {self.year}")
        if self.volume:
            lines.append(f"VL  - {self.volume}")
        if self.issue:
            lines.append(f"IS  - {self.issue}")
        if self.pages:
            lines.append(f"SP  - {self.pages.split('-')[0].strip()}")
            if "-" in self.pages:
                lines.append(f"EP  - {self.pages.split('-')[-1].strip()}")
        if self.publisher:
            lines.append(f"PB  - {self.publisher}")
        if self.address:
            lines.append(f"CY  - {self.address}")
        if self.doi:
            lines.append(f"DO  - {self.doi}")
        if self.url:
            lines.append(f"UR  - {self.url}")
        if self.isbn:
            lines.append(f"SN  - {self.isbn}")
        if self.issn:
            lines.append(f"SN  - {self.issn}")
        if self.abstract:
            lines.append(f"AB  - {self.abstract}")
        if self.keywords:
            for k in self.keywords:
                lines.append(f"KW  - {k}")
        if self.note:
            lines.append(f"N1  - {self.note}")
        if self.language == "zh":
            lines.append("LA  - zh")
        elif self.language == "en":
            lines.append("LA  - en")
        lines.append("ER  - ")
        return "\n".join(lines) + "\n"

    # ----------------------------------------------------------------- GB/T 7714-2015 (顺序编码制)
    def to_gbt7714(self) -> str:
        """GB/T 7714—2015 顺序编码制 string without the leading [n]."""
        if self.verification.get("status") == "no_library_match" or (self.type == "other" and not self.authors):
            # unparseable manuscript list item: keep verbatim, flagged; do not invent structure
            return self.title.rstrip(".") + "  [⚠ 未在文献库中找到对应条目，需人工核验]"
        code = TYPE_MAP.get(self.type, TYPE_MAP["other"])[2]
        au = _gbt_authors(self.authors)
        parts: List[str] = []
        head = f"{au}. {self.title}[{code}]." if au else f"{self.title}[{code}]."
        # Chinese entries: keep full-width punctuation conventions; titles don't get a trailing period
        # duplicated. We build piece-wise:
        segs: List[str] = []
        if au:
            segs.append(au)
        if self.type in ("conference-paper", "book-chapter") and (self.journal or self.publisher or self.year):
            # GB/T: 题名[C]//会议录. 地: 出版者, 年. 页.
            tail = f"// {self.journal}." if self.journal else ""
            segs.append(f"{self.title}[{code}]{tail}")
            pub = f"{self.address}: {self.publisher}" if self.address and self.publisher else (self.address or self.publisher)
            segs.append((f"{pub}, {self.year}." if pub else f"{self.year}.") if self.year else (f"{pub}." if pub else ""))
            if self.pages:
                segs.append(f"{self.pages}.")
        else:
            segs.append(f"{self.title}[{code}].")
            if self.type == "journal-article":
                segs.append(f"{self.journal}, {self.year}".rstrip(", ") + (f", {self.volume}" if self.volume else "") +
                            (f"({self.issue})" if self.issue else "") + (f": {self.pages}" if self.pages else "") + ".")
            elif self.type in ("book",):
                segs.append((f"{self.address}: " if self.address else "") + f"{self.publisher}, {self.year}.")
                if self.pages:
                    segs.append(f"{self.pages}.")
            elif self.type in ("thesis-phd", "thesis-masters"):
                segs.append(f"{self.address}: {self.journal or self.publisher}, {self.year}.")
            elif self.type == "tech-report":
                segs.append(f"{self.address}: {self.publisher or self.journal}, {self.year}.")
            elif self.type == "webpage":
                segs.append(f"[EB/OL]. ({self.year}). {self.url}." if self.year else f"[EB/OL]. {self.url}.")
            elif self.type == "preprint":
                segs.append(f"{self.journal or 'preprint'}, {self.year}.")
            elif self.type == "dataset":
                segs.append(f"{self.publisher}, {self.year}.")
            else:
                segs.append(f"{self.publisher}, {self.year}." if self.publisher else f"{self.year}.")
        if self.doi:
            segs.append(f"DOI: {self.doi}.")
        segs = [s for s in segs if s and s != "."]
        out = " ".join(segs)
        out = re.sub(r"\.\s*\.", ".", out)
        out = re.sub(r"\[([A-Z/]+)\]\s*//", r"[\1]//", out)
        return out

    # ----------------------------------------------------------------- APA 7
    def to_apa(self) -> str:
        au = _apa_authors(self.authors)
        year = f"({self.year})" if self.year else "(n.d.)"
        title = self.title
        if self.type == "journal-article":
            j = self.journal
            vol = f", {self.volume}" if self.volume else ""
            iss = f"({self.issue})" if self.issue else ""
            pg = f", {self.pages}" if self.pages else ""
            tail = f" https://doi.org/{self.doi}" if self.doi else (f" {self.url}" if self.url else "")
            return f"{au} {year}. {title}. *{j}*{vol}{iss}{pg}.{tail}"
        if self.type == "conference-paper":
            tail = f" https://doi.org/{self.doi}" if self.doi else (f" {self.url}" if self.url else "")
            return f"{au} {year}. {title}. In {self.journal}{' (' + self.pages + ')' if self.pages else ''}.{tail}"
        if self.type in ("book",):
            tail = f" https://doi.org/{self.doi}" if self.doi else ""
            return f"{au} {year}. *{title}*. {self.publisher}.{tail}"
        if self.type == "book-chapter":
            tail = f" https://doi.org/{self.doi}" if self.doi else ""
            return f"{au} {year}. {title}. In {'(Eds.)'} {self.journal}{' (' + self.pages + ')' if self.pages else ''}. {self.publisher}.{tail}"
        if self.type in ("thesis-phd", "thesis-masters"):
            kind = "Doctoral dissertation" if self.type == "thesis-phd" else "Master's thesis"
            return f"{au} {year}. *{title}* [{kind}, {self.journal or self.publisher}]. {self.url or ''}".strip()
        if self.type == "tech-report":
            return f"{au} {year}. {title} (Report No. {self.issue}). {self.publisher}."
        if self.type == "webpage":
            return f"{au} {year}. {title}. {self.url}".strip()
        if self.type == "preprint":
            srv = self.journal or "PsyArXiv"
            tail = f" https://doi.org/{self.doi}" if self.doi else ""
            return f"{au} {year}. {title} [Preprint]. {srv}.{tail}"
        if self.type == "dataset":
            tail = f" https://doi.org/{self.doi}" if self.doi else ""
            return f"{au} {year}. *{title}* [Data set]. {self.publisher}.{tail}"
        if self.type == "software":
            tail = f" https://doi.org/{self.doi}" if self.doi else ""
            return f"{au} {year}. *{title}* [Computer software]. {self.url or self.publisher}.{tail}"
        return f"{au} {year}. {title}. {self.publisher}.".strip()


# --------------------------------------------------------------------------------------
# Normalisation helpers
# --------------------------------------------------------------------------------------
_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_PUNCT = re.compile(r"[\s\-–—_/.,;:!?()\[\]{}<>\"'“”‘’《》〈〉、，。；：！？【】«»]+")


def has_cjk(s: str) -> bool:
    return bool(_CJK.search(s or ""))


# pinyin ↔ CJK surname hints (loaded once; file lives in ../references relative to this script)
_SURNAME_PINYIN_TO_CJK: Dict[str, str] = {}
_SURNAME_CJK_TO_PINYIN: Dict[str, List[str]] = {}
try:
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "surnames_zh_en.json")
    with open(_p, encoding="utf-8") as _f:
        for _k, _v in json.load(_f).items():
            if _k.startswith("_"):
                continue
            _k = _k.rstrip("_")
            _SURNAME_PINYIN_TO_CJK[_k] = _v
            _SURNAME_CJK_TO_PINYIN.setdefault(_v, []).append(_k)
except Exception:
    pass


def surname_equiv(a: str, b: str) -> bool:
    """True if two surname keys plausibly denote the same Chinese surname (张 / zhang / 张英 / Zhang Ying).
    A hint, not proof — callers must still require another signal."""
    a, b = a.lower(), b.lower()
    if not a or not b or a == b:
        return a == b
    if has_cjk(a) == has_cjk(b):
        if has_cjk(a):
            return a[0] == b[0]
        return a.startswith(b) or b.startswith(a)
    cjk, pin = (a, b) if has_cjk(a) else (b, a)
    cjk_s = cjk[0]
    if pin in _SURNAME_PINYIN_TO_CJK and _SURNAME_PINYIN_TO_CJK[pin] == cjk_s:
        return True
    if cjk_s in _SURNAME_CJK_TO_PINYIN and any(pin.startswith(p) or p.startswith(pin) for p in _SURNAME_CJK_TO_PINYIN[cjk_s]):
        return True
    return False


def authors_equivalent(ka: List[str], kb: List[str]) -> bool:
    return any(surname_equiv(x, y) for x in ka for y in kb)


def detect_language(text: str) -> str:
    if not text:
        return ""
    cjk = len(_CJK.findall(text))
    letters = len(re.findall(r"[A-Za-z]", text))
    if cjk == 0:
        return "en" if letters else ""
    if letters == 0:
        return "zh"
    return "zh" if cjk * 2 >= letters else "en"


def normalise_title(t: str) -> str:
    """Lowercase, strip diacritics, drop punctuation/whitespace and a leading article.
    Keeps CJK characters verbatim (they are information-bearing)."""
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.lower().strip()
    t = _PUNCT.sub("", t)
    return t


def split_authors(s: str) -> List[str]:
    """Split an author string on BibTeX ' and ', ';', '？, newlines, or ' & '."""
    if not s:
        return []
    s = re.sub(r"\s+and\s+", " ; ", s, flags=re.I) if re.search(r"\w\.*\s+and\s+\w", s) else s
    s = s.replace("；", ";").replace("\n", ";")
    parts = re.split(r"\s*[;]\s*|\s*&\s*", s)
    return [p.strip(" ,.") for p in parts if p.strip()]


def _family_given(a: str) -> Tuple[str, str]:
    a = a.strip()
    if "," in a:
        fam, _, giv = a.partition(",")
        return fam.strip(), giv.strip()
    # "Ying Zhang" / "Zhang Ying" / "张英" → family = last token for Western, whole for CJK
    if has_cjk(a):
        return a, ""
    toks = a.split()
    if len(toks) == 1:
        return toks[0], ""
    return toks[-1], " ".join(toks[:-1])


def author_keys(authors: Iterable[str]) -> List[str]:
    """Family-name keys, lowercased, diacritics folded, for matching.
    CJK names yield both the full name and the surname (first char), so '张英' and '张' or
    'Zhang' (when a romanised form is supplied) can still be compared downstream."""
    keys = []
    for a in authors:
        fam, _ = _family_given(a)
        fam_n = unicodedata.normalize("NFKD", fam)
        fam_n = "".join(ch for ch in fam_n if not unicodedata.combining(ch)).lower()
        fam_n = _PUNCT.sub("", fam_n)
        if not fam_n:
            continue
        keys.append(fam_n)
        if has_cjk(fam_n) and len(fam_n) > 1:
            keys.append(fam_n[0])          # surname only
            keys.append("".join(reversed(fam_n)))  # given-first order (Zhang Ying vs Ying Zhang)
    return keys


def _bib_author(a: str) -> str:
    fam, giv = _family_given(a)
    if has_cjk(fam) and not giv:
        return f"{{{fam}}}"
    if not giv:
        return f"{{{fam}}}"
    initials = "".join(f"{p[0]}." for p in re.split(r"[\s\-]+", giv) if p)
    return f"{fam}, {initials}" if has_cjk(fam) else f"{fam}, {giv}"


def _ris_author(a: str) -> str:
    fam, giv = _family_given(a)
    return f"{fam}, {giv}" if giv else fam


def _gbt_authors(authors: List[str], limit: int = 3) -> str:
    """GB/T 7714: 'Family GI, Family GI, Family GI, et al.' (≤3 then '等'/'et al');
    Chinese names are written in full without initials."""
    out = []
    for a in authors[:limit]:
        if a.strip().lower() in ("others", "other", "et al", "et al."):
            continue
        fam, giv = _family_given(a)
        if has_cjk(fam):
            out.append(a.replace(",", "").replace(" ", "") if has_cjk(a) else fam)
        else:
            ini = "".join(p[0].upper() for p in re.split(r"[\s\-]+", giv) if p)
            out.append(f"{fam.upper()} {ini}".strip())
    if not out:
        return ""
    if len(authors) > limit:
        out.append("等" if any(has_cjk(x) for x in authors) else "et al")
    return ", ".join(out)


def _apa_authors(authors: List[str]) -> str:
    authors = [a for a in authors if a.strip().lower() not in ("others", "other", "et al", "et al.")]
    n = len(authors)
    out = []
    for a in authors:
        fam, giv = _family_given(a)
        if has_cjk(fam):
            out.append(fam)
        else:
            ini = "".join(f"{p[0]}." for p in re.split(r"[\s\-]+", giv) if p)
            out.append(f"{fam}, {ini}".strip().rstrip(","))
    if n == 0:
        return ""
    if n == 1:
        return out[0]
    if n == 2:
        return f"{out[0]}, & {out[1]}"
    if n <= 20:
        return ", ".join(out[:-1]) + f", & {out[-1]}"
    return ", ".join(out[:19]) + ", . . . " + out[-1]


def _bib_escape(s: str) -> str:
    return (s or "").replace("\\", "\\textbackslash{}").replace("%", "\\%").replace("&", "\\&") \
        .replace("#", "\\#").replace("_", "\\_").replace("$", "\\$") if re.search(r"[%&#_$]", s or "") and not s.startswith("\\") else (s or "")


# --------------------------------------------------------------------------------------
# Library container + parsers
# --------------------------------------------------------------------------------------
class Library:
    def __init__(self, entries: Optional[List[Entry]] = None):
        self.entries: List[Entry] = entries or []

    # ---------------------------------------------------------------- lookup
    def get(self, ref_id: str) -> Optional[Entry]:
        for e in self.entries:
            if e.ref_id == ref_id:
                return e
        return None

    def by_key(self, key: str) -> Optional[Entry]:
        for e in self.entries:
            if e.source_key == key or e.ref_id == key or key in e.merged_from:
                return e
        return None

    def ref_ids(self) -> List[str]:
        return [e.ref_id for e in self.entries]

    def to_list(self) -> List[dict]:
        return [e.to_dict() for e in self.entries]

    @classmethod
    def from_list(cls, items: List[dict]) -> "Library":
        return cls([Entry(**{**{"ref_id": f"R{i+1:03d}"}, **{k: v for k, v in it.items() if k in Entry.__dataclass_fields__}})
                    for i, it in enumerate(items)])

    # ---------------------------------------------------------------- serialise
    def to_bibtex(self) -> str:
        return "".join(e.to_bibtex() for e in self.entries)

    def to_ris(self) -> str:
        return "".join(e.to_ris() for e in self.entries)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_list(), ensure_ascii=False, indent=indent)


# ------------------------------ BibTeX ------------------------------------------------
_BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s{}]+)\s*,(.*?)\n?\}\s*(?=\n|$|@)", re.S)
_BIB_FIELD = re.compile(r"(\w+)\s*=\s*(?:\{|\"|)(.*?)(?=\s*,\s*\n|\s*\n\s*\}|\s*\}\s*$)", re.S | re.M)


def parse_bibtex(text: str) -> List[Entry]:
    entries = []
    text = text.replace("\r\n", "\n")
    pos = 0
    for m in _BIB_ENTRY.finditer(text):
        bt, key, body = m.group(1).lower(), m.group(2).strip(), m.group(3)
        fields = {}
        # brace-aware field splitting
        depth, buf, name, parts = 0, [], None, []
        i = 0
        cur_name = None
        while i < len(body):
            ch = body[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            if ch == "=" and depth == 0 and cur_name is None:
                cur_name = "".join(buf).strip().lower()
                buf = []
            elif ch == "," and depth == 0 and cur_name is not None:
                parts.append((cur_name, "".join(buf).strip()))
                cur_name, buf = None, []
            else:
                buf.append(ch)
            i += 1
        if cur_name is not None:
            parts.append((cur_name, "".join(buf).strip()))
        for k, v in parts:
            v = v.strip().rstrip(",").strip()
            v = re.sub(r"^\"(.*)\"$", r"\1", v, flags=re.S)
            v = _strip_braces(v)
            fields[k] = v
        e = Entry(ref_id="", type=BIBTEX_TO_CANONICAL.get(bt, "other"), source_key=key)
        e.title = fields.get("title", "")
        e.authors = split_authors(fields.get("author", ""))
        e.year = fields.get("year", "")
        e.journal = fields.get("journal", fields.get("booktitle", ""))
        e.volume = fields.get("volume", "")
        e.issue = fields.get("number", fields.get("issue", ""))
        e.pages = fields.get("pages", "").replace("--", "-").replace("–", "-")
        e.publisher = fields.get("publisher", "")
        e.address = fields.get("address", "")
        e.doi = fields.get("doi", "")
        e.url = fields.get("url", fields.get("howpublished", "") if "http" in fields.get("howpublished", "") else "")
        e.isbn = fields.get("isbn", "")
        e.issn = fields.get("issn", "")
        e.note = fields.get("note", "")
        e.abstract = fields.get("abstract", "")
        e.keywords = [k.strip() for k in re.split(r"[,;]", fields.get("keywords", "")) if k.strip()]
        if fields.get("language"):
            e.language = "zh" if re.search(r"zh|chinese|涓枃", fields["language"], re.I) else (
                "en" if re.search(r"en|english", fields["language"], re.I) else "")
        if fields.get("eprint"):
            e.arxiv_id = fields["eprint"]
            if e.type == "other":
                e.type = "preprint"
        if "school" in fields and e.type in ("thesis-phd", "thesis-masters", "other"):
            e.journal = fields["school"]
            e.type = e.type if e.type != "other" else "thesis-phd"
        if "institution" in fields:
            e.publisher = e.publisher or fields["institution"]
        if not e.language:
            e.language = detect_language(e.title + " " + " ".join(e.authors))
        entries.append(e)
    return entries


def _strip_braces(s: str) -> str:
    s = s.strip().rstrip(",").strip()
    while s.startswith("{") and s.endswith("}") and _balanced(s[1:-1]):
        s = s[1:-1].strip()
    # single-line entries: the closing brace belongs to the entry, not the field
    if s.startswith("{") and "{" not in s[1:] and "}" not in s[1:]:
        s = s[1:].strip()
    return s.strip()


def _balanced(s: str) -> bool:
    d = 0
    for ch in s:
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
            if d < 0:
                return False
    return d == 0


# ------------------------------ RIS ---------------------------------------------------
def parse_ris(text: str) -> List[Entry]:
    entries: List[Entry] = []
    cur: Optional[dict] = None
    last_tag = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        m = re.match(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$", line)
        if not m:
            if cur and last_tag and line.strip():
                cur[last_tag] = cur.get(last_tag, "") + " " + line.strip()
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {"_type": val.upper(), "AU": [], "KW": []}
            last_tag = tag
            continue
        if cur is None:
            continue
        if tag == "ER":
            entries.append(_ris_record_to_entry(cur))
            cur = None
            continue
        if tag in ("AU", "A1", "A2", "A3", "A4"):
            cur["AU"].append(val)
        elif tag == "KW":
            cur["KW"].append(val)
        else:
            cur[tag] = val
        last_tag = tag
    if cur:
        entries.append(_ris_record_to_entry(cur))
    return entries


def _ris_record_to_entry(r: dict) -> Entry:
    ty = r.get("_type", "GEN")
    e = Entry(ref_id="", type=RIS_TO_CANONICAL.get(ty, "other"), source_key=r.get("ID", ""))
    e.authors = [a for a in r.get("AU", []) if a]
    e.title = r.get("TI", "") or r.get("CT", "")
    e.journal = r.get("T2", "") or r.get("JO", "") or r.get("JF", "") or r.get("BT", "")
    e.year = (r.get("PY", "") or "")[:4]
    e.volume = r.get("VL", "")
    e.issue = r.get("IS", "") or r.get("IS", "")
    sp, ep = r.get("SP", ""), r.get("EP", "")
    e.pages = f"{sp}-{ep}" if sp and ep else (sp or "")
    e.publisher = r.get("PB", "")
    e.address = r.get("CY", "")
    e.doi = r.get("DO", "")
    e.url = r.get("UR", "")
    sn = r.get("SN", "")
    if re.match(r"^\d{3}-?\d{4}", sn) and len(sn.replace("-", "")) >= 8:
        e.issn = sn
    elif sn:
        e.isbn = sn
    e.note = r.get("N1", "")
    e.abstract = r.get("AB", "")
    e.keywords = r.get("KW", [])
    la = r.get("LA", "").lower()
    if la.startswith("zh") or "chi" in la:
        e.language = "zh"
    elif la.startswith("en") or "eng" in la:
        e.language = "en"
    if e.url and "arxiv.org" in e.url and not e.arxiv_id:
        e.arxiv_id = e.url.rsplit("/", 1)[-1]
    if not e.language:
        e.language = detect_language(e.title + " " + " ".join(e.authors))
    return e


# ------------------------------ CNKI / generic tagged text ---------------------------
def parse_cnki_text(text: str) -> List[Entry]:
    """CNKI RefWorks-ish / 'Title: ...' style exports and generic 'Label: value' blocks.
    Records are separated by blank lines or by a line starting with 'Title'/'棰樺悕'."""
    entries: List[Entry] = []
    blocks: List[List[str]] = []
    cur: List[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(line.rstrip())
    if cur:
        blocks.append(cur)
    # if a single block has many 'Title:' occurrences, split there
    flat = [l for b in blocks for l in b]
    if len(flat) > 2 and sum(1 for l in flat if re.match(r"^(Title|题名)\s*[:：]", l, re.I)) > 1:
        blocks, cur = [], []
        for l in flat:
            if re.match(r"^(Title|题名)\s*[:：]", l, re.I) and cur:
                blocks.append(cur)
                cur = []
            cur.append(l)
        if cur:
            blocks.append(cur)
    for b in blocks:
        rec = _tagged_block(b)
        if not rec or not (rec.get("title") or rec.get("Title")):
            continue
        entries.append(_flat_record_to_entry(rec))
    return entries


def _tagged_block(lines: List[str]) -> dict:
    rec: Dict[str, List[str]] = {}
    tag = None
    for l in lines:
        m = re.match(r"^([A-Za-z\u4e00-\u9fa5/（）() ]{1,30}?)\s*[:：]\s*(.*)$", l)
        if m and (re.match(r"^[A-Z][A-Za-z ]*$", m.group(1).strip()) or has_cjk(m.group(1)) or m.group(1).strip() in _CNKI_LABELS):
            tag = m.group(1).strip()
            rec.setdefault(tag, []).append(m.group(2).strip())
        elif tag:
            rec[tag][-1] += " " + l.strip()
    return rec


_CNKI_LABELS = {
    "Title": "title", "题名": "title", "篇名": "title", "Author": "author", "作者": "author",
    "Inventor": "author", "Source": "journal", "鏉ユ簮": "journal", "鍒婂悕": "journal", "Journal": "journal",
    "Published": "year", "出版年": "year", "年": "year", "Date": "year", "出版日期": "year",
    "Vol": "volume", "卷": "volume", "Issue": "issue", "期": "issue", "No": "issue",
    "Pages": "pages", "页码": "pages", "起页": "pages", "Publisher": "publisher", "出版者": "publisher",
    "DOI": "doi", "Keyword": "keywords", "关键词": "keywords", "Keywords": "keywords",
    "Abstract": "abstract", "鎽樿": "abstract", "URL": "url", "Link": "url", "ISBN": "isbn", "ISSN": "issn",
    "Language": "language", "璇": "language", "Type": "type", "鏂囩尞绫诲瀷": "type", "Document Type": "type",
    "Address": "address", "鍦扮偣": "address", "School": "school", "瀛︽牎": "school", "Degree": "degree",
    "Institution": "institution", "Notes": "note", "澶囨敞": "note", "Cited": "note",
}


def _flat_record_to_entry(rec: dict) -> Entry:
    norm: Dict[str, List[str]] = {}
    for k, vals in rec.items():
        nk = _CNKI_LABELS.get(k, k.lower())
        norm.setdefault(nk, []).extend(vals)
    g = lambda k, d="": (norm.get(k) or [d])[0] if norm.get(k) else d  # noqa: E731
    e = Entry(ref_id="", type=infer_type({"type": g("type")}), source_key=g("id") or g("accession number"))
    e.title = g("title")
    e.authors = split_authors("; ".join(norm.get("author", [])))
    e.journal = g("journal") or g("source") or g("conference")
    e.year = re.sub(r"\D", "", g("year"))[:4] if g("year") else ""
    e.volume = g("volume")
    e.issue = g("issue")
    e.pages = re.sub(r"\s*[-–—]+\s*", "-", g("pages"))
    e.publisher = g("publisher") or g("institution")
    e.address = g("address")
    e.doi = g("doi")
    e.url = g("url")
    e.isbn = g("isbn")
    e.issn = g("issn")
    e.abstract = g("abstract")
    e.keywords = [k.strip() for kv in norm.get("keywords", []) for k in re.split(r"[;；,，]", kv) if k.strip()]
    e.note = g("note")
    if g("school") and e.type in ("thesis-phd", "thesis-masters", "other"):
        e.journal = g("school")
        e.type = "thesis-masters" if "master" in g("degree").lower() or "纭曞＋" in g("degree") else "thesis-phd"
    la = g("language").lower()
    e.language = "zh" if re.search(r"zh|chi|中", la) else ("en" if re.search(r"en|eng|英", la) else "")
    if not e.language:
        e.language = detect_language(e.title + " " + " ".join(e.authors))
    if "arxiv" in (e.url + e.journal).lower():
        e.arxiv_id = e.url.rsplit("/", 1)[-1] if e.url else ""
        if e.type == "other":
            e.type = "preprint"
    return e


# ------------------------------ JSON / CSV -------------------------------------------
def parse_json_library(text: str) -> List[Entry]:
    data = json.loads(text)
    items = data if isinstance(data, list) else (
        data.get("items") or data.get("references") or data.get("entries") or data.get("records") or [])
    if isinstance(data, dict) and not items:
        # maybe {key: {...}} mapping
        items = [{"source_key": k, **v} for k, v in data.items() if isinstance(v, dict)]
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(_json_record_to_entry(it))
    return out


_JSON_FIELDS = {
    "title": ("title", "Title", "tit", "TI"),
    "authors": ("authors", "author", "Author", "creators", "AU", "au"),
    "year": ("year", "Year", "date", "published", "issued", "PY", "pub_year", "publication_year"),
    "journal": ("journal", "container_title", "source", "publication", "booktitle", "proceedings", "journalName", "T2", "venue"),
    "volume": ("volume", "vol", "VL"),
    "issue": ("issue", "number", "num", "IS"),
    "pages": ("pages", "page", "page_range", "sp", "SP"),
    "publisher": ("publisher", "Publisher", "PB"),
    "address": ("address", "city", "CY", "place"),
    "doi": ("doi", "DOI", "DO"),
    "url": ("url", "URL", "link", "UR", "href"),
    "isbn": ("isbn", "ISBN"),
    "issn": ("issn", "ISSN"),
    "language": ("language", "lang", "LA"),
    "abstract": ("abstract", "AB"),
    "note": ("note", "notes", "comment"),
    "keywords": ("keywords", "keyword", "KW", "subjects"),
    "type": ("type", "entry_type", "document_type", "documentType", "item_type", "TY", "kind", "genre"),
    "arxiv_id": ("arxiv_id", "arxivId", "eprint", "arxiv"),
    "source_key": ("key", "id", "citekey", "citation_key", "ref_id", "ID"),
}


def _json_record_to_entry(it: dict) -> Entry:
    g = {}
    for canon, names in _JSON_FIELDS.items():
        for n in names:
            if n in it and it[n] not in (None, "", []):
                g[canon] = it[n]
                break
    e = Entry(ref_id="", type=infer_type({"type": g.get("type", "")}), source_key=str(g.get("source_key", "") or ""))
    e.title = str(g.get("title", "") or "")
    au = g.get("authors", "")
    if isinstance(au, list):
        e.authors = [str(a) if not isinstance(a, dict) else _author_from_dict(a) for a in au]
    else:
        e.authors = split_authors(str(au))
    y = g.get("year", "")
    if isinstance(y, dict):
        y = y.get("raw") or y.get("date-parts", [[""]])[0][0] or ""
    if isinstance(y, list):
        y = y[0] if y else ""
    e.year = re.sub(r"\D", "", str(y))[:4] if y else ""
    for k in ("journal", "volume", "issue", "publisher", "address", "isbn", "issn", "abstract", "note", "language", "arxiv_id"):
        v = g.get(k, "")
        if isinstance(v, list):
            v = v[0] if v else ""
        setattr(e, k, str(v) if v is not None else "")
    pg = g.get("pages", "")
    if isinstance(pg, list):
        pg = "-".join(str(x) for x in pg)
    e.pages = re.sub(r"\s*[-–—]+\s*", "-", str(pg or ""))
    e.doi = str(g.get("doi", "") or "").replace("https://doi.org/", "").strip()
    u = g.get("url", "")
    if isinstance(u, list):
        u = u[0] if u else ""
    if isinstance(u, dict):
        u = u.get("url") or u.get("href") or ""
    e.url = str(u or "")
    kw = g.get("keywords", "")
    e.keywords = [str(k).strip() for k in (kw if isinstance(kw, list) else re.split(r"[;；,，]", str(kw))) if str(k).strip()]
    if not e.language:
        e.language = detect_language(e.title + " " + " ".join(e.authors))
    if e.arxiv_id and e.type == "other":
        e.type = "preprint"
    return e


def _author_from_dict(a: dict) -> str:
    fam = a.get("family") or a.get("lastName") or a.get("last") or a.get("surname") or ""
    giv = a.get("given") or a.get("firstName") or a.get("first") or a.get("givenName") or ""
    lit = a.get("literal") or a.get("name")
    if lit:
        return str(lit)
    return f"{fam}, {giv}".strip(", ") if giv else str(fam)


def parse_csv_library(text: str) -> List[Entry]:
    rows = list(csv.DictReader(io.StringIO(text)))
    return [_json_record_to_entry({k: v for k, v in r.items() if v}) for r in rows]


def parse_library_file(path: str) -> Tuple[List[Entry], str]:
    """Parse by extension (and content sniffing). Returns (entries, format)."""
    fmt = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    return parse_library(text, fmt or "txt")


def parse_library(text: str, fmt: str = "") -> Tuple[List[Entry], str]:
    fmt = (fmt or "").lower().lstrip(".")
    if fmt in ("bib", "bibtex") or (not fmt and re.search(r"@\w+\s*{", text)):
        return parse_bibtex(text), "bibtex"
    if fmt in ("ris",) or (not fmt and re.search(r"^TY  - ", text, re.M)):
        return parse_ris(text), "ris"
    if fmt == "json":
        try:
            return parse_json_library(text), "json"
        except json.JSONDecodeError:
            pass
    if fmt == "csv":
        return parse_csv_library(text), "csv"
    if fmt in ("txt", "cnki", "enw", ""):
        ents = parse_cnki_text(text)
        if ents:
            return ents, "cnki/tagged-text"
        ents = parse_ris(text)
        if ents:
            return ents, "ris"
        ents = parse_bibtex(text)
        if ents:
            return ents, "bibtex"
    return [], "unknown"


# --------------------------------------------------------------------------------------
# Manuscript model
# --------------------------------------------------------------------------------------
# In-text citation marker families we understand. Each regex must expose named groups:
#   body  = the inner text (keys / numbers),  pre  = optional prefix ("see", "e.g."), post = suffix ("p. 12")
MARKERS = {
    # [1]  [1,2]  [1-3]  [1, 3–5]   — numeric / GB-T / IEEE / Vancouver
    "numeric-bracket": re.compile(r"(?<!\!)\[(?P<body>\d{1,4}(?:\s*[,,;\-–]\s*\d{1,4})*)\](?!\()".replace(",,", ",，")),
    # superscripts handled as ^[1] or <sup>[1]</sup>
    "superscript": re.compile(r"(?:\^|\{\{sup\}\}|<sup>)\s*\[(?P<body>\d{1,4}(?:\s*[,,;\-–]\s*\d{1,4})*)\]\s*(?:\{\{/sup\}\}|</sup>)?".replace(",,", ",，")),
    # (Smith, 2020)  (Smith & Jones, 2020, p. 4)  (Smith et al., 2020; Lee, 2019)  （张, 2020）
    "author-year": re.compile(r"[\(（](?P<pre>(?:see|e\.g\.|cf\.|参见|例如)\s+)?(?P<body>[^()（）]{2,160}?\b(?:1[5-9]|20)\d{2}[a-z]?(?:\s*[;；,，]\s*[^()（）]{2,160}?\b(?:1[5-9]|20)\d{2}[a-z]?)*)\s*(?P<post>,\s*(?:pp?\.\s*)?[^)）]*)?[\)）]"),
    # [Smith2020]  [smith2020a]  — alphanumeric citekeys in brackets
    "citekey-bracket": re.compile(r"(?<!\!)\[(?P<body>[A-Za-z][A-Za-z0-9_\-]*?[A-Za-z]{0,3}\d{2,4}[a-z]?(?:\s*[;；,，]\s*[A-Za-z][A-Za-z0-9_\-]*?[A-Za-z]{0,3}\d{2,4}[a-z]?)*)\](?!\()"),
    # [@smith2020] / [@smith2020; @lee2019] pandoc
    "pandoc": re.compile(r"(?<!\!)\[(?P<pre>[^\]@]{0,20})?(?P<body>@[A-Za-z][\w\-\.]*?\d{4}[a-z]?(?:\s*[;,]\s*@[A-Za-z][\w\-\.]*?\d{4}[a-z]?)*)\](?!\()"),
    # 〔1〕 or 【1】 (Chinese typography)
    "numeric-cjk": re.compile(r"[〔【]\s*(?P<body>\d{1,4}(?:\s*[,,;\-–]\s*\d{1,4})*)\s*[〕】]".replace(",,", ",，")),
    # \cite{key} / \citep{key} / \upcite{key}
    "latex-cite": re.compile(r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|upcite|parencite|textcite|autocite|footcite)\*?(?:\[(?:[^\]]*)\])*\{(?P<body>[^}]+)\}"),
}

# Section detection for Markdown / plain manuscripts
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_REF_HEADINGS = re.compile(
    r"^\s*(?:#+\s*)?(?:\d+\.?\s*)?(references?|bibliography|works cited|cited literature|"
    r"参考文献|文後參考文獻|文后参考文献|引用文献|引用書目|资料来源|參考文獻|参 考 文 献)\s*$",
    re.I,
)
_FIG_CAPTION = re.compile(r"^\s*(?:\*\*)?(fig(?:ure)?\.?|鍥緗鍦東table|琛▅appendix|闄勫綍|闄勯寗)\s*\.?\s*([A-Z]?\d+)", re.I)


@dataclass
class Citation:
    """One in-text citation occurrence."""
    cid: str                       # C001 ...
    start: int                     # char offsets in manuscript text
    end: int
    style: str                     # marker family
    raw: str                       # raw text, e.g. "[3, 4]"
    keys: List[str]                # resolved refs (numbers as 'n:3', keys as-is, author-year as 'ay:smith2020')
    section: str = ""
    paragraph: int = 0
    sentence_index: int = 0
    before_text: str = ""          # ~60 chars before the marker (for anchor checks)
    after_text: str = ""           # ~60 chars after
    pre: str = ""
    post: str = ""
    resolved: List[str] = field(default_factory=list)   # ref_ids
    unresolved: List[str] = field(default_factory=list)
    anchor_status: str = ""        # sentence-end | mid-sentence | paragraph-end | caption | unknown
    claim: str = ""                # sentence text the citation supports (LLM may refine)
    match_basis: str = ""          # why this ref supports this claim (LLM)
    needs_review: List[str] = field(default_factory=list)


@dataclass
class Manuscript:
    text: str
    path: str = ""
    sections: List[dict] = field(default_factory=list)    # [{"title","level","start","end"}]
    citations: List[Citation] = field(default_factory=list)
    ref_section_range: Tuple[int, int] = (0, 0)           # where the reference list lives (0,0)=none
    ref_list_items: List[dict] = field(default_factory=list)  # [{"n":1,"start","end","text","label"}]
    marker_style: str = ""                                 # dominant style detected
    format: str = "text"                                   # md|txt|docx-converted
    warnings: List[str] = field(default_factory=list)

    # ---------------------------------------------------------------- body
    @property
    def body_text(self) -> str:
        s, e = self.ref_section_range
        if s == 0 and e == 0:
            return self.text
        return self.text[:s] + self.text[e:]


def parse_manuscript(text: str, path: str = "") -> Manuscript:
    text = text.replace("\r\n", "\n").replace("\u00a0", " ")
    ms = Manuscript(text=text, path=path)
    if path.lower().endswith(".md") or re.search(r"^#{1,6}\s+\S", text, re.M):
        ms.format = "md"
    # sections
    pos = 0
    lines = text.split("\n")
    offs = []
    for l in lines:
        offs.append(pos)
        pos += len(l) + 1
    heads = []
    for i, l in enumerate(lines):
        m = _HEADING.match(l)
        if m:
            heads.append({"title": m.group(2).strip(), "level": len(m.group(1)), "line": i, "start": offs[i]})
    if not heads:
        # plain-text numbered headings "1. Introduction" / "一、引言"
        for i, l in enumerate(lines):
            if re.match(r"^\s*(?:\d+(\.\d+)*\.?|[一二三四五六七八九十]+[、.]|第[一二三四五六七八九十]+[章节部分])\s*\S", l) and len(l.strip()) < 60:
                heads.append({"title": l.strip(), "level": 1, "line": i, "start": offs[i]})
    for i, h in enumerate(heads):
        h["end"] = heads[i + 1]["start"] if i + 1 < len(heads) else len(text)
    ms.sections = heads
    # reference section
    for h in heads:
        if _REF_HEADINGS.match(h["title"]):
            ms.ref_section_range = (h["start"], h["end"])
            break
    if ms.ref_section_range == (0, 0):
    # fallback: a run of ≥3 lines starting with [n] near the end
        m = re.search(r"(?ms)^\s*\[1\]\s*.*?(?=^\s*\[2\]\s*)", text)
        if m:
            # find end: last [n] line
            last = None
            for mm in re.finditer(r"(?m)^\s*\[(\d{1,3})\]\s+", text[m.start():]):
                last = m.start() + mm.end()
            ms.ref_section_range = (m.start(), last or len(text))
            ms.warnings.append("reference section found by [n] pattern, not by heading")
    ms.ref_list_items = _parse_ref_list(text, ms.ref_section_range)
    ms.citations, ms.marker_style = _find_citations(text, ms)
    return ms


def _parse_ref_list(text: str, rng: Tuple[int, int]) -> List[dict]:
    s, e = rng
    if s == 0 and e == 0:
        return []
    seg = text[s:e]
    items = []
    pat = re.compile(r"(?m)^\s*(?:\[[ ]?(\d{1,3})[ ]?\]|(\d{1,3})[.、．]|（(\d{1,3})）)\s+")
    ms_ = list(pat.finditer(seg))
    for i, m in enumerate(ms_):
        n = m.group(1) or m.group(2) or m.group(3)
        start = s + m.start()
        end = s + (ms_[i + 1].start() if i + 1 < len(ms_) else len(seg))
        items.append({"n": int(n), "start": start, "end": end,
                      "text": text[s + m.end():end].strip(), "label": m.group(0).strip()})
    return items


def _find_citations(text: str, ms: Manuscript) -> Tuple[List[Citation], str]:
    cits: List[Citation] = []
    rs, re_ = ms.ref_section_range
    in_refs = lambda p: rs != 0 and rs <= p < re_  # noqa: E731
    # Dominant style vote: count matches outside ref section per family
    votes: Dict[str, int] = {}
    per_family: Dict[str, List[re.Match]] = {}
    for fam, rx in MARKERS.items():
        hits = [m for m in rx.finditer(text) if not in_refs(m.start())]
        # filter: numeric-bracket matches that are actually citekeys are excluded by citekey regex itself;
    # numeric-bracket inside table cells like "[0]" or years "[2020]" → keep only if number plausible
        if fam in ("numeric-bracket", "numeric-cjk", "superscript"):
            hits = [m for m in hits if not _looks_like_noncitation(m, text)]
        per_family[fam] = hits
        votes[fam] = len(hits)
    # latex-cite / pandoc dominate if present
    style = max(votes.items(), key=lambda kv: kv[1])[0] if any(votes.values()) else ""
    if votes.get("author-year", 0) and votes["author-year"] >= max(votes.get("numeric-bracket", 0), votes.get("citekey-bracket", 0)):
        style = "author-year"
    chosen = [style]
    if "latex-cite" not in chosen and votes.get("latex-cite"):
        chosen.append("latex-cite")       # \cite{} placeholders (e.g. model-inserted) are always honoured
    if style == "superscript" and votes.get("numeric-bracket"):
        chosen.append("numeric-bracket")
    if style == "numeric-bracket" and votes.get("superscript"):
        chosen.append("superscript")
    for fam in chosen:
        for m in per_family[fam]:
            cits.append(_make_citation(m, fam, text, ms))
    cits.sort(key=lambda c: c.start)
    # drop overlaps (keep first)
    out: List[Citation] = []
    for c in cits:
        if out and c.start < out[-1].end:
            continue
        out.append(c)
    for i, c in enumerate(out):
        c.cid = f"C{i+1:03d}"
        c.paragraph = text.count("\n\n", 0, c.start) + 1
        c.section = _section_for(ms, c.start)
        c.anchor_status = _anchor_status(c, text)
    return out, style


def _looks_like_noncitation(m: re.Match, text: str) -> bool:
    body = m.group("body")
    nums = [int(x) for x in re.findall(r"\d+", body)]
    if not nums:
        return True
    if any(n > 400 for n in nums):    # [2020] years etc.
        return True
    if len(body) == 4 and body.isdigit():  # [1999]
        return True
    # preceded by '^' handled elsewhere; table cells like "[1]" after 'r' e.g. 'r[1]' arrays
    prev = text[max(0, m.start() - 2):m.start()]
    if re.search(r"[A-Za-z_]\[?$", prev) and not prev.endswith(" "):
        return True
    if text[m.end():m.end() + 1] == "(":
        return True
    return False


def _make_citation(m: re.Match, fam: str, text: str, ms: Manuscript) -> Citation:
    body = m.group("body")
    pre = m.groupdict().get("pre") or ""
    post = m.groupdict().get("post") or ""
    keys: List[str] = []
    if fam in ("numeric-bracket", "superscript", "numeric-cjk"):
        for tok in re.split(r"[,，;；]", body):
            tok = tok.strip()
            if re.match(r"^\d+\s*[-–—]\s*\d+$", tok):
                a, b = map(int, re.split(r"[-–—]", tok))
                keys.extend(f"n:{k}" for k in range(a, b + 1))
            elif tok.isdigit():
                keys.append(f"n:{int(tok)}")
        if fam == "superscript" and not (m.group(0).startswith("^") or "<sup>" in m.group(0) or "{{sup}}" in m.group(0)):
            fam = "numeric-bracket"
    elif fam == "citekey-bracket":
        keys = [k.strip() for k in re.split(r"[,;岋紱]", body) if k.strip()]
    elif fam == "latex-cite":
        keys = [k.strip() for k in body.split(",") if k.strip()]
    elif fam == "pandoc":
        keys = re.findall(r"@([A-Za-z][\w\-\.]*\d{4}[a-z]?)", m.group(0))
    elif fam == "author-year":
        for part in re.split(r"[;；]", body):
            part = part.strip()
            mm = re.match(r"(?P<pre>(?:see|e\.g\.|cf\.|参见|例如)\s+)?(?P<au>[^,，]+?)(?:,|\s)\s*(?P<yr>(?:1[5-9]|20)\d{2}[a-z]?)", part)
            if mm:
                keys.append(f"ay:{_ay_key(mm.group('au'))}|{mm.group('yr')}")
            else:
                keys.append(f"ay:?|{part}")
        pre = pre or ""
    c = Citation(cid="", start=m.start(), end=m.end(), style=fam, raw=m.group(0), keys=keys, pre=pre, post=post)
    c.before_text = text[max(0, m.start() - 80):m.start()]
    c.after_text = text[m.end():m.end() + 80]
    # the sentence containing the marker
    sent_s = max(text.rfind(". ", 0, m.start()), text.rfind("。", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    sent_e_candidates = [x for x in (text.find(". ", m.end()), text.find("。", m.end()), text.find("\n", m.end())) if x != -1]
    sent_e = min(sent_e_candidates) + 1 if sent_e_candidates else len(text)
    c.claim = text[sent_s:sent_e].strip()
    return c


def _ay_key(au: str) -> str:
    au = re.sub(r"\s*(et al\.?|绛墊&|and|寍,)\s*", " ", au)
    first = re.split(r"\s+", au.strip())[0] if au.strip() else ""
    return _PUNCT.sub("", first.lower())


def _section_for(ms: Manuscript, pos: int) -> str:
    cur = ""
    for h in ms.sections:
        if h["start"] <= pos:
            cur = h["title"]
        else:
            break
    return cur


def _anchor_status(c: Citation, text: str) -> str:
    line_start = text.rfind("\n", 0, c.start) + 1
    line_end = text.find("\n", c.end)
    line_end = len(text) if line_end == -1 else line_end
    line = text[line_start:line_end]
    if _FIG_CAPTION.match(line):
        return "caption"
    after = text[c.end:c.end + 3]
    before = text[max(0, c.start - 2):c.start]
    if re.match(r"^\s*[.。;；]?\s*$", text[c.end:line_end].strip("\n")) or text[c.end:line_end].strip() in ("", ".", "。"):
        return "paragraph-end" if text[c.end:line_end].strip() == "" else "sentence-end"
    if re.match(r"^[,，]", after) or re.search(r"[,，]$", before):
        return "mid-sentence"
    if re.match(r"^\s*[.。]", after):
        return "sentence-end"
    return "mid-sentence"


# --------------------------------------------------------------------------------------
    # Resolution of citation keys → ref_ids
# --------------------------------------------------------------------------------------
def resolve_citations(ms: Manuscript, lib: Library) -> None:
    """Fill Citation.resolved / unresolved using the library and the manuscript's own ref list.
    Numeric keys resolve against the manuscript's numbered list (position), then that item's
    text is matched to a library entry; keys resolve by source_key; author-year by author+year."""
    items = ms.ref_list_items
    for c in ms.citations:
        c.resolved, c.unresolved = [], []
        for k in c.keys:
            rid = None
            if k.startswith("n:"):
                n = int(k[2:])
                item = next((it for it in items if it["n"] == n), None)
                if item:
                    rid = _match_ref_text_to_library(item["text"], lib)
                    if not rid:
                        c.needs_review.append(f"list item [{n}] has no library match")
                        c.unresolved.append(k)
                        continue
                else:
    # no ref list in manuscript: numeric → library by position (1-based) if available
                    if 1 <= n <= len(lib.entries):
                        rid = lib.entries[n - 1].ref_id
                        c.needs_review.append(f"[{n}] resolved by library position (manuscript has no ref list)")
                    else:
                        c.unresolved.append(k)
                        continue
            elif k.startswith("ay:"):
                au, yr = k[3:].split("|", 1) if "|" in k[3:] else (k[3:], "")
                rid = _match_author_year(au, yr, lib)
                if not rid:
                    c.unresolved.append(k)
                    continue
            else:
                e = lib.by_key(k)
                rid = e.ref_id if e else _match_ref_text_to_library(k, lib)
                if not rid:
                    c.unresolved.append(k)
                    continue
            if rid and rid not in c.resolved:
                c.resolved.append(rid)


def _match_ref_text_to_library(text: str, lib: Library) -> Optional[str]:
    t = text.strip()
    if not t:
        return None
    nt = normalise_title(t)
    # DOI in text
    m = re.search(r"10\.\d{4,9}/[^\s\]\)]+", t)
    if m:
        doi = m.group(0).rstrip(".")
        for e in lib.entries:
            if e.doi and e.doi.lower() == doi.lower():
                return e.ref_id
    # arXiv id
    m = re.search(r"(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(v\d+)?", t)
    if m and "arxiv" in t.lower():
        for e in lib.entries:
            if e.arxiv_id and e.arxiv_id in t:
                return e.ref_id
    # title containment (normalised)
    best, best_score = None, 0.0
    for e in lib.entries:
        et = e.sort_title
        if not et:
            continue
        if et in nt or nt in et:
            score = len(min(et, nt, key=len)) / max(len(et), 1)
            if score > best_score:
                best, best_score = e.ref_id, score
    if best and best_score >= 0.6:
        return best
    # author+year
    yr = re.search(r"(1[5-9]|20)\d{2}", t)
    if yr:
        for e in lib.entries:
            if e.year == yr.group(0) and any(k in t.lower() for k in e.author_keys()):
                return e.ref_id
    return None


def _match_author_year(au: str, yr: str, lib: Library) -> Optional[str]:
    cands = []
    for e in lib.entries:
        if yr and e.year and e.year != yr:
            continue
        if au and au != "?" and (au in e.author_keys() or any(surname_equiv(au, k) for k in e.author_keys())):
            cands.append(e)
        elif au and au != "?" and any(au in k or k in au for k in e.author_keys()):
            cands.append(e)
    if len(cands) == 1:
        return cands[0].ref_id
    if len(cands) > 1:
        return cands[0].ref_id  # ambiguous; disambiguation suffix handled by caller warning
    return None


# --------------------------------------------------------------------------------------
# Rendering numbers / markers
# --------------------------------------------------------------------------------------
def format_numeric_marker(numbers: List[int], style: str = "bracket") -> str:
    """[1, 2, 3] → '[1-3]'; [1, 3] → '[1,3]' (GB/T) or '[1, 3]' (ieee)."""
    nums = sorted(set(numbers))
    if not nums:
        return ""
    ranges: List[Tuple[int, int]] = []
    s = p = nums[0]
    for n in nums[1:]:
        if n == p + 1:
            p = n
            continue
        ranges.append((s, p))
        s = p = n
    ranges.append((s, p))
    parts = []
    for a, b in ranges:
        if b - a >= 2:
            parts.append(f"{a}-{b}" if style != "gbt" else f"{a}-{b}")
        elif b == a + 1:
            parts.append(f"{a},{b}")
        else:
            parts.append(str(a))
    sep = "," if style in ("gbt", "vancouver") else ", "
    inner = sep.join(parts).replace(",", sep) if sep == ", " else inner_join(parts)
    if style in ("gbt", "vancouver"):
        inner = ",".join(parts)
    elif style == "ieee":
        inner = ", ".join(parts)
    else:
        inner = ",".join(parts)
    return f"[{inner}]"


def inner_join(parts: List[str]) -> str:
    return ",".join(parts)


# --------------------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------------------
def diff_summary(before: str, after: str) -> dict:
    import difflib
    sm = difflib.SequenceMatcher(None, before, after)
    ops = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            ops.append({"op": tag, "before": before[max(0, i1 - 20):i2 + 20], "after": after[max(0, j1 - 20):j2 + 20]})
    return {"changed": before != after, "n_edits": len(ops), "edits": ops[:200]}


def read_text(path: str) -> str:
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def docx_to_text(path: str) -> str:
    """Minimal docx → text (paragraphs, headings, tables) without python-docx.
    Headings are rendered as Markdown '# ' so the section parser can see them."""
    import zipfile
    from xml.etree import ElementTree as ET
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out: List[str] = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
        body = root.find(W + "body")
    # style → heading level map
        styles = {}
        if "word/styles.xml" in names:
            sroot = ET.fromstring(z.read("word/styles.xml"))
            for st in sroot.iter(W + "style"):
                sid = st.get(W + "styleId") or ""
                name_el = st.find(W + "name")
                name = (name_el.get(W + "val") if name_el is not None else "") or ""
                m = re.match(r"(?:heading|鏍囬)\s*(\d)", name, re.I)
                if m:
                    styles[sid] = int(m.group(1))
        for el in body:
            tag = el.tag.replace(W, "")
            if tag == "p":
                txt, sup = _para_text(el, W)
                if not txt.strip():
                    continue
                ppr = el.find(W + "pPr")
                lvl = 0
                if ppr is not None:
                    ps = ppr.find(W + "pStyle")
                    if ps is not None:
                        lvl = styles.get(ps.get(W + "val"), 0)
                        sid = (ps.get(W + "val") or "").lower()
                        if re.match(r"heading(\d)", sid):
                            lvl = int(re.match(r"heading(\d)", sid).group(1))
                if sup:
                    txt = txt  # superscript digits already wrapped as ^[..] in _para_text
                out.append(("#" * lvl + " " + txt) if lvl else txt)
            elif tag == "tbl":
                for tr in el.iter(W + "tr"):
                    cells = []
                    for tc in tr.findall(W + "tc"):
                        cells.append(" ".join(_para_text(p, W)[0] for p in tc.findall(W + "p")).strip())
                    out.append("| " + " | ".join(cells) + " |")
                out.append("")
    return "\n\n".join(out)


def _para_text(p, W) -> Tuple[str, bool]:
    parts: List[str] = []
    sup_runs: List[str] = []
    has_sup = False
    for r in p.iter(W + "r"):
        rpr = r.find(W + "rPr")
        is_sup = False
        if rpr is not None:
            va = rpr.find(W + "vertAlign")
            if va is not None and va.get(W + "val") == "superscript":
                is_sup = True
        t = "".join((x.text or "") for x in r.findall(W + "t"))
        if is_sup and re.fullmatch(r"\s*\d+(?:[,，\-–]\s*\d+)*\s*", t or ""):
            has_sup = True
            if parts and parts[-1].endswith("[") :
                pass
            parts.append(f"^[{t.strip()}]")
        else:
            parts.append(t)
    # merge patterns like "^[1]" "-^[2]" into "^[1-2]"
    txt = "".join(parts)
    return txt, has_sup
