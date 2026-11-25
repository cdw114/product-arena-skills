#!/usr/bin/env python3
"""Phase A: inspect the input bundle, build the paragraph store and the source registry.

Usage:
  python scripts/inspect_inputs.py --input /input --out /app/work/input_inventory.json

Writes:
  <work>/input_inventory.json          what was found, roles, counts, missing
  <work>/paragraphs/<source_id>.jsonl   one record per paragraph (the quote store)
  <work>/sources.json                   registry built from corpus-manifest.json (fallback: inferred)
  <work>/contract.json                  output_contract + case_id copied from case.json (if present)

Tolerant to: JSON / JSONL / Markdown / JATS XML inputs, missing files, nested wrappers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import read_json, read_jsonl, write_json, write_jsonl, slug  # noqa: E402

# ---------------------------------------------------------------------------
# heuristic role detection by filename
# ---------------------------------------------------------------------------
ROLE_RULES = [
    (re.compile(r"corpus-manifest", re.I), "manifest"),
    (re.compile(r"^material\.json$|material[-_.]index|paragraphs[-_.]index", re.I), "material_index"),
    (re.compile(r"primary", re.I), "paper_primary"),
    (re.compile(r"secondary", re.I), "paper_secondary"),
    (re.compile(r"case\.json$", re.I), "case"),
    (re.compile(r"task\.md$|task\.txt$|README", re.I), "task"),
    (re.compile(r"\.xml$", re.I), "jats_xml"),
    (re.compile(r"resources\.ya?ml$", re.I), "resources"),
]


def role_of(path: Path) -> str:
    n = path.name
    for rx, role in ROLE_RULES:
        if rx.search(n):
            return role
    if n.endswith(".json"):
        return "paper_unknown"
    if n.endswith(".md"):
        return "markdown_unknown"
    return "other"


# ---------------------------------------------------------------------------
# generic paragraph extraction from arbitrary JSON structures
# ---------------------------------------------------------------------------
ID_KEYS = ["paragraph_id", "paragraphId", "pid", "id", "para_id", "p_id"]
TEXT_KEYS = ["text", "content", "body", "paragraph", "plain_text", "value"]
SRC_KEYS = ["source_id", "sourceId", "doi", "paper_id", "paperId", "document_id", "doc_id", "work"]
SEC_KEYS = ["section", "section_path", "sectionPath", "heading", "section_title", "path"]
PAGE_KEYS = ["page", "page_number", "pageNumber", "pdf_page"]


def _first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def walk_records(obj, src_hint, out):
    """Iterative, non-duplicating version of the paragraph finder."""
    stack = [(obj, src_hint, 0)]
    while stack:
        cur, src, depth = stack.pop()
        if depth > 12:
            continue
        if isinstance(cur, dict):
            txt = _first(cur, TEXT_KEYS)
            pid = _first(cur, ID_KEYS)
            if isinstance(txt, str) and txt.strip() and pid is not None:
                s = _first(cur, SRC_KEYS) or src
                sec = _first(cur, SEC_KEYS)
                if isinstance(sec, list):
                    sec = " / ".join(str(x) for x in sec)
                out.append({
                    "paragraph_id": str(pid),
                    "source_id": str(s) if s else None,
                    "section_path": str(sec) if sec is not None else "",
                    "text": txt,
                    "page": _first(cur, PAGE_KEYS),
                })
                continue
            local_src = _first(cur, SRC_KEYS) or src
            for v in cur.values():
                stack.append((v, local_src, depth + 1))
        elif isinstance(cur, list):
            for v in cur:
                stack.append((v, src, depth + 1))


def extract_from_json(path: Path, src_hint):
    try:
        data = read_json(path)
    except json.JSONDecodeError:
        return extract_from_jsonl(path, src_hint)
    out = []
    walk_records(data, src_hint, out)
    return out


def extract_from_jsonl(path: Path, src_hint):
    out = []
    for rec in read_jsonl(path):
        walk_records(rec, src_hint, out)
    return out


HEAD_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def extract_from_markdown(path: Path, src_hint):
    """Markdown: headings define section_path, non-empty blocks become paragraphs.

    Paragraph ids are positional and clearly synthetic: 'md:<slug>-<n>'.
    They are NOT JATS ids and are flagged as such in the inventory.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out, sec, buf, n = [], [], [], 0
    for ln in lines:
        m = HEAD_RE.match(ln)
        if m:
            if buf and "".join(buf).strip():
                n += 1
                out.append({"paragraph_id": f"md:{slug(path.stem)}-{n}", "source_id": src_hint,
                            "section_path": " / ".join(sec), "text": " ".join(buf).strip(), "page": None})
            buf = []
            level = len(m.group(1))
            sec = sec[: level - 1] + [m.group(2).strip()]
            continue
        if ln.strip() == "":
            if buf and "".join(buf).strip():
                n += 1
                out.append({"paragraph_id": f"md:{slug(path.stem)}-{n}", "source_id": src_hint,
                            "section_path": " / ".join(sec), "text": " ".join(buf).strip(), "page": None})
            buf = []
            continue
        buf.append(ln.strip())
    if buf and "".join(buf).strip():
        n += 1
        out.append({"paragraph_id": f"md:{slug(path.stem)}-{n}", "source_id": src_hint,
                    "section_path": " / ".join(sec), "text": " ".join(buf).strip(), "page": None})
    return out


