#!/usr/bin/env python3
"""Shared helpers for the literature-kg skill scripts (stdlib only).

Paragraph store format: one JSON object per line in /app/work/paragraphs/<source_id>.jsonl
    {"paragraph_id","source_id","section_path","text","page"(optional),"file"}
Graph format: a single JSON {"nodes":[...],"edges":[...]}
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

WORK = Path(os.environ.get("KG_WORK", "/app/work"))
PARA_DIR = WORK / "paragraphs"


# ---------------------------------------------------------------- io
def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path, rows):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- paragraphs
def load_paragraphs(para_dir=None):
    """Return {(source_id, paragraph_id): paragraph}."""
    para_dir = Path(para_dir) if para_dir else PARA_DIR
    idx = {}
    if not para_dir.exists():
        return idx
    for fp in sorted(para_dir.glob("*.jsonl")):
        for p in read_jsonl(fp):
            idx[(p["source_id"], p["paragraph_id"])] = p
    return idx


# ---------------------------------------------------------------- normalisation
_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    """Case/whitespace/punctuation-insensitive key for alias matching."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\u2010-\u2015\-_/\\,;:.()'\"\[\]{}<>]+", " ", s)
    s = _WS.sub(" ", s).strip()
    return s


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "x"


def norm_quote(q: str) -> str:
    """Normalise a quote for tolerant substring matching (whitespace, curly quotes, dashes)."""
    q = unicodedata.normalize("NFKC", q or "")
    q = q.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    q = q.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    q = _WS.sub(" ", q).strip()
    return q


def quote_in_text(quote: str, text: str) -> bool:
    return norm_quote(quote) in norm_quote(text)


# ---------------------------------------------------------------- graph
def load_graph(path):
    g = read_json(path)
    g.setdefault("nodes", [])
    g.setdefault("edges", [])
    return g


def node_index(g):
    return {n["id"]: n for n in g["nodes"]}


def edge_index(g):
    return {e["id"]: e for e in g["edges"]}


def evidence_sources(obj):
    """Distinct source_ids over an evidence list, or over a node/edge dict."""
    ev = obj.get("evidence", []) if isinstance(obj, dict) else (obj or [])
    return sorted({e.get("source_id") for e in ev if isinstance(e, dict) and e.get("source_id")})


def is_cross_paper(node_or_edge):
    return len(evidence_sources(node_or_edge.get("evidence"))) >= 2


def iter_evidence(g):
    for n in g["nodes"]:
        for e in n.get("evidence", []):
            yield ("node", n["id"], e)
    for ed in g["edges"]:
        for e in ed.get("evidence", []):
            yield ("edge", ed["id"], e)


# ---------------------------------------------------------------- output
def eprint(*a):
    print(*a, file=sys.stderr)
