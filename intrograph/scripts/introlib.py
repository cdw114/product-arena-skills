#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""introlib — parsing, ledger model and citation handling for the
introduction / related-work writing skill.

Pure Python standard library (>= 3.8). No third-party dependency, no network.

The module is deliberately layered so each layer can be imported and tested on
its own:

    text utils        split_sentences / extract_numbers / detect_lang ...
    materials         discover_materials / classify_text
    library           parse_bibtex / parse_ris / parse_refjson / build_library
    manuscript        parse_manuscript -> ManuscriptIndex
    draft             parse_draft     -> DraftIndex
    ledgers           empty_ledger / load_ledger / validate_ledger

Nothing here decides whether the writing is good. That is audit_rules.py.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import unicodedata

# --------------------------------------------------------------------------- #
# 0. small text utilities
# --------------------------------------------------------------------------- #

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_ABBR = [
    "et al.", "e.g.", "i.e.", "vs.", "cf.", "Fig.", "Figs.", "fig.", "figs.",
    "Tab.", "Eq.", "Eqs.", "Ref.", "Refs.", "Sec.", "Sect.", "No.", "approx.",
    "ca.", "resp.", "Dr.", "Prof.", "al.", "etc.", "i.d.", "arXiv.",
]

TRAILING_PUNCT = "。！？；.!?;:：,，、 \t\u3000\"'”’)）]】"


def norm_ws(s: str) -> str:
    """Collapse all whitespace runs to one space and strip."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def strip_md(s: str) -> str:
    """Remove the most common markdown decoration but keep the words."""
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)          # images
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)      # links
    s = re.sub(r"`([^`]*)`", r"\1", s)                  # inline code
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)           # bold
    s = re.sub(r"(?<!\w)(\*|_)(.+?)\1(?!\w)", r"\2", s)  # italics
    return s


def norm_cmp(s: str) -> str:
    """Normalise for substring comparison: NFKC, lowercase, letters+digits only.

    Used to test whether a quoted limitation really occurs in the source text,
    so it must be robust to punctuation, dashes, ligatures and full-width forms.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)
    return s


def detect_lang(text: str, default: str = "zh") -> str:
    """'zh' when CJK characters outnumber latin letters, else 'en'."""
    if not text:
        return default
    cjk = len(CJK_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk == 0 and latin == 0:
        return default
    return "zh" if cjk >= max(1, latin * 0.25) else "en"


def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def split_sentences(text: str, lang: str = "auto") -> list:
    """Split a paragraph into sentences.

    Handles the mixed Chinese/English case that real manuscripts contain, keeps
    decimal points and the usual Latin abbreviations inside one sentence.
    """
    if not text:
        return []
    t = text
    for i, a in enumerate(_ABBR):
        t = t.replace(a, "\x00%d\x00" % i)
    out, buf, i, n = [], [], 0, len(t)
    while i < n:
        ch = t[i]
        buf.append(ch)
        if ch in "。！？":
            out.append("".join(buf))
            buf = []
        elif ch in ".!?":
            nxt = t[i + 1] if i + 1 < n else ""
            if nxt == "" or nxt.isspace() or nxt in "\"')]}”’":
                out.append("".join(buf))
                buf = []
        i += 1
    if buf:
        out.append("".join(buf))
    res = []
    for s in out:
        for i2, a in enumerate(_ABBR):
            s = s.replace("\x00%d\x00" % i2, a)
        s = s.strip()
        if s and re.search(r"\w", s):
            res.append(s)
    return res


def split_paragraphs(text: str) -> list:
    """Blank-line separated blocks; a heading or list item also starts a block."""
    if not text:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks, buf = [], []
    for line in text.split("\n"):
        if not line.strip():
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            continue
        if is_heading_line(line) and buf:
            blocks.append("\n".join(buf))
            buf = []
        buf.append(line)
        if is_heading_line(line) or re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            blocks.append("\n".join(buf))
            buf = []
    if buf:
        blocks.append("\n".join(buf))
    return [b for b in (x.strip() for x in blocks) if b]


MD_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
NUM_HEAD = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
CN_NUM_HEAD = re.compile(r"^([一二三四五六七八九十]+)[、.]\s*(\S.*)$")
CN_CHAP_HEAD = re.compile(r"^第\s*([一二三四五六七八九十百零〇\d]+)\s*([章节部分])\s*(\S.*)$")
TEX_HEAD = re.compile(r"^\\(?:sub)*section\*?\{([^}]*)\}")


def is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 120:
        return False
    if MD_HEAD.match(s):
        return True
    if TEX_HEAD.match(s):
        return True
    if CN_CHAP_HEAD.match(s) and len(s) < 80:
        return True
    if re.match(r"^(Abstract|摘要|Keywords|关键词|References|参考文献|Introduction|Conclusion)\b",
                s, re.I) and len(s) < 60:
        return True
    if NUM_HEAD.match(s) and len(s) < 90 and not s.endswith(("。", ".", "；")):
        # "1 Introduction" / "4.2 Ablation study" but not "1.5 times faster ..."
        num = NUM_HEAD.match(s).group(1)
        rest = NUM_HEAD.match(s).group(2)
        if re.match(r"^[A-Z\u4e00-\u9fff]", rest) and len(rest.split()) <= 14:
            return True
    if CN_NUM_HEAD.match(s) and len(s) < 60:
        return True
    return False


def heading_info(line: str) -> dict:
    """Best-effort (level, number, title) for a heading line, else None."""
    s = line.strip()
    m = MD_HEAD.match(s)
    if m:
        title = m.group(2).strip()
        nm = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$", title)
        if nm:
            return {"level": len(m.group(1)), "number": nm.group(1), "title": nm.group(2).strip()}
        return {"level": len(m.group(1)), "number": "", "title": title}
    m = TEX_HEAD.match(s)
    if m:
        return {"level": 1, "number": "", "title": m.group(1).strip()}
    m = CN_CHAP_HEAD.match(s)
    if m:
        return {"level": 1, "number": m.group(1) + m.group(2), "title": (m.group(3) or "").strip()}
    m = NUM_HEAD.match(s)
    if m and is_heading_line(s):
        return {"level": m.group(1).count(".") + 1, "number": m.group(1), "title": m.group(2).strip()}
    m = CN_NUM_HEAD.match(s)
    if m:
        return {"level": 1, "number": m.group(1), "title": m.group(2).strip()}
    return {"level": 1, "number": "", "title": s}


# --------------------------------------------------------------------------- #
# 1. numbers
# --------------------------------------------------------------------------- #

_NUM_RE = re.compile(
    r"(?<![\w.])"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*"
    r"(‰|%|个百分点|倍|ms|µs|us|ns|min|hours|hour|hrs|h|s|"
    r"K|°C|℃|nm|µm|um|mm|cm|km|m|kg|mg|µg|ug|ng|mL|ml|L|µL|mM|µM|uM|nM|pM|M|"
    r"eV|keV|MeV|GeV|kHz|MHz|GHz|Hz|kV|V|mA|W|kW|dB|"
    r"GB|TB|MB|KB|kB|FPS|fps|QPS|qps|"
    r"F1|BLEU|ROUGE|mAP|IoU|PSNR|SSIM|AUC|RMSE|MAE|R2|R²|"
    r"kcal/mol|kJ/mol|kJ|kcal|Å|angstrom|Da|kDa)"
)

_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def _to_float(s: str):
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def extract_numbers(text: str) -> list:
    """Numeric tokens that carry a unit or a decimal point.

    Integers without a unit are deliberately not returned: "3 groups" or a list
    index is not a scientific claim we can trace, and flagging it produces noise.
    """
    out = []
    if not text:
        return out
    for m in _NUM_RE.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "")
        if not unit and "." not in raw:
            continue
        val = _to_float(raw)
        if val is None:
            continue
        s, e = max(0, m.start() - 45), min(len(text), m.end() + 45)
        out.append({
            "raw": raw, "unit": unit, "value": val,
            "context": norm_ws(text[s:e]),
            "pos": m.start(),
        })
    return out


