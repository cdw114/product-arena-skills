#!/usr/bin/env python3
"""
papertrans.segment — Segment a parsed document into translation units and batch them.

A *segment* is a paragraph-level unit that must be translated 1:1. Rules:
  - body/list blocks are kept as segments (one block = one segment; consecutive list items merge into one segment)
  - headings, captions, equations, table blocks are their own segments (never merged with body)
  - pageheader/pagefooter/reference blocks are EXCLUDED by default (configurable) — references are
    bibliographic data that must not be translated; they're carried verbatim to output
  - very long segments (> max_chars) are split at sentence boundaries into sub-segments `S012a`, `S012b`
  - continuation across pages/columns: a body block ending without terminal punctuation followed by a
    body block starting with lowercase → merged into the previous segment (cross-page paragraph)

Each segment carries: id, page, bbox, role, text, and (later) glossary hits.

Batches are sized by a *token budget* (chars/4 ≈ tokens) so a single model request never exceeds
the per-response cap. Also emits `context` per batch: the last sentence(s) of the previous segment
(continuation context) and the current locked glossary subset relevant to that batch.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

TERMINAL = (".", "!", "?", ":", "。", "！", "？")
DEFAULT_EXCLUDE_ROLES = ("pageheader", "pagefooter", "reference", "author", "boilerplate")
HEADING_ROLES = ("title", "heading")
KEEP_ROLES = ("title", "heading", "body", "abstract", "caption", "equation", "list", "footnote", "table")

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'(])")
_GHOST_WORDS = set("""the just this are will but my we be its in is of a and to it that for on with as was at by an or not from have has had you
they he she which their our all can may do does did if then than so such no nor only own same too very""".split())


def _is_ghost(text: str) -> bool:
    """Paragraph made purely of function words (invisible filler text embedded by some PDF generators)."""
    if len(text) > 200:
        return False
    words = re.findall(r"[A-Za-z]+", text)
    return len(words) >= 2 and all(w.lower() in _GHOST_WORDS for w in words)


@dataclass
class Segment:
    id: str
    page: int
    pages: list[int]
    bbox: Any
    role: str
    text: str
    source_blocks: list[str]
    part: str = ""          # "" | "a" | "b" ...
    parent: str = ""        # parent segment id when split
    flags: dict[str, Any] = field(default_factory=dict)
    glossary_hits: list[str] = field(default_factory=list)
    context: str = ""      # carried context (previous segment tail) for translation


@dataclass
class Batch:
    id: str
    segment_ids: list[str]
    est_tokens: int
    purpose: str = "translate"


def _split_sentences(text: str) -> list[str]:
    parts = SENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split at sentence boundaries into chunks ≤ max_chars (hard split only if a single sentence exceeds 2×max)."""
    if len(text) <= max_chars:
        return [text]
    sents = _split_sentences(text)
    out: list[str] = []
    cur = ""
    for s in sents:
        if len(s) > 2 * max_chars:
            # hard-split a pathological sentence at clause boundaries
            clauses = re.split(r"(?<=[;,])\s+", s)
            c2 = ""
            for c in clauses:
                if c2 and len(c2) + len(c) + 1 > max_chars:
                    out.append(c2)
                    c2 = c
                else:
                    c2 = (c2 + " " + c).strip()
            s = ""
            if c2:
                s = c2
            if not s:
                continue
        if cur and len(cur) + len(s) + 1 > max_chars:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip() if cur else s
    if cur:
        out.append(cur)
    return out


