#!/usr/bin/env python3
"""pdf_extract.py — deterministic PDF → structured skeleton JSON.

Stage 1 of the pipeline. No LLM involved. Produces a skeleton that the
agent later fills in (summaries, knowledge points) using section text
that is already chunked, page-anchored and reading-order corrected.

Usage:
    python pdf_extract.py INPUT.pdf OUT_DIR [--ocr-lang eng] [--max-pages N]

Outputs (under OUT_DIR):
    skeleton.json   full machine skeleton (sections, blocks, figures, tables)
    sections.md     one markdown block per section (for the agent to read)
    extract_report.json  run status, method used, anomalies, stats

Design notes
------------
* Heading source priority: PDF outline/bookmarks → font-size heuristic →
  numbered-heading regex → single-section fallback. The method actually
  used is recorded in extract_report.json.
* Two-column reading order: text blocks are sorted column-major using the
  page's dominant column layout (detected per page from block x-positions).
* Anchors: every block gets an anchor id `p{page}:{block}` (1-based page,
  block index in reading order). The agent references these ids; the
  verifier checks they exist and that quoted text is inside them.
* Scanned / encrypted / no-text PDFs are detected, reported, and routed:
  encryption → fail with a clear reason (needs password); no text layer →
  optional OCR via pytesseract if available, otherwise report OCR_REQUIRED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass, field, asdict
from typing import Any

try:
    import pymupdf  # PyMuPDF >= 1.24 exposes `pymupdf`; older `fitz`
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        pymupdf = None  # type: ignore

# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Block:
    bid: str                 # anchor id, e.g. p3:b12
    page: int               # 1-based
    idx: int                # index within page (reading order)
    kind: str               # heading | paragraph | caption | list | equation | table | other
    text: str
    bbox: list[float] = field(default_factory=list)
    font_size: float = 0.0
    font: str = ""
    bold: bool = False
    section_path: list[str] = field(default_factory=list)  # e.g. ["3", "3.2"]
    column: int = 0

@dataclass
class Section:
    sid: str                # section id, e.g. "s3.2" or "s0" for preamble
    number: str             # "3.2" or "" for unnumbered
    title: str
    level: int
    anchor: str             # heading block id
    page_start: int
    page_end: int
    block_ids: list[str] = field(default_factory=list)
    parent: str = ""

@dataclass
class Figure:
    fid: str
    kind: str               # figure | table
    number: str             # "1", "2a", "" if unknown
    caption: str
    anchor: str
    page: int

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

NUM_HEADING = re.compile(
    r"^\s*(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(?P<title>[A-Z\u4e00-\u9fff][^\n]{1,80})\s*$"
)
ROMAN = re.compile(r"^\s*((?:X{0,3})?(?:IX|IV|V?I{1,3})|[IVX]+)\.?\s+[A-Z][^\n]{1,80}$")
CN_HEADING = re.compile(r"^\s*(?:[一二三四五六七八九十]+[、.．]|第[一二三四五六七八九十]+[章节部分])\s*([^\n]{1,60})$")
CAPTION_RE = re.compile(r"^\s*(Figure|Fig\.|Table|Tab\.|图|表|Eq\.|Equation)\s*([0-9A-Za-z]+(?:\.[0-9]+)?[a-z]?)\s*[:.|．]?\s*(.*)$", re.I)
ABSTRACT_RE = re.compile(r"^\s*(abstract|summary|摘\s*要|提要)\b", re.I)
REFERENCES_RE = re.compile(r"^\s*(references|bibliography|参考文献|literature cited|works cited)\b", re.I)
ACK_RE = re.compile(r"^\s*(acknowledg(e)?ments?|致\s*谢|acknowledgements?)\b", re.I)
APPENDIX_RE = re.compile(r"^\s*(appendix|supplementary (material|information)|附录|补充材料)\b", re.I)
FRONT_KEYS = ("abstract", "introduction", "摘 要", "摘要", "1. introduction", "1 introduction")

# Section kinds
K_HEAD, K_PARA, K_CAPTION, K_LIST, K_EQ, K_TABLE, K_OTHER = "heading paragraph caption list equation table other".split()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _is_numbered_title(text: str) -> tuple[str, str, int] | None:
    """Return (number, title, level) if text looks like a numbered heading."""
    m = NUM_HEADING.match(text)
    if m and len(text) <= 90:
        num = m.group("num")
        title = _norm(m.group("title"))
        # avoid mistaking '1.5 GHz ...' measurements: a short decimal number glued to a unit
        if num and "." in num and re.match(r"^\d+\.\d$", num) and re.match(r"^\s*\d+\.\d\s*(GHz|MHz|kHz|Hz|nm|mm|cm|kg|mL|dl|kV|MeV|keV|eV|ns|ms|min|ppm|wt|%)\b", text):
            return None
        level = num.count(".") + 1
        return num, title, level
    return None


# --------------------------------------------------------------------------- #
# Layout detection
# --------------------------------------------------------------------------- #

def _detect_columns(page_blocks: list[dict], page_width: float) -> int:
    """Estimate column count from block x-centers (1, 2, or 3)."""
    xs = []
    for b in page_blocks:
        if b["type"] != 0:
            continue
        w = b["bbox"][2] - b["bbox"][0]
        if w < page_width * 0.35:  # narrow block, likely column-constrained
            xs.append((b["bbox"][0] + b["bbox"][2]) / 2)
    if len(xs) < 4:
        return 1
    xs.sort()
    gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
    gaps.sort(reverse=True)
    big = [g for g in gaps if g[0] > page_width * 0.15]
    if not big:
        return 1
    ncols = min(3, len(big) + 1)
    return ncols


def _column_of(x0: float, x1: float, ncols: int, page_width: float) -> int:
    if ncols <= 1:
        return 0
    center = (x0 + x1) / 2
    span = x1 - x0
    if span > page_width * 0.6:  # spanning block (title, wide figure)
        return -1  # full width; sort first in its band
    return min(ncols - 1, int(center // (page_width / ncols)))


def _reading_order(blocks: list[Block], ncols: int) -> list[Block]:
    """Column-major order with full-width blocks (col -1) acting as band separators."""
    if ncols <= 1:
        return sorted(blocks, key=lambda b: (b.bbox[1] if b.bbox else 0, b.bbox[0] if b.bbox else 0))
    # group by vertical bands separated by full-width blocks
    bands: list[list[Block]] = [[]]
    for b in sorted(blocks, key=lambda b: b.bbox[1] if b.bbox else 0):
        if b.column == -1:
            bands.append([b])
            bands.append([])
        else:
            bands[-1].append(b)
    out: list[Block] = []
    for band in bands:
        if not band:
            continue
        if band[0].column == -1:
            out.extend(band)
        else:
            out.extend(sorted(band, key=lambda b: (b.column, b.bbox[1], b.bbox[0])))
    return out


# --------------------------------------------------------------------------- #
# Page text extraction
# --------------------------------------------------------------------------- #

def _blocks_from_page(doc, pno: int, col_hint: int | None) -> tuple[list[Block], int, list[dict]]:
    page = doc[pno]
    pw = page.rect.width
    raw = page.get_text("dict")
    items: list[dict] = []
    for b in raw["blocks"]:
        if b["type"] != 0:
            continue
        lines_out = []
        sizes: list[float] = []
        fonts: list[str] = []
        bold = False
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            txt = "".join(s["text"] for s in l["spans"])
            lines_out.append((txt, l["bbox"]))
            for s in spans:
                sizes.append(s["size"])
                fonts.append(s["font"])
                if "bold" in s["font"].lower() or (s["flags"] & 16):
                    bold = True
        if not lines_out:
            continue
        text = _join_lines(lines_out)
        items.append({
            "bbox": list(b["bbox"]),
            "text": text,
            "size": statistics.median(sizes) if sizes else 0.0,
            "font": statistics.mode(fonts) if fonts else "",
            "bold": bold,
        })
    ncols = col_hint if col_hint else _detect_columns(raw["blocks"], pw)
    blocks: list[Block] = []
    for i, it in enumerate(items):
        blocks.append(Block(
            bid=f"p{pno + 1}:b{i}", page=pno + 1, idx=i, kind=K_OTHER, text=it["text"],
            bbox=it["bbox"], font_size=it["size"], font=it["font"], bold=it["bold"],
            column=_column_of(it["bbox"][0], it["bbox"][2], ncols, pw),
        ))
    ordered = _reading_order(blocks, ncols)
    for i, b in enumerate(ordered):
        b.idx = i
        b.bid = f"p{pno + 1}:b{i}"
    images = page.get_image_info() if hasattr(page, "get_image_info") else []
    drawings = page.get_drawings() if hasattr(page, "get_drawings") else []
    fig_info = [{"bbox": list(im["bbox"]) if "bbox" in im else None, "w": im.get("width"), "h": im.get("height")} for im in images]
    return ordered, ncols, {"images": fig_info, "n_drawings": len(drawings)}


def _join_lines(lines: list[tuple[str, list[float]]]) -> str:
    """Join lines: de-hyphenate line breaks, keep paragraph text flowing."""
    out = ""
    for txt, bb in lines:
        if out.endswith("-") and not out.endswith(" -") and re.search(r"[a-z]-$", out) and txt[:1].islower():
            out = out[:-1] + txt
        elif not out:
            out = txt
        elif out.endswith(("-", "\u2010")):
            out = out + txt
        else:
            out = out + " " + txt
    return _norm(out)


# --------------------------------------------------------------------------- #
# Heading detection
# --------------------------------------------------------------------------- #

def _outline_sections(doc) -> list[dict]:
    """Use the PDF outline (bookmarks) if present and non-trivial."""
    try:
        toc = doc.get_toc(simple=True)
    except Exception:
        return []
    if not toc or len(toc) < 3:
        return []
    return [{"level": l, "title": _norm(t), "page": p} for l, t, p in toc]


def _body_font_size(blocks: list[Block]) -> float:
    sizes = [b.font_size for b in blocks if b.kind == K_OTHER and len(b.text) > 60]
    return statistics.median(sizes) if sizes else 10.0


def _heuristic_headings(blocks: list[Block], body: float) -> list[tuple[Block, str, str, int]]:
    """Font-size + pattern heading detection. Returns (block, number, title, level)."""
    found = []
    page1_sizes = [b.font_size for b in blocks if b.page == 1]
    page1_max = max(page1_sizes, default=0)
    for b in blocks:
        t = b.text.strip()
        if len(t) > 110 or "\n" in t and len(t) > 60:
            continue
        # the document title on page 1 is not a section: the largest genuine title
        # text above the abstract (watermarks/running heads are excluded)
        if b.page == 1 and page1_max > body + 3 and not _is_numbered_title(t):
            if re.search(r"arXiv|preprint|doi|©|copyright|vol\.|no\.\s*\d", t, re.I):
                continue
            if b.font_size >= body + 3:
                continue
        num = title = None
        level = 1
        mh = _is_numbered_title(t)
        if mh:
            num, title, level = mh
        elif ROMAN.match(t) and b.font_size >= body + 0.5:
            num, title = _norm(t.split(".")[0]).strip(), _norm(t.split(".", 1)[1]) if "." in t else t
        elif CN_HEADING.match(t):
            num = re.match(r"^\s*([^ ]+?)[\s、.．]", t).group(1)
            title = CN_HEADING.match(t).group(1).strip()
        elif b.font_size >= body + 1.5 and b.bold and len(t) <= 80 and t[:1].isupper():
            num, title = "", t
        elif b.font_size >= body + 2.5 and len(t) <= 60 and not t.endswith((".", ",", ";", ":")) and not CAPTION_RE.match(t):
            num, title = "", t
        elif b.bold and len(t) <= 60 and (REFERENCES_RE.match(t) or ACK_RE.match(t) or APPENDIX_RE.match(t) or ABSTRACT_RE.match(t)):
            num, title = "", t
        else:
            continue
        # reject captions / footers / running heads
        if CAPTION_RE.match(t) or re.match(r"^\d{1,4}$", t) or "arXiv" in t or re.search(r"(preprint|proceedings|conference|journal|vol\.|pp\.)", t, re.I) and len(t) < 90:
            continue
        if title:
            found.append((b, num or "", title, level))
    return found


NUM_PREFIX = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){1,3})\s*$")


def _find_number_prefix(target: Block, cands: list[Block]) -> str:
    """Some PDFs emit the section number as a separate bold block right before
    the title text ('3.2.1' + 'Scaled Dot-Product Attention'). Return it."""
    tx0, ty0 = target.bbox[0], target.bbox[1]
    for b in cands:
        m = NUM_PREFIX.match(b.text)
        if not m:
            continue
        same_line = abs(b.bbox[1] - ty0) < 6 and 0 <= (tx0 - b.bbox[2]) < 60
        just_before = 0 <= ty0 - b.bbox[3] < 14 and abs(b.bbox[0] - tx0) < 40
        if same_line or just_before:
            return m.group(1)
    return ""


def _map_outline_to_blocks(outline: list[dict], blocks_by_page: dict[int, list[Block]]) -> list[tuple[Block, str, str, int]]:
    """Match outline titles to the heading block on the target page (or next page).

    Numbering: prefer the number printed in the PDF (inline or as a separate
    prefix block); otherwise derive it from the outline hierarchy so sibling
    ids stay consistent (3.1, 3.2, ... at level 2 under '3').
    """
    out = []
    used: set[str] = set()
    counters: dict[int, int] = {}
    for e in outline:
        cands = [b for b in blocks_by_page.get(e["page"], []) + blocks_by_page.get(e["page"] + 1, []) if b.bid not in used]
        if not cands:
            cands = blocks_by_page.get(e["page"], []) + blocks_by_page.get(e["page"] + 1, [])
        if not cands:
            continue
        key = re.sub(r"^\s*[\d.]+\s*", "", e["title"].lower()).strip()
        best, best_score = None, 0.0
        for b in cands:
            t = re.sub(r"^\s*\d{1,2}(?:\.\d{1,2}){0,3}\s+", "", b.text.lower()).strip()
            if not t:
                continue
            if key and (key in t or t in key):
                numbered = 0.15 if re.match(r"^\s*\d{1,2}(?:\.\d{1,2}){0,3}\s+", b.text) else 0.0
                short = 0.1 if len(t) <= len(key) + 8 else 0.0
                sc = len(key) / max(len(t), len(key)) + (0.25 if b.bold or b.font_size >= 11 else 0) + numbered + short
                if sc > best_score:
                    best, best_score = b, sc
        if best is None:
            k2 = key[:25]
            for b in cands:
                if k2 and k2 in b.text.lower():
                    best = b
                    break
        if best is None:
            continue
        used.add(best.bid)
        m = _is_numbered_title(best.text)
        if m:
            num, title = m[0], m[1]
        else:
            num = _find_number_prefix(best, cands)
            title = re.sub(r"^\s*\d{1,2}(?:\.\d{1,2}){1,3}\s+", "", best.text.strip())
        if not num:
            counters[e["level"]] = counters.get(e["level"], 0) + 1
            for deeper in [k for k in counters if k > e["level"]]:
                del counters[deeper]
            if e["level"] == 1:
                num = str(counters[1])
            else:
                parent_num = ".".join(str(counters.get(i, 1)) for i in range(1, e["level"]))
                num = f"{parent_num}.{counters[e['level']]}" if parent_num else str(counters[e["level"]])
        if not title or len(title) > 100:
            title = e["title"]
        out.append((best, num, title, e["level"]))
    return out


# --------------------------------------------------------------------------- #
# Main extraction
# --------------------------------------------------------------------------- #

def extract(pdf_path: str, ocr_lang: str = "eng", max_pages: int | None = None, force_ocr: bool = False) -> dict[str, Any]:
    if pymupdf is None:
        return {"status": "failed", "reason": "PyMuPDF not installed (pip install pymupdf)", "skeleton": None}
    report: dict[str, Any] = {"input": os.path.abspath(pdf_path), "anomalies": [], "warnings": []}
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:  # corrupted / not a PDF
        return {"status": "failed", "reason": f"cannot open PDF: {e}", "skeleton": None, "report": report}

    if doc.is_encrypted:
        try:
            ok = doc.authenticate("")
        except Exception:
            ok = False
        if not ok:
            report["anomalies"].append({"kind": "ENCRYPTED", "detail": "PDF is password protected; text cannot be extracted without the password."})
            return {"status": "refused", "reason": "encrypted PDF requires a password", "skeleton": None, "report": report}
        report["warnings"].append("PDF was encrypted with an empty user password; opened without a password.")

    n_pages = len(doc)
    if max_pages:
        n_pages = min(n_pages, max_pages)
    report["pages"] = n_pages
    report["total_pages_in_file"] = len(doc)
    report["metadata"] = {k: v for k, v in (doc.metadata or {}).items() if v}

    # ---- quick text-layer check on a sample of pages
    sample = range(0, len(doc), max(1, len(doc) // 8))
    chars = sum(len(doc[i].get_text().strip()) for i in sample)
    ocr_used = False
    if chars < 20 * len(list(sample)) or force_ocr:
        report["anomalies"].append({"kind": "NO_TEXT_LAYER", "detail": "Sampled pages contain almost no embedded text (scanned or image-only PDF)."})
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            import io
        except ImportError:
            report["anomalies"].append({"kind": "OCR_UNAVAILABLE", "detail": "pytesseract/Pillow not installed; OCR not possible in this environment."})
            return {"status": "refused", "reason": "no text layer and OCR unavailable", "skeleton": None, "report": report}
        # OCR path
        ocr_used = True
        for pno in range(n_pages):
            pix = doc[pno].get_pixmap(dpi=200)
            text = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang=ocr_lang)
            doc[pno].insert_text((50, 50), "", fontsize=1)  # no-op to keep page
            # store OCR text in a side structure
        report["ocr"] = {"used": True, "lang": ocr_lang}

    # ---- pass 1: blocks
    blocks_by_page: dict[int, list[Block]] = {}
    page_meta: dict[int, dict] = {}
    for pno in range(n_pages):
        if ocr_used:
            page = doc[pno]
            pix = page.get_pixmap(dpi=200)
            import pytesseract, io
            from PIL import Image
            text = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang=ocr_lang)
            paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
            bls = [Block(bid=f"p{pno + 1}:b{i}", page=pno + 1, idx=i, kind=K_OTHER, text=_norm(p)) for i, p in enumerate(paras)]
            blocks_by_page[pno + 1] = bls
            page_meta[pno + 1] = {"ncols": 1, "ocr": True}
            continue
        bls, ncols, meta = _blocks_from_page(doc, pno, None)
        blocks_by_page[pno + 1] = bls
        page_meta[pno + 1] = {"ncols": ncols, **meta}

    all_blocks = [b for p in sorted(blocks_by_page) for b in blocks_by_page[p]]
    if not all_blocks or sum(len(b.text) for b in all_blocks) < 200:
        report["anomalies"].append({"kind": "INSUFFICIENT_TEXT", "detail": f"Only {sum(len(b.text) for b in all_blocks)} characters extracted."})
        return {"status": "refused", "reason": "insufficient text extracted", "skeleton": None, "report": report}

    body = _body_font_size(all_blocks)
    report["body_font_size"] = round(body, 2)

    # ---- classify blocks
    for b in all_blocks:
        t = b.text.strip()
        if CAPTION_RE.match(t):
            b.kind = K_CAPTION
        elif re.search(r"(?<!\w)\(\d{1,3}\)\s*$", t) and len(t) < 400 and re.search(r"[=∑∫∂√±×÷≈≤≥]", t):
            b.kind = K_EQ
        elif re.match(r"^(\(?[a-z]\)|[•·\-–]|\d+\.)\s+", t) and len(t) < 600:
            b.kind = K_LIST
        # else paragraph (or heading later)
        if b.kind == K_OTHER:
            b.kind = K_PARA

    # ---- headings
    outline = _outline_sections(doc)
    heads: list[tuple[Block, str, str, int]] = []
    method = "none"
    if outline and not ocr_used:
        heads = _map_outline_to_blocks(outline, blocks_by_page)
        if heads:
            method = "outline"
    heuristic = _heuristic_headings(all_blocks, body) if not ocr_used else []
    if heads:
        # Outlines are often incomplete (missing References / Acknowledgements /
        # Appendix). Merge heuristic hits that are not already covered by an
        # outline-matched block (same page & overlapping bbox ⇒ same heading).
        covered = [(h[0].page, h[0].bbox) for h in heads]
        def _key(s: str) -> str:
            return re.sub(r"^[\d.\s]+", "", s.lower()).strip(" .:")
        outline_keys = {_key(h[2]) for h in heads}
        def _covered(b: Block) -> bool:
            k = _key(b.text)
            for p, bb in covered:
                if p != b.page:
                    continue
                if bb and b.bbox and not (b.bbox[2] < bb[0] or b.bbox[0] > bb[2] or b.bbox[3] < bb[1] or b.bbox[1] > bb[3]):
                    return True
            for ok in outline_keys:
                if ok and (ok in k or k in ok) and min(len(ok), len(k)) >= 6:
                    return True
            return False
        extra = [h for h in heuristic if not _covered(h[0]) and not any(h[0] is x[0] for x in heads)]
        if extra:
            method = "outline+font"
            heads = sorted(heads + extra, key=lambda h: (h[0].page, h[0].idx))
    else:
        heads = heuristic
        if heads:
            method = "font-size+pattern"
    if heads:
        for b, num, title, lvl in heads:
            b.kind = K_HEAD
    report["heading_method"] = method
    report["headings_found"] = len(heads)

    # ---- sections
    sections: list[Section] = []
    preamble_blocks = [b for b in all_blocks if b.page < (heads[0][0].page if heads else 1) or (heads and b is not heads[0][0] and (b.page, b.idx) < (heads[0][0].page, heads[0][0].idx))]
    sections.append(Section(sid="s0", number="", title="Preamble (title, authors, abstract)", level=0, anchor=preamble_blocks[0].bid if preamble_blocks else (heads[0][0].bid if heads else all_blocks[0].bid), page_start=1, page_end=(heads[0][0].page if heads else n_pages)))
    for i, (b, num, title, lvl) in enumerate(heads):
        sid = f"s{num}" if num else f"h{i + 1}"
        title_l = title.lower()
        if REFERENCES_RE.match(title_l) or title_l in ("references", "bibliography"):
            title_norm = "References"
        else:
            title_norm = title
        sections.append(Section(sid=sid, number=num, title=title_norm, level=lvl, anchor=b.bid, page_start=b.page, page_end=b.page))
    # assign blocks & page ranges
    sec_iter = iter(sections)
    cur = next(sec_iter)
    # map heading block -> section
    head_to_sec = {h[0].bid: s for h, s in zip(heads, sections[1:])}
    cur_sec = sections[0]
    for b in all_blocks:
        if b.bid in head_to_sec:
            cur_sec = head_to_sec[b.bid]
        cur_sec.block_ids.append(b.bid)
        cur_sec.page_end = max(cur_sec.page_end, b.page)
        b.section_path = ([cur_sec.number] if cur_sec.number else []) if cur_sec.sid != "s0" else []
    # parents
    for s in sections[1:]:
        if s.number and "." in s.number:
            parent_num = s.number.rsplit(".", 1)[0]
            for p in sections:
                if p.number == parent_num:
                    s.parent = p.sid
                    break
        else:
            s.parent = "s0"
    report["sections"] = len(sections) - 1

    # ---- figures & tables from captions
    figs: list[Figure] = []
    for b in all_blocks:
        m = CAPTION_RE.match(b.text.strip())
        if m:
            kw = m.group(1).lower()
            kind = "table" if kw.startswith(("tab", "表")) else "figure"
            figs.append(Figure(fid=f"{'T' if kind == 'table' else 'F'}{m.group(2)}", kind=kind, number=m.group(2), caption=b.text.strip(), anchor=b.bid, page=b.page))
    # dedup: extended captions (same number, consecutive) → keep first
    seen = {}
    for f in figs:
        seen.setdefault(f.fid, f)
    figs = list(seen.values())
    report["figures"] = sum(1 for f in figs if f.kind == "figure")
    report["tables"] = sum(1 for f in figs if f.kind == "table")

    # ---- per-section stats & flags
    sec_stats = []
    for s in sections:
        bls = [b for b in all_blocks if b.bid in set(s.block_ids)]
        nchar = sum(len(b.text) for b in bls)
        has_eq = any(b.kind == K_EQ for b in bls)
        has_img = any(page_meta.get(p, {}).get("images") for p in range(s.page_start, s.page_end + 1))
        sec_stats.append({"sid": s.sid, "title": s.title, "chars": nchar, "blocks": len(bls), "pages": [s.page_start, s.page_end], "equations": has_eq, "images_nearby": has_img})
    # anomalies about structure
    if method == "none":
        report["anomalies"].append({"kind": "NO_HEADINGS", "detail": "No headings detected via outline or font heuristics; treating whole document as one section."})
    if any(st["chars"] < 150 for st in sec_stats[1:]) and len(sec_stats) > 3:
        report["warnings"].append("Some sections are very short (<150 chars); they may be heading-detection false positives or genuinely short sections.")
    if n_pages >= 40:
        report["warnings"].append(f"Long document ({n_pages} pages); consider reading sections in batches.")
    if any(page_meta[p].get("ncols", 1) >= 2 for p in page_meta):
        report["layout"] = "multi-column detected; reading order corrected column-major"
    # missing captions for images
    n_imgs = sum(len(page_meta[p].get("images", [])) for p in page_meta)
    if n_imgs > len(figs) * 2 and n_imgs > 4:
        report["warnings"].append(f"{n_imgs} embedded images but only {len(figs)} captions found; some figures may lack captions or be logos.")

    skeleton = {
        "source": os.path.abspath(pdf_path),
        "metadata": report.get("metadata", {}),
        "pages": n_pages,
        "body_font_size": round(body, 2),
        "heading_method": method,
        "sections": [asdict(s) for s in sections],
        "section_stats": sec_stats,
        "blocks": [asdict(b) for b in all_blocks],
        "figures": [asdict(f) for f in figs],
        "page_meta": {str(k): v for k, v in page_meta.items()},
    }
    return {"status": "success", "skeleton": skeleton, "report": report}


def write_sections_md(skeleton: dict, path: str, max_chars_per_section: int = 6000) -> None:
    blocks = {b["bid"]: b for b in skeleton["blocks"]}
    lines = [f"# {os.path.basename(skeleton['source'])} — sections (machine skeleton)\n"]
    for s in skeleton["sections"]:
        bls = [blocks[i] for i in s["block_ids"] if i in blocks]
        text = "\n\n".join(f"[{b['bid']}|{b['kind']}] {b['text']}" for b in bls)
        truncated = False
        if len(text) > max_chars_per_section:
            text = text[:max_chars_per_section] + f"\n\n[... truncated {len(text) - max_chars_per_section} chars; read skeleton.json for the rest]"
            truncated = True
        lines.append(f"\n## {s['sid']} {('§' + s['number'] + ' ') if s['number'] else ''}{s['title']}  (pp.{s['page_start']}–{s['page_end']}, anchor {s['anchor']}){'  [TRUNCATED]' if truncated else ''}\n\n{text}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("out_dir")
    ap.add_argument("--ocr-lang", default="eng+chi_sim" if os.name != "nt" else "eng")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--force-ocr", action="store_true")
    ap.add_argument("--max-chars", type=int, default=6000)
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    res = extract(a.pdf, ocr_lang=a.ocr_lang, max_pages=a.max_pages, force_ocr=a.force_ocr)
    rep = res.get("report", {})
    rep["status"] = res["status"]
    if res.get("reason"):
        rep["reason"] = res["reason"]
    with open(os.path.join(a.out_dir, "extract_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    if res["status"] != "success":
        print(json.dumps({"status": res["status"], "reason": res.get("reason"), "report": rep}, ensure_ascii=False, indent=1))
        return 2
    with open(os.path.join(a.out_dir, "skeleton.json"), "w", encoding="utf-8") as f:
        json.dump(res["skeleton"], f, ensure_ascii=False)
    write_sections_md(res["skeleton"], os.path.join(a.out_dir, "sections.md"), a.max_chars)
    print(json.dumps({"status": "success", "out_dir": a.out_dir, "pages": rep["pages"], "sections": rep["sections"], "heading_method": rep["heading_method"], "figures": rep["figures"], "tables": rep["tables"], "anomalies": rep["anomalies"], "warnings": rep["warnings"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
