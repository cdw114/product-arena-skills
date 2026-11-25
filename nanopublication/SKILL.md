---
name: nanopublication
description: Extract atomic scientific claims (nanopublications) from a paper passage. Splits compound sentences into single-verdict claims, binds each to a minimal verbatim evidence span with page/paragraph/char offsets, separates direct evidence from inference and "not reported", checks quality, and exports machine-readable JSON plus W3C-Nanopub-compatible TriG. Use when task asks to split claims, give evidence or provenance, build a claim graph, or output nanopublication / claim-evidence pairs from a PDF or text.
---

# Nanopublication: answer the question, and show the evidence

A nanopublication is one **atomic claim** (a statement that can be judged true or false on its own) plus the **smallest evidence span that justifies it**, the **place in the source**, and **source metadata**.

Core rule: **every claim must be traceable to the source text; anyone can verify it claim by claim.**

## 0. Scope

- Use for: extracting claims, results, data points, methods from a paper (PDF or text); tasks asking for "evidence", "source location", "traceable", "machine-readable", nanopublications, claim graphs.
- Not for: summaries, translation, literature reviews, entity linking to external databases.
- Boundary: read only the provided material. No network, no outside facts. Every judgement rests on the source text.

## 1. Contract

### 1.1 Inputs (read in this order)

| Path | Content | Required |
|---|---|---|
| `/input/case.json` | `case_id`, material paths, `task.md`, `output_contract` | yes |
| `/input/task.md` | what to read, the question, output requirements | yes |
| `/input/<material>` | PDF or .md/.txt named by `case.json` | yes |

Open the material file itself. Never assume its content from the label.

### 1.2 Outputs (write to `/app/output`)

| File | Content |
|---|---|
| `result.json` | Main result. Every field of `output_contract` + `case_id` + a `nanopub` block (§2) |
| `assertions.json` | Claim list only (`nanopub.assertions` + `nanopub.relations`) for downstream parsers |
| `assertions.md` | Human view: each claim, its quote, locator, confidence |
| `report.md` | Coverage, unresolved items, quality-check results, limitations |
| `nanopubs.trig` | Optional: W3C-Nanopub-compatible RDF. Generate when the task asks for RDF |

Save a first complete `result.json` with `status: "partial"` as soon as one section is done, then improve it. Budget is 64 model requests / 900 s per case: spend it on reading, not on writing code.

### 1.3 Result shape

Field names follow `output_contract`. When the contract does not fix the structure, use:

```json
{
  "case_id": "...",
  "status": "success | partial | failed",
  "answer": "answer to the task question, citing claim ids like [A3]",
  "sources": [{"path": "/input/x.pdf", "kind": "pdf", "pages_read": [1, 2], "sha256": "..."}],
  "nanopub": {
    "schema_version": "nanopub-skill/1.0",
    "document": {"title": null, "authors": [], "year": null, "doi": null, "venue": null, "version": null, "identifier_type": "doi", "identifier_value": null},
    "assertions": ["§2.1"],
    "relations": ["§2.2"],
    "unresolved": [{"item": "...", "reason": "not_reported"}],
    "quality": "§2.3"
  }
}
```

All paths below are relative to the Skill directory. At the start of a run set `SKILL_DIR` to the installed Skill path (the evaluator installs it at `/skills/weekly-skill`; if that path does not exist, find the directory containing this `SKILL.md`). JSON schema: `$SKILL_DIR/schemas/nanopub.schema.json`. Field dictionary: `$SKILL_DIR/references/field-dictionary.md`.

## 2. Fields

### 2.1 Assertion