def number_key(value, unit: str = "") -> str:
    """Canonical comparison key for a number, tolerant to 0.9410 vs 0.941."""
    if value is None:
        return ""
    try:
        v = round(float(value), 6)
    except (TypeError, ValueError):
        return ""
    return ("%g" % v) + ("|" + unit.lower() if unit else "")


def number_keys_of(text: str) -> set:
    return {number_key(d["value"], d["unit"]) for d in extract_numbers(text)}


# --------------------------------------------------------------------------- #
# 2. citation markers
# --------------------------------------------------------------------------- #

CITE_KIND_NUMERIC = "numeric"
CITE_KIND_KEY = "key"
CITE_KIND_AUTHOR_YEAR = "author-year"

_CITE_NUM = re.compile(r"[\[［]\s*(\d{1,3}(?:\s*[-–—,，、]\s*\d{1,3})*)\s*[\]］]")
_CITE_LATEX = re.compile(r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|upcite|supercite)"
                         r"\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")
_CITE_PANDOC = re.compile(r"\[(@[A-Za-z0-9_:.\-]+(?:\s*;\s*@[A-Za-z0-9_:.\-]+)*)\]")
_CITE_WIKI = re.compile(r"\[\[([A-Za-z][A-Za-z0-9_:.\-]{1,60})\]\]")
_CITE_AY = re.compile(
    r"\(([A-Z][A-Za-zÀ-ÿ'’\-]+(?:\s+(?:et\s+al\.?|and|&|和|等)\s*(?:[A-Z][A-Za-zÀ-ÿ'’\-]+)?)?"
    r"(?:\s*,\s*[A-Z][A-Za-zÀ-ÿ'’\-]+)*"
    r"(?:,?\s*(?:19|20)\d{2}[a-z]?(?:\s*[;，,]\s*[^()]{1,80}?(?:19|20)\d{2}[a-z]?)*)?)\)"
)
_CITE_AY_NARRATIVE = re.compile(
    r"\b([A-Z][A-Za-zÀ-ÿ'’\-]+(?:\s+et\s+al\.?)?)\s*[（(]\s*((?:19|20)\d{2})[a-z]?\s*[)）]"
)
_CITE_CN = re.compile(r"([\u4e00-\u9fff]{2,3}?)(?:等(?:人)?)?\s*[（(]\s*((?:19|20)\d{2})[a-z]?\s*[)）]")


def expand_num_spec(spec: str) -> list:
    nums = []
    for part in re.split(r"[,，、]", spec):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d{1,3})\s*[-–—]\s*(\d{1,3})$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < a <= b <= a + 60:
                nums.extend(range(a, b + 1))
            continue
        if re.match(r"^\d{1,3}$", part):
            nums.append(int(part))
    return nums


def parse_citations(text: str) -> list:
    """All citation markers in `text`, in reading order.

    Each marker: {raw, kind, keys[], nums[], surnames[], year, start, end}
    Kinds are not exclusive in principle, but a marker is tagged with the form
    that matched it.
    """
    out = []
    taken = []

    def free(a, b):
        for x, y in taken:
            if a < y and x < b:
                return False
        return True

    def add(m, kind, **kw):
        if not free(m.start(), m.end()):
            return
        taken.append((m.start(), m.end()))
        rec = {"raw": m.group(0), "kind": kind, "keys": [], "nums": [],
               "surnames": [], "year": None, "start": m.start(), "end": m.end()}
        rec.update(kw)
        out.append(rec)

    for m in _CITE_LATEX.finditer(text):
        keys = [k.strip() for k in re.split(r"[,，]", m.group(1)) if k.strip()]
        add(m, CITE_KIND_KEY, keys=keys)
    for m in _CITE_PANDOC.finditer(text):
        keys = [k.strip().lstrip("@") for k in re.split(r";", m.group(1)) if k.strip()]
        add(m, CITE_KIND_KEY, keys=keys)
    for m in _CITE_WIKI.finditer(text):
        add(m, CITE_KIND_KEY, keys=[m.group(1)])
    for m in _CITE_NUM.finditer(text):
        add(m, CITE_KIND_NUMERIC, nums=expand_num_spec(m.group(1)))
    for m in _CITE_AY.finditer(text):
        inner = m.group(1)
        if not free(m.start(), m.end()):
            continue
        subs = []
        for part in re.split(r"[;；]", inner):
            years = re.findall(r"(?:19|20)\d{2}", part)
            if not years:
                continue
            surnames = [s for s in re.findall(r"[A-Z][A-Za-zÀ-ÿ'’\-]{1,}", part)
                        if s.lower() not in ("et", "al", "and")]
            if surnames:
                subs.append((surnames, years[0]))
        if not subs:
            continue
        # one parenthetical can carry several citations: "(Smith et al., 2020; Lee, 2024)"
        # must yield two records with their own years, not one record with the first year
        taken.append((m.start(), m.end()))
        for surnames, year in subs:
            out.append({"raw": m.group(0), "kind": CITE_KIND_AUTHOR_YEAR, "keys": [], "nums": [],
                        "surnames": surnames, "year": year,
                        "start": m.start(), "end": m.end()})
    for m in _CITE_AY_NARRATIVE.finditer(text):
        add(m, CITE_KIND_AUTHOR_YEAR, surnames=[m.group(1).split()[0]], year=m.group(2))
    for m in _CITE_CN.finditer(text):
        add(m, CITE_KIND_AUTHOR_YEAR, surnames=[m.group(1)], year=m.group(2))

    out.sort(key=lambda r: r["start"])
    return out


def citation_key_set(cites: list) -> set:
    """Flattened identity of the cited items, used only for 'is there a marker'.

    For numeric markers the number is the identity; for keys the key; for
    author-year the surname+year pair.
    """
    s = set()
    for c in cites:
        if c["kind"] == CITE_KIND_KEY:
            s.update("k:" + k.lower() for k in c["keys"])
        elif c["kind"] == CITE_KIND_NUMERIC:
            s.update("n:%d" % n for n in c["nums"])
        else:
            for sn in c["surnames"]:
                s.add("ay:%s:%s" % (sn.lower(), c["year"]))
    return s


def citation_style_of(text: str) -> str:
    c = parse_citations(text)
    if not c:
        return "none"
    kinds = {x["kind"] for x in c}
    if CITE_KIND_KEY in kinds and (CITE_KIND_NUMERIC in kinds):
        return "mixed"
    if CITE_KIND_KEY in kinds:
        return "key"
    if CITE_KIND_NUMERIC in kinds:
        return "numeric"
    return "author-year"


def has_citation(text: str) -> bool:
    return bool(parse_citations(text))


# --------------------------------------------------------------------------- #
# 3. author-year helpers
# --------------------------------------------------------------------------- #

def surname_of(name: str) -> str:
    """Best-effort surname. Handles 'Smith, J.', 'John Smith', 'Zhang Wei', '张三'."""
    if not name:
        return ""
    n = norm_ws(name)
    if CJK_RE.search(n):
        n = re.sub(r"[\d\*†‡§¶]", "", n).strip()
        return n[:3]
    if "," in n:
        return n.split(",")[0].strip()
    parts = [p for p in re.split(r"\s+", n) if p]
    return parts[-1] if parts else n


