---
name: methods-experiments-writer
description: Turn scattered research materials (config files, training logs, code, dataset notes, README, paper) into an evidence-bound Methods and Experiments section where every number traces to a file, conflicts between sources are kept instead of silently resolved, and gaps are handed back to the author as answerable questions. Use when asked to draft, write, revise or audit a Methods / Experimental Setup / 方法与实验 section, or when a paper's methods must be made reproducible enough for someone else to re-run. Not for editing prose that already has its sources settled.
---

# Methods and Experiments writer

A methods section is not prose that sounds like a methods section. It is a claim that
a reader can act on: given this file, this command and these values, you get this
result. This skill produces that kind of section out of whatever materials exist, and
it produces the trail that lets a reviewer check it.

The load-bearing rule:

> **A number with no locator does not enter the prose.** Not "is softened", not "is
> marked as approximate" — it does not enter. If the materials do not contain it, the
> section says `TO-CONFIRM` and `open_questions.md` names the file the author must open.

Most methods-writing failures are not stylistic. They are a smooth paragraph containing
a learning rate nobody can find, a dataset version that changed, and a baseline that was
given a different budget. This skill is built to fail loudly on those three.

## When to use this

Use it when the request is to produce or repair a methods/experiments section **from
materials** — code, configs, logs, dataset cards, a README, a draft paper — and the
result has to be checkable.

Do not use it when:

- the task is a literature review, an abstract, or a discussion section;
- the facts are already settled in the prompt and the job is only wording — just write it;
- the request is to invent a plausible methods section for a study that has no materials.
  That is fabrication, and this skill will refuse rather than produce it.

## Inputs

At run time the case supplies:

| path | what it is | required |
|---|---|---|
| `/input/case.json` | case id, audience, and `output_contract` — the exact fields the deliverable must carry | no, but strongly preferred |
| `/input/task.md` | the instruction: section, audience, language, length, format | no |
| `/input/**` | the materials themselves: `*.yaml`, `*.json`, `*.toml`, `*.log`, `*.py`, `*.md`, `*.pdf`, `*.csv`, `*.ipynb` | yes |

**Read the actual files.** Do not infer the contents of `materials/config.yaml` from its
name, and do not assume a `.pdf` was parsed for you — check whether a text layer came out.

Language: write the section in the language of `task.md` unless `case.json` says
otherwise. `scripts/scan_case.py` records the detected language in `work/contract.json`.

## The five commands

Work under `/app/work`, deliver to `/app/output`. Run from the skill root.

```bash
# 1. inventory + parse every material into an evidence ledger
python3 scripts/scan_case.py --input /input --work /app/work

# 2. read work/scan_report.md, then write the section into work/draft.md citing [E####]
#    (this is your work; no command does it for you)

# 3. check the draft: every number sourced, six elements covered, table agrees
python3 scripts/audit_draft.py --draft /app/work/draft.md --work /app/work

# 4. fix what the audit names, and re-run it until verdict is "ready" or you accept
#    the remainder as TO-CONFIRM

# 5. build the deliverables and result.json
python3 scripts/emit_outputs.py --input /input --work /app/work --out /app/output
```

`python3 scripts/selftest.py` runs all five on a bundled toy case and asserts the
result. Run it once if you want to see the pipeline work before trusting it on a real
case. It needs no arguments and touches nothing outside a temp directory.

Budget note: steps 1, 3 and 5 are the whole toolchain. Do not re-run step 1 after every
sentence — draft the whole section, then audit, then revise. Re-scanning per paragraph
is how a 64-request budget disappears.

## What step 1 gives you

`work/evidence.json` is the ledger: one row per atomic fact, each with a locator.

```json
{"eid": "E0009", "kind": "config_value", "name": "train.learning_rate",
 "value": "0.0003", "display": "0.0003", "unit": "1", "applies_to": "config",
 "source_locator": "materials/config.yaml#/train/learning_rate",
 "method": "yaml", "confidence": "high", "status": "ok"}
```

Locator forms, all re-openable by a reviewer:

