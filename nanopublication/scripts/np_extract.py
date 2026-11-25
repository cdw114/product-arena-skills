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
import subprocess
import sys

MARK = "=== page {n} ==="


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pages_pdf_fitz(path):
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return pages


def pages_pdf_pdftotext(path):
    out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, check=True)
    text = out.stdout.decode("utf-8", "replace")
    return text.split("\f")


def pages_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return [f.read()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", help="optional json path for extraction metadata")
    a = ap.parse_args()

    if not os.path.isfile(a.input):
        print(json.dumps({"status": "failed", "reason": "source_unavailable", "path": a.input}))
        return 2

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

    pages = [p if p else "" for p in pages]
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    non_empty = [i + 1 for i, p in enumerate(pages) if p.strip()]

    if backend == "none" or (ext == ".pdf" and not non_empty):
        res = {"status": "failed", "reason": "no_text_layer", "backend": backend, "note": note,
               "path": a.input, "sha256": sha256_of(a.input), "pages": len(pages)}
        print(json.dumps(res))
        if a.meta:
            with open(a.meta, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
        return 2

    chunks = []
    for i, p in enumerate(pages, 1):
        chunks.append(MARK.format(n=i))
        chunks.append(p.rstrip("\n"))
    text = "\n".join(chunks) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    res = {"status": "ok", "backend": backend, "path": a.input, "sha256": sha256_of(a.input),
           "pages": len(pages), "pages_with_text": non_empty, "chars": len(text), "out": a.out}
    print(json.dumps(res))
    if a.meta:
        with open(a.meta, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
