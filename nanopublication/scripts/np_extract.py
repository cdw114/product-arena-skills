#!/usr/bin/env python3
"""Extract per-page text from a PDF or text file with stable page markers.

Usage:
    python3 np_extract.py <input.pdf|input.txt|input.md> --out /app/work/text.txt

Output format (what np_build.py / np_validate.py expect):
    === page 1 ===
    <text of page 1>
    === page 2 ===
    ...

Backends, in order: PyMuPDF (fitz), pdftotext (poppler), plain read.
Exit code 0 on success, 2 when no text layer is available (needs OCR), 1 on error.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MARK = "=== page {n} ==="


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pages_pdf_fitz(path):
    import fitz  # PyMuPDF
    with fitz.open(path) as doc:
        return [page.get_text("text") for page in doc]


def pages_pdf_pdftotext(path):
    out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, check=True)
    text = out.stdout.decode("utf-8", "replace")
    if text.endswith("\f"):
        text = text[:-1]
    return text.split("\f")


def pages_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return [f.read()]


def select_pages(spec, total):
    if spec is None:
        return list(range(1, total + 1))
    selected = set()
    for part in spec.split(","):
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part.strip())
        if not match:
            raise ValueError(f"invalid page or range: {part!r}")
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= total:
            raise ValueError(f"page range {part!r} is outside 1–{total}")
        selected.update(range(first, last + 1))
    return sorted(selected)


def write_result(a, text, **meta):
    output = Path(a.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    res = {"path": a.input, "out": a.out, "chars": len(text), **meta}
    if a.meta:
        path = Path(a.meta)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res))
    return 2 if res["status"] == "failed" else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", help="optional json path for extraction metadata")
    ap.add_argument("--pages", help="physical 1-based pages, e.g. 2,4-6")
    ap.add_argument("--ocr-text", metavar="PAGE=PATH", action="append", default=[],
                    help="UTF-8 OCR text for an in-scope page without native text; repeat per page")
    a = ap.parse_args()

    if not os.path.isfile(a.input):
        return write_result(a, "", status="failed", reason="source_unavailable")

    ext = os.path.splitext(a.input)[1].lower()
    backend, pages, note = None, [], None
    if ext == ".pdf":
        try:
            pages = pages_pdf_fitz(a.input)
            backend = "pymupdf"
        except Exception:
            try:
                pages = pages_pdf_pdftotext(a.input)
                backend = "pdftotext"
            except Exception:
                backend, note = "none", "no PDF text backend available"
    else:
        pages = pages_text(a.input)
        backend = "text"

    sha256 = sha256_of(a.input)
    if backend == "none":
        return write_result(a, "", status="failed", reason="no_text_layer", backend=backend,
                            note=note, sha256=sha256, pages=len(pages))
    try:
        selected = select_pages(a.pages, len(pages))
        page_text = {n: pages[n - 1] or "" for n in selected}
        native = [n for n, content in page_text.items() if content.strip()]
        ocr = []
        for entry in a.ocr_text:
            page, sep, path = entry.partition("=")
            if not sep or not re.fullmatch(r"[0-9]+", page):
                raise ValueError(f"OCR text entry must be PAGE=PATH: {entry}")
            number = int(page)
            if number not in page_text or page_text[number].strip():
                raise ValueError(f"OCR page {number} is outside scope or already has text")
            content = Path(path).read_text(encoding="utf-8-sig")
            if not content.strip():
                raise ValueError(f"OCR for page {number} is empty")
            page_text[number] = content
            ocr.append(number)
    except (OSError, ValueError) as exc:
        return write_result(a, "", status="failed", reason="invalid_extraction_scope",
                            note=str(exc), sha256=sha256, backend=backend, pages=len(pages))
    missing = [n for n, content in page_text.items() if not content.strip()]
    chunks = []
    for number, content in page_text.items():
        chunks.extend([MARK.format(n=number), content.rstrip("\n")])
    available = sorted(set(native) | set(ocr))
    outcome = {"status": "partial" if missing else "ok"} if available else {
        "status": "failed", "reason": "no_text_layer"}
    return write_result(a, "\n".join(chunks) + "\n", **outcome, backend=backend,
                        sha256=sha256, pages=len(pages), pages_requested=selected,
                        pages_with_text=available, pages_with_native_text=native,
                        pages_without_text=missing, ocr_pages=sorted(ocr))


if __name__ == "__main__":
    sys.exit(main())
