---
name: nanopublication
description: Extract atomic scientific claims from a supplied paper or passage and attach verbatim evidence with verifiable source locations. Use for nanopublications, claim-evidence pairs, and claim graphs that need provenance and machine-readable JSON or TriG.
---

# Nanopublication

Answer the reading task with independently checkable claims. Use the supplied material as the source of evidence. Follow the requested pages, topics and output contract. A general summary or translation uses its own workflow.

## Read and extract

1. Read the task, the output contract and the actual material. In the evaluator, read `/input/case.json` and `/input/task.md`, use `/app/work` for drafts and write the bundle to `/app/output`. For a supplied PDF or passage outside the evaluator, use the user's paths. Set `SKILL_DIR` to the directory containing this file.
2. Run `python3 "$SKILL_DIR/scripts/np_extract.py" <material> --out text.txt --meta meta.json`. If the task specifies a page range, add `--pages 2,4-6` using physical PDF pages. Keep this text as the reference for quotes and offsets. Check `pages_without_text` even when extraction returns usable text. If you can OCR those pages, verify the OCR against the image and rerun with `--ocr-text 4=page4.txt` for each recovered page. The file must contain just that page's UTF-8 OCR text. The result records `ocr_pages`, and claims citing those pages have confidence at most medium. Pass `--text-meta meta.json` to the builder so it can report missing pages or a failed extraction.
3. Read the in-scope material and draft `assertions.yaml` or JSON. Copy each quote from the extracted text. Write `doc.json` from metadata printed in the source when available. Use [the field dictionary](references/field-dictionary.md) for field shapes and [the controlled vocabulary](references/controlled-vocabulary.md) for categories and relation directions.

## Write and verify claims

For each question, record which claim IDs answer it and which requested items remain unresolved. Before finalising, read each answer alongside its cited clauses. Check the direction of the effect, comparison sign, population, baseline, and uncertainty. Record the physical pages actually reviewed in `meta.json` under `pages_read`. The extractor's `pages_with_text` is only a text-layer inventory.

- Give each claim one independently checkable proposition. Split independent coordinated statements and individual links in a causal chain. Keep the comparison, scope and units with the result they qualify. Preserve negation, hedging, authorship and vague quantifiers. Keep printed numeric precision and units. Use a quoted string for a magnitude with significant trailing zeros or other formatting to preserve.
- Use the smallest continuous passage that establishes the claim. Include enough context to resolve pronouns and comparisons. Use a separate located `controlling_quote` if another sentence supplies a necessary limit. For body-level data, use the body passage. Put matching abstract wording in `supporting_evidence`. When sources disagree, preserve both spans, mark the conflict and explain how it limits the answer.
- Match each value to its entity, metric and experimental conditions. For example, if a sentence gives Group A 28.4 BLEU and Group B 24.1 BLEU, extract one result per group and cite the clause that establishes it. For tables, quote the source row and use the printed row and column labels in `locator.table`. The checker can use Markdown or fixed-layout text with separated columns. If a cell is blank or the text layer misaligns columns, verify against the original table and record ambiguity where the cell cannot be established. For figures, record `locator.figure` and locate the caption or accompanying text.
- Use `direct` for claims stated in the material. Use `inferred` for deductions with an explicit rationale and an acyclic chain of claim IDs grounded in direct evidence. Use `not_reported` only for a task item absent from the reviewed scope. Its quote is empty and its offset is null. Distinguish absence, unread scope, unavailable material and ambiguous evidence.
- Provide page, paragraph, sentence or adjacent `prefix`/`suffix` hints when the same wording appears more than once. The builder locates the exact source slice, retaining PDF line breaks. If several matches survive, review the candidates. If the quote cannot be located, correct the draft from the source or keep the item in `unresolved`. A location failure supplies no premises for a deduction.
- Add relations when requested or needed to express a supported connection. Each edge requires a quote and two existing claim IDs. When an abstract restates an identical body claim, keep one assertion plus supplementary evidence. Keep distinct claims for different populations, conditions or metrics.

A draft claim can use flat quote and locator fields. The builder will nest them under `evidence`.

```yaml
- id: A1
  text: Group A scored 28.4 BLEU on the English-to-German task.
  claim_type: result
  subject: Group A
  predicate: scored
  object: 28.4 BLEU
  qualifiers: {magnitude: 28.4, unit: BLEU, metric: BLEU, population: the English-to-German task}
  quote: "Group A scored 28.4 BLEU on the English-to-German task."
  locator: {page: 2, prefix: "Results."}
  relation: direct
  confidence: high
```

## Build the bundle

Save a partial bundle once useful evidence is available.

```sh
python3 "$SKILL_DIR/scripts/np_build.py" finalise \
  --assertions assertions.yaml --text text.txt --text-meta meta.json \
  --case /input/case.json --out /app/output --status partial
```

Pass `--doc doc.json`, `--relations relations.json` or `--unresolved unresolved.json` when you have them. Inspect a disputed quote with `np_build.py locate --text text.txt --quote "..." --page 2`. Omit `--page` to list candidates when its location is unknown.

Review the claim and quote side by side in `report.md`. Check units, which entity each value describes, negation, uncertainty and conditions. The script detects common mismatches in numbers, unit pairs, parallel clauses and table cells. Review cases involving pronouns, distant context, multiple clauses, or other associations that require reading the passage. Fix the input drafts and rerun.

Write `fields.json` using the shape in the case's output contract. For prose, use `{"answer":"Group A scored 28.4 BLEU [A1]."}`. For per-question objects, link answers using the contract's evidence fields, for example `"claim_ids":["A1"]` when allowed. After reviewing the scope and evidence, rerun `finalise` with `--fields fields.json --status success`. Pending evidence, missing required fields, invalid claim references or failed checks keep the result partial. Use `--status partial` when work remains even if automated checks pass. When the source is unavailable, pass the extractor metadata and an empty assertion array to produce a failed result with a source diagnostic. Use `--unresolved` for gaps identified during reading. The builder writes one status to JSON, the report and CLI output.

| Output | Contents |
|---|---|
| `result.json` | Case ID, status, task fields, sources and the `nanopub` block |
| `assertions.json` | Assertions, relations and unresolved items |
| `assertions.md` | Claims with quotes and locators |
| `report.md` | Coverage, checks, items to review and claims paired with source passages |
| `nanopubs.trig` | Optional RDF export via `np_build.py trig --assertions /app/output/result.json --out /app/output/nanopubs.trig`. The full result carries the document metadata. Pass `--orcid` only for a known publication creator. |

Report pages and topics reviewed, any gaps and the OCR pages where applicable. For a separate structural and contract check, run `np_validate.py /app/output/result.json --text text.txt --case /input/case.json`. Without a case, pass `--schema "$SKILL_DIR/schemas/nanopub.schema.json"` to check the result schema.

Use the [synthetic example](references/minimal-example.md) to check a local installation. The development checkout also includes regression tests. Run them with `python3 -B -m unittest discover -s "$SKILL_DIR/tests" -v`.
