# Worked example — **EXAMPLE ONLY**

> This is a trimmed, illustrative example of the skill's output on a synthetic
> two-section fixture (`scripts/selftest.py` builds the same one). It is **not** a
> case answer, and its paper does not exist. Do not copy it as a result.

## Input

```bash
bash scripts/run.sh extract fixture.pdf /app/work
# -> /app/work/skeleton.json, sections.md, extract_report.json
```

`sections.md` excerpt (the `[page:block|kind]` prefixes are the anchors):

```
## s1 1 Introduction  (pp.1–1, anchor p1:b0)

[p1:b0|heading] 1 Introduction

[p1:b1|paragraph] Most sequence models rely on recurrence, which prevents parallel
training within a sequence.

[p1:b2|paragraph] We propose a network architecture based solely on attention mechanisms.
```

## The draft the agent writes

```json
{
  "run_status": {"status": "success"},
  "paper_card": {
    "research_question": {
      "value": "Whether attention alone suffices without recurrence.",
      "source": "reported",
      "evidence": [{"anchor": "p1:b1", "quote": "Most sequence models rely on recurrence"}]
    },
    "data": {"value": null, "source": "not_reported"},
    "method": {
      "value": "Attention over scaled dot products.",
      "source": "reported",
      "evidence": [{"anchor": "p2:b1", "quote": "softmax over scaled dot products"}]
    }
  },
  "sections": [
    {
      "sid": "s1",
      "purpose": "Motivate dropping recurrence.",
      "conclusion": "Recurrence blocks parallelism.",
      "link_to_previous": "opening section",
      "evidence": [{"anchor": "p1:b1", "quote": "prevents parallel training"}]
    },
    {
      "sid": "s2",
      "purpose": "Define attention.",
      "evidence": [{"anchor": "p2:b1", "quote": "softmax over scaled dot products"},
                   {"anchor": "F1", "quote": null}]
    }
  ],
  "knowledge_points": [
    {"id": "KP-001", "term": "Self-attention", "aliases": ["intra-attention"],
     "type": "concept", "statement": "Attention within one sequence.",
     "evidence": [{"anchor": "p1:b2", "quote": "solely on attention"}]},
    {"id": "KP-002", "term": "Scaled dot-product attention", "type": "method",
     "statement": "Softmax over scaled dot products.",
     "evidence": [{"anchor": "p2:b1", "quote": "scaled dot products"}]}
  ],
  "answers": [{"qid": "Q1", "question": "What replaces recurrence?",
               "answer": "Attention.",
               "evidence": [{"anchor": "p1:b2", "quote": "attention mechanisms"}]}]
}
```

## The validator's verdict

```bash
bash scripts/run.sh validate /app/work /app/output
```

```
{
 "status": "success",
 "problems": [],
 "anchors_checked": 9, "anchors_ok": 9, "anchors_coarse": 0, "anchors_failed": 0,
 "coverage": {"body_sections_total": 2, "body_sections_covered": 2,
              "card_fields_filled": 8, "card_fields_total": 8,
              "figures_total": 1, "figures_referenced": 0,
              "knowledge_points": 2}
}
```

## Output excerpt (`/app/output/notes.md`)

```markdown
Run status: **success** — ok
Anchor check: 9/9 ok (0 coarse) · 0 failed

## 1. Paper card

| field | value | source | evidence |
|---|---|---|---|
| research_question | Whether attention alone suffices without recurrence. | reported | `p1:b1` p.1 |
| data | — | not_reported | — |

## 2. Section-by-section notes (2/2 body sections)

### §1 Introduction (s1, pp.1–1)

- **purpose**: Motivate dropping recurrence.
- **conclusion**: Recurrence blocks parallelism.
- **link_to_previous**: opening section
- **evidence**: `p1:b1` p.1 “prevents parallel training…”
```

## What a failing variant looks like

Changing the first quote to a paraphrase makes the validator refuse it:

```json
"evidence": [{"anchor": "p1:b1", "quote": "recurrence stops you training in parallel"}]
```

```
"anchors_failed": 1,
"failures": [{"where": "section:s1", "anchor": "p1:b1",
              "issues": ["quote not found in anchored block"]}],
"status": "partial"
```

That downgrade is the point: a claim whose text is not in the paper does not get
to pass as a verified note.
