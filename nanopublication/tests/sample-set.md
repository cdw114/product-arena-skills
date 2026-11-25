# Sample set — 20 claim-sentence patterns with the expected treatment

| # | Source pattern | Expected treatment |
|---|---|---|
| 1 | "X and Y both increased" | split: 2 claims |
| 2 | "X increased and caused Y" | split: "X increased" + "X caused Y" |
| 3 | "A causes B causes C" | split: A->B, B->C |
| 4 | "assays ran at pH 7.4, and cells grew at 37 C" | split: 2 claims |
| 5 | "only when p53 was intact" | own claim + `qualifies` on the main claim |
| 6 | "reduced by 48% relative to vehicle" | 1 claim; comparator in qualifiers |
| 7 | "48% vs 12% reduction" | 2 value claims + `compared_to` |
| 8 | "no significant difference (p = 0.41)" | 1 claim, negated=true, p in qualifiers |
| 9 | "may inhibit MEK" | hedge=may, confidence<=medium |
| 10 | "Smith et al. reported IC50 = 3.2 uM" | claimed_by, background |
| 11 | "several patients responded" | keep "several", no number |
| 12 | "IC50 = 3.2 uM" | 1 claim, do not split |
| 13 | table cell "compound 3 / 1.1" | 1 claim per cell, locator.table |
| 14 | "in vitro, ..." | condition in qualifiers; if in another sentence -> controlling_quote |
| 15 | abstract repeats body | body evidence, abstract -> supporting_evidence, same_as |
| 16 | "Section 3 describes" | skip |
| 17 | "the mechanism remains unclear" | claim_type=question or limitation, hedge |
| 18 | "twofold higher than A" | derived_from A if values given, else direct with comparator |
| 19 | "not reported" in task | not_reported + unresolved |
| 20 | OCR page | confidence<=medium, note in report |

Rows 1-4: validator Q2 (compound text). Rows 6,8,9,12: Q12/Q13. Row 13: locator.table.
