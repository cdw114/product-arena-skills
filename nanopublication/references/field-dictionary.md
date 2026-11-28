# Field dictionary — nanopub-skill/1.0

Normative definitions for every field in `assertions.json` / `result.json.nanopub`.
Types: `string`, `number`, `bool`, `enum`, `list`, `object`. "Req" = required unless stated.

## Assertion

| Field | Type | Req | Definition | Allowed values / format |
|---|---|---|---|---|
| `id` | string | yes | Stable identifier, unique within the document, in order of first appearance | `A1`, `A2`, ... |
| `text` | string | yes | The atomic claim as one sentence with one predicate; a faithful paraphrase of the source | no facts beyond the source; keep hedges and negations |
| `claim_type` | enum | yes | Kind of claim | `observation`, `definition`, `method`, `result`, `interpretation`, `limitation`, `hypothesis`, `question`, `other` |
| `subject` | string | yes | First word(s) of the S-P-O triple, source terminology | 1-3 words |
| `predicate` | string | yes | Relation asserted by the source verb, source direction | 1-3 words |
| `object` | string | yes | What the predicate applies to | 1-3 words |
| `qualifiers` | object | no | Conditions, population, magnitude that scope the claim | keys below; `null` when absent |
| `qualifiers.population` | string | no | Sample, system, cohort, population | as printed |
| `qualifiers.condition` | string | no | Experimental or clinical condition (dose, temperature, pH, genotype) | as printed, unit included |
| `qualifiers.timeframe` | string | no | Duration or time point | as printed |
| `qualifiers.metric` | string | no | Measured quantity | as printed |
| `qualifiers.comparator` | string | no | Reference against which the claim is made | as printed |
| `qualifiers.magnitude` | number or string | no | Numeric value exactly as printed (no unit conversion, no rounding); string for ranges or "n.d." | |
| `qualifiers.unit` | string | no | Unit exactly as printed | |
| `qualifiers.negated` | bool | no | True when the source negates the predicate | |
| `evidence` | object | yes | Evidence binding | |
| `evidence.quote` | string | yes | Minimal sufficient, contiguous source span | `text[start:end] == quote` for evidence-bearing claims. Empty for `not_reported`. |
| `evidence.locator` | object | yes | Where the quote is | keys below |
| `evidence.locator.page` | number | if located | Physical page, 1-based (PDF page index) | matches `=== page N ===` marker |
| `evidence.locator.paragraph` | number | if located | Paragraph index within the page, 1-based | blank line separates paragraphs |
| `evidence.locator.sentence` | number | if located | Sentence index within the paragraph, 1-based | derived from sentence punctuation |
| `evidence.locator.char_offset` | list or null | yes | `[start, end)` into the whole extracted text | Half-open Unicode code point indices (Python string indices). Null for `not_reported`. |
| `evidence.locator.prefix` / `suffix` | string | no | Adjacent source snippets used to select an occurrence | Matching collapses whitespace. Page, paragraph and sentence can also serve as hints. |
| `evidence.locator.table` | object | no | `{id, row, column}` when the claim comes from a table cell | |
| `evidence.locator.figure` | string | no | Figure id when the claim comes from a caption | |
| `evidence.relation` | enum | yes | How the evidence relates to the claim | `direct`, `inferred`, `not_reported` |
| `evidence.quote_verbatim` | bool | yes | True only when the quote matches the source exactly | |
| `evidence.normalization_note` | string | no | Any reversible normalisation applied (whitespace, ligatures, hyphenation) | |
| `controlling_quote` | string | no | Sentence that limits the claim's scope | verbatim |
| `controlling_quote_scope` | enum | if `controlling_quote` | Which part the controlling quote limits | `scope_of_whole_claim`, `scope_of_part_of_claim` |
| `controlling_quote_locator` | object | if `controlling_quote` | Locator for the scope-setting sentence | Defaults to the main quote's page when drafting. Provide a page hint when it differs. |
| `claimed_by` | string | no | Author of the claim when it reports someone else's work | e.g. `"Smith et al."`; `null` for this paper |
| `hedge` | string | no | The hedging word used by the source | see `controlled-vocabulary.md` |
| `confidence` | enum | yes | Confidence grade per the [controlled vocabulary](controlled-vocabulary.md#confidence) | `high`, `medium`, `low` |
| `confidence_reason` | string | no | One sentence explaining a non-obvious grade | |
| `narrative_role` | enum | no | Role of the claim in the argument | see `controlled-vocabulary.md` |
| `inference_chain` | list | if `inferred` | Steps from source facts to the claim | `[{from: [ids], to: "this", rationale}]`. Every dependency must lead to a direct claim with a verified source span. |
| `supporting_evidence` | list | no | Further quotes backing the same claim | `[{quote, locator}]` |

## Relation

| Field | Type | Req | Definition |
|---|---|---|---|
| `id` | string | yes | `R1`, `R2`, ... |
| `subject` | string | yes | Claim id that plays the role named by `predicate` |
| `predicate` | enum | yes | `supports`, `contradicts`, `refines`, `qualifies`, `depends_on`, `same_as`, `derived_from`, `extends`, `part_of`, `compared_to` |
| `object` | string | yes | Claim id the role is played on |
| `evidence` | object | yes | `{quote, locator}` proving the relation |
| `confidence` | enum | yes | `high`, `medium`, `low` |

## Unresolved

| Field | Type | Req | Definition |
|---|---|---|---|
| `assertion_id` | string | if listed claim | The `not_reported` claim |
| `item` | string | yes | What was expected but not obtained |
| `reason` | enum | yes | `not_reported`, `ambiguous`, `out_of_scope`, `conflicting_evidence`, `source_unavailable`, `quote_not_found`, `unsupported_inference` |
| `detail` | string | no | One sentence |
| `evidence_id` | string | no | Original claim or relation ID and optional evidence role |
| `review_required` | boolean | no | True when the issue needs resolution before completion |
| `quote`, `locator_hint`, `candidates` | string, object, list | no | Submitted evidence and hints followed by candidate source locations, when available |

## Quality (`nanopub.quality`)

| Field | Definition |
|---|---|
| `n_assertions`, `n_relations` | counts |
| `n_direct`, `n_inferred`, `n_not_reported` | counts by `evidence.relation` |
| `n_unique_quotes` | distinct `evidence.quote` strings |
| `avg_quote_words` | mean length of quotes |
| `coverage` | `{paragraphs_total, paragraphs_with_assertion, ratio}` |
| `checks` | `[{id, passed, detail}]` from `np_validate.py` |
| `unresolved_summary` | count per `reason` |

## Document (`nanopub.document`)

`title`, `authors` (list), `year`, `doi`, `venue`, `version`, `identifier_type`, `identifier_value`. Fill only what is printed on the material; otherwise `null`. Do not guess a DOI.
