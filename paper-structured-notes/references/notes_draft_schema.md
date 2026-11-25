# notes_draft.json — the file the agent writes

`build_notes.py` reads exactly this shape. All keys are optional except
`run_status`; missing keys degrade to empty, and the validator then reports low
coverage instead of failing silently.

```json
{
  "run_status": {"status": "success", "reason": null},

  "paper_card": {
    "research_question": {"value": "...", "source": "reported",
                          "evidence": [{"anchor": "p1:b4", "quote": "..."}]},
    "data":             {"value": "...", "source": "reported", "evidence": [...]},
    "method":           {"value": "...", "source": "reported", "evidence": [...]},
    "main_findings":    {"value": "...", "source": "reported", "evidence": [...]},
    "conclusion":       {"value": "...", "source": "reported", "evidence": [...]},
    "limitations":      {"value": null, "source": "not_reported"},
    "scope_conditions": {"value": "...", "source": "reported", "evidence": [...]},
    "open_questions":   {"value": "...", "source": "reported", "evidence": [...]}
  },

  "sections": [
    {
      "sid": "s3.2",
      "purpose": "Introduce attention as the sole mixing mechanism.",
      "method": "",
      "results": "",
      "conclusion": "Attention replaces recurrence entirely.",
      "link_to_previous": "Solves the sequential-computation cost raised in §3.1.",
      "limitations": "",
      "figures": ["F2"],
      "not_reported": null,
      "evidence": [{"anchor": "p3:b5", "quote": "..."}]
    }
  ],

  "knowledge_points": [
    {"id": "KP-001", "term": "Self-attention", "aliases": ["intra-attention"],
     "type": "concept", "statement": "...", "conditions": "...",
     "related": ["KP-002"], "evidence": [{"anchor": "p3:b7", "quote": "..."}]}
  ],

  "answers": [
    {"qid": "Q1", "question": "What replaces recurrence?",
     "answer": "...", "evidence": [{"anchor": "p2:b1", "quote": "..."}]}
  ],

  "uncertainty": ["Figure 3 was a raster image; the axis values could not be read."],
  "extraction_notes": ["Skeleton used the PDF outline; Appendix B merged into References."],
  "change_log": ["v1: initial notes", "v2: added §5.4 after re-reading p.8"]
}
```

## Field-by-field

| key | type | rules |
|---|---|---|
| `run_status.status` | string | `success` \| `partial` \| `cannot_determine` \| `refused`. The validator may downgrade `success` to `partial` when checks fail; it never upgrades. |
| `run_status.reason` | string\|null | required when status is not `success` |
| `paper_card.*` | object | all eight field names from `field_dictionary.md`; each with `value`, `source`, `evidence` |
| `paper_card.*.source` | enum | `reported` \| `not_reported` \| `uncertain` \| `conflicting` |
| `sections[].sid` | string | must exist in `skeleton.json` — a typo is reported under `coverage.unknown_section_ids` and the note is dropped from coverage |
| `sections[].evidence` | array | 1–3 `{anchor, quote}`; `[]` is allowed but the item counts as unverified |
| `knowledge_points[].id` | string | unique; `KP-001` style |
| `knowledge_points[].aliases` | array | absorbs synonyms (this is how duplicates are avoided) |
| `answers[].qid` | string | the task's question id when it has one, else `Q1`, `Q2`… |
| `uncertainty` | array of strings | anything a human must confirm |

## Minimal valid draft

```json
{"run_status": {"status": "refused", "reason": "PDF is a scan and OCR is unavailable"}}
```
This is honoured: `build_notes.py` exits 2 and still writes a `result.json` that
records the refusal, so a failure is machine-readable rather than an empty folder.
