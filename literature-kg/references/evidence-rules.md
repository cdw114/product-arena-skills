# Evidence rules and cross-paper alignment guide

This is the rulebook the Skill applies. Every example is illustrative (示例), not a case answer.

## 1. What counts as evidence

| situation | allowed? | how to record |
|---|---|---|
| Paper A: "We fine-tuned BERT on SST-2 and obtained 92.1 %." | yes, direct | node `model:BERT`, edge `evaluated_on(BERT, SST-2)`, edge `reports_value(BERT, accuracy) value="92.1 %"` conditions from the same paragraph |
| Paper B (related work): "Devlin et al. reported 92.1 % with BERT." | yes, but **cited** | node with `attribution: cited`, `confidence: low`; `definition` starts "As reported by <B>: …" — never as B's own result |
| Paragraph mentions "BERT" and "SST-2" in different sentences, no relation stated | **no edge** | co-occurrence is not evidence |
| "Future work may apply X to Y." | only as `hypothesizes` | `confidence: low`, `evidence_strength: indirect` |
| Figure shows a value; text does not state it | **no** | `unreported: ["value shown only in Fig. 3; pixel data not provided"]` |
| A number appears only in supplementary material | **no** | `unreported` |
| Two papers give different numbers for the same aligned object | yes, both | two `reports_value` edges + `contradicts` edge + `merge_conflicts` entry; **never average** |

Quote discipline: a quote is copied, not paraphrased. If the sentence is long, quote the clause that carries the relation (20–200 chars). If you cannot copy a clause that states the relation, you do not have evidence for the relation.

## 2. Identity tests for cross-paper alignment

`scripts/align_candidates.py` proposes pairs. For each pair answer T1–T4 **from quotes**, then decide:

```
T1  same real-world object?     (same model instance / dataset release / material batch / task definition / person)
T2  same conditions/samples?    (population, sample size, hyper-params, measurement protocol)
T3  definitions agree?         (or one paper is silent)
T4  value conflict?            (different numbers for the same metric)
```

| T1 | T2 | T3 | T4 | decision | what you write |
|---|---|---|---|---|---|
| yes | yes | yes | no | **merge** | `merge_basis: [same_explicit_name, same_definition, compatible_conditions]` |
| yes | differs | yes | maybe | **merge object, keep conditions apart** | merge_basis without `compatible_conditions`; each `reports_value` edge keeps its own `conditions`; T4 conflict → `merge_conflicts` + `contradicts` |
| yes | differs | differs | — | **merge only if** the object is clearly named the same (e.g. a public dataset) and the difference is in use, not in definition; otherwise **uncertain** | record why |
| no (same name, different object — e.g. two cohorts both called "validation set") | — | — | — | **keep_separate** | `related_to` edge, `merge_conflicts.kind: different_object` |
| generic term ("CNN", "transformer", "PLA", "serum") | — | — | — | **class/instance pattern** | merge as a *class* node only when both papers use it as a class; keep per-paper instance nodes `N:model:cnn@<source>` with `instance_of` edges to the class |

Hard rules:
- Same generic method/material term ≠ same physical sample, model instance, dataset or condition.
- Same paper in two formats (JSON + Markdown + XML) ≠ cross-paper evidence. One `source_id`.
- Do not force every alias to merge. A paper-local alias with no counterpart stays local.
- Never combine two papers' conditions, samples or numeric results into one conclusion. A "consensus" is only ever a list of per-paper `reports_value` edges; if they differ, say `consensus_status: not_formed`.
- Case root DOI / title / authors belong to the **primary** paper. Never copy them onto a secondary node or source record.

## 3. Positions

- Position = `source_id` + `paragraph_id` (JATS ids supplied by the organizer).
- The bundle has no PDF pages. **Never write `page: 1`** or call a JATS id a page. If a paragraph carries a `page` field in the input, keep it and mark `page_source: "input"`; otherwise omit the field.
- Inline formulas are linearized (`x^2` → `x2` or similar). Copy the linearized form. Verify against `secondary-publisher.xml` if present; note `reason: linearized_math`.

## 4. Evidence strength

- `direct`: the quote states the fact/relation explicitly.
- `indirect`: inferred from two sentences, a review sentence, or hedged language.
- Never emit an edge with `cooccurrence_only`.

## 5. Status vocabulary

| status | when |
|---|---|
| `success` | all task-required entity/relation types, ≥3 queries, evidence verified, no unresolved contract field |
| `partial` | something is missing: a file, a required entity type not found, budget exhausted, queries unresolvable, unverified quotes dropped |
| `not_determinable` | the task cannot be answered from the materials at all (e.g. only scanned PDF with no OCR tool) |
| `refused` | the task asks to fabricate data not in the corpus |

`status_reason` must say what is partial and where a human should take over.

## 6. Worked alignment examples (illustrative)

**A. Merge, compatible.** Paper P: "we evaluate on SST-2 (Socher et al., 2013)". Paper S: "the Stanford Sentiment Treebank (SST-2) is used as the test set". → T1 yes (public dataset, same citation/name), T2 compatible, T3 agree. Merge `N:dataset:sst-2`; aliases `["SST-2", "Stanford Sentiment Treebank"]`; `merge_basis: [same_explicit_name, same_citation, compatible_conditions]`.

**B. Merge object, conditions conflict.** P: "RoBERTa-large achieved 94.8 % on SST-2 (10k training samples)". S: "RoBERTa reached 92.3 % on SST-2 (1k samples)". → merge `model:roberta` (T1 yes), **not** `compatible_conditions`; two `reports_value` edges, `contradicts` edge, `merge_conflicts.kind: value_conflict`, resolution `merged_with_conditions_recorded`.

**C. Keep separate.** P: "the validation set (n=500)". S: "our validation split contains 200 patients". → both say "validation set" but T1 no. Keep separate; `related_to` edge; `merge_conflicts.kind: different_sample`.

**D. Class/instance.** P: "a 3-layer CNN encoder". S: "we use a CNN with residual blocks". → class node `N:model:cnn` (merged, generic), instances `N:model:cnn@P`, `N:model:cnn@S` with `instance_of` → class. No claim that the two CNNs are the same model.

**E. Same paper twice.** `primary-material.json` and a Markdown rendering of it. → one `source_id`; `sources[].duplicate_formats: ["primary.md"]`; not a cross-paper node.
