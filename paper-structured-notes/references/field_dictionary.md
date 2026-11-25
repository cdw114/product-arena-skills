# Field dictionary

Two record types are filled per paper: the **paper card** (one row set, identical
fields for every paper so several papers can sit side by side) and **knowledge
points** (searchable entries). Both use the anchor rules in `anchor_format.md`.

## 1. Paper card fields

| field | what belongs there | typical anchor | source value |
|---|---|---|---|
| `research_question` | The question or hypothesis the authors say they address. Quote their framing; do not restate it in your own research vocabulary. | abstract or intro, last paragraph | `reported` |
| `data` | Dataset / sample / cohort: name, size, source, time span, inclusion or filtering rules, splits. For a methods paper with no dataset, record what was evaluated on. | methods, experiments, data section | `not_reported` if genuinely absent |
| `method` | Pipeline, model, algorithm, instrument or procedure. Include the conditions that make it work: hyper-parameters, resolution, thresholds, software versions, assumptions. | methods, model, setup section | `reported` |
| `main_findings` | The principal results, with numbers **and units**, and against what comparator (baseline, control, previous best). One finding per sentence. | results, main text | `reported` |
| `conclusion` | What the authors conclude, as they put it. Keep their strength of claim ("suggests" vs "demonstrates"). | discussion, conclusion | `reported` |
| `limitations` | Limitations the authors state, plus conditions that bound the claim. If the paper states none, `source: not_reported` with an empty value — this is a real finding, not a gap in your reading. | discussion, limitations, appendix | `reported` / `not_reported` |
| `scope_conditions` | The setting in which the conclusion holds: population, site, scale, regime, language, temperature/pressure range, model size. The precondition that, if changed, voids the claim. | anywhere the setting is defined | `reported` |
| `open_questions` | Future work and unresolved items, as stated. | conclusion, discussion | `reported` / `not_reported` |

### Field entry shape

```json
"method": {
  "value": "Transformer: 6 encoder/decoder layers, d_model=512, 8 heads, trained on WMT 2014 En-De (4.5M sentence pairs) for 100k steps.",
  "source": "reported",
  "evidence": [
    {"anchor": "p3:b12", "quote": "we use a stack of 6 identical layers"},
    {"anchor": "p7:b4", "quote": "trained for a total of 100,000 steps or 12 hours"}
  ]
}
```

Rules:
- `source` ∈ `reported` | `not_reported` | `uncertain` | `conflicting`.
- `not_reported` → `value: null`, no evidence needed; the field still must appear.
- `uncertain` → a value plus a `note` saying why (ocr damage, ambiguous wording,
  value only in a figure you could not read).
- `conflicting` → a value plus a `note` naming both places and what differs.
  Never silently pick one of two numbers the paper reports differently.
- Two evidence anchors beat one when the field combines numbers from two places.

## 2. Section note fields

| field | meaning |
|---|---|
| `sid` | Skeleton section id (`s3.2`, `h24`) — must exist in `skeleton.json`. |
| `purpose` | What this section is for in the paper's argument. |
| `method` | What was done here (experiment, derivation, setup). Empty if the section is not about doing something. |
| `results` | What came out, with numbers. Empty if none. |
| `conclusion` | What the section establishes. |
| `link_to_previous` | How it follows from the previous section — "resolves the cost problem raised in §3.2", "tests the claim from §4 on a second task". |
| `limitations` | Section-local caveats. |
| `figures` | Figure/table ids discussed here (`F1`, `T2`). |
| `not_reported` | What a reader would expect here but the section does not give. |
| `evidence` | 1–3 `{anchor, quote}` pairs for the section's key claims. |

## 3. Knowledge point fields

| field | meaning |
|---|---|
| `id` | `KP-001` style, unique in the note set. |
| `term` | The preferred surface form used in the paper. |
| `aliases` | Abbreviations, synonyms, the other-language form. This is where duplicates get absorbed. |
| `type` | `concept` \| `variable` \| `method` \| `finding` \| `metric` \| `dataset`. |
| `statement` | One sentence that is true according to the paper. |
| `conditions` | When the statement applies. |
| `related` | Other `KP-` ids. |
| `evidence` | At least one block anchor + quote. |

Merge rule: same idea under two names → one entry, the second name goes in
`aliases`. Different ideas under the same word (e.g. "attention" as a mechanism vs
as a measured weight) → separate entries whose `statement` disambiguates.
