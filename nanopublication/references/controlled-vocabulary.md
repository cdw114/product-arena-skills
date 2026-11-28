# Controlled vocabulary — nanopub-skill/1.0

Every enum field must use exactly one value from this file. Unknown values fail `Q14_enums`.

## claim_type

| Value | Use for |
|---|---|
| `observation` | Something measured or seen (spectra, counts, images) |
| `definition` | A term or quantity defined by the authors |
| `method` | Procedure, material, instrument, parameter choice |
| `result` | A measured or computed outcome compared to nothing or to a comparator |
| `interpretation` | Authors' explanation of a result (mechanism, reason) |
| `limitation` | Stated weakness or caveat |
| `hypothesis` | Proposed explanation not tested here |
| `question` | Open question posed by the authors |
| `other` | None of the above (say why in `confidence_reason`) |

## narrative_role

`background`, `gap`, `objective`, `method`, `result`, `conclusion`, `limitation`, `future_work`, `other`

## evidence.relation

| Value | Meaning |
|---|---|
| `direct` | S-P-O, numbers, units and conditions each appear in the quote |
| `inferred` | Needs reasoning steps using only source facts + arithmetic/logic; `inference_chain` required |
| `not_reported` | Source does not say it; listed in `unresolved` |

## predicate (relation between claims)

| Value | Direction convention | Example |
|---|---|---|
| `supports` | subject is evidence for object | A3 (dose-response) supports A1 (efficacy) |
| `contradicts` | subject and object cannot both hold as stated | abstract vs body numbers |
| `refines` | subject narrows object | A5 (subtype-specific effect) refines A2 (general effect) |
| `qualifies` | subject states a condition under which object holds | A4 (only in p53-WT) qualifies A1 |
| `depends_on` | subject depends on the method, input or result in object | A7 (IC50) depends_on A6 (assay) |
| `same_as` | identical S-P-O and qualifiers | abstract vs body restatement |
| `derived_from` | subject is calculated from object | A9 (fold change) derived_from A8 (raw values) |
| `extends` | subject generalises object beyond its stated scope | A11 extends A10 |
| `part_of` | subject is a component of object | A12 part_of A13 |
| `compared_to` | subject is measured against object | A14 compared_to A15 |

## confidence

| Value | Condition (all of) |
|---|---|
| `high` | `direct`, `quote_verbatim=true`, no hedge, numbers/units verbatim |
| `medium` | `direct` with hedge; or `inferred` with chain using only source facts + arithmetic/logic; or abstract-only evidence |
| `low` | `inferred` with an assumption; or `not_reported`; or unresolved conflict |

## hedge words

`may`, `might`, `could`, `can`, `suggest`, `suggests`, `suggested`, `associated with`, `likely`, `possibly`, `appear`, `appears`, `tends`, `relatively`, `somewhat`, `putative`, `potentially`, `reportedly`, `whether`, `remains unclear`

## unresolved.reason

| Value | Use when |
|---|---|
| `not_reported` | Task asks for something the material does not state |
| `ambiguous` | Material is unclear (unreadable table, conflicting wording) |
| `out_of_scope` | Requested item lies outside the reading scope given in task.md |
| `conflicting_evidence` | Two passages disagree and cannot be resolved from the text |
| `source_unavailable` | Material missing or unreadable |
| `quote_not_found` | A submitted quote could not be located in the extracted text |
| `unsupported_inference` | A deduction lacks an acyclic chain of claims grounded in source evidence |

## Split triggers (when a sentence must be split)

| Trigger | Example | Result |
|---|---|---|
| multiple subjects | "X and Y both increased" | 2 claims |
| multiple predicates | "X increased and caused Y" | 2 claims |
| causal chain | "A causes B causes C" | A->B, B->C |
| coordinated clauses | "assays ran at pH 7.4, and cells grew at 37 C" | 2 claims |
| condition as finding | "only when p53 is intact" | own claim + `qualifies` |
| contrast with values | "48% vs 12% reduction" | 1 claim per value + `compared_to`; the comparison itself kept as `qualifiers.comparator` when only one side has a value |