| Field | Type | Req | Rule |
|---|---|---|---|
| `id` | string | yes | `A1`, `A2`, ... unique, stable, in order of first appearance |
| `text` | string | yes | One sentence, one predicate. Paraphrase of the source only; add nothing the source does not say |
| `claim_type` | enum | yes | `observation` `definition` `method` `result` `interpretation` `limitation` `hypothesis` `question` `other` |
| `subject` `predicate` `object` | string | yes | 1-3 words each, **use the words the quote itself uses** (`we`, not "the authors"; `these models`, not "the Transformer" when the quote says "these models"), keep the source's direction ("A higher than B": do not write "B lower than A") |
| `qualifiers` | object | no | `{population, condition, timeframe, metric, comparator, magnitude, unit, negated}`; `null` where absent |
| `evidence.quote` | string | yes | Minimal sufficient span: contiguous, verbatim, no ellipsis, no paraphrase |
| `evidence.locator` | object | yes | `{page, paragraph, sentence, char_offset}`; at least `char_offset` must resolve (§3.3) |
| `evidence.relation` | enum | yes | `direct` `inferred` `not_reported` (§3.5) |
| `evidence.quote_verbatim` | bool | yes | true only if the quote matches the source exactly |
| `claimed_by` | string | no | Author of the claim when it is someone else's result (`"Smith et al."`); null for this paper |
| `hedge` | string | no | Source's hedging word if any (`may`, `suggests`, `associated with`); null otherwise |
| `confidence` | enum | yes | `high` `medium` `low` (§3.6) |
| `narrative_role` | enum | no | `background` `gap` `objective` `method` `result` `conclusion` `limitation` `future_work` `other` |
| `inference_chain` | list | if inferred | `[{"from": ["A3"], "to": "this", "rationale": "one sentence"}]` |
| `supporting_evidence` | list | no | Extra quotes that back the same claim (`[{quote, locator}]`) |

### 2.2 Relation

| Field | Type | Req | Rule |
|---|---|---|---|
| `id` | string | yes | `R1`, `R2`, ... |
| `subject` | string | yes | Claim id that plays the role (e.g. the supporting claim) |
| `predicate` | enum | yes | `supports` `contradicts` `refines` `qualifies` `depends_on` `same_as` `derived_from` `extends` `part_of` `compared_to` (§4) |
| `object` | string | yes | Claim id that is supported / contradicted / ... |
| `evidence` | object | yes | Quote + locator proving the relation; a relation with no source text is not allowed |
| `confidence` | enum | yes | `high` `medium` `low` |

### 2.3 Quality report (`nanopub.quality`)

`n_assertions`, `n_relations`, `n_direct`, `n_inferred`, `n_not_reported`, `n_unique_quotes`, `coverage: {scope, paragraphs_total, paragraphs_with_assertion, ratio}`, `checks: [{id, passed, detail}]` (ids in §5), `unresolved_summary` (count per reason).

## 3. Splitting rules

### 3.1 Atomicity test

A sentence **must be split** when any of these hold:

1. **Multiple subjects**: different subjects share a predicate ("X and Y both increased" -> two claims).
2. **Multiple predicates**: one subject has two or more predicates ("X increased and caused Y" -> "X increased" + "X caused Y").
3. **Causal chain**: A causes B causes C -> "A -> B" + "B -> C".
4. **Coordinated clauses**: two full propositions joined by and / or / while / semicolon ("assays were run at pH 7.4, and cells were grown at 37 C" -> two claims).
5. **Condition + main clause**: if the condition restricts the claim's scope it goes to `qualifiers.condition`; if the condition is itself a finding ("only when p53 is intact") it becomes its own claim linked with `qualifies`.
6. **Contrast / comparison**: "A higher than B" is one claim with `qualifiers.comparator = "B"`. If each side's value is stated, also emit one claim per value and link with `compared_to`.

Do **not** split a single valued proposition ("IC50 = 3.2 uM" is one claim, not "IC50 exists" + "IC50 = 3.2 uM").

A split is finished when each piece satisfies: **the evidence span alone is enough to judge that piece true or false.**

Worked example (source: "Treatment with 5 mg/kg compound 3 reduced tumor volume by 48% relative to vehicle.")

Wrong (one blob): `text = "Treatment with 5 mg/kg compound 3 reduced tumor volume by 48% relative to vehicle."` with `subject = "the whole sentence"`.

Right:

```json
{"id": "A1", "text": "Compound 3 at 5 mg/kg reduced tumor volume by 48% relative to vehicle.",
 "claim_type": "result", "subject": "compound 3", "predicate": "reduced", "object": "tumor volume",
 "qualifiers": {"condition": "5 mg/kg", "metric": "tumor volume", "comparator": "vehicle", "magnitude": 48, "unit": "%"},
 "evidence": {"quote": "Treatment with 5 mg/kg compound 3 reduced tumor volume by 48% relative to vehicle.",
              "locator": {"page": 3, "paragraph": 2, "sentence": 1, "char_offset": [4120, 4198]},
              "relation": "direct", "quote_verbatim": true},
 "hedge": null, "confidence": "high", "narrative_role": "result"}
```

The comparison "relative to vehicle" is kept as a qualifier, not split off, because it does not state a separate value.

### 3.2 Per-paragraph workflow

