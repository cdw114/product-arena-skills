# Graph schema (v1)

Graph file: a single JSON object `{"nodes": [...], "edges": [...]}`. Scripts in `scripts/` read and write this; `assemble_result.py` embeds it in `result.json`.

Node and edge ids are stable strings `N:<type>:<slug>` / `E:<type>:<src-slug>-><dst-slug>`. **Never renumber existing ids on incremental update** — new nodes get new ids, merged nodes keep the id of the first-seen node and record the absorbed id in `merged_from`.

## Node

| field | type | required | meaning |
|---|---|---|---|
| `id` | string | yes | `N:<type>:<slug>` |
| `type` | enum | yes | `researcher` `institution` `material` `method` `task` `model` `metric` `dataset` `conclusion` `condition` `other` |
| `canonical_name` | string | yes | the name as it appears in the *first* paper that mentions it; no invented names |
| `aliases` | string[] | yes (may be `[]`) | every other surface form found in the corpus, including unmerged ones |
| `definition` | string | yes (may be `""`) | one sentence paraphrase; **no numbers** unless they appear in a quote; for third-party reported facts start with `As reported by <source_id>: ` |
| `evidence` | evidence[] | yes, ≥1 | see below |
| `sources` | string[] | auto | distinct `source_id`s over evidence (set by scripts) |
| `first_seen` | string | yes | `source_id` of the earliest evidence (must be one of `sources`) |
| `attribution` | enum | yes | `author` (paper's own claim) / `cited` (paper reports others' work) / `background` (generic) |
| `confidence` | enum | yes | `high` / `medium` / `low` |
| `merged_from` | string[] | when merged | ids absorbed by alignment |
| `merge_basis` | string[] | when merged | subset of `same_explicit_name` `same_definition` `same_citation` `compatible_conditions` `class_instance_pattern` |
| `provenance` | object | auto | `{"extraction": "llm", "verified_by": "scripts/graph_op.py"}` |

## Edge

| field | type | required | meaning |
|---|---|---|---|
| `id` | string | yes | `E:<type>:<src>-><dst>` |
| `type` | enum | yes | see relation catalogue |
| `src`, `dst` | node id | yes | direction: `src` is the grammatical subject of the evidence sentence |
| `evidence` | evidence[] | yes, ≥1 | |
| `conditions` | string | yes (may be `""`) | paper-local conditions copied from the context (sample, hyper-params, population). **Never combined across papers** |
| `metric`, `value` | string/number | for `reports_value` only | the reported number *as written* (keep units/significance in `conditions`) |
| `evidence_strength` | enum | yes | `direct` / `indirect` (never create from `cooccurrence_only`) |
| `attribution` | enum | yes | as node |
| `confidence` | enum | yes | |
| `cross_paper` | bool | auto | true when evidence spans ≥2 source_ids |

## Evidence item

```json
{"source_id": "10.xxx/yyy", "paragraph_id": "pa-012", "quote": "verbatim text", "attribution": "author", "evidence_strength": "direct"}
```

- `source_id`: one of the `corpus-manifest.json` ids. Never the case root DOI for a secondary paper.
- `paragraph_id`: the organizer's JATS paragraph id exactly as given. **Not a PDF page.** If the bundle has no page numbers, no `page` field is written at all.
- `quote`: exact substring of the paragraph text (tolerant to whitespace, curly quotes and dashes). Scripts refuse anything else.
- Inline math is linearized in the paragraph text; copy it as-is. Use `secondary-publisher.xml` only to verify a linearized formula, and note it in `uncertainties` with `reason: linearized_math`.

## Relation catalogue

| type | direction | example |
|---|---|---|
| `uses` | method → data/model | "we fine-tune RoBERTa on SST-2" |
| `evaluated_on` | model/method → dataset | |
| `proposed_by` | method/model → researcher (or paper) | |
| `compared_with` | A → B (A is the subject) | |
| `outperforms` | A → B, **requires a direct comparison statement** | |
| `supports` | evidence/result → conclusion | |
| `contradicts` | A ↔ B (conflicting values) | also listed in `merge_conflicts` |
| `extends` | B → A (B extends A) | |
| `cites` | paper/node → paper/node | |
| `reports_value` | node → metric (with `value`, `conditions`) | paper-local, never merged |
| `measures` | metric/task → thing measured | |
| `instance_of` | specific model/sample → class node | used for generic terms across papers |
| `related_to` | any, for kept-separate alignment pairs | confidence low |
| `hypothesizes` | author → claim | future work / "may" statements, confidence low |

Add a type only if `task.md` requires it; record it in `change_log`.