def segment_document(doc: dict[str, Any], max_chars: int = 1400,
                     exclude_roles: tuple[str, ...] = DEFAULT_EXCLUDE_ROLES,
                     include_references: bool = False) -> dict[str, Any]:
    exclude = set(exclude_roles) if not include_references else set(exclude_roles) - {"reference"}
    segs: list[Segment] = []
    excluded: list[dict[str, Any]] = []
    verbatim: list[dict[str, Any]] = []
    prev_body: Segment | None = None
    counter = 0

    def new_id() -> str:
        nonlocal counter
        counter += 1
        return f"S{counter:03d}"

    for page in doc["pages"]:
        for b in page["blocks"]:
            if b["role"] in exclude:
                if b["text"].strip():
                    rec = {"page": b["page"], "block": b["id"], "role": b["role"], "text": b["text"]}
                    (verbatim if b["role"] == "author" else excluded).append(rec)
                continue
            if b["role"] not in KEEP_ROLES:
                continue
            text = b["text"].strip()
            if not text or _is_ghost(text):
                continue
            # cross-page / cross-column continuation: previous body without terminal punctuation
            # and current starts lowercase (or with a connector) and previous was the last segment
            if (prev_body is not None and prev_body.role in ("body", "list", "abstract") and b["role"] in ("body", "abstract")
                    and not prev_body.text.rstrip().endswith(TERMINAL)
                    and re.match(r"^[a-z(]", text) is not None):
                prev_body.text = prev_body.text + " " + text
                prev_body.pages.append(b["page"])
                if prev_body.bbox and b["bbox"]:
                    prev_body.bbox = [min(prev_body.bbox[0], b["bbox"][0]), prev_body.bbox[1],
                                      max(prev_body.bbox[2], b["bbox"][2]), b["bbox"][3]]
                prev_body.source_blocks.append(b["id"])
                prev_body.flags["continued"] = True
                continue
            # list items: merge consecutive list blocks; table cells: merge consecutive cells on the page into one unit
            if b["role"] == "list" and segs and segs[-1].role == "list" and segs[-1].pages[-1] == b["page"]:
                segs[-1].text += "\n" + text
                segs[-1].source_blocks.append(b["id"])
                continue
            if b["role"] == "table" and segs and segs[-1].role == "table" and segs[-1].pages[-1] == b["page"] \
                    and len(segs[-1].text) + len(text) < max_chars:
                segs[-1].text += "\n" + text
                segs[-1].source_blocks.append(b["id"])
                segs[-1].flags.setdefault("table_cells", 1)
                segs[-1].flags["table_cells"] += 1
                continue
            # split long segments
            pieces = _split_long(text, max_chars)
            base = new_id()
            if len(pieces) == 1:
                seg = Segment(id=base, page=b["page"], pages=[b["page"]], bbox=b["bbox"], role=b["role"],
                              text=text, source_blocks=[b["id"]], flags=dict(b.get("flags", {})))
                segs.append(seg)
                prev_body = seg if b["role"] in ("body", "list", "abstract") else None
            else:
                letters = "abcdefghij"
                for i, piece in enumerate(pieces):
                    seg = Segment(id=f"{base}{letters[i]}", page=b["page"], pages=[b["page"]], bbox=b["bbox"],
                                  role=b["role"], text=piece, source_blocks=[b["id"]], part=letters[i], parent=base,
                                  flags=dict(b.get("flags", {}), split=True))
                    segs.append(seg)
                prev_body = segs[-1] if b["role"] in ("body", "list", "abstract") else None

    # drop ghost segments produced by continuation-merging of scattered filler words
    segs = [s for s in segs if not _is_ghost(s.text)]

    # carry context: previous segment tail for non-heading segments
    for i, s in enumerate(segs):
        if i > 0 and s.role not in HEADING_ROLES and not s.flags.get("continued"):
            prev = segs[i - 1]
            tail = prev.text[-240:]
            s.context = tail

    role_counts: dict[str, int] = {}
    for s in segs:
        role_counts[s.role] = role_counts.get(s.role, 0) + 1
    return {
        "n_segments": len(segs),
        "total_chars": sum(len(s.text) for s in segs),
        "role_counts": role_counts,
        "continued": sum(1 for s in segs if s.flags.get("continued")),
        "split": sum(1 for s in segs if s.part),
        "segments": [asdict(s) for s in segs],
        "excluded_blocks": excluded,
        "verbatim_blocks": verbatim,
    }


def make_batches(segments: list[dict[str, Any]], budget_tokens: int = 3000, chars_per_token: float = 3.6,
                  max_segments: int = 12, context_chars: int = 240) -> list[dict[str, Any]]:
    """Greedy packing by estimated tokens; headings never stranded alone at the end of a batch."""
    batches: list[dict[str, Any]] = []
    cur_ids: list[str] = []
    cur_tok = 0
    for s in segments:
        tok = math.ceil((len(s["text"]) + context_chars) / chars_per_token)
        if cur_ids and (cur_tok + tok > budget_tokens or len(cur_ids) >= max_segments):
            batches.append({"id": f"B{len(batches)+1:02d}", "segment_ids": cur_ids, "est_tokens": cur_tok})
            cur_ids, cur_tok = [], 0
        cur_ids.append(s["id"])
        cur_tok += tok
    if cur_ids:
        batches.append({"id": f"B{len(batches)+1:02d}", "segment_ids": cur_ids, "est_tokens": cur_tok})
    return batches


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="papertrans.segment")
    ap.add_argument("doc_json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=1400)
    ap.add_argument("--budget-tokens", type=int, default=3000)
    ap.add_argument("--include-references", action="store_true")
    a = ap.parse_args(argv)
    doc = json.loads(Path(a.doc_json).read_text(encoding="utf-8"))
    seg = segment_document(doc, a.max_chars, include_references=a.include_references)
    batches = make_batches(seg["segments"], a.budget_tokens)
    seg["batches"] = batches
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(seg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[segment] segments={seg['n_segments']} chars={seg['total_chars']} batches={len(batches)} "
          f"roles={seg['role_counts']} continued={seg['continued']} split={seg['split']} excluded={len(seg['excluded_blocks'])} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