def extract_from_jats(path: Path, src_hint):
    """JATS XML: <body> → <sec>/<p>. Paragraph ids come from the element's id attribute if
    present, else a synthetic 'jats:<sec-n>-<p-n>' id."""
    out = []
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as e:
        return out, f"xml parse error: {e}"
    doi = src_hint
    for art in root.iter("article"):
        for ids in art.iter("article-id"):
            if ids.get("pub-id-type") == "doi" and not doi:
                doi = (ids.text or "").strip()
    body = root.find(".//body")
    if body is None:
        return out, "no <body> element"
    sec_title = []

    def text_of(el):
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip()

    def walk_sec(sec, titles):
        t = sec.find("title")
        titles2 = titles + ([text_of(t)] if t is not None else [])
        p_n = 0
        for child in sec:
            if child.tag == "sec":
                walk_sec(child, titles2)
            elif child.tag == "p":
                p_n += 1
                pid = child.get("id") or f"jats:{slug('-'.join(titles2) or 'root')}-{p_n}"
                out.append({"paragraph_id": pid, "source_id": doi, "section_path": " / ".join(titles2),
                            "text": text_of(child), "page": None})
            elif child.tag in ("abstract", "trans-abstract"):
                for p in child.iter("p"):
                    p_n += 1
                    pid = p.get("id") or f"jats:abstract-{p_n}"
                    out.append({"paragraph_id": pid, "source_id": doi, "section_path": " / ".join(titles2 + ["Abstract"]),
                                "text": text_of(p), "page": None})
    for sec in body.findall("sec"):
        walk_sec(sec, sec_title)
    for p in body.findall("p"):
        out.append({"paragraph_id": p.get("id") or f"jats:body-{len(out)+1}", "source_id": doi,
                    "section_path": "", "text": text_of(p), "page": None})
    for ab in root.iter("abstract"):
        for p in ab.iter("p"):
            pid = p.get("id") or f"jats:front-abstract-{len(out)+1}"
            out.append({"paragraph_id": pid, "source_id": doi, "section_path": "Abstract", "text": text_of(p), "page": None})
    return out, None