- text or log: `materials/train.log:4` (1-based line)
- JSON/YAML/TOML config: `materials/config.yaml#/train/learning_rate` (JSON pointer)
- code: `materials/train.py:14` (the line the default is on)

`status` is `ok` or `conflict`. `confidence` is `high` (a value parsed out of a
structured file), `medium` (a log line or a heuristic key match) or `low` (a prose
sentence, kept for wording only — never for a number).

`work/scan_report.md` is the human view: materials table, parameter rows, conflicts, a
coverage prefill, and the gap/questions list. Read this, not the raw JSON.

## Writing the draft

Follow `templates/section_outline.md`. The six elements are not optional; the audit
scores each one:

1. **Procedure** — ordered steps. Each step states input, operation, output, and the
   condition under which it fails. A step that hides a decision inside "then we train
   the model" is not a step.
2. **Experimental setup** — hardware, software versions, environment, seeds, repeats.
   Training, validation and test are described as separate passes with separate data.
3. **Parameters** — a table with name, value, unit, what it acts on, and source.
4. **Datasets and splits** — name, version, size, preprocessing, split ratios, how the
   split was drawn, and what each subset is used for.
5. **Baselines and comparison** — who the baseline is, its version, whether the budget
   was equal, the metric, and the statistics (mean over how many runs, what dispersion).
6. **Reproducibility and limitations** — code version, command, data access; and limits
   tied to a concrete failure scenario ("fails when the effective batch changes"), not
   "has some limitations".

Cite as you write: `... at a learning rate of 0.0003 [E0009] ...`. One tag can cover
several numbers in the same clause; a number in a different clause needs its own.

The four questions the section must survive, which are also the audit's four checks:

- **写得全** — are steps, setup, parameters, data, baselines and limits all present, or
  only the readable spine?
- **写得准** — do the values match the config, the log and the code? Did any number get
  smoothed in to make a sentence flow?
- **做得着** — can a reader re-run it from what is written here: version, environment,
  seed, command?
- **说得住** — are gaps and uncertainties marked and handed back, and do the limits name
  a real failure instead of a courtesy?

## Conflicts: keep both, ask, never pick

When two sources disagree about one parameter, `scan_case.py` marks both rows
`status: conflict` and writes the question into `work/gaps.json`. Do this:

- report **both** values in the prose, each with its citation;
- say plainly that the materials disagree and that the run's actual value is unconfirmed;
- put a `**TO-CONFIRM — <parameter>.**` paragraph naming the two files.

Do **not** average them, prefer the config because it is "the source of truth", or
prefer the log because it is "what happened". You do not know which is true. A methods
section that silently picks one is worse than one that admits the disagreement, because
the reader trusts it.

The same applies to a missing value: write `TO-CONFIRM`, not a plausible default.

## Output layout

`emit_outputs.py` writes into `/app/output`:

| file | content |
|---|---|
| `result.json` | `case_id`, `status`, **every field `output_contract` names**, `sources`, `uncertainty`, `change_log`, `fact_source_map` |
| `methods_and_experiments.md` | the section |
| `parameter_table.md` / `.csv` | name, value, unit, target, source, status |
| `evidence_map.md` | every ledger row with its locator |
| `coverage_report.md` | six-element status, open gaps, conflicts, audit summary |
| `open_questions.md` / `.json` | what the author must confirm, each naming a file |
| `reproducibility_checklist.md` | ticked only where the section actually states the item |
| `change_log.md` | the steps this run performed and the counts |
| `manifest.json` | file, size and SHA-256 for everything above |

`result.json.status` is `success` only when every contract field is filled and the
audit did not block; `partial` when something is missing, with `status_detail` saying
what; `failed` when no section could be produced at all. An unfilled contract field is
written as `null` and listed in `uncertainty` — never padded with plausible text.

If `output_contract` is absent, `templates/result_contract_default.json` supplies a
five-field default and `result.json.output_contract_source` says `default`, so a
reviewer can tell the difference.

## When something is missing

