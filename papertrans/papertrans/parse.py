#!/usr/bin/env python3
"""
papertrans.parse — PDF → structured blocks with page/bbox/font hints.

Backend priority: PyMuPDF (best layout) → pypdf (text-only, layout mode) → pdftotext CLI.
Every block gets: id (P{page:02d}B{idx:02d}), page, bbox, font hints, role.

Usage:
  python -m papertrans.parse INPUT.pdf --out work/doc.json [--backend auto|pymupdf|pypdf|pdftotext] [--max-pages N]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------------------------
# Role classification regexes
# ---------------------------------------------------------------------------------------------
CAPTION_RE = re.compile(r"^\s*(Fig(?:ure)?\.?|Table|Scheme|Chart|Algorithm|Box)\s*\.?\s*S?\d", re.I)
REF_START_RE = re.compile(r"^\s*(?:\[\d+\]|\d{1,3}\.\s+|[A-Z][A-Za-z'’\-]+\s+(?:et al\.|and\s+[A-Z]))")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+", re.I)
ARXIV_RE = re.compile(r"arXiv:\d{4}\.\d{4,5}(v\d+)?", re.I)
CITE_RE = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*[a-z]?\]|\(\s*[A-Z][^()]{1,40}\d{4}[a-z]?\s*(?:;[^()]*)?\)")
EQUATION_HINT_RE = re.compile(r"\\begin\{|\\frac\{|\\sum_|\\int_|\\mathbf\{|\\mathrm\{|\$\$|\\\[\s*$")
MATH_SYM_RE = re.compile(r"[∫≈≤≥≠±×÷∂∇∞√∝∈ℝℕℤ⇌∑∏]")
SUBSCRIPT_RE = re.compile(r"\b[A-Za-z]_\{?[A-Za-z0-9]+\}?")
RELATION_RE = re.compile(r"(?<![A-Za-z<>=])[A-Za-z]\s*(?:=|≤|≥|<|>|≈)\s*[\d(]|10\^?\{?[-−]?\d+|\d+\s*±\s*\d+")
LIST_RE = re.compile(r"^\s*(?:\(\d{1,2}\)|[a-z]\)|[•·▪–-]|\d+\.)\s+")
PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$")
HEADER_FOOT_RE = re.compile(
    r"(?:arXiv:|doi:|DOI|ISSN|Proceedings|Journal of|Vol\.|Received|Accepted|Published|"
    r"Downloaded|Copyright|©|Licensed under|Creative Commons|Preprint|Manuscript|"
    r"Running head|in review|Not for distribution|page \d+ of \d+|hereby grants|attribution is provided|"
    r"licen[cs]ed under|open access|This article is|downloaded from)", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
UPPER_RATIO_MIN = 0.85  # ALL CAPS detection


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", text)


def _upper_ratio(text: str) -> float:
    w = _words(text)
    if not w:
        return 0.0
    return sum(1 for x in w if len(x) > 1 and x.isupper()) / len(w)


def _digits(text: str) -> list[str]:
    return re.findall(r"(?<![A-Za-z])[-−]?\d+(?:[.,]\d+)?", text)


def _clean(text: str) -> str:
    text = text.replace("\u00ad\n", "").replace("\u00ad", "")  # soft hyphen
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _merge_lines(lines: list[str]) -> str:
    """Join PDF lines into one paragraph; hyphen at EOL → join without space."""
    out = ""
    for ln in lines:
        ln = ln.rstrip()
        if not ln:
            continue
        if out.endswith("-") and not out.endswith(" -"):
            out = out[:-1] + ln.lstrip()
        else:
            out = (out + " " + ln).strip() if out else ln
    return _clean(out)


# ---------------------------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------------------------
def _join_spans(spans: list[dict], gap_em: float = 0.18) -> str:
    """Concatenate spans on one line, inserting a space where the horizontal gap between spans indicates one
    (PyMuPDF often omits inter-word spaces in span text)."""
    out = ""
    prev = None
    for s in spans:
        txt = s.get("text", "")
        if not txt:
            continue
        if prev is not None and not txt[0].isspace() and out and not out[-1].isspace():
            size = s.get("size") or prev.get("size") or 10.0
            gap = s["bbox"][0] - prev["bbox"][2]
            if gap > gap_em * size and not (out.endswith("(") or txt[0] in ")],.;:"):
                out += " "
        out += txt
        prev = s
    return out


def _parse_pymupdf(pdf: Path, max_pages: int | None) -> list[dict[str, Any]]:
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        import fitz  # type: ignore

    doc = fitz.open(str(pdf))
    pages = []
    for pno in range(len(doc)):
        if max_pages and pno >= max_pages:
            break
        page = doc[pno]
        W, H = page.rect.width, page.rect.height
        d = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
        raw = []
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            lines = []
            sizes, bold, ital, mono, n = [], 0, 0, 0, 0
            for ln in b.get("lines", []):
                spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                lines.append(_join_spans(spans))
                for s in spans:
                    L = len(s["text"])
                    sizes += [s["size"]] * max(1, L)
                    if "bold" in s.get("font", "").lower() or (s.get("flags", 0) & 16):
                        bold += L
                    if "italic" in s.get("font", "").lower() or "oblique" in s.get("font", "").lower() or (s.get("flags", 0) & 2):
                        ital += L
                    if "mono" in s.get("font", "").lower() or "courier" in s.get("font", "").lower():
                        mono += L
                    n += max(1, L)
            if not lines:
                continue
            x0, y0, x1, y1 = b["bbox"]
            raw.append({
                "page": pno + 1,
                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                "width": W, "height": H,
                "lines": lines,
                "size": round(sum(sizes) / len(sizes), 2) if sizes else None,
                "bold": round(bold / n, 2) if n else 0.0,
                "italic": round(ital / n, 2) if n else 0.0,
                "mono": round(mono / n, 2) if n else 0.0,
                "nchars": sum(len(x) for x in lines),
            })
        pages.append(raw)
    doc.close()
    return pages


def _parse_pypdf(pdf: Path, max_pages: int | None) -> list[dict[str, Any]]:
    import pypdf  # type: ignore

    reader = pypdf.PdfReader(str(pdf))
    pages = []
    for pno, page in enumerate(reader.pages):
        if max_pages and pno >= max_pages:
            break
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:  # noqa: BLE001
            text = page.extract_text() or ""
        raw = []
        for para in re.split(r"\n\s*\n", text):
            lines = [ln for ln in para.splitlines() if ln.strip()]
            if not lines:
                continue
            raw.append({
                "page": pno + 1, "bbox": None, "width": None, "height": None,
                "lines": lines, "size": None, "bold": None, "italic": None, "mono": None,
                "nchars": sum(len(x) for x in lines),
            })
        pages.append(raw)
    return pages


def _parse_pdftotext(pdf: Path, max_pages: int | None) -> list[dict[str, Any]]:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext not found")
    cmd = [exe, "-layout", "-enc", "UTF-8"]
    if max_pages:
        cmd += ["-f", "1", "-l", str(max_pages)]
    cmd += [str(pdf), "-"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    pages = []
    for pno, ptext in enumerate(out.split("\f")):
        raw = []
        for para in re.split(r"\n\s*\n", ptext):
            lines = [ln for ln in para.splitlines() if ln.strip()]
            if not lines:
                continue
            raw.append({
                "page": pno + 1, "bbox": None, "width": None, "height": None,
                "lines": lines, "size": None, "bold": None, "italic": None, "mono": None,
                "nchars": sum(len(x) for x in lines),
            })
        pages.append(raw)
    return pages


# ---------------------------------------------------------------------------------------------
# Role classification
# ---------------------------------------------------------------------------------------------
GHOST_RE = re.compile(r"^(?:(?:the|just|this|are|will|but|my|we|be|its|in|is|of|a|and|to|it|that|for|on|with|as|was|at|by|an|or|not|from|have|has|had|you|they|he|she|which|their|our|all|can|may|do|does|did|if|then|than|so|such|no|nor|only|own|same|too|very|s|t|o|d|ll|re|ve|m)\b[\s]*)+$", re.I)
_GHOST_SINGLE = set(GHOST_RE.pattern.split("(?:")[1].split(")")[0].replace("\\b", "").split("|"))


def _is_ghost(text: str) -> bool:
    """Invisible filler text some PDF generators embed (e.g. the 40 most common English words repeated)."""
    if len(text) > 200:
        return False
    return bool(GHOST_RE.match(text.strip())) and len(re.findall(r"[A-Za-z]+", text)) >= 2


def classify(block: dict[str, Any], ctx: dict[str, Any]) -> str:
    text = _merge_lines(block["lines"])
    n = block["nchars"]
    size = block.get("size") or ctx.get("body_size") or 10.0
    bold = block.get("bold") or 0.0
    page = block["page"]
    bbox = block.get("bbox")

    if _is_ghost(text):
        return "boilerplate"
    if len(_words(text)) == 1 and _words(text)[0].lower() in _GHOST_SINGLE and not re.search(r"[.,;:!?()]", text):
        return "boilerplate"

    # Position: page header/footer bands (only if font info available); long text in bands = body/footnote
    if bbox and block.get("height") and ctx.get("body_size"):
        H = block["height"]
        digits_n = len(re.findall(r"\d", text))
        is_running = bool(HEADER_FOOT_RE.search(text)) or bool(PAGE_NUM_RE.match(text))
        if bbox[1] < 0.08 * H and size <= ctx["body_size"] * 1.05 and is_running:
            return "pageheader"
        if bbox[3] > 0.93 * H and size <= ctx["body_size"] * 1.05 and n < 80:
            return "pagefooter"

    if n <= 3 and PAGE_NUM_RE.match(text):
        return "pagefooter"
    if EQUATION_HINT_RE.search(text) and (MATH_SYM_RE.search(text) or len(_words(text)) <= 4):
        return "equation"
    if CAPTION_RE.match(text):
        return "caption"
    if DOI_RE.search(text) and n < 400 and not CITE_RE.search(text[:60]):
        # DOI/isolated citation string
        pass
    if REF_START_RE.match(text) and (DOI_RE.search(text) or ARXIV_RE.search(text) or re.search(r"\d{4}[a-z]?\.", text[-200:])):
        return "reference"
    if HEADER_FOOT_RE.search(text) and n < 250 and (EMAIL_RE.search(text) or n < 120) and page == 1:
        return "pageheader"
    if page == 1 and bbox and block.get("height") and bbox[1] < 0.2 * block["height"] and HEADER_FOOT_RE.search(text) and n < 400:
        return "pageheader"  # arXiv / license banner at top of first page
    # Title / headings by font
    if HEADING_KEYWORDS.match(text.strip()) and n < 60:
        return "heading"
    if size >= 1.25 * ctx.get("body_size", 10) and bold >= 0.5 and n < 400:
        return "heading"
    if size >= 1.15 * ctx.get("body_size", 10) and n < 80 and not text.endswith((".", ",", ";", ":")) and _words(text) and _words(text)[0][0].isupper():
        return "heading"
    if bold >= 0.8 and 20 <= n <= 200 and not text.endswith((".", ",", ";")):
        return "heading"
    if _upper_ratio(text) >= UPPER_RATIO_MIN and 10 <= n <= 200:
        return "heading"
    if LIST_RE.match(text) or text.startswith(("\u2022", "\u25aa", "\u2013")):
        return "list"
    if size < 0.9 * ctx.get("body_size", 10) and n < 600 and bbox and block.get("height") and bbox[1] > 0.6 * block["height"]:
        return "footnote"
    if bbox and block.get("height") and bbox[1] > 0.85 * block["height"] and n < 800:
        return "footnote"
    if RELATION_RE.search(text) or SUBSCRIPT_RE.search(text):
        return "body"  # body with math — still body, marked by flag
    return "body"


def _estimate_body_size(blocks: list[dict[str, Any]]) -> float:
    sizes = [b["size"] for b in blocks if b.get("size") and b["nchars"] > 80]
    if not sizes:
        sizes = [b["size"] for b in blocks if b.get("size")]
    if not sizes:
        return 10.0
    # mode with 0.5 bin
    from collections import Counter

    c = Counter(round(s * 2) / 2 for s in sizes)
    return float(c.most_common(1)[0][0])


# ---------------------------------------------------------------------------------------------
# Paragraph merging (PyMuPDF gives line-level or fragment-level blocks)
# ---------------------------------------------------------------------------------------------
def _same_column(a: dict, b: dict, W: float) -> bool:
    """Blocks share a column if x-centers are on the same side of the page midline, or overlap horizontally ≥ 60%."""
    ax0, ay0, ax1, ay1 = a["bbox"]
    bx0, by0, bx1, by1 = b["bbox"]
    ov = max(0, min(ax1, bx1) - max(ax0, bx0))
    wa, wb = ax1 - ax0, bx1 - bx0
    if wa > 0 and wb > 0 and ov / min(wa, wb) >= 0.6:
        return True
    mid = W / 2
    return (ax1 <= mid + 15 and bx1 <= mid + 15) or (ax0 >= mid - 15 and bx0 >= mid - 15)


def _should_merge(a: dict, b: dict, W: float, body_size: float, line_h: float) -> bool:
    if not a.get("bbox") or not b.get("bbox"):
        return False
    if not _same_column(a, b, W):
        return False
    if b["bbox"][1] < a["bbox"][3] - 2:          # not below → different column flow
        return False
    gap = b["bbox"][1] - a["bbox"][3]
    if gap > 1.2 * line_h:                        # blank line = paragraph break
        return False
    sa, sb = a.get("size") or body_size, b.get("size") or body_size
    if abs(sa - sb) > 0.6:
        return False
    ta = _merge_lines(a["lines"])
    tb = _merge_lines(b["lines"])
    # don't merge across role boundaries: caption, heading-ish (bold), list start, equation, numbered sub-heading
    if CAPTION_RE.match(tb) or CAPTION_RE.match(ta):
        return False
    if b.get("bold", 0) > 0.6 and b["nchars"] < 120:
        return False
    if re.match(r"^\d+(?:\.\d+)+\s+[A-Z]", tb) and b.get("bold", 0) >= 0.25 and len(tb) < 120:
        return False
    if HEADING_KEYWORDS.match(tb.strip()) and len(tb) < 80:
        return False
    if LIST_RE.match(tb) or LIST_RE.match(ta):
        return False
    if EQUATION_HINT_RE.search(tb) and len(_words(tb)) <= 4:
        return False
    if _upper_ratio(tb) >= UPPER_RATIO_MIN and 10 <= len(tb) <= 120:
        return False
    # indent-start (new paragraph starts with indented x0) — compare left edges
    if b["bbox"][0] - a["bbox"][0] > 6 and b["bbox"][0] > a["bbox"][0] and len(tb) > 40:
        return False
    # short previous line (< 55% of block width) = paragraph ended
    if a.get("_short_last") and not ta.endswith(("-", ",")):
        return False
    return True


def _merge_fragments(raw: list[dict], W: float, body_size: float) -> list[dict]:
    """Merge consecutive line/fragment blocks in the same column into paragraphs (geometry-aware blocks only)."""
    geo = [b for b in raw if b.get("bbox")]
    if not geo:
        return raw
    hs = [b["bbox"][3] - b["bbox"][1] for b in geo if len(b["lines"]) == 1]
    line_h = statistics.median(hs) if hs else 12.0
    # mark blocks whose last line is short relative to column width
    for b in raw:
        if len(b["lines"]) >= 1 and b.get("bbox"):
            # estimate char width from the block itself
            est = b["bbox"][2] - b["bbox"][0]
            last = b["lines"][-1]
            b["_short_last"] = False
    merged: list[dict] = []
    for b in raw:
        b = dict(b)
        b["_short_last"] = False
        if merged and _should_merge(merged[-1], b, W, body_size, line_h):
            a = merged[-1]
            a["lines"] = a["lines"] + b["lines"]
            a["bbox"] = [min(a["bbox"][0], b["bbox"][0]), a["bbox"][1], max(a["bbox"][2], b["bbox"][2]), b["bbox"][3]]
            a["nchars"] += b["nchars"]
            # weighted averages for font hints
            na, nb = len(" ".join(a["lines"])), b["nchars"]
            for k in ("size", "bold", "italic", "mono"):
                if a.get(k) is not None and b.get(k) is not None:
                    a[k] = round((a[k] * na + b[k] * nb) / (na + nb), 2)
        else:
            merged.append(b)
    return merged


def _detect_line_height(raw: list[dict]) -> float:
    hs = [b["bbox"][3] - b["bbox"][1] for b in raw if b.get("bbox") and len(b["lines"]) == 1]
    return statistics.median(hs) if hs else 12.0


SUBHEAD_RE = re.compile(r"^(\d+(?:\.\d+)+\s+[A-Z][^\n]{2,70}?)(?=\s+[A-Z][a-z]|\s+[A-Z]{2,}\b|$)")
NUM_ONLY_RE = re.compile(r"^\d+(?:\.\d+)+\.?$")


def _split_leading_subheading(page: list[dict]) -> list[dict]:
    """A merged paragraph starting with a numbered sub-heading ('3.2.3' / 'Applications of Attention …' or
    '3.5 Positional Encoding Since …') is split into a heading block + body block."""
    out = []
    for b in page:
        lines = b.get("lines") or []
        if b.get("bbox") and len(lines) >= 2 and b["nchars"] > 20:
            l0 = lines[0].strip()
            l1 = lines[1].strip()
            consumed = 1
            if NUM_ONLY_RE.match(l0) and re.match(r"^[A-Z]", l1):
                l1_is_title = 3 <= len(l1) <= 90 and not l1.endswith((".", ";", ":")) and not re.search(r"[.:;]\s+[a-z]", l1)
                if l1_is_title:
                    # number on its own line: the whole next line is the title (never split inside it)
                    head_txt = (l0 + " " + l1).strip()
                    rest_first = ""
                    consumed = 2
                    # two-line title: following short, unpunctuated, Capitalized line
                    if (len(lines) >= 4 and 4 <= len(lines[2].strip()) <= 50 and not lines[2].strip().endswith("-")
                            and len(re.findall(r"[A-Za-z]+", lines[2])) <= 6
                            and re.match(r"^[A-Z][a-z]", lines[2].strip())
                            and not lines[2].strip().endswith((".", ",", ";", ":"))
                            and not re.search(r"[.:;]\s+[a-z]", lines[2])):
                        head_txt = head_txt + " " + lines[2].strip()
                        consumed = 3
                else:
                    # number line + body line: try to cut the inline title at the first sentence start
                    joined = l0 + " " + l1
                    m2 = SUBHEAD_RE.match(joined)
                    if m2 and len(m2.group(1)) <= 90 and len(joined) > len(m2.group(1)):
                        head_txt = m2.group(1).strip()
                        rest_first = joined[m2.end():].strip()
                        consumed = 2
                    else:
                        out.append(b)
                        continue
            else:
                m = SUBHEAD_RE.match(l0)
                if not (m and len(m.group(1)) <= 90 and len(l0) > len(m.group(1))):
                    out.append(b)
                    continue
                head_txt = m.group(1).strip()
                rest_first = l0[m.end():].strip()
            head = dict(b)
            head["lines"] = [head_txt]
            head["nchars"] = len(head_txt)
            head["bbox"] = [b["bbox"][0], b["bbox"][1], b["bbox"][2], b["bbox"][1] + (b["bbox"][3] - b["bbox"][1]) * consumed / max(1, len(lines))]
            head["bold"] = 1.0
            body = dict(b)
            body["lines"] = ([rest_first] if rest_first else []) + lines[consumed:]
            body["nchars"] = sum(len(x) for x in body["lines"])
            body["bbox"] = [b["bbox"][0], head["bbox"][3], b["bbox"][2], b["bbox"][3]]
            out.append(head)
            if body["nchars"] > 0:
                out.append(body)
            continue
        out.append(b)
    return out


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------
HEADING_KEYWORDS = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?(?:Abstract|Introduction|Related Work|Background|Methods?|Materials and Methods|"
    r"Methodology|Experiments?|Experimental Setup|Results(?: and Discussion)?|Discussion|Conclusions?|"
    r"Acknowledg(e)?ments?|References|Bibliography|Supplementary(?: Material| Information)?|Appendix|"
    r"Limitations|Data Availability|Author Contributions?|Conflict of Interest|Declaration|Funding|"
    r"Theoretical Background|Model|Architecture|Training|Inference|Evaluation|Ablation Stud(?:y|ies)|"
    r"Analysis|Implementation Details?|Future Work|Keywords)\b\.?\s*$", re.I)
AUTHOR_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\b(?:University|Institute|Research|Laborator|Department|Dept\.|College|School of|Inc\.|Corp\.|GmbH|Academy|Centre|Center)\b")
SECTION_REF_ROLES = ("title", "heading")
NAME_LINE_RE = re.compile(r"^(?:[A-Z][\w.'’\-]+(?:\s+[A-Z][\w.'’\-]+){1,3}(?:\s*[∗†‡§¶\d]{1,3})?\s*,?\s*){2,}$")
_FUNC_WORDS = set("""the a an of in on at to for from with without by as is are was were be been being this that these those
it its and or but we our their there which who whom what when where why how not no can could may might must shall should
will would has have had do does did using used use based via per also both each into onto over under between among within
during after before while until since about against more most less least very much many few some any all other another""".split())


def _page_geometry(raw: list[dict]) -> tuple[float, float]:
    W = next((b["width"] for b in raw if b.get("width")), 612.0)
    H = next((b["height"] for b in raw if b.get("height")), 792.0)
    return W, H


def parse_pdf(pdf: Path, backend: str = "auto", max_pages: int | None = None,
              ocr_dir: Path | None = None) -> dict[str, Any]:
    backend_err: dict[str, str] = {}
    order = ["pymupdf", "pypdf", "pdftotext"] if backend == "auto" else [backend]
    pages_raw = None
    used = None
    for be in order:
        try:
            if be == "pymupdf":
                pages_raw = _parse_pymupdf(pdf, max_pages)
            elif be == "pypdf":
                pages_raw = _parse_pypdf(pdf, max_pages)
            else:
                pages_raw = _parse_pdftotext(pdf, max_pages)
            used = be
            break
        except Exception as e:  # noqa: BLE001
            backend_err[be] = f"{type(e).__name__}: {e}"
    if pages_raw is None:
        raise RuntimeError("No PDF backend available: " + json.dumps(backend_err, ensure_ascii=False))

    ocr_used: list[int] = []
    if ocr_dir and Path(ocr_dir).is_dir():
        # OCR text files P{n}.txt (or page-{n}.txt) override pages that have no/little text layer
        for f in sorted(Path(ocr_dir).glob("*.txt")):
            m = re.search(r"(\d+)", f.stem)
            if not m:
                continue
            pno = int(m.group(1)) - 1
            if 0 <= pno < len(pages_raw):
                text = f.read_text(encoding="utf-8-sig", errors="replace")
                if not text.strip():
                    continue
                cur_chars = sum(b["nchars"] for b in pages_raw[pno])
                if cur_chars >= 200:
                    continue  # page already has a text layer; keep layout-aware parse
                blocks = []
                for para in re.split(r"\n\s*\n", text):
                    lines = [ln for ln in para.splitlines() if ln.strip()]
                    if not lines:
                        continue
                    blocks.append({"page": pno + 1, "bbox": None, "width": None, "height": None, "lines": lines,
                                   "size": None, "bold": None, "italic": None, "mono": None,
                                   "nchars": sum(len(x) for x in lines)})
                if blocks:
                    pages_raw[pno] = blocks
                    ocr_used.append(pno + 1)

    all_blocks = [b for p in pages_raw for b in p]
    body_size = _estimate_body_size(all_blocks) if used == "pymupdf" else 10.0
    ctx = {"body_size": body_size}

    # merge line-level fragments into paragraphs (PyMuPDF only; pypdf/pdftotext already give paragraphs)
    if used == "pymupdf":
        pages_raw = [_merge_fragments(p, W, body_size) for p in pages_raw for W, H in [_page_geometry(p)]]
        pages_raw = [_split_leading_subheading(p) for p in pages_raw]
    all_blocks = [b for p in pages_raw for b in p]
    body_size = _estimate_body_size(all_blocks) if used == "pymupdf" else 10.0
    ctx = {"body_size": body_size}

    doc_pages = []
    for pno, raw in enumerate(pages_raw):
        W, H = _page_geometry(raw)
        # Column detection: body blocks on a page clustering into 2 x-ranges
        x0s = sorted(b["bbox"][0] for b in raw if b.get("bbox") and b["nchars"] > 100)
        two_col = False
        if x0s:
            mid = (min(x0s) + max(x0s)) / 2
            left = [x for x in x0s if x < mid - 20]
            right = [x for x in x0s if x > mid + 20]
            two_col = bool(left and right and len(left) >= 2 and len(right) >= 2)

        def key(b):
            bb = b["bbox"] or [0, 0, 0, 0]
            if two_col and bb[2] > W / 2 + 15 and bb[0] > W / 2 - 40 and b["nchars"] > 40:
                return (1, bb[1])
            return (0, bb[1])

        blocks = []
        for b in sorted(raw, key=key):
            text = _merge_lines(b["lines"])
            if not text:
                continue
            role = classify(b, ctx)
            bid = f"P{b['page']:02d}B{len(blocks)+1:02d}"
            blocks.append({
                "id": bid,
                "page": b["page"],
                "bbox": b["bbox"],
                "n_chars": b["nchars"],
                "size": b.get("size"),
                "bold": b.get("bold"),
                "italic": b.get("italic"),
                "mono": b.get("mono"),
                "role": role,
                "text": text,
                "flags": {
                    "math": bool(RELATION_RE.search(text) or MATH_SYM_RE.search(text) or SUBSCRIPT_RE.search(text)),
                    "citations": len(CITE_RE.findall(text)),
                    "digits": len(_digits(text)),
                    "caption_label": bool(CAPTION_RE.match(text)),
                },
            })
        doc_pages.append({"page": pno + 1, "width": W, "height": H,
                          "two_column": two_col, "blocks": blocks})

    # ---- Title: largest-size short block on page 1 above the first body text
    first = doc_pages[0]["blocks"] if doc_pages else []
    title = None
    cands = [b for b in first if b.get("size") and b["size"] >= 1.2 * body_size and 15 <= b["n_chars"] <= 300
             and b["role"] not in ("pageheader", "pagefooter")]
    if cands:
        title = max(cands, key=lambda b: (b["size"], -b["bbox"][1]))
        title["role"] = "title"
    elif first:
        # no font geometry (pypdf/pdftotext): title = first short block before the first heading that is not a banner
        for b in first[:6]:
            t = b["text"].strip()
            if (b["role"] in ("pageheader", "pagefooter") or HEADER_FOOT_RE.search(t) or b["n_chars"] > 300
                    or AUTHOR_RE.search(t) or "\n" in t):
                continue
            if 15 <= b["n_chars"] <= 300:
                b["role"] = "title"
                title = b
                break
        if title is None:
            for b in first[:3]:
                if b["n_chars"] > 20 and b["role"] not in ("pageheader", "pagefooter"):
                    b["role"] = "title"
                    title = b
                    break

    # ---- Title continuation line(s): same size, directly below, short, no terminal period (multi-line titles)
    if title is not None and title.get("size"):
        for b in first:
            if b is title or b["role"] in ("pageheader", "pagefooter"):
                continue
            if (b.get("size") and abs(b["size"] - title["size"]) < 0.6
                    and 0 <= b["bbox"][1] - title["bbox"][3] < 1.6 * title["size"]
                    and b["n_chars"] < 200 and not b["text"].rstrip().endswith((".", "?", "!"))):
                title["text"] = title["text"].rstrip().rstrip(",") + " " + b["text"].strip()
                title["n_chars"] = len(title["text"])
                title["bbox"] = [min(title["bbox"][0], b["bbox"][0]), title["bbox"][1],
                                 max(title["bbox"][2], b["bbox"][2]), b["bbox"][3]]
                b["role"] = "boilerplate"  # merged away
                break  # at most one continuation line (covers 2-line titles; 3-line titles rare)

    # ---- Authors / affiliations on page 1: blocks between title and first heading/abstract that look like names
    if first:
        seen_title = False
        for b in first:
            if b is title:
                seen_title = True
                continue
            if not seen_title or b["role"] in ("pageheader", "pagefooter", "heading", "title", "boilerplate"):
                continue
            t = b["text"].strip()
            t1 = re.sub(r"\s+", " ", t)
            FUNC_RATIO = 0.35
            words = re.findall(r"[A-Za-z]+", t)
            func = sum(1 for w in words if w.lower() in _FUNC_WORDS)
            looks_author = (
                (AUTHOR_RE.search(t) and not t.endswith((".", "?", "!")))       # emails / institutions
                or (bool(NAME_LINE_RE.match(t1)) and len(t1) <= 120
                    and not re.search(r"\b(?:Is|Are|Was|The|Of|And|For|To|In|On|With|By|A|An)\b", t1))  # "Jacob Devlin Ming-Wei Chang ..."
                or (b.get("bbox") and title.get("bbox") and b["bbox"][1] < title["bbox"][3] + 0.22 * (doc_pages[0].get("height") or 792) and not t.endswith((".", "?", "!", ":"))
                    and b["n_chars"] < 300 and words and func / len(words) <= FUNC_RATIO
                    and sum(1 for w in re.findall(r"\b[A-Z][\w.'’\-]+", t)) >= 2)
            )
            if looks_author:
                b["role"] = "author"
                continue
            if HEADING_KEYWORDS.match(t):
                b["role"] = "heading"
                break
            if b["n_chars"] > 400:
                break

    # ---- Headings by keyword (e.g. "3.2 Applications") on all pages; mark "Abstract" paragraph
    for p in doc_pages:
        for b in p["blocks"]:
            if b["role"] in ("pageheader", "pagefooter", "caption", "reference", "equation"):
                continue
            t = b["text"].strip()
            if HEADING_KEYWORDS.match(t) and b["n_chars"] < 60:
                b["role"] = "heading"
            elif t.startswith("Abstract") and b["n_chars"] > 60 and b["page"] == 1:
                b["role"] = "abstract"

    # ---- Table grids: rows of ≥3 short blocks side by side (same y-band, different x) on ≥3 rows → role "table"
    for p in doc_pages:
        shorts = [b for b in p["blocks"] if b["role"] in ("body", "list") and 0 < b["n_chars"] <= 60 and b["bbox"]]
        if len(shorts) >= 9:
            rows: dict[int, list] = {}
            for b in shorts:
                rows.setdefault(round(b["bbox"][1] / 6), []).append(b)   # 6pt y-bands
            grid_rows = [r for r in rows.values() if len({round(b["bbox"][0] / 15) for b in r}) >= 3
                         and max(b["n_chars"] for b in r) <= 40]
            if len(grid_rows) >= 3:
                cell_ids = {b["id"] for r in grid_rows for b in r}
                for b in shorts:
                    if b["id"] in cell_ids:
                        b["role"] = "table"
                        b["flags"]["table_cell"] = True

    # ---- Reference section: everything after the "References" heading is reference material
    in_refs = False
    for p in doc_pages:
        for b in p["blocks"]:
            if b["role"] == "heading" and re.match(r"^(?:\d+\.?\s+)?References?\s*$", b["text"], re.I):
                in_refs = True
                continue
            if b["role"] == "heading" and in_refs and not re.match(r"^(?:\d+\.?\s+)?References?\s*$", b["text"], re.I):
                in_refs = False  # e.g. "Appendix" after references
            if in_refs and b["role"] not in ("pageheader", "pagefooter", "heading"):
                b["role"] = "reference"

    n_blocks = sum(len(p["blocks"]) for p in doc_pages)
    empty_pages = [p["page"] for p in doc_pages if not p["blocks"]]
    warnings: list[str] = []
    if empty_pages:
        warnings.append(f"text layer missing/empty on pages {empty_pages} (OCR needed)")
    low_text = [p["page"] for p in doc_pages if sum(b["n_chars"] for b in p["blocks"]) < 200 and p["blocks"]]
    if low_text:
        warnings.append(f"very little extractable text on pages {low_text} (scanned/figure-heavy?)")
    if used != "pymupdf":
        warnings.append(f"layout analysis degraded: backend={used} (no font/position info)")
    if ocr_used:
        warnings.append(f"OCR text substituted for pages without text layer: {ocr_used} (no layout/font info on these pages)")
    return {
        "source": str(pdf),
        "backend": used,
        "backend_errors": backend_err,
        "n_pages": len(doc_pages),
        "body_size": body_size,
        "n_blocks": n_blocks,
        "title": title["text"] if title else None,
        "empty_pages": empty_pages,
        "ocr_pages": ocr_used,
        "warnings": warnings,
        "pages": doc_pages,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="papertrans.parse", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", default="auto", choices=["auto", "pymupdf", "pypdf", "pdftotext"])
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--ocr-dir", default=None, help="dir with P{n}.txt OCR text to substitute for text-less pages")
    a = ap.parse_args(argv)
    doc = parse_pdf(Path(a.pdf), a.backend, a.max_pages, Path(a.ocr_dir) if a.ocr_dir else None)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[parse] backend={doc['backend']} pages={doc['n_pages']} blocks={doc['n_blocks']} "
          f"empty_pages={doc['empty_pages'] or 'none'} → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