def sha256_of(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# manifest handling
# ---------------------------------------------------------------------------
def parse_manifest(path: Path):
    """Return list of source records {source_id, doi, title, authors, role, license, source_hash}."""
    data = read_json(path)
    raw = []
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        for k in ("papers", "items", "documents", "sources", "corpus", "works", "records"):
            if isinstance(data.get(k), list):
                raw = data[k]
                break
        if not raw:
            raw = [v for v in data.values() if isinstance(v, (dict, list))]
            raw = [x for x in raw if isinstance(x, dict)] or [data]
    recs = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        doi = _first(r, ["doi", "DOI", "root_doi", "rootDoi"])
        recs.append({
            "source_id": str(_first(r, ["source_id", "sourceId", "id"]) or doi or ""),
            "doi": doi,
            "title": _first(r, ["title", "name"]),
            "authors": _first(r, ["authors", "author", "creators"]),
            "role": _first(r, ["role", "part", "kind"]) or ("primary" if len(recs) == 0 else "secondary"),
            "license": _first(r, ["license", "licence", "rights"]),
            "source_hash": _first(r, ["source_hash", "sourceHash", "hash", "sha256", "content_hash", "checksum"]),
            "files": _first(r, ["files", "file", "paths", "path"]) or [],
            "raw_keys": sorted(r.keys()),
        })
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default=None)
    ap.add_argument("--work", default=None, help="work dir (default: $KG_WORK or /app/work)")
    args = ap.parse_args()

    inp = Path(args.input)
    work = Path(args.work) if args.work else Path(__import__("os").environ.get("KG_WORK", "/app/work"))
    out_inv = Path(args.out) if args.out else work / "input_inventory.json"
    work.mkdir(parents=True, exist_ok=True)

    files = []
    SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".cache"}
    if inp.exists():
        for p in sorted(inp.rglob("*")):
            if p.is_file() and not (set(p.relative_to(inp).parts) & SKIP_DIRS):
                files.append(p)
    # task.md may sit next to case.json; also look one level up
    if not any(p.name.lower() == "task.md" for p in files):
        for cand in [inp / "task.md", inp.parent / "task.md", Path("/app/task.md")]:
            if cand.exists() and cand not in files:
                files.append(cand)

    inventory = {"input_dir": str(inp), "exists": inp.exists(), "files": [], "missing_expected": [], "warnings": []}
    EXPECTED = ["case.json", "task.md", "corpus-manifest.json", "material.json",
                "primary-material.json", "secondary-material.json"]
    names = {p.name for p in files}
    for e in EXPECTED:
        if e not in names:
            inventory["missing_expected"].append(e)

    # --- case.json / contract
    case = {}
    for p in files:
        if p.name == "case.json":
            try:
                case = read_json(p)
            except Exception as e:  # noqa: BLE001
                inventory["warnings"].append(f"case.json unreadable: {e}")
    contract = {
        "case_id": case.get("case_id") or case.get("id") or case.get("caseId") or "unknown",
        "output_contract": case.get("output_contract") or case.get("contract") or [],
        "task": case.get("task") or case.get("instruction") or case.get("prompt"),
        "root_doi": case.get("doi") or case.get("root_doi"),
        "root_title": case.get("title"),
        "root_authors": case.get("authors"),
        "raw_keys": sorted(case.keys()),
    }
    write_json(work / "contract.json", contract)

    # --- manifest → sources
    sources = []
    manifest_path = next((p for p in files if role_of(p) == "manifest"), None)
    if manifest_path:
        try:
            sources = parse_manifest(manifest_path)
            inventory["manifest"] = {"path": str(manifest_path), "records": len(sources)}
        except Exception as e:  # noqa: BLE001
            inventory["warnings"].append(f"manifest unreadable: {e}")

    # --- per-file inventory + paragraph extraction
    all_paras = []
    for p in files:
        role = role_of(p)
        rec = {"path": str(p), "name": p.name, "role": role, "bytes": p.stat().st_size, "sha256": None, "status": "ok", "records": 0, "note": ""}
        try:
            rec["sha256"] = sha256_of(p)
        except Exception:  # noqa: BLE001
            pass
        src_hint = None
        if sources:
            for s in sources:
                fl = s.get("files") or []
                fl = [fl] if isinstance(fl, str) else fl
                if p.name in [Path(str(x)).name for x in fl] or (s.get("role") == "primary" and "primary" in p.name.lower()) or (s.get("role") == "secondary" and "secondary" in p.name.lower()):
                    src_hint = s["source_id"] or s["doi"]
        if role in ("paper_primary", "paper_secondary", "material_index", "paper_unknown", "manifest"):
            try:
                paras = extract_from_json(p, src_hint)
                # attach the file name so duplicate-format detection can work later
                for q in paras:
                    q["file"] = p.name
                    if q["source_id"] is None:
                        q["source_id"] = src_hint
                all_paras.extend(paras)
                rec["records"] = len(paras)
            except Exception as e:  # noqa: BLE001
                rec["status"] = "unreadable"
                rec["note"] = str(e)
        elif role == "markdown_unknown" and p.name.lower() not in ("task.md", "readme.md"):
            paras = extract_from_markdown(p, src_hint)
            for q in paras:
                q["file"] = p.name
                q["page"] = None
            all_paras.extend(paras)
            rec["records"] = len(paras)
            rec["note"] = "synthetic paragraph ids (md:*)"
        elif role == "jats_xml":
            try:
                paras, err = extract_from_jats(p, src_hint)
                rec["records"] = len(paras)
                rec["note"] = ("verification source only (not a third paper); " + (f"error: {err}" if err else "parsed ok"))
                write_jsonl(work / "paragraphs" / f"_xml_{p.stem}.jsonl", paras)
            except Exception as e:  # noqa: BLE001
                rec["status"] = "unreadable"
                rec["note"] = str(e)
        inventory["files"].append(rec)

    # --- resolve source ids for paragraphs that lack one
    unresolved = [q for q in all_paras if not q.get("source_id")]
    if unresolved:
        # fall back: derive one source id per file when the file is single-paper
        by_file = {}
        for q in unresolved:
            by_file.setdefault(q["file"], []).append(q)
        for fn, qs in by_file.items():
            guess = None
            for s in sources:
                if s.get("doi") and (s["doi"] in fn):
                    guess = s["doi"]
            if guess is None and sources and len(sources) >= 2 and "secondary" in fn.lower():
                guess = [s for s in sources if s.get("role") == "secondary"][0]["source_id"] or [s for s in sources if s.get("role") == "secondary"][0]["doi"]
            if guess is None and sources and "primary" in fn.lower():
                guess = sources[0]["source_id"] or sources[0]["doi"]
            guess = guess or fn
            for q in qs:
                q["source_id"] = guess
            inventory["warnings"].append(f"paragraphs in {fn} had no source_id; assigned '{guess}' (verify against corpus-manifest.json)")

    # --- dedupe: the same paragraph may appear in material.json AND the per-paper file
    seen = {}
    for q in all_paras:
        key = (q["source_id"], q["paragraph_id"])
        if key in seen:
            seen[key].setdefault("also_in", []).append(q["file"])
            # prefer the record that has a section_path/page if the first lacked it
            if not seen[key].get("section_path") and q.get("section_path"):
                seen[key]["section_path"] = q["section_path"]
            if seen[key].get("page") is None and q.get("page") is not None:
                seen[key]["page"] = q["page"]
        else:
            q.setdefault("also_in", [])
            seen[key] = q
    paras = list(seen.values())

    # --- duplicate-format detection (same paper in several files ≠ cross-paper evidence)
    by_src_files = {}
    for q in paras:
        by_src_files.setdefault(q["source_id"], set()).update([q["file"]] + q.get("also_in", []))
    inventory["files_per_source"] = {k: sorted(v) for k, v in by_src_files.items()}
    if sources:
        for s in sources:
            s["files"] = sorted(by_src_files.get(s["source_id"] or s["doi"], set()))
            s["paragraph_count"] = sum(1 for q in paras if q["source_id"] == (s["source_id"] or s["doi"]))
            s["duplicate_formats"] = [f for f in s["files"] if f != s["files"][0]] if len(s["files"]) > 1 else []
    else:
        # infer sources from paragraphs
        for sid in sorted(by_src_files):
            qs = [q for q in paras if q["source_id"] == sid]
            sources.append({"source_id": sid, "doi": sid if sid.startswith("10.") else None, "title": None,
                            "authors": None, "role": "primary" if not sources else "secondary",
                            "license": None, "source_hash": None, "files": sorted(by_src_files[sid]),
                            "paragraph_count": len(qs), "duplicate_formats": [],
                            "note": "inferred: no corpus-manifest.json found"})
        inventory["warnings"].append("no corpus-manifest.json; sources inferred from paragraph records")
    for s in sources:
        s.setdefault("status", "ok")
        s.setdefault("paragraph_count", 0)
        if s["paragraph_count"] == 0:
            s["status"] = "missing"

    # --- write paragraph store, one file per source
    pdir = work / "paragraphs"
    pdir.mkdir(parents=True, exist_ok=True)
    for sid in by_src_files:
        qs = [q for q in paras if q["source_id"] == sid]
        for q in qs:
            q.pop("also_in", None)
        write_jsonl(pdir / f"{slug(sid)}.jsonl", qs)
    inventory["paragraph_store"] = str(pdir)
    inventory["paragraph_counts"] = {sid: sum(1 for q in paras if q["source_id"] == sid) for sid in by_src_files}
    inventory["synthetic_ids"] = sorted({q["paragraph_id"].split(":")[0] + ":" for q in paras if q["paragraph_id"].startswith(("md:", "jats:", "syn"))})
    if inventory["synthetic_ids"]:
        inventory["warnings"].append(
            "some paragraph ids are synthetic (md:/jats:) — they are positional anchors in this bundle, NOT PDF pages; "
            "if the bundle has no PDF page numbers do not report any page.")

    write_json(work / "sources.json", sources)
    write_json(out_inv, inventory)

    # --- summary to stdout (what the agent reads first)
    print(json.dumps({
        "input_dir": str(inp), "files": len(files),
        "roles": {r["name"]: r["role"] + (f" [{r['records']}]" if r["records"] else "") for r in inventory["files"]},
        "missing_expected": inventory["missing_expected"],
        "case_id": contract["case_id"], "output_contract": contract["output_contract"],
        "sources": [{"source_id": s["source_id"], "role": s["role"], "paragraphs": s["paragraph_count"],
                     "files": s["files"], "status": s["status"]} for s in sources],
        "warnings": inventory["warnings"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
