# Anchor format and verification semantics

Every key note carries an anchor so a reader — or a script — can reopen the source
at that exact place. Anchors are cheap to write and are checked mechanically; an
anchor that cannot be checked is not an anchor.

## 1. Forms

| form | meaning | resolution | coarse? |
|---|---|---|---|
| `p7:b12` | page 7, block 12 (reading order on that page) | exact block; quote must be inside its text | no |
| `p7` | page 7 only | page must exist; no text check | **yes** |
| `s3.2` | section 3.2 | section must exist in `skeleton.json` | **yes** |
| `F2`, `T1` | figure 2, table 1 | figure/table id from the skeleton's `figures` list | **no** |

- Page and block indices are **1-based**; block index counts in the reading order
  produced by the extractor (column-major on multi-column pages).
- `p7:b12` uses a colon. A hyphen (`p7-b12`) or a space is rejected.
- Only `p{page}:b{block}` plus a quote counts as a **verified** anchor. `p7`,
  `s3.2` are accepted but reported as coarse, and a note whose only evidence is
  coarse does not count as verified for the run status.

## 2. Quote rules

- 12–300 characters, copied **verbatim** from that block.
- Matching is whitespace-normalised and hyphenation-normalised:
  `attention weights` = `attention\nweights`; `multi-head` = `multihead` is **not**
  equal (medial hyphens inside a word are handled, line-break hyphens are removed).
- Punctuation beyond the block's own text is ignored on both sides; a paraphrase
  fails. That is the point.
- A quote may be a fragment (first half of a long paragraph). It must not span two
  blocks — pick the block that actually contains the words.

## 3. How much evidence

| claim | evidence needed |
|---|---|
| section note | 1–3 anchors covering its key claim |
| card field | ≥1 anchor per distinct number or condition; 2 when the value combines two places |
| knowledge point | ≥1 block anchor |
| answer to a task question | ≥1 block anchor per part of the answer |

Prefer `main_findings` numbers quoting the results block, not the abstract: the
abstract is a coarser restatement and is where rounding mismatches come from.

## 4. What the validator reports

`build_notes.py` writes `validation.json`:

| key | meaning |
|---|---|
| `anchors_checked` | total anchors seen |
| `anchors_ok` | resolved and quote verified |
| `anchors_coarse` | resolved but page/section only |
| `anchors_failed` | unresolved, out-of-range, or quote not found |
| `failures[]` | each failure with `where`, `anchor`, `quote`, `issues` |
| `coverage` | sections covered/total, card fields filled, figures referenced, kp count |
| `dup_kp_ids`, `dup_kp_terms` | duplicate knowledge points |

Run status rules: any failed anchor or >25% missing body sections forces
`partial`; nothing usable forces `refused`.

## 5. Why block anchors and not character offsets

Character offsets break the moment a PDF is re-extracted by another tool version,
and page-only anchors cannot be checked at all. A block id is stable within one
extraction, survives re-reading, and — combined with a verbatim quote — lets any
checker prove the claim is really there without trusting the note writer.
