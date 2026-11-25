---
name: paper-structured-notes
description: >-
  Turn a real research paper (PDF, or /input/case.json pointing at one) into
  section-aligned structured notes rather than a flat summary: a fixed-field paper
  card, one note per original section in the paper's own argument order, a
  de-duplicated knowledge-point list, and a machine-checkable page/block anchor on
  every key claim. Use for 文献总结 / 结构化笔记, paper summary, reading notes,
  parameter and finding extraction, or answering questions about a paper with
  citations.
---

# Paper structured notes

Produce notes that **match the paper's own section structure**, **keep every key
finding anchored to a page/block that a checker can re-open**, and **say plainly
what the paper does not report**. Deterministic work (PDF parsing, section
splitting, anchor verification, coverage accounting) is done by the scripts; you
only supply reading and wording.

## When to use

Use when the deliverable is *notes/summary/answers about one paper*, and the
reader must be able to go back to the source. Do **not** use it to reproduce
numbers by simulation, to regenerate figures, or to review code.

## Inputs

| What | Where | Notes |
|---|---|---|
| Case descriptor | `/input/case.json` | Usually `{case_id, materials, questions/task, output_contract}`. **Read it first** — field names vary per case. |
| Task statement | `/input/task.md` | The questions to answer and the required output fields. |
| Paper | referenced from `case.json` (`materials[].path`), or a PDF you are given | Never assume the paper's content from its filename or domain label. |
| Work dir | `/app/work` | Scratch: skeleton, per-section text, your draft. |
| Output dir | `/app/output` | Final `result.json`, `notes.md`, plus any human-readable extras. |

Missing `case.json`/`task.md`: proceed with the PDF alone, and record the absence
in `run_status.reason` and `uncertainty`.

## Procedure

### Step 0 — Read the task before the paper
Read `/input/case.json` and `/input/task.md`. Write down (a) the case id, (b) the
exact output fields the grader expects, (c) which questions must be answered.
If the case supplies its own `output_contract`, that contract wins over the
default shape described in `references/output_contract.md` — keep all its field
names and add nothing in their place.

### Step 1 — Locate the paper and extract a deterministic skeleton
```bash
python3 scripts/prepare.py --work /app/work          # finds the PDF from /input/case.json
# or, when you already know the file:
bash scripts/run.sh extract /path/to/paper.pdf /app/work
```
`prepare.py` writes `case_summary.json` (case id, the questions it found, the
output fields it expects, every PDF candidate) and then runs the extractor, so
you get the skeleton and the task in one step. If several PDFs exist and the wrong
one was chosen, rerun with `--pdf`.

