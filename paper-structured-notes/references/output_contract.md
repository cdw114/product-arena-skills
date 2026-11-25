# Output contract

## 1. Required file

`/app/output/result.json`. Always written, including on refusal, so the grader
never finds an empty output directory.

```json
{
  "case_id": "string  — from case.json when present, else the output dir name",
  "input": {
    "case_json": {},                  // echoed as read, so the run is traceable
    "source_pdf": "absolute path",
    "pages": 15,
    "heading_method": "outline | outline+font | font-size+pattern | none"
  },
  "run_status": {
    "status": "success | partial | cannot_determine | refused",
    "reason": "string or null",
    "problems": ["..."],
    "generated_at": "ISO 8601 UTC",
    "skill": "paper-structured-notes",
    "stage": "build_notes"
  },
  "result": {
    "paper_card": [
      {"field": "research_question", "description": "...", "status": "filled|missing",
       "value": "...", "source": "reported|not_reported|uncertain|conflicting",
       "evidence": [{"anchor": "p2:b1", "quote": "...", "page": 2, "verified": "ok|failed"}],
       "note": null}
    ],
    "sections": [
      {"sid": "s3.2", "purpose": "...", "method": "...", "results": "...",
       "conclusion": "...", "link_to_previous": "...", "limitations": "...",
       "figures": ["F2"], "not_reported": null,
       "evidence": [{"anchor": "...", "quote": "...", "page": 5, "verified": "ok"}]}
    ],
    "knowledge_points": [
      {"id": "KP-001", "term": "...", "aliases": [], "type": "...",
       "statement": "...", "conditions": "...", "related": [], "evidence": [...]}
    ],
    "answers": [
      {"qid": "Q1", "question": "...", "answer": "...", "evidence": [...]}
    ],
    "figures_in_paper": [{"fid": "F1", "kind": "figure", "number": "1",
                          "caption": "...", "anchor": "p3:b0", "page": 3}],
    "figures_referenced": ["F2", "T1"]
  },
  "evidence": {
    "anchor_format": "p{page}:b{block} ...",
    "verification": {"anchors_checked": 0, "anchors_ok": 0, "anchors_coarse": 0,
                     "anchors_failed": 0, "failures": []},
    "coverage": {"body_sections_total": 0, "body_sections_covered": 0,
                 "sections_missing": [], "unknown_section_ids": [],
                 "card_fields_filled": 0, "card_fields_total": 8,
                 "figures_total": 0, "figures_referenced": 0,
                 "knowledge_points": 0},
    "section_map": [{"sid": "s1", "number": "1", "title": "Introduction",
                     "pages": [2, 2], "anchor": "p2:b0"}]
  },
  "uncertainty": {
    "not_reported_fields": [], "uncertain_fields": [], "conflicting_fields": [],
    "unverified_items": [], "duplicate_kp_ids": [], "duplicate_kp_terms": [],
    "figures_without_caption_read": [], "agent_declared": [],
    "notes_on_extraction": []
  },
  "change_log": []
}
```

## 2. Companion files

| file | role |
|---|---|
| `notes.md` | the same content for a human reader; section headings mirror the paper |
| `validation.json` | the audit: anchors checked/failed, coverage counts, duplicate knowledge points |
| `work/skeleton.json` | kept in the work dir (not the output dir) — cite it if a grader asks how sections were cut |

## 3. When the case supplies its own output_contract

`/input/case.json` may define the fields it wants. Then:

1. Keep every field name it defines, at the top level of `result.json`.
2. Keep the `run_status`, `evidence`, `uncertainty`, `change_log` blocks — they
   are additive and never conflict with a case contract.
3. Put the case's own fields under `result` **and** mirror them at the top level
   only if the contract shows them at the top level.
4. Never delete a case field because it looked unanswerable: fill it with
   `null` + an `uncertainty` entry saying why.

## 4. Status discipline

| status | when |
|---|---|
| `success` | every body section noted, card complete (`filled` or `not_reported`), `anchors_failed == 0` |
| `partial` | usable content but any failed anchor, missing sections, or declared gap |
| `cannot_determine` | material present but the asked question is not answerable from it |
| `refused` | material missing, encrypted, or no text layer and no OCR |

A `partial` with precise reasons scores better than a `success` that a checker
disproves. Do not relabel: the validator already forces `partial` on failed
anchors.