1. **Segment**: split into sentences; keep source order.
2. **Tag** each sentence: simple / coordinated / causal / conditional / comparative / negated / hedged / attributed / navigational.
3. **Skip** navigational sentences ("Section 3 describes ..."), acknowledgements, reference entries.
4. **Split** per §3.1; assign `claim_type`.
5. **Bind evidence**: minimal sufficient span + locator (§3.4).
6. **Decide direct / inferred / not_reported** (§3.5).
7. **Rate confidence** (§3.6).
8. **Link** relations across all claims (§4).
9. **Check** with `python3 $SKILL_DIR/scripts/np_validate.py` (§5) and record unresolved items.

### 3.3 Locators

`locator = {page, paragraph, sentence, char_offset}`.

- `page`: physical PDF page, 1-based (not the printed number); must match the page number used in the extracted text.
- `paragraph`: 1-based within the page; blank line or indent starts a paragraph; each table / caption is one paragraph.
- `sentence`: 1-based within the paragraph.
- `char_offset`: `[start, end)` into the **whole extracted text** (`/app/work/text.txt`, pages joined with `\n\n`). This is the machine key: `text[start:end] == evidence.quote` must hold exactly.
- Tables: add `locator.table = {"id": "Table 1", "row": "compound 3", "column": "IC50 (uM)"}`. Figures: `locator.figure = "Figure 2"`.

Always fill `char_offset`. `python3 $SKILL_DIR/scripts/np_build.py locate` computes it from the quote so page and offset agree. PDF text contains line breaks: write the quote with single spaces and `finalise` will match it across line breaks and store the exact source slice (words unchanged, `normalization_note` set).

### 3.4 Minimal sufficient evidence

A span is **minimal sufficient** when:

1. **Sufficient**: reading only this span (plus common sense) is enough to judge the claim true or false.
2. **Minimal**: removing any token breaks sufficiency.
3. **Contiguous**: a continuous run of the source (may cross a sentence boundary; never stitch non-adjacent text, never use "...").
4. **Self-contained**: no context outside the span is needed; if context is needed, extend the span or mark the claim `inferred`. In particular the span must contain the claim's subject: a span that starts at "while being more parallelizable..." cannot support subject = "these models"; start the span at "show these models to be superior..." instead.

**Copy, never recall.** Take the quote from `/app/work/text.txt` (select, copy), not from memory of the paper. One remembered word off ("show these models are superior" vs the real "show these models to be superior") and Q3 fails. Write the quote with single spaces; `finalise` matches across PDF line breaks (`English-\nto-German` included) and stores the exact source slice.

Special cases:

- **Controlling quote**: when the evidence is verbatim but another sentence in the paragraph limits the claim's scope ("... in vitro ..."), put that sentence in `controlling_quote` and set `controlling_quote_scope` to `scope_of_whole_claim` or `scope_of_part_of_claim`.
- **Abstract vs body**: an abstract summary sentence is not evidence for a body data claim. Use the body sentence; the abstract sentence goes to `supporting_evidence`.
- **Conflict**: body and abstract disagree -> body wins; keep both and add an `unresolved` entry with reason `conflicting_evidence`.
- **Numbers**: never convert units or round; `magnitude` is the number as printed, `unit` the unit as printed.
- **Negation**: keep the negation in `text` ("no significant difference was observed"); set `qualifiers.negated = true`.
- **Hedges**: keep "may / might / suggests / associated with" in `text` and record the word in `hedge`.
- **Attribution**: "Smith et al. reported ..." -> `claimed_by = "Smith et al."`, `narrative_role = "background"`.
- **Vague quantifiers**: "some / several / markedly" stay as words; do not turn them into numbers.
- **Tables / captions**: every cell is one claim (subject = row label, predicate = column header, object = value). Caption sentences follow the body rules.

### 3.5 Direct vs inferred vs not reported

- `direct`: subject, predicate, object, numbers, units and conditions of the claim each appear in the quote. Allowed normalisation: "5 mg/kg" -> `magnitude 5`, `unit mg/kg`.
- `inferred`: needs one or more reasoning steps using **only** source facts plus arithmetic, logic or standard unit conversion. `inference_chain` is required and its `from` must cite claim ids that exist in this document. No outside facts.
- `not_reported`: the source does not say it, or the material is unavailable. The claim stays in `assertions` with `evidence.relation = "not_reported"` and is also listed in `unresolved`.

A claim with a hedge keeps its hedged wording and its confidence is capped at `medium`.