def split_authors(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = []
        for x in raw:
            if isinstance(x, dict):
                items.append(norm_ws(str(x.get("name") or x.get("family") or x.get("literal") or "")))
            else:
                items.append(norm_ws(str(x)))
        return [x for x in items if x]
    s = str(raw)
    s = s.replace("\n", " ")
    if re.search(r"\s+and\s+|;\s*", s) and "," in s and len(s.split(",")) > 3:
        pass
    parts = re.split(r"\s+and\s+|;\s*|、|\band\b(?=\s+[A-Z\u4e00-\u9fff])", s)
    parts = [norm_ws(p.strip(" ,.")) for p in parts]
    parts = [p for p in parts if p]
    if len(parts) <= 1 and "," in s:
        segs = [norm_ws(x) for x in s.split(",") if norm_ws(x)]
        if len(segs) == 2:
            # "Lee, Kai" / "Kipf, Thomas N" is ONE author in BibTeX's
            # `author = {Surname, Given}` form. "Kipf T N, Welling M" is two authors in
            # GB/T's `Surname Initials` form: the tell is a trailing initial on the left
            # segment, or initials-only on the right.
            left_ends_initial = bool(re.search(r"\s[A-Z]\.?$", segs[0]))
            right_starts_plain = bool(re.match(r"^[A-Z][a-zà-ÿ'’\-]+(\s|$)", segs[1]))
            right_is_initials = bool(re.match(r"^[A-Z]\.?(\s*[A-Z]\.?)*$", segs[1]))
            if right_starts_plain and not right_is_initials and not left_ends_initial:
                return [segs[0] + ", " + segs[1]]
        pairs, i = [], 0
        while i < len(segs):
            if i + 1 < len(segs) and re.match(r"^[A-Z]\.?(\s*[A-Z]\.?)*$", segs[i + 1]):
                pairs.append(segs[i] + ", " + segs[i + 1])
                i += 2
            else:
                pairs.append(segs[i])
                i += 1
        parts = pairs
    return parts or [norm_ws(s)]


# --------------------------------------------------------------------------- #
# 4. material discovery
# --------------------------------------------------------------------------- #

TEXT_EXT = {".md", ".markdown", ".txt", ".tex", ".rst", ".org", ".text", ".csv",
            ".tsv", ".bib", ".ris", ".json", ".jsonl", ".yaml", ".yml", ".enw"}
BIN_EXT = {".pdf", ".docx", ".doc", ".pptx"}
SKIP_DIRS = {"__pycache__", ".git", ".hg", ".svn", "node_modules", ".ipynb_checkpoints"}
LIB_EXT = {".bib", ".ris", ".enw", ".nbib"}
SKIP_NAMES = {"task.md", "readme.md", "readme.txt", "notes.md"}


def read_text(path: str) -> str:
    """Read a text file with a few tolerant encodings."""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError:
            return ""
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def list_files(root: str, limit: int = 400) -> list:
    """Recursively list candidate files, skipping VCS/cache directories."""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            p = os.path.join(dirpath, fn)
            if os.path.islink(p):
                continue
            out.append(p)
            if len(out) >= limit:
                return out
    return out


MANU_HINTS = ("introduction", "related work", "related-work", "background",
              "method", "experiment", "discussion", "conclusion", "abstract",
              "manuscript", "paper", "draft", "正文", "引言", "相关工作", "方法", "实验")
LIB_HINTS = ("bib", "reference", "bibliograph", "citation", "文献", "参考文献", "library", "refs")


def classify_text(text: str, path: str) -> str:
    """'library' | 'manuscript' | 'notes' | 'unknown'.

    Decision is content-first: a .bib file that parses to entries is a library
    whatever its name; a long prose file with headings is a manuscript.
    """
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    head = (text or "")[:4000]

    if ext in LIB_EXT:
        return "library"
    n_bib = len(re.findall(r"@\w+\s*\{", head))
    if n_bib >= 2:
        return "library"
    if len(re.findall(r"^TY\s{2}-", head, re.M)) >= 1:
        return "library"
    if re.search(r"^\s*(?:\[?\d+\]?[.)]?\s*)?(?:doi|DOI)\s*[:=]\s*10\.", head, re.M) and \
            len(re.findall(r"(?:^|\n)\s*(?:doi|DOI)\s*[:=]", head)) >= 2:
        return "library"

    # JSON shaped like a reference list
    st = head.strip()
    if st[:1] in "[{":
        try:
            obj = json.loads(text)
            entries = _json_entries(obj)
            if entries and _looks_like_refs(entries):
                return "library"
        except Exception:
            pass

    if ext == ".csv" or ext == ".tsv":
        try:
            rows = list(csv.reader(io.StringIO(text[:20000]), delimiter=("," if ext == ".csv" else "\t")))
            if rows and _looks_like_refs([dict(zip(rows[0], r)) for r in rows[1:6]]):
                return "library"
        except Exception:
            pass

    words = len(re.findall(r"\S+", head))
    heads = len([ln for ln in head.splitlines() if is_heading_line(ln)])
    if words > 120 and (heads >= 2 or re.search(r"\bthe\b|\bof\b|\band\b|\u7684", head)):
        if any(h in name for h in LIB_HINTS) and heads == 0 and words < 400:
            return "library"
        return "manuscript"
    if heads >= 2 and words > 40:
        return "manuscript"
    if any(h in name for h in MANU_HINTS) and words > 40:
        return "manuscript"
    return "notes"


def discover_materials(input_dir: str, exclude=()) -> list:
    """Classify every readable file under `input_dir`."""
    out = []
    excl = {os.path.abspath(p) for p in exclude if p}
    for p in list_files(input_dir):
        ap = os.path.abspath(p)
        if ap in excl:
            continue
        ext = os.path.splitext(p)[1].lower()
        name = os.path.basename(p)
        if ext in BIN_EXT:
            out.append({"path": p, "name": name, "ext": ext, "kind": "binary",
                        "size": os.path.getsize(p) if os.path.exists(p) else 0,
                        "text": "", "note": "binary material: text must be extracted elsewhere"})
            continue
        if ext not in TEXT_EXT:
            continue
        text = read_text(p)
        if not text.strip():
            continue
        kind = classify_text(text, p)
        if name.lower() in SKIP_NAMES and kind == "manuscript":
            kind = "notes"
        out.append({"path": p, "name": name, "ext": ext, "kind": kind,
                    "size": len(text.encode("utf-8")), "text": text, "note": ""})
    order = {"manuscript": 0, "library": 1, "notes": 2, "unknown": 3, "binary": 4}
    out.sort(key=lambda m: (order.get(m["kind"], 9), -m["size"]))
    return out


# --------------------------------------------------------------------------- #
# 5. reference library
# --------------------------------------------------------------------------- #

FIELD_ALIASES = {
    "title": ("title", "题名", "题目", "name", "article-title", "primary_title", "t1"),
    "authors": ("author", "authors", "作者", "creators", "au", "a1", "by"),
    "year": ("year", "年份", "年", "date", "issued", "publication_year", "py", "y1", "published"),
    "venue": ("venue", "journal", "booktitle", "期刊", "来源", "刊名", "container-title",
              "journal_title", "publication", "publisher", "t2", "jo", "jf", "so", "source"),
    "doi": ("doi", "DOI", "dois"),
    "arxiv": ("arxiv", "arxiv_id", "eprint", "arxivid"),
    "abstract": ("abstract", "摘要", "summary", "ab"),
    "keywords": ("keywords", "keyword", "关键词", "kw", "tags"),
    "url": ("url", "link", "uri"),
    "type": ("type", "entry_type", "kind", "文献类型", "itemtype"),
    "volume": ("volume", "卷", "vol"),
    "issue": ("issue", "number", "期", "no"),
    "pages": ("pages", "页码", "page", "sp", "ep", "start_page", "firstpage"),
    "publisher": ("publisher", "出版社", "school", "institution"),
    "isbn": ("isbn", "issn"),
    "note": ("note", "notes", "备注"),
    "key": ("key", "id", "citekey", "citation-key", "ref_id", "label"),
}

TYPE_MAP = {
    "article": "journal", "journal": "journal", "jour": "journal", "j": "journal",
    "inproceedings": "conference", "conference": "conference", "proceedings": "conference",
    "c": "conference", "paper-conference": "conference",
    "book": "book", "m": "book", "monograph": "book",
    "thesis": "thesis", "phdthesis": "thesis", "mastersthesis": "thesis", "d": "thesis",
    "techreport": "report", "report": "report", "r": "report",
    "misc": "misc", "online": "web", "web": "web", "eb-ol": "web",
    "preprint": "preprint", "unpublished": "preprint",
    "incollection": "chapter", "chapter": "chapter",
}


def _pick(d: dict, field: str):
    low = {str(k).strip().lower(): v for k, v in d.items()}
    for alias in FIELD_ALIASES[field]:
        if alias.lower() in low:
            v = low[alias.lower()]
            if v not in (None, "", [], {}):
                return v
    return None


def _norm_type(raw) -> str:
    if not raw:
        return ""
    t = re.sub(r"[^a-z\-]", "", str(raw).strip().lower())
    return TYPE_MAP.get(t, t or "")


def _bib_entries(text: str) -> list:
    """Brace-balanced BibTeX parser."""
    out = []
    i, n = 0, len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        m = re.match(r"@(\w+)\s*[{(]\s*([^,\s]*)\s*,", text[at:])
        if not m:
            i = at + 1
            continue
        etype, key = m.group(1).lower(), m.group(2)
        j = at + m.end()
        depth, k = 1, j
        while k < n and depth > 0:
            c = text[k]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == "(" and depth == 1 and etype == "comment":
                pass
            k += 1
        body = text[j:k - 1] if depth == 0 else text[j:]
        fields = {}
        pos = 0
        while pos < len(body):
            fm = re.match(r"\s*([A-Za-z_\-]+)\s*=\s*", body[pos:])
            if not fm:
                # skip to next comma at depth 0
                cm = re.search(r"[,\n]", body[pos:])
                if not cm:
                    break
                pos += cm.end()
                continue
            name = fm.group(1).lower()
            p = pos + fm.end()
            if p < len(body) and body[p] == "{":
                d, q = 0, p
                while q < len(body):
                    if body[q] == "{":
                        d += 1
                    elif body[q] == "}":
                        d -= 1
                        if d == 0:
                            break
                    q += 1
                val = body[p + 1:q]
                pos = q + 1
            elif p < len(body) and body[p] == '"':
                q = body.find('"', p + 1)
                q = q if q > p else len(body)
                val = body[p + 1:q]
                pos = q + 1
            else:
                mm = re.match(r"([^,}\n]+)", body[p:])
                val = mm.group(1) if mm else ""
                pos = p + (mm.end() if mm else 0)
            fields[name] = norm_ws(re.sub(r"[{}]", "", val))
            while pos < len(body) and body[pos] in " \t\r\n,":
                pos += 1
        if key:
            e = _from_fields(fields, key=key, etype=etype)
            if e.get("title") or e.get("authors"):
                out.append(e)
        i = max(k, at + 1)
    return out


def _from_fields(fields: dict, key: str = "", etype: str = "") -> dict:
    title = _pick(fields, "title")
    authors = _pick(fields, "authors")
    year = _pick(fields, "year")
    if isinstance(year, str):
        ym = re.search(r"(?:19|20)\d{2}", year)
        year = int(ym.group(0)) if ym else None
    elif isinstance(year, (int, float)):
        year = int(year)
    else:
        year = None
    doi = _pick(fields, "doi")
    if doi:
        dm = re.search(r"10\.\d{4,9}/[^\s,;]+", str(doi))
        doi = dm.group(0).rstrip(".") if dm else norm_ws(str(doi))
    pages = norm_ws(str(_pick(fields, "pages") or ""))
    pages = re.sub(r"\s*[–—−]\s*", "-", pages)
    pages = re.sub(r"-{2,}", "-", pages).strip(",.;")
    etype2 = _norm_type(etype or _pick(fields, "type"))
    return {
        "key": norm_ws(str(key)) if key else norm_ws(str(_pick(fields, "key") or "")),
        "title": norm_ws(str(title)) if title else "",
        "authors": split_authors(authors),
        "year": year,
        "venue": norm_ws(str(_pick(fields, "venue") or "")),
        "doi": doi or "",
        "arxiv": norm_ws(str(_pick(fields, "arxiv") or "")),
        "abstract": norm_ws(str(_pick(fields, "abstract") or "")),
        "keywords": _as_list(_pick(fields, "keywords")),
        "url": norm_ws(str(_pick(fields, "url") or "")),
        "type": etype2,
        "volume": norm_ws(str(_pick(fields, "volume") or "")),
        "issue": norm_ws(str(_pick(fields, "issue") or "")),
        "pages": pages,
        "publisher": norm_ws(str(_pick(fields, "publisher") or "")),
        "isbn": norm_ws(str(_pick(fields, "isbn") or "")),
        "note": norm_ws(str(_pick(fields, "note") or "")),
        "source": "",
    }


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [norm_ws(str(x)) for x in v if norm_ws(str(x))]
    return [x for x in (norm_ws(y) for y in re.split(r"[;,，；]|\s{2,}", str(v))) if x]


def _ris_entries(text: str) -> list:
    out, cur = [], {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$", line)
        if not m:
            if line.strip() and cur:
                last = cur.get("_last")
                if last:
                    cur[last] = (cur[last] + " " + line.strip()).strip()
            continue
        tag, val = m.group(1), norm_ws(m.group(2))
        if tag == "TY":
            cur = {"TY": val}
            cur["_last"] = "TY"
        elif tag == "ER":
            if cur:
                out.append(cur)
            cur = {}
        else:
            cur[tag] = (cur.get(tag, "") + " " + val).strip() if tag in cur else val
            cur["_last"] = tag
    if cur:
        out.append(cur)
    res = []
    for r in out:
        fields = {
            "title": r.get("TI") or r.get("T1") or r.get("CT"),
            "authors": [r[k] for k in sorted(r) if k in ("AU", "A1", "A2") and isinstance(r[k], str)] or None,
            "year": r.get("PY") or r.get("Y1") or r.get("DA"),
            "venue": r.get("JO") or r.get("JF") or r.get("T2") or r.get("BT"),
            "doi": r.get("DO"),
            "abstract": r.get("AB") or r.get("N2"),
            "keywords": r.get("KW"),
            "url": r.get("UR") or r.get("L2"),
            "type": r.get("TY"),
            "volume": r.get("VL"),
            "issue": r.get("IS") or r.get("C7"),
            "pages": (r.get("SP", "") + ("-" + r["EP"] if r.get("EP") else "")).strip("-") or None,
            "publisher": r.get("PB"),
            "isbn": r.get("SN"),
            "note": r.get("N1"),
            "key": r.get("ID") or r.get("C1"),
        }
        fields = {k: v for k, v in fields.items() if v}
        e = _from_fields(fields, key=fields.get("key") or "", etype=str(fields.get("type") or ""))
        if e.get("title") or e.get("authors"):
            res.append(e)
    return res


def _json_entries(obj) -> list:
    if isinstance(obj, dict):
        for k in ("references", "entries", "items", "library", "refs", "data", "records", "bibliography"):
            v = obj.get(k)
            if isinstance(v, list):
                return v
        if all(isinstance(v, (str, int, float, list, type(None))) for v in obj.values()):
            return [obj]
        # dict of key -> entry
        vals = [v for v in obj.values() if isinstance(v, dict)]
        if vals and len(vals) == len([v for v in obj.values() if not isinstance(v, (str, int, float))]):
            return [dict(v, key=v.get("key", k)) for k, v in obj.items() if isinstance(v, dict)]
        return []
    if isinstance(obj, list):
        return obj
    return []


def _looks_like_refs(entries: list) -> bool:
    if not entries:
        return False
    hit = 0
    for e in entries[:8]:
        if not isinstance(e, dict):
            continue
        if _pick(e, "title") and (_pick(e, "year") or _pick(e, "authors") or _pick(e, "venue")):
            hit += 1
    return hit >= max(1, min(3, len(entries)))


def _field_lines_entries(text: str) -> list:
    """CNKI / INSPIRE style records: `Field: value` blocks separated by blank lines
    or by a leading record marker."""
    blocks, buf = [], []
    for line in text.splitlines():
        if not line.strip():
            if buf:
                blocks.append(buf)
                buf = []
            continue
        buf.append(line)
    if buf:
        blocks.append(buf)
    if len(blocks) == 1 and len(blocks[0]) > 40:
        # no blank lines: split on 'Title'/'题名' restart
        recs, cur = [], []
        for line in blocks[0]:
            if re.match(r"^\s*(?:Title|题名|题目)\s*[:：]", line, re.I) and cur:
                recs.append(cur)
                cur = []
            cur.append(line)
        if cur:
            recs.append(cur)
        blocks = recs
    out = []
    for b in blocks:
        fields = {}
        for line in b:
            m = re.match(r"^\s*([^:：]{1,24})\s*[:：]\s*(.*)$", line)
            if m:
                fields[norm_ws(m.group(1)).lower()] = norm_ws(m.group(2))
            elif fields:
                fields[list(fields)[-1]] = (fields[list(fields)[-1]] + " " + line.strip()).strip()
        if not fields:
            continue
        e = _from_fields(fields, key=str(_pick(fields, "key") or ""), etype=str(_pick(fields, "type") or ""))
        if e.get("title") or (e.get("authors") and e.get("year")):
            out.append(e)
    return out


def parse_library_file(path: str, text: str) -> tuple:
    """Return (entries, format_name). Never raises."""
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    if ext in (".bib",) or re.search(r"@\w+\s*\{", text[:4000]):
        e = _bib_entries(text)
        if e:
            return e, "bibtex"
    if ext in (".ris", ".enw", ".nbib") or re.search(r"^TY\s{2}-", text, re.M):
        e = _ris_entries(text)
        if e:
            return e, "ris"
    st = text.strip()
    if st[:1] in "[{":
        try:
            obj = json.loads(text)
            raw = _json_entries(obj)
            e = []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                ent = _from_fields(r, key=str(_pick(r, "key") or ""), etype=str(_pick(r, "type") or ""))
                if ent.get("title") or ent.get("authors"):
                    e.append(ent)
            if e:
                return e, "json"
        except Exception:
            pass
    if ext in (".csv", ".tsv"):
        try:
            delim = "," if ext == ".csv" else "\t"
            rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
            e = []
            for r in rows:
                if not r:
                    continue
                ent = _from_fields(r, key=str(_pick(r, "key") or ""), etype=str(_pick(r, "type") or ""))
                if ent.get("title") or ent.get("authors"):
                    e.append(ent)
            if e:
                return e, "csv"
        except Exception:
            pass
    e = _field_lines_entries(text)
    if len(e) >= 1 and any(x.get("title") for x in e):
        return e, "field-lines"
    return [], "unparsed:" + name


def _entry_identity(e: dict) -> str:
    if e.get("doi"):
        return "doi:" + e["doi"].lower()
    t = norm_cmp(e.get("title"))
    if t:
        return "t:" + t[:90]
    a = surname_of((e.get("authors") or [""])[0]).lower()
    return "ay:%s:%s" % (a, e.get("year"))


def dedupe_entries(entries: list) -> tuple:
    """Merge duplicates. Returns (merged_list, merge_log).

    Identity: DOI, then normalised title, then first-author surname + year with a
    title similarity guard. Every merge records the signal that produced it.
    """
    merged, log = [], []
    by_id = {}
    for e in entries:
        ident = _entry_identity(e)
        tgt = by_id.get(ident)
        if tgt is None and e.get("title"):
            nt = norm_cmp(e["title"])
            for cand in merged:
                if not cand.get("title"):
                    continue
                ct = norm_cmp(cand["title"])
                if ct == nt and nt:
                    tgt = cand
                    log.append({"signal": "title_exact", "kept": cand["ref_id"], "merged": e.get("key") or e.get("title"),
                                "title": e.get("title")})
                    break
                if (cand.get("year") == e.get("year")
                        and surname_of((cand.get("authors") or [""])[0]).lower()
                        == surname_of((e.get("authors") or [""])[0]).lower()
                        and nt and ct and (_ratio(ct, nt) >= 0.9)):
                    tgt = cand
                    log.append({"signal": "author_year_title_similar", "kept": cand["ref_id"],
                                "merged": e.get("key") or e.get("title"), "title": e.get("title")})
                    break
        if tgt is None:
            e = dict(e)
            e["ref_id"] = "R%04d" % (len(merged) + 1)
            e["merged_from"] = []
            merged.append(e)
            by_id[ident] = e
        else:
            tgt["merged_from"].append({k: e.get(k) for k in ("key", "title", "year", "doi", "source")})
            for f in ("year", "venue", "doi", "abstract", "volume", "issue", "pages", "publisher", "url", "type"):
                if not tgt.get(f) and e.get(f):
                    tgt[f] = e[f]
            if len(e.get("authors") or []) > len(tgt.get("authors") or []):
                tgt["authors"] = e["authors"]
            for k in e.get("keywords") or []:
                if k not in (tgt.get("keywords") or []):
                    tgt.setdefault("keywords", []).append(k)
            for k in e.get("aliases") or []:
                tgt.setdefault("aliases", []).append(k)
    for m in merged:
        m.pop("aliases", None)
    return merged, log


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    hit = sum(1 for i in range(len(short) - 1) if short[i:i + 2] in long_)
    denom = max(1, len(short) - 1)
    return min(1.0, hit / denom)


def build_library(materials: list) -> dict:
    """Assemble the reference library from every library-kind material."""
    entries, sources, logs = [], [], []
    formats = []
    for m in materials:
        if m["kind"] != "library":
            continue
        e, fmt = parse_library_file(m["path"], m["text"])
        formats.append(fmt)
        sources.append({"path": m["path"], "format": fmt, "n": len(e)})
        for x in e:
            x = dict(x)
            x["source"] = m["path"]
            entries.append(x)
        logs.append("library %s: %d entries (%s)" % (os.path.basename(m["path"]), len(e), fmt))
    merged, merge_log = dedupe_entries(entries)
    for m in merged:
        m.setdefault("must_cite", False)
        m.setdefault("role", "")
        m.setdefault("cluster", "")
        m.setdefault("notes", "")
    return {
        "entries": merged,
        "n_raw": len(entries),
        "sources": sources,
        "formats": formats,
        "merge_log": merge_log,
        "log": logs,
        "fallback": "none" if merged else "empty",
    }


def library_index(lib: dict) -> dict:
    """Lookup tables for citation resolution."""
    idx = {"by_key": {}, "by_doi": {}, "by_num": {}, "by_ay": {}, "by_title": {}}
    for i, e in enumerate(lib.get("entries") or []):
        k = norm_ws(str(e.get("key") or "")).lower()
        if k:
            idx["by_key"].setdefault(k, e)
        if e.get("doi"):
            idx["by_doi"].setdefault(e["doi"].lower(), e)
        nt = norm_cmp(e.get("title"))
        if nt:
            idx["by_title"].setdefault(nt[:120], e)
        ay = "%s|%s" % (surname_of((e.get("authors") or [""])[0]).lower(), e.get("year"))
        if ay != "|None":
            idx["by_ay"].setdefault(ay, e)
            for a in (e.get("authors") or [])[:6]:
                idx["by_ay"].setdefault("%s|%s" % (surname_of(a).lower(), e.get("year")), e)
        # positional number, 1-based, for numeric citation styles
        idx["by_num"][i + 1] = e
        if e.get("index"):
            try:
                idx["by_num"][int(e["index"])] = e
            except (TypeError, ValueError):
                pass
    return idx


def resolve_citation(c: dict, idx: dict, reflist: list = None) -> dict:
    """Resolve one parsed marker to library entries.

    Returns {ref_ids, method, unresolved, ambiguous}.
    """
    out = {"ref_ids": [], "method": "", "unresolved": [], "ambiguous": []}
    if c["kind"] == CITE_KIND_KEY:
        for k in c["keys"]:
            e = idx["by_key"].get(k.lower()) or idx["by_title"].get(norm_cmp(k)[:120])
            if e:
                out["ref_ids"].append(e["ref_id"])
                out["method"] = out["method"] or "citekey"
            else:
                out["unresolved"].append(k)
    elif c["kind"] == CITE_KIND_NUMERIC:
        n_ref = len(reflist or [])
        for num in c["nums"]:
            e = None
            method = ""
            if reflist and 1 <= num <= n_ref:
                e = reflist[num - 1]
                method = "manuscript_reflist"
            elif num in idx["by_num"]:
                e = idx["by_num"][num]
                method = "library_order"
            rid = (e or {}).get("ref_id")
            if rid:
                out["ref_ids"].append(rid)
                out["method"] = out["method"] or method
            elif e is not None:
                out["unresolved"].append("[%d]" % num)
            else:
                out["unresolved"].append("[%d]" % num)
    else:
        for sn in c["surnames"]:
            cand = idx["by_ay"].get("%s|%s" % (sn.lower(), c["year"]))
            if not cand:
                cand = idx["by_ay"].get("%s|%s" % (surname_of(sn).lower(), c["year"]))
            if cand:
                out["ref_ids"].append(cand["ref_id"])
                out["method"] = out["method"] or "author-year"
            else:
                key = "%s %s" % (sn, c["year"])
                hit = [e for e in (idx["by_ay"].values()) if str(e.get("year")) == str(c["year"])
                       and surname_of((e.get("authors") or [""])[0]).lower() == surname_of(sn).lower()]
                if len(hit) == 1:
                    out["ref_ids"].append(hit[0]["ref_id"])
                    out["method"] = out["method"] or "author-year"
                elif len(hit) > 1:
                    out["ambiguous"].append(key)
                else:
                    out["unresolved"].append(key)
    out["ref_ids"] = list(dict.fromkeys(out["ref_ids"]))
    return out


# --------------------------------------------------------------------------- #
# 6. manuscript index
# --------------------------------------------------------------------------- #

FIG_RE = re.compile(r"(?:Fig(?:ure)?s?\.?|图)\s*([0-9]{1,3})(?:\s*[（(]?([a-z])[)）]?)?")
TAB_RE = re.compile(r"(?:Tab(?:le)?s?\.?|表)\s*([0-9]{1,3})(?:\s*[（(]?([a-z])[)）]?)?")
EQN_RE = re.compile(r"\((\d{1,3}[a-z]?)\)\s*$")
CAPTION_RE = re.compile(r"^\s*(?:Fig(?:ure)?s?\.?|图|Tab(?:le)?s?\.?|表)\s*([0-9]{1,3})")
REF_HEAD_RE = re.compile(r"^\s*(?:#+\s*)?(?:References|Reference|Bibliography|参考文献|引用文献|文献列表)\s*$", re.I)
ABS_HEAD_RE = re.compile(r"^\s*(?:#+\s*)?(?:Abstract|摘要)\s*[:：]?\s*(.*)$", re.I)
KW_RE = re.compile(r"^\s*(?:#+\s*)?(?:Key\s*words?|Keywords?|关键词)\s*[:：]?\s*(.*)$", re.I)
CN_REF_ITEM = re.compile(r"^\s*[\[［]?(\d{1,3})[\]］]?[.、)]?\s+(.*)$")


def parse_manuscript(text: str, path: str = "") -> dict:
    """Structural index of the manuscript: what the contribution ledger can point at."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    sections, cur = [], None
    reflist_raw, ref_mode = [], False
    abs_lines, kw_lines = [], []
    in_abs, in_kw = False, False

    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        mhead = REF_HEAD_RE.match(s) and len(s) < 40
        if mhead:
            ref_mode = True
            in_abs = in_kw = False
            continue
        if ref_mode:
            if s and (MD_HEAD.match(s) or TEX_HEAD.match(s)):
                ref_mode = False
            else:
                reflist_raw.append(s)
                continue
        ma = ABS_HEAD_RE.match(s)
        if ma and len(s) < 30:
            in_abs = True
            in_kw = False
            if ma.group(1).strip():
                abs_lines.append(ma.group(1).strip())
            continue
        mk = KW_RE.match(s)
        if mk and len(s) < 40:
            in_kw = True
            in_abs = False
            if mk.group(1).strip():
                kw_lines.append(mk.group(1).strip())
            continue
        if is_heading_line(s):
            in_abs = in_kw = False
            hi = heading_info(s)
            cur = {"level": hi["level"], "number": hi["number"], "title": hi["title"],
                   "line": len(sections) + 1, "text": ""}
            sections.append(cur)
            continue
        if in_abs and s:
            abs_lines.append(s)
        elif in_kw and s:
            kw_lines.append(s)
        if cur is not None:
            cur["text"] = (cur["text"] + " " + s).strip() if cur["text"] else s

    try:
        reflist = parse_reflist(reflist_raw)
    except Exception:
        reflist = []

    figures, tables, equations = {}, {}, []
    for ln in lines:
        s = ln.strip()
        if CAPTION_RE.match(s):
            for m in FIG_RE.finditer(s):
                figures.setdefault(int(m.group(1)), norm_ws(s)[:240])
            for m in TAB_RE.finditer(s):
                tables.setdefault(int(m.group(1)), norm_ws(s)[:240])
        me = EQN_RE.search(s)
        if me and len(s) < 200:
            equations.append({"label": me.group(1), "text": norm_ws(s)})
    for m in FIG_RE.finditer(text):
        figures.setdefault(int(m.group(1)), "")
    for m in TAB_RE.finditer(text):
        tables.setdefault(int(m.group(1)), "")
    for m in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        n = len(figures) + 1
        figures.setdefault(n, norm_ws(m.group(1))[:240])

    title = ""
    for s in sections:
        if s["level"] == 1 and s["title"]:
            title = s["title"]
            break
    if not title:
        for ln in lines[:6]:
            if ln.strip() and len(ln.strip()) < 160:
                title = norm_ws(ln.strip())
                break

    abstract = norm_ws(" ".join(abs_lines))
    keywords = []
    for k in kw_lines:
        keywords.extend([x for x in re.split(r"[;；,，]", k) if norm_ws(x)])
    keywords = [norm_ws(x) for x in keywords if norm_ws(x)]

    intro_sections = [s for s in sections
                      if re.search(r"introduction|related\s*work|background|引言|绪论|相关工作|研究背景",
                                   s["title"] or "", re.I)]

    return {
        "path": path,
        "chars": len(text),
        "words": len(re.findall(r"\S+", text)),
        "lang": detect_lang(text),
        "title": title,
        "abstract": abstract,
        "keywords": keywords,
        "sections": sections,
        "section_titles": [s["title"] for s in sections],
        "figures": [{"label": "Fig. %d" % k, "number": k, "caption": v} for k, v in sorted(figures.items())],
        "tables": [{"label": "Table %d" % k, "number": k, "caption": v} for k, v in sorted(tables.items())],
        "equations": equations,
        "reflist": reflist,
        "reflist_n": len(reflist),
        "intro_sections": [s["title"] for s in intro_sections],
        "numbers": sorted(number_keys_of(text)),
        "text": text,
    }


def parse_reflist(lines: list) -> list:
    """Parse a manuscript reference list into entries (no ref_id yet).

    Two layouts are supported: one record per line (the overwhelmingly common
    case, with an optional `[n]` / `n.` prefix), and records wrapped over
    several indented lines, which are re-joined into one block.
    """
    if not lines:
        return []
    start_re = re.compile(r"^\s*[\[［]?\d{1,3}[\]］]?[.、)]?\s+[A-Z\u4e00-\u9fff\"]")
    apa_start_re = re.compile(r"^\s*[A-Z][A-Za-z'’\-]+,\s")
    blocks, buf = [], []
    for s in lines:
        s = s.strip()
        if not s:
            continue
        new_record = bool(start_re.match(s))
        if not new_record and buf and apa_start_re.match(s) and re.search(r"(?:19|20)\d{2}", s):
            # an unnumbered APA/IEEE entry starts only when the previous one looks finished
            prev = " ".join(buf)
            new_record = bool(re.search(r"(?:19|20)\d{2}", prev)) and prev.rstrip().endswith((".", "。"))
        if new_record and buf:
            blocks.append(buf)
            buf = [s]
        elif new_record:
            buf = [s]
        else:
            buf.append(s)
    if buf:
        blocks.append(buf)
    out = []
    for b in blocks:
        raw = norm_ws(" ".join(b))
        if len(raw) < 8:
            continue
        m = re.match(r"^\s*[\[［]?(\d{1,3})[\]］]?[.、)]?\s*(.*)$", raw)
        num, body = (int(m.group(1)), m.group(2)) if m else (None, raw)
        if num is None and not re.search(r"(?:19|20)\d{2}", raw):
            continue
        e = parse_ref_string(body)
        if not e.get("title") and not e.get("authors"):
            continue
        e["reflist_number"] = num if num is not None else (len(out) + 1)
        e["raw"] = raw
        out.append(e)
    return out


def link_reflist(manuscript: dict, library: dict) -> dict:
    """Attach every manuscript reference-list entry to a library entry.

    A numeric citation style (`[3]`) can only be resolved against the manuscript's
    own reference list, so each list entry must point at exactly one library entry.
    When the list entry matches nothing it becomes a new library entry marked
    `unverified_metadata`, because the metadata came from the author's typesetting
    rather than from a bibliographic record, and the audit reports that honestly.

    Returns a small report so the caller can log how many entries were linked.
    """
    entries = library.setdefault("entries", [])
    by_doi, by_title, by_ay = {}, [], {}
    for e in entries:
        if e.get("doi"):
            by_doi[e["doi"].lower()] = e
        if e.get("title"):
            by_title.append((norm_cmp(e["title"]), e))
        ay = "%s|%s" % (surname_of((e.get("authors") or [""])[0]).lower(), e.get("year"))
        if ay != "|None":
            by_ay.setdefault(ay, []).append(e)

    linked = created = 0
    for r in manuscript.get("reflist") or []:
        hit, how = None, ""
        if r.get("doi") and r["doi"].lower() in by_doi:
            hit, how = by_doi[r["doi"].lower()], "doi"
        if hit is None and r.get("title"):
            nt = norm_cmp(r["title"])
            if nt:
                best, score = None, 0.0
                for ct, e in by_title:
                    if not ct:
                        continue
                    if ct.startswith(nt[:60]) or nt.startswith(ct[:60]):
                        s = 1.0
                    else:
                        s = _ratio(nt[:120], ct[:120])
                    if s > score:
                        best, score = e, s
                if best is not None and score >= 0.55:
                    hit, how = best, "title_overlap(%.2f)" % score
        if hit is None:
            ay = "%s|%s" % (surname_of((r.get("authors") or [""])[0]).lower(), r.get("year"))
            cand = by_ay.get(ay) or []
            if len(cand) == 1:
                hit, how = cand[0], "author_year"
            elif len(cand) > 1:
                nt = norm_cmp(r.get("title"))
                best = max(cand, key=lambda e: _ratio(nt, norm_cmp(e.get("title"))))
                hit, how = best, "author_year+title"
        if hit is not None:
            r["ref_id"] = hit["ref_id"]
            r["link_method"] = how
            linked += 1
        else:
            new = dict(r)
            new["ref_id"] = "X%04d" % (created + 1)
            new["merged_from"] = []
            new["source"] = "manuscript_reflist"
            new["unverified_metadata"] = True
            new.setdefault("must_cite", False)
            new.setdefault("role", "")
            new.setdefault("cluster", "")
            new.setdefault("notes", "")
            entries.append(new)
            r["ref_id"] = new["ref_id"]
            r["link_method"] = "unmatched_new_entry"
            created += 1
    if created:
        library.setdefault("log", []).append(
            "reference list: %d entries matched library records, %d kept as unverified list-only entries"
            % (linked, created))
    library["reflist_links"] = {"linked": linked, "created": created}
    return library


def parse_ref_string(s: str) -> dict:
    """Parse one formatted reference string into fields (GB/T, APA, Vancouver, IEEE)."""
    e = {"title": "", "authors": [], "year": None, "venue": "", "doi": "", "type": "",
         "volume": "", "issue": "", "pages": "", "publisher": "", "arxiv": "", "url": "",
         "abstract": "", "keywords": [], "note": "", "key": "", "source": "manuscript_reflist"}
    s = norm_ws(s)
    ym = re.findall(r"(?:19|20)\d{2}", s)
    if ym:
        e["year"] = int(ym[-1] if len(ym) > 1 else ym[0])
    dm = re.search(r"(?:doi[:\s]*)?(10\.\d{4,9}/[^\s,;\]\)]+)", s, re.I)
    if dm:
        e["doi"] = dm.group(1).rstrip(".")
    am = re.search(r"arXiv[:\s]*(\d{4}\.\d{4,5}(?:v\d+)?)", s, re.I)
    if am:
        e["arxiv"] = am.group(1)
    tm = re.search(r"\[([JCMDNRSEB])(?:/OL)?\]", s)
    if tm:
        e["type"] = {"J": "journal", "C": "conference", "M": "book", "D": "thesis",
                     "R": "report", "N": "news", "S": "standard", "E": "web", "B": "chapter"}.get(tm.group(1), "")
        s = s[:tm.start()] + " " + s[tm.end():]
    quote = re.search(r"[“\"]([^”\"]{6,220})[”\"]", s)
    if quote:
        e["title"] = norm_ws(quote.group(1))
        head = s[:quote.start()]
        tail = s[quote.end():]
    else:
        parts = re.split(r"\.\s+", s)
        head = parts[0] if parts else ""
        rest = parts[1:]
        if e.get("year") and e["year"] >= 1980:
            cut = [p for p in rest if not re.fullmatch(r"\s*(?:19|20)\d{2}\s*\.?", p or "")]
            ttl = cut[0] if cut else ""
            if re.fullmatch(r"\s*[\[［]?\d{1,3}[\]］]?\.?\s*", ttl or ""):
                ttl = cut[1] if len(cut) > 1 else ""
            e["title"] = norm_ws(ttl)
        tail = ". ".join(rest[1:]) if len(rest) > 1 else ""
    e["authors"] = split_authors(re.split(r"\.\s+", head)[0]) if head else []
    if e.get("title") and "//" in e["title"]:
        ttl2, _, ven2 = e["title"].partition("//")
        e["title"] = norm_ws(ttl2)
        if not e.get("venue") and norm_ws(ven2):
            e["venue"] = norm_ws(ven2)[:120]
    e["title"] = re.sub(r"^\s*//\s*", "", e.get("title") or "").strip()
    vm = re.search(r"[,，]\s*(\d{1,4})\s*(?:\(\s*([\dA-Za-z\-]+)\s*\))?\s*[,:：]\s*(\d{1,6}\s*[-–—]\s*\d{1,6}|\d{1,6})", tail or s)
    if vm:
        e["volume"] = vm.group(1)
        e["issue"] = vm.group(2) or ""
        e["pages"] = norm_ws(vm.group(3))
    vm2 = re.search(r"\b(\d{1,4})\s*\(\s*(\d{1,3})\s*\)\s*[:：]\s*(\d{1,6}\s*[-–—]\s*\d{1,6})", tail or s)
    if vm2 and not e["volume"]:
        e["volume"], e["issue"], e["pages"] = vm2.group(1), vm2.group(2), norm_ws(vm2.group(3))
    seg = [x for x in re.split(r"\.\s+", tail or "") if x.strip()]
    for x in seg:
        if not e["venue"] and re.search(r"[A-Za-z\u4e00-\u9fff]{3,}", x) and not re.search(r"^\s*\d", x) \
                and not re.search(r"doi|http|vol\.|pp\.|no\.", x, re.I):
            e["venue"] = norm_ws(x)[:120]
            break
    um = re.search(r"https?://\S+", s)
    if um:
        e["url"] = um.group(0)
    return e


# --------------------------------------------------------------------------- #
# 7. draft parsing
# --------------------------------------------------------------------------- #

PART_ORDER = ["background", "related_work", "gap", "contributions"]
PART_LABEL = {
    "background": {"zh": "研究背景", "en": "Background"},
    "related_work": {"zh": "相关工作", "en": "Related Work"},
    "gap": {"zh": "研究空白", "en": "Research Gap"},
    "contributions": {"zh": "主要贡献", "en": "Contributions"},
}
PART_ALIASES = {
    "background": r"背景|background|motivation|动机|引言|introduction|研究现状",
    "related_work": r"相关工作|related\s*work|文献综述|literature\s*review|研究进展|prior\s*work",
    "gap": r"空白|gap|不足|limitation|问题|挑战|challenge|open\s*(?:problem|question)",
    "contributions": r"贡献|contribution|本文工作|our\s*work|主要工作|创新",
}
SLOT_RE = re.compile(r"<!--\s*part:\s*([a-z_]+)\s*-->", re.I)
SLOT_END_RE = re.compile(r"<!--\s*/part:\s*([a-z_]+)\s*-->", re.I)


def parse_draft(text: str, lang: str = "auto") -> dict:
    """Split the draft into typed parts, paragraphs, sentences and citations."""
    text = (text or "").replace("\r\n", "\n")
    lang = detect_lang(text) if lang == "auto" else lang
    parts, method = {p: "" for p in PART_ORDER}, "none"

    cur = None
    buf = {p: [] for p in PART_ORDER}
    for line in text.split("\n"):
        ms = SLOT_RE.search(line)
        if ms and ms.group(1) in buf:
            cur = ms.group(1)
            method = "slot"
            continue
        me = SLOT_END_RE.search(line)
        if me and me.group(1) in buf:
            cur = None
            continue
        if cur:
            buf[cur].append(line)
        elif method == "none":
            buf.setdefault("_preamble", []).append(line)
    if method == "slot":
        parts = {p: "\n".join(buf[p]).strip() for p in PART_ORDER}
    else:
        # heading-based fallback
        blocks = []
        curp = None
        for line in text.split("\n"):
            s = line.strip()
            if is_heading_line(s) or (len(s) < 60 and re.match(r"^(?:#+\s*)?[\d一二三四五六七八九十]*[.、)]?\s*\S{2,30}$", s)
                                      and any(re.search(v, s, re.I) for v in PART_ALIASES.values())):
                hit = None
                for p in PART_ORDER:
                    if re.search(PART_ALIASES[p], s, re.I):
                        hit = p
                        break
                if hit:
                    curp = hit
                    blocks.append(("h", hit))
                    continue
            if curp:
                blocks.append(("t", curp, line))
        acc = {p: [] for p in PART_ORDER}
        for b in blocks:
            if b[0] == "t":
                acc[b[1]].append(b[2])
        if any(acc.values()):
            method = "heading"
            parts = {p: "\n".join(acc[p]).strip() for p in PART_ORDER}

    out = {"lang": lang, "method": method, "parts": {}, "paragraphs": [],
           "sentences": [], "citations": parse_citations(text), "text": text}
    all_paras = []
    for p in PART_ORDER:
        body = parts.get(p, "")
        paras = [strip_md(x) for x in split_paragraphs(body)]
        paras = [x for x in paras if x and not is_heading_line(x)]
        out["parts"][p] = {"text": body, "paragraphs": paras,
                           "chars": len(body), "present": bool(body.strip())}
        for i, para in enumerate(paras):
            sents = split_sentences(para, lang)
            sobjs = []
            for j, s in enumerate(sents):
                sobjs.append({"part": p, "para": i, "index": j, "text": s,
                              "citations": parse_citations(s), "has_citation": has_citation(s)})
            rec = {"part": p, "index": i, "text": para, "sentences": sobjs,
                   "sentence_texts": sents,
                   "citations": parse_citations(para),
                   "ref_ids": [], "unresolved": [], "ambiguous": []}
            out["sentences"].extend(sobjs)
            all_paras.append(rec)
    out["paragraphs"] = all_paras
    out["char_count"] = sum(len(out["parts"][p]["text"]) for p in PART_ORDER)
    return out


# --------------------------------------------------------------------------- #
# 8. ledgers
# --------------------------------------------------------------------------- #

LEDGER_SPEC = {
    "refs": {
        "file": "ledger_refs.json",
        "required": [],
        "item_fields": ["ref_id", "role", "cluster", "must_cite"],
        "roles": ["seminal", "representative", "recent", "baseline", "survey",
                  "application", "ambiguous", "irrelevant", "other"],
    },
    "groups": {
        "file": "ledger_groups.json",
        "required": ["groups"],
        "work_fields": ["ref_id", "method_route", "data_setting", "evaluation", "conclusion", "limitation"],
        "item_fields": ["group_id", "label", "dimension", "works", "comparison"],
    },
    "gaps": {
        "file": "ledger_gaps.json",
        "required": ["gaps"],
        "limitation_kinds": ["shared_limitation", "uncovered_scenario", "conflicting_conclusions",
                             "evaluation_gap", "method_gap", "data_gap"],
        "item_fields": ["gap_id", "statement", "derived_from", "how_filled", "confidence"],
    },
    "contributions": {
        "file": "ledger_contributions.json",
        "required": ["contributions"],
        "kinds": ["method", "experiment", "analysis", "data", "system", "theory"],
        "locator_types": ["figure", "table", "section", "result", "equation"],
        "item_fields": ["contribution_id", "text", "kind", "evidence", "scope"],
    },
}


def empty_ledger(kind: str) -> dict:
    if kind == "refs":
        return {"entries": [], "note": "one row per library ref: {ref_id, role, cluster, must_cite, one_line}"}
    if kind == "groups":
        return {"groups": [], "note": "group by problem / method route; every work needs all comparison fields"}
    if kind == "gaps":
        return {"gaps": [], "note": "each gap must be derived from cited works and point at the contributions that fill it"}
    if kind == "contributions":
        return {"contributions": [], "note": "each contribution needs at least one resolvable evidence locator"}
    return {}


def load_ledger(path: str, kind: str) -> tuple:
    """Return (ledger, problems). Missing file is not an error; malformed is."""
    problems = []
    if not path or not os.path.isfile(path):
        return empty_ledger(kind), ["missing:" + os.path.basename(path or "")]
    try:
        obj = json.loads(read_text(path))
    except Exception as exc:
        return empty_ledger(kind), ["malformed:%s (%s)" % (os.path.basename(path), exc)]
    if not isinstance(obj, dict):
        return empty_ledger(kind), ["not_an_object:" + os.path.basename(path)]
    return obj, problems


def compare_tokens(a: str, b: str) -> int:
    """Cheap overlap count of content tokens (used for paraphrase overlap)."""
    ta = set(_content_tokens(a))
    tb = set(_content_tokens(b))
    return len(ta & tb)


_STOP = set("""a an the of and or in on to for with by from as at is are was were be been being this that these those
we our it its their they them which who whom whose what when where how not no but if then than so such can may might
have has had do does did will would should could also more most less least very much many few all any both each
""".split())
_ZH_STOP = {"的", "了", "是", "在", "和", "与", "及", "或", "等", "对", "从", "到", "为",
            "之", "其中", "这", "那", "些", "个", "我们", "他们", "它们", "本文", "进行",
            "可以", "具有", "通过", "使用", "采用", "一种", "以及", "并且", "但是", "因为"}


def _content_tokens(text: str) -> list:
    t = (text or "").lower()
    out = []
    for w in re.findall(r"[a-z][a-z\-]{2,}", t):
        if w not in _STOP:
            out.append(w)
    for ch in re.finditer(r"[\u4e00-\u9fff]{2,}", t):
        s = ch.group(0)
        if s in _ZH_STOP:
            continue
        for i in range(len(s) - 1):
            bg = s[i:i + 2]
            if bg not in _ZH_STOP:
                out.append(bg)
    return out