| situation | what to do |
|---|---|
| no `case.json` / no `output_contract` | use the default contract; record `output_contract_source: "default"` |
| materials are unreadable (binary, scanned PDF, no text layer) | scan records the gap; extract the text yourself with whatever tool the image has, save it, and re-run `scan_case.py --extra-text <file>`. Never write the section from the file name. |
| no parameter anywhere in the materials | do not write a parameters section that looks authoritative. Emit the section without values, a `TO-CONFIRM` block, and a question list. `status: partial`. |
| a table cell disagrees with the ledger | the audit reports it; fix the table or the citation and say which source won |
| the audit keeps blocking on a number you believe is right | add the source file and line to `work/evidence.json` as a new row, then re-run. If there is no source, the number is wrong even if it is right. |
| a contract field has no deliverable behind it | leave it `null`; `emit_outputs.py` names it in `uncertainty` |
| Office output required (.docx/.pptx) | `emit_outputs.py --docx auto` builds one when `python-docx` is present and a PDF/PNG preview when LibreOffice is present. If either is missing, `previews.notes` says so — record that limit, do not claim a preview you did not render. |

## Self-check before you finish

Run through this; each line is something a reviewer will look for.

- [ ] `python3 scripts/audit_draft.py` reports `unsourced_numbers: 0` — or every remaining
      one is inside `TO-CONFIRM` and named in `open_questions.md`.
- [ ] `elements_complete` equals `elements_total` — or the gap is explained in the report.
- [ ] Every conflict found by the scan appears in `open_questions.md` and in the prose.
- [ ] The limitations section names at least one concrete condition, and no sentence in
      it could be pasted into a different paper unchanged.
- [ ] `result.json` has `case_id` and every `output_contract` field.
- [ ] `uncertainty` is non-empty. A run with no uncertainty on real materials has almost
      certainly hidden something, not found everything.
- [ ] No number in the section lacks a citation in its own paragraph.

## Layout of this skill

```
SKILL.md                          this file
README.md                         install, usage, dependencies, limits, maintenance
scripts/mew_lib.py                locators, config parsing, number handling, the ledger
scripts/scan_case.py              step 1: inventory + parse -> evidence ledger
scripts/audit_draft.py            step 3: number sourcing, table alignment, coverage
scripts/emit_outputs.py           step 5: deliverables + result.json
scripts/selftest.py               runs the whole chain on the bundled toy case
templates/section_outline.md      the section skeleton, slot by slot
templates/param_table.md          the parameter table shape
templates/gap_questions.md        how to phrase a question the author can answer
templates/repro_checklist.md      the reproducibility checklist
templates/evidence_ledger.schema.json   the ledger row schema
templates/result_contract_default.json  fallback output_contract
templates/output_plan.json        optional override mapping contract fields to files
references/six_elements.md        what "complete" means for each of the six
references/writing_rules.md       sentence-level rules that keep prose evidence-bound
references/failure_modes.md       twelve documented ways this goes wrong, and the fix
references/worked_example.md      a walk through the toy case, input to output
examples/input/                   the toy case (config, log, code, README, task)
examples/reference/draft.md       the draft that case should produce
```

Everything is Python 3 standard library. Nothing here needs a network connection, a GPU,
or a package install. Optional, if the image has them: `PyYAML` (better config parsing),
`python-docx` (a .docx deliverable), `PyMuPDF` or `pypdf` (PDF text), LibreOffice (PDF
preview). Each one degrades to a recorded note rather than an exception.

## Limits

- The scanner is a rule-based extractor. It finds what looks like a parameter; it does
  not know what your experiment means. Where it returns `confidence: low` (prose), do not
  use the row as a number.
- A config default is not proof the run used that value. Only a log line or an author
  statement is. The conflict machinery exists because of exactly this gap.
- Coverage is keyword-based and can be satisfied superficially. Re-read the draft
  yourself; the checklist is a floor, not a verdict.
- Splits, seeds and preprocessing are the most commonly missing facts in real materials.
  Expect several `TO-CONFIRM` blocks. That is the correct output, not a failure.
