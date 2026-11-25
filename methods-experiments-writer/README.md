# methods-experiments-writer

Turns scattered research materials into a Methods and Experiments section where every
number traces to a file, source conflicts are kept instead of silently resolved, and
gaps are handed back to the author as answerable questions.

**Status:** working. `python3 scripts/selftest.py` runs the whole chain on a bundled toy
case and asserts the result (positive run, negative run, contract check, resource budget).

---

## What problem it solves

A methods section is usually written last, from memory, out of materials that disagree
with each other. The failure is always the same shape: a fluent paragraph containing a
value nobody can locate, a dataset version that moved, and a baseline that quietly got a
different budget. Reviewers cannot check it, and a reader cannot re-run it.

This skill makes the pipeline explicit:

```
materials ──scan──> evidence ledger (one row per fact, with a locator)
                          │
                          ├──> you draft, citing [E0001] as you go
                          │
                          └──> audit: every number sourced? table agrees? six elements?
                                        │
                                        └──> deliverables + result.json
```

Three properties do the work:

1. **Nothing enters the prose without a locator.** The audit tokenises the finished draft
   and checks each number against the ledger row its own paragraph cites. A number with no
   row is an error, not a warning.
2. **Disagreement survives.** When a config says `0.01` and the log says `0.1`, both rows
   are kept, both are written, and a question is raised. The skill never picks a winner.
3. **Gaps are product, not failure.** A `TO-CONFIRM` block naming the file to open is the
   correct output when the materials are silent, and it is counted as such.

## Install

No install. Python 3.9+ standard library only, no network, no GPU.

```bash
cp -r methods-experiments-writer ~/.agents/skills/        # or wherever your harness looks
```

Optional, each detected at run time and each degrading to a recorded note:

| package | used for | without it |
|---|---|---|
| `PyYAML` | real YAML config parsing | a built-in indentation reader handles flat/nested maps; flow maps fall back to line scanning |
| `python-docx` | a `.docx` deliverable | markdown only; `previews.notes` records it |
| `PyMuPDF` / `pypdf` / `pdfminer` | PDF text | the PDF is recorded as an unreadable gap; extract text yourself and use `--extra-text` |
| LibreOffice (`soffice`) | PDF/PNG preview of the docx | docx is still produced; no preview, and that is stated |

## Use

```bash
python3 scripts/scan_case.py  --input /input --work /app/work
# read /app/work/scan_report.md, draft into /app/work/draft.md citing [E####]
python3 scripts/audit_draft.py --draft /app/work/draft.md --work /app/work
python3 scripts/emit_outputs.py --input /input --work /app/work --out /app/output
```

Minimal invocation on the bundled toy case:

```bash
python3 scripts/selftest.py --keep ./selftest_out
ls selftest_out/out          # the deliverables, including result.json
```

### Command reference

`scan_case.py`

| flag | default | meaning |
|---|---|---|
| `--input` | `/input` | case directory: `case.json`, `task.md`, and the materials |
| `--work` | `/app/work` | where the ledger and reports go |
| `--extra-text` | – | a text file you extracted yourself (e.g. PDF text), merged as prose evidence |
| `--max-files` | `400` | stop after this many material files |

`audit_draft.py`

| flag | default | meaning |
|---|---|---|
| `--draft` | required | the markdown to check |
| `--work` | `/app/work` | reads `evidence.json`, writes `audit.json` / `audit.md` |
| `--strict` | off | exit 1 when a number is unsourced or a table row disagrees |
| `--language` | detected | `zh` or `en`, for the report wording |

`emit_outputs.py`

| flag | default | meaning |
|---|---|---|
| `--input` | `/input` | read `case.json` for `output_contract` |
| `--work` | `/app/work` | ledger, audit, optional `output_plan.json` |
| `--out` | `/app/output` | where deliverables and `result.json` are written |
| `--docx` | `auto` | `auto` builds docx + preview when the image supports it; `none` skips |

## What it outputs

`result.json` carries `case_id` and **every field the case's `output_contract` names**,
plus the fields the task asks of any writing skill:

| field | content |
|---|---|
| `outputs` | one entry per contract field, filled with the deliverable text |
| `field_manifest` | which deliverable backed each contract field |
| `fact_source_map` | every ledger row: fact, value, locator, confidence |
| `version_and_boundaries` | counts, conflicts, audit verdict, limitations of the run |
| `sources` | input files with class, size and SHA-256 |
| `uncertainty` | gaps, conflicts, assumptions — each with `resolve_by` |
| `change_log` | what the run did, in order, plus revisions the audit forced |
| `status` / `status_detail` | `success` / `partial` / `failed`, and why |

Alongside it: the section, the parameter table (md + csv), the evidence map, the coverage
report, the question list (md + json), the reproducibility checklist and a manifest with
SHA-256 for every file.

## Design notes

**Why a ledger and not a template.** A template produces a section that is complete in
shape and empty in content — the paragraph on "datasets" exists, and says nothing a reader
can use. The ledger inverts the order: extract first, then write only what the extraction
supports. Coverage is then a property of the materials plus the questions asked, not of
the template.

**Why conflicts are kept.** Preferring the config "because it is the source of truth" is
wrong whenever a CLI override ran; preferring the log "because it is what happened" is
wrong whenever the log is from a smoke test. Both choices look confident and are
sometimes false. Reporting both costs one paragraph and is never false.

**Why block locality, not sentence locality.** The audit checks a number against the
citations in its own paragraph (a table row counts as its own paragraph). Sentence-level
matching looked stricter but reported a false positive every time a citation landed one
line-break away from its number, which is how a numeric audit gets ignored.

**Why numbers that label structure are masked.** Section numbers, ordered-list markers,
figures, citation brackets, versions and timestamps are all digits. Masking them is what
lets `unsourced_numbers: 0` mean something.

## Limits

- Rule-based extraction. It finds things that look like parameters; it does not know what
  the experiment means. `confidence: low` rows are prose and are not numbers.
- A config default is not evidence of what ran. Only a log line or the author is.
- Coverage is keyword-based and can be satisfied superficially. Treat it as a floor.
- Splits, seeds and preprocessing are the most-missing facts in real materials, so expect
  several `TO-CONFIRM` blocks. That is the correct output.

## Maintaining it

- Adding a parameter vocabulary entry: `scripts/mew_lib.py`, `PARAM_VOCAB`.
- Adding an extraction rule: `scripts/scan_case.py`, one `add_*_rows` function per file
  class. Every rule must set a `source_locator`; a row without one is a bug.
- Adding a coverage element or piece: `scripts/audit_draft.py`, `ELEMENT_SPECS`. Both
  Chinese and English patterns are required, because cases arrive in both.
- After any change, `python3 scripts/selftest.py` must stay green. It asserts an exact
  conflict count and an exact element count, so a rule change that shifts either is
  visible rather than silent.
