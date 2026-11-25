# Troubleshooting paper variants

Check `extract_report.json` **before** writing notes. Most failures here are
cheap to fix and expensive to discover after you have already written the notes.

## 1. Scanned / image-only PDF

Symptom: `status: refused`, anomaly `NO_TEXT_LAYER`; `sections.md` empty or a few
stray characters.

- With OCR available (`pip install pytesseract pillow`, plus the `tesseract`
  binary): `python scripts/pdf_extract.py in.pdf work --force-ocr --ocr-lang eng+chi_sim`.
- Without OCR: report `refused` with reason `no text layer and OCR unavailable`.
  Do **not** invent content from the filename, and do not describe the paper from
  prior knowledge — that is fabrication, not reading.
- OCR notes: OCR text has no reliable block geometry, so anchors degrade to
  page-level and every note is `coarse`. Say so in `uncertainty`.

## 2. Encrypted / permission-restricted PDF

Symptom: `status: refused`, anomaly `ENCRYPTED`.

- `pdf_extract.py` first tries an empty user password (common for publisher PDFs).
- Still encrypted → `refused`, reason "encrypted PDF requires a password". This is
  the correct answer; ask the operator for the password or an unlocked copy.
- Copy-protected but readable PDFs (owner password only) are fine: text extraction
  is allowed, and the run proceeds normally.

## 3. Two columns read in the wrong order

Symptom: paragraph text jumps between columns mid-sentence; section text contains
fragments of two different topics.

- The extractor detects columns per page and reads column-major (with full-width
  titles/figure bands as separators). If a page is misdetected, the report's
  `layout` line says whether multi-column was detected at all.
- Verify by reading one page of `sections.md` against the PDF image. If order is
  still wrong, that page is likely a mixed layout (e.g. a wide table between two
  column bands): treat its section as `partial` and anchor claims to the block you
  can see is right, rather than trusting block neighbours.
- Never "fix" reading order by reordering `skeleton.json` by hand — block ids are
  the anchors; reordering silently breaks every quote check.

## 4. Figures, tables, equations not extractable

Symptom: `figures` count low; `n embedded images but only N captions` warning;
equation blocks appear as `attention(Q, K, V ) = softmax(...` fragments.

- Captions are matched by `Figure|Fig.|Table|图|表` + number. Missing captions mean
  figures cannot be anchored precisely — anchor to the nearest paragraph and say
  "figure not machine-readable" in `uncertainty`.
- Vector figures (no raster image) still have captions; anchor to the caption block.
- Equations: **never** transcribe an equation you cannot verify. If you must refer
  to one, quote the surrounding sentence and note that the formula is an image.
- If a number appears only inside a figure, record it as `uncertain` — not as a
  reported value.

## 5. Very long documents (60+ pages, theses, reviews)

Symptom: `warnings` includes a long-document note; `sections.md` is large.

- Read sections in batches by page range; write `notes_draft.json` incrementally
  (add sections, rerun `validate`), so a budget cut-off still leaves a valid file.
- Prioritise: abstract, each numbered top-level section, results, limitations.
  Appendix/reference sections get a one-line note each, not a full read.
- `sections.md` truncates a section at 6000 chars with an explicit
  `[... truncated N chars]` marker — when you see it, read the rest from
  `skeleton.json` before summarising, or mark the section `partial`.

## 6. Non-Chinese / non-English papers

- Chinese papers: headings like `一、引言`, `第3章 方法`, and captions `图3`, `表1`
  are recognised. `--ocr-lang chi_sim+eng` for scans.
- Other languages: heading detection is font/size based and works without
  language knowledge, but the note text should stay in the **language of the
  task statement** unless the case says otherwise. Quote in the original language
  and translate inside the note body — a translated quote will fail verification.
- If the paper mixes languages (e.g. Chinese abstract, English body), note which
  language each field came from in `uncertainty`.

## 7. Headings wrong or missing

Symptom: `heading_method: none`, or one giant section, or headings that are really
paragraph fragments.

- `none` → no outline and no font-size signal: the document may use a uniform font
  (some LaTeX exports), or the "headings" are only bold runs. Content is still
  readable; produce a single-section note set with `heading_method` recorded, and
  set `run_status: partial` because section alignment is not trustworthy.
- Heading detected inside a paragraph (`... results. 4 Experiments`) → the paper
  embeds headings in running text. Anchor by paragraph and reconstruct the section
  list by hand in the notes only if the case asks for section alignment.
- Duplicate or empty sections after extraction: see the printed `sections` count vs
  the paper's table of contents; a mismatch of one or two is usually the preamble
  or a merged appendix and is safe to note in `uncertainty`.

## 8. Budget or time exhausted mid-run

Write `notes_draft.json` after the **first** section, validate, and keep
appending. A validated `partial` result at 60% beats an unvalidated draft at 95%:
`build_notes.py` writes a complete `result.json` from whatever exists.