### 3.6 Confidence

| Level | All of |
|---|---|
| `high` | `relation = direct`, `quote_verbatim = true`, no `hedge`, numbers and units verbatim |
| `medium` | `direct` with a hedge; or `inferred` with a chain using only source facts and arithmetic / logic; or evidence from the abstract only |
| `low` | `inferred` with an assumption in the chain; or `not_reported`; or unresolved conflict |

## 4. Relation vocabulary

| Predicate | Meaning | Evidence needed |
|---|---|---|
| `supports` | subject is evidence for object | both claims plus the linking sentence |
| `contradicts` | subject and object cannot both hold as stated | both quotes |
| `refines` | subject narrows object (more specific population, condition) | both quotes |
| `qualifies` | subject states a condition under which object holds | the conditional sentence |
| `depends_on` | object's result is computed from subject (input data, method) | methods sentence |
| `same_as` | same S-P-O and qualifiers (restated in abstract and body) | both quotes |
| `derived_from` | subject is calculated from object | methods sentence |
| `extends` | subject generalises object beyond its stated scope | both quotes |
| `part_of` | subject is one component of object | grouping sentence |
| `compared_to` | subject is measured against object | comparison sentence |

Direction: `subject` plays the role named by the predicate; `object` is what it plays it on. In "A supports B", A = `subject`.

Merge rules:

- **Merge** two claims when S-P-O and all qualifiers are identical; keep the first evidence, move the other to `supporting_evidence` and record `same_as`.
- **Do not merge** when qualifiers differ (different condition, population or metric): those are different claims.
- **Keep at most 12 claims per paragraph.** If more, merge the least informative ones and say so in `report.md`.

## 5. Quality checks

Run `python3 $SKILL_DIR/scripts/np_validate.py /app/output/result.json --text /app/work/text.txt --schema $SKILL_DIR/schemas/nanopub.schema.json`. Exit code 0 = pass. Checks:

| id | Check | Fix when it fails |
|---|---|---|
| `Q1_unique_ids` | ids unique | renumber |
| `Q2_atomic` | no claim `text` has two finite verbs joined by and / but / ; or two "that" clauses | split per §3.1 |
| `Q3_quote_found` | every quote occurs in `text.txt` | copy the exact substring from `text.txt` |
| `Q3b_relation_quote_found` | every relation quote occurs in `text.txt` | same |
| `Q4_offset_matches` | `text[start:end] == quote` | run `np_build.py locate` |
| `Q5_minimal` | quote is not a whole paragraph (> 60 words) unless one sentence | trim to the minimal span |
| `Q6_no_ellipsis` | no "..." or "[...]" in quotes | use a contiguous span |
| `Q7_relation_target` | every relation cites existing claim ids | fix ids |
| `Q8_direct_has_spo` | `direct` claims: subject and object words appear in the quote (case-insensitive) | mark `inferred` or fix the quote |
| `Q9_inferred_chain` | every `inferred` claim has a non-empty chain with existing `from` ids | add chain |
| `Q10_not_reported_listed` | every `not_reported` claim appears in `unresolved` | add entry |
| `Q11_no_blob` | average quote length < 45 words | shorten quotes |
| `Q12_confidence_rule` | confidence consistent with §3.6 | adjust |
| `Q13_qualifiers_kept` | source numbers appear in `qualifiers` or `text` | add |
| `Q14_enums` | all enum fields use the controlled vocabulary | fix the value |
| `Q15_relation_evidence` | every relation has a quote | add or drop the relation |
| `Q16_json_schema` | `result.json` matches `schemas/nanopub.schema.json` | fix the named path |

Optional fields (`controlling_quote`, `inference_chain`, `narrative_role`, ...) must be **absent** when empty, not `null`; `finalise` enforces this. Only `qualifiers`, `hedge`, `claimed_by` may be `null`.

## 6. Tooling