The extractor writes `skeleton.json` (sections, blocks, figures, tables),
`sections.md` (each section's text with `[p3:b12|paragraph]` prefixes) and
`extract_report.json` (status, heading method, anomalies, warnings).

Read `extract_report.json` first:
- `status: success` → continue.
- `refused` + `ENCRYPTED` → stop; report that the PDF needs a password.
- `refused` + `OCR_UNAVAILABLE` / `NO_TEXT_LAYER` → the PDF is a scan. Say so in
  `run_status`; if `pytesseract` + `Pillow` exist, rerun with `--force-ocr`.
- `NO_HEADINGS`, very short sections, or wrong section titles → see
  `references/troubleshooting.md` before writing anything.

Verify the skeleton **before** spending model calls: open `sections.md` and check
that the section list and their page ranges look like the paper's own table of
contents. Fix cheaply with the flags in troubleshooting; do not hand-edit
`skeleton.json` (anchors would drift).

### Step 2 — Read section by section, in the paper's order
Work through `sections.md` in order. For each section record, in the paper's own
terms: `purpose`, `method`, `results`, `conclusion`, and `link_to_previous` (how
this section follows from the last — this is what makes the notes an argument
chain and not a bullet dump). Skip nothing silently: a section you cannot fill
gets `not_reported` with the reason.

Never write a claim without taking a `quote` from the block you read it in. Quote
verbatim (12–300 chars); the validator checks it is a real substring of that
block after whitespace/hyphen normalisation.

### Step 3 — Fill the paper card (fixed fields, comparable across papers)
Fill every field of `references/field_dictionary.md`: `research_question`,
`data`, `method`, `main_findings`, `conclusion`, `limitations`,
`scope_conditions`, `open_questions`. Each field carries
`source: reported | not_reported | uncertain | conflicting` and its own evidence.
`not_reported` is a legitimate, expected value — use it instead of guessing.
`scope_conditions` is the one most often skipped and the one that makes the
conclusion valid; fill it from the paper's setting, population, scale, or
assumption list.

### Step 4 — Knowledge points, de-duplicated
Extract the concepts, variables, methods and findings that a later reader would
search for. One entry per idea: `id` (`KP-001`…), `term`, `aliases`
(abbreviations and synonyms), `type` (`concept|variable|method|finding|metric|
dataset`), `statement`, `conditions`, `related`, `evidence`. Merge synonyms into
one entry with aliases rather than repeating the idea; the validator flags
duplicate terms and duplicate ids.

### Step 5 — Write the draft, then validate
Write `/app/work/notes_draft.json` in the shape of
`references/notes_draft_schema.md`, then:
```bash
bash scripts/run.sh validate /app/work /app/output [/input/case.json] [/input/task.md]
```
This prints checked/failed anchor counts and coverage, and writes `result.json`,
`notes.md` and `validation.json`. Exit code 0 = usable, 2 = refused (nothing to
emit). If anchors fail, fix the quote or the anchor id and rerun — do not bypass.

### Step 6 — Audit before finishing
```bash
bash scripts/run.sh check /app/output
```
Exit 0 = no blocking problem. It flags: missing required blocks, a status that
contradicts the checks, failed anchors, sections with no note, card fields absent
entirely, placeholder text, and an empty uncertainty block. Fix what it reports,
then stop — an honest, audited `partial` is worth more than an unaudited draft.

## Output

`/app/output/result.json` — the machine contract:

```json
{"case_id": "...",
 "run_status": {"status": "success|partial|cannot_determine|refused", "reason": "..."},
 "result": {"paper_card": [...], "sections": [...], "knowledge_points": [...], "answers": [...]},
 "evidence": {"anchor_format": "p{page}:b{block}", "verification": {...}, "coverage": {...}},
 "uncertainty": {"not_reported_fields": [...], "uncertain_fields": [...], ...},
 "change_log": [...]}
```

`/app/output/notes.md` — the same content for a human reader.
`/app/output/validation.json` — anchor/coverage audit.

## Anchor format (short)

`p{page}:b{block}` — 1-based page, block index in column-major reading order;
`p7` alone is a page-level anchor (allowed, flagged coarse); `F2`/`T1` reference
figure/table 2/1; `s3.2` is a section anchor (allowed, flagged coarse).
A **key** claim needs block-level anchor **plus** a verbatim quote. Full rules in
`references/anchor_format.md`.

## Honest reporting

- `success`: every body section noted, all card fields filled or `not_reported`,
  no failed anchors.
- `partial`: real content, but missing sections/fields or unverifiable quotes —
  say which in `run_status.reason`.
- `cannot_determine`: the material does not let you answer the asked question;
  state what is missing.
- `refused`: encrypted/scanned-without-OCR/missing material — state the reason and
  what a human must supply.
Never present a guess as a paper claim, and never invent a page number.

## Files

| Path | Role |
|---|---|
| `scripts/prepare.py` | read `case.json`, find the PDF, run the extractor |
| `scripts/pdf_extract.py` | PDF → skeleton (sections, blocks, figures, tables, reading order) |
| `scripts/build_notes.py` | validate draft → `result.json`, `notes.md`, `validation.json` |
| `scripts/audit.py` | post-run audit of an output dir (what `check` runs) |
| `scripts/selftest.py` | offline self-test of both stages on a synthetic fixture |
| `scripts/run.sh` | one-command entry point (bash) |
| `scripts/run.py` | same entry point for environments without bash |
| `references/field_dictionary.md` | card fields + knowledge-point fields |
| `references/anchor_format.md` | anchor rules and verification semantics |
| `references/notes_draft_schema.md` | exact JSON shape the agent must write |
| `references/output_contract.md` | `result.json` shape and how to merge a case's own contract |
| `references/troubleshooting.md` | scanned/encrypted/two-column/超长/非中文 papers |
| `references/example.md` | worked example (marked as example, not a case answer) |

## Requirements

`python3` (3.9+). `extract` needs PyMuPDF (`pip install pymupdf`); optional OCR
needs `pytesseract` + `Pillow`. `validate` and `check` are pure standard library.
Budget note: `extract` costs no model calls; read `sections.md` in as few passes
as the budget allows and write the draft in one file rather than many small edits.