| Script | Use |
|---|---|
| `python3 $SKILL_DIR/scripts/np_extract.py <pdf|txt> --out /app/work/text.txt` | Extract per-page text with stable page markers (`=== page N ===`). Uses PyMuPDF if present, else `pdftotext`, else a plain read. |
| `python3 $SKILL_DIR/scripts/np_build.py locate --text /app/work/text.txt --quote "<text>"` | Print `{page, paragraph, sentence, char_offset}` for a quote; exits 1 when not found |
| `python3 $SKILL_DIR/scripts/np_build.py finalise --assertions /app/work/assertions.yaml --relations /app/work/relations.json --doc /app/work/doc.json --text /app/work/text.txt --text-meta /app/work/meta.json --case /input/case.json --out /app/output --status partial` | Fill locators, validate, write `result.json` (contract fields + `case_id` + `nanopub`), `assertions.json`, `assertions.md`, `report.md`. `--relations`, `--doc`, `--text-meta` are optional but pass all three when you have them. Exit 1 when a check fails; read the table it prints |
| `python3 $SKILL_DIR/scripts/np_build.py trig --assertions /app/output/assertions.json --doc /app/work/doc.json --out /app/output/nanopubs.trig` | W3C-Nanopub-shaped TriG (assertion / provenance / publication info graphs) |
| `python3 $SKILL_DIR/scripts/np_validate.py /app/output/result.json --text /app/work/text.txt --schema $SKILL_DIR/schemas/nanopub.schema.json` | Run Q1-Q16 (Q16 = JSON schema, no `jsonschema` package needed), print a table, non-zero exit on failure |

`assertions.yaml` is a short list you write while reading; `finalise` does the rest so you never hand-compute offsets:

```yaml
- id: A1
  text: Compound 3 at 5 mg/kg reduced tumor volume by 48% relative to vehicle.
  claim_type: result
  subject: compound 3
  predicate: reduced
  object: tumor volume
  qualifiers: {condition: "5 mg/kg", metric: "tumor volume", comparator: "vehicle", magnitude: 48, unit: "%"}
  quote: "Treatment with 5 mg/kg compound 3 reduced tumor volume by 48% relative to vehicle."
  relation: direct
  confidence: high
  narrative_role: result
```

## 7. Procedure (one pass)

1. Read `case.json`, `task.md`. Note the question, the reading scope and `output_contract`.
2. `np_extract.py <material> --out /app/work/text.txt --meta /app/work/meta.json` (records `sha256`, backend, pages).
3. Read the in-scope pages in full. Write `/app/work/doc.json` (title, authors, year, doi, venue; `null` when not printed).
4. For each in-scope paragraph run §3.2. Write claims to `/app/work/assertions.yaml` as you go; save early.
5. Write relations (§4) to `/app/work/relations.json` (a JSON list; see `tests/` for the shape).
6. `np_build.py finalise` with the full command from §6. It prints the check table; fix every failed check at its source (the yaml), re-run. Then run `np_validate.py ... --schema $SKILL_DIR/schemas/nanopub.schema.json`; exit 1 means something still fails.
7. `finalise` already wrote `report.md`; add one paragraph on what was not read and why. If the task asks for RDF run `np_build.py trig`.
8. Final `result.json`: fill the `output_contract` fields that need prose (`answer` etc.); set `status = "success"` only when every contract field is filled and all checks pass; keep `"partial"` otherwise and name the limits in `report.md`.

## 8. Failure handling

| Situation | Do | Say |
|---|---|---|
| PDF has no text layer | Run OCR (`ocrmypdf` or `pdftoppm` + `tesseract`) if available; else read page images and type what is visible | `sources.kind = "ocr"`, confidence capped at `medium`, say which pages |
| Material file missing | Do not invent content | `status = "failed"`, `unresolved` reason `source_unavailable` |
| Table unreadable | Extract what is legible | list unreadable cells in `unresolved` as `ambiguous` |
| Quote not found after two fixes | Mark `relation = "inferred"` with chain `from: []`, `rationale: "quote reconstruction failed"` | confidence `low`, note in `report.md` |
| Contract field cannot be filled | Leave the key present with `null` | explain in `report.md` |
| Budget nearly gone (>= 50 requests or >= 750 s) | Stop reading, finalise what exists | `status = "partial"`, list unread scope |
| Source and task disagree (e.g. task asks for data the paper does not report) | Answer from the source only | `unresolved` reason `not_reported`; never fill from outside knowledge |

## 9. Self-check before finishing

- [ ] Every claim has one subject, one predicate, one object.
- [ ] Every quote is found verbatim at its `char_offset`.
- [ ] Every `inferred` claim has a chain whose `from` ids exist.
- [ ] Every `not_reported` item is in `unresolved` with a reason.
- [ ] Numbers and units are as printed; nothing converted.
- [ ] Hedges and negations are preserved in `text`.
- [ ] `result.json` has every `output_contract` field and `case_id`.
- [ ] `report.md` names the scope not read and any OCR pages.
