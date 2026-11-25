#!/usr/bin/env python3
"""
papertrans.translate — Build per-batch translation requests and render the prompt.

Each batch file (batches/B01.json) contains:
  {
    "batch_id": "B01", "target_lang": "zh", "glossary": {term_id: {source, target, abbr}},
    "segments": [{"id": "S001", "role": "body", "page": 1, "context": "...", "masked": "...",
                  "marks": [{"surface": "⟦NUM#0001⟧", "kind": "NUM", "original": "3.5 mg"}], ...}]
  }
The agent translates `masked` → target language, copying every ⟦..⟧ token verbatim, and writes
  translations.json = {"S001": "...", "S002": "..."}
`render_prompt` produces the exact instruction text (so the agent's prompt is deterministic and
auditable rather than improvised).

Placeholder IDs are unique across the WHOLE document (idx_offset accumulates), so a placeholder
from one segment appearing in another is detected as "unexpected".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .protect import protect_text, marks_to_json

PROMPT_TEMPLATE = """You are translating a scientific paper into {lang_name}. The text has been pre-processed:
every number+unit, citation, figure/table/equation reference, inline math expression and glossary-locked
term is replaced by an opaque token like ⟦NUM#0012⟧. These tokens MUST be copied verbatim into the
translation at the position where the original span belongs (respecting {lang_name} word order).
Do NOT translate, transliterate, split, merge, renumber or delete any ⟦..⟧ token.

Glossary (locked; already masked as ⟦TERM#..⟧ — just copy the token):
{glossary_block}

Rules:
1. Translate each segment separately. Output ONLY a JSON object {{"segment_id": "translation", ...}}
   with one entry per input segment id. No commentary, no markdown fences.
2. Keep the register of scientific prose; do not add, omit, summarize or explain content.
3. Translate what the text means, not word-for-word; keep negation, quantifiers, hedging
   (may, suggest, significantly) and logical connectives (however, therefore, whereas) exact.
4. `context` is the end of the previous segment for continuity only — do NOT translate or repeat it.
5. If a span is genuinely untranslatable or ambiguous, keep the source wording and append
   the marker [待确认: 原因] / [UNSURE: reason] right after it. Never silently guess.
6. Keep list-item line breaks (one line per bullet) and heading brevity.
7. Before writing each segment, re-check every ⟦NUM#..⟧/⟦MATH#..⟧: it must sit next to the same quantity or
   predicate as in the source (e.g. "score of X after training for Y days" → X by "score", Y by "days").
   The tokens are opaque; the program can only verify presence and order, not which noun they belong to.
"""


def lang_name(code: str) -> str:
    return {"zh": "Simplified Chinese", "en": "English", "ja": "Japanese", "ko": "Korean",
            "de": "German", "fr": "French", "es": "Spanish"}.get(code, code)


def build_batches(seg: dict[str, Any], glossary: dict[str, Any], out_dir: Path, target_lang: str = "zh",
                  kinds=("TERM", "CITE", "REF", "NUM", "MATH")) -> dict[str, Any]:
    from .glossary import active_terms

    out_dir.mkdir(parents=True, exist_ok=True)
    terms = active_terms(glossary)
    segs_by_id = {s["id"]: s for s in seg["segments"]}
    idx = 0
    batches_out = []
    all_marks: dict[str, list[dict[str, Any]]] = {}
    masked_texts: dict[str, str] = {}
    for b in seg["batches"]:
        items = []
        gids_used: set[str] = set()
        for sid in b["segment_ids"]:
            s = segs_by_id[sid]
            res = protect_text(s["text"], terms, idx_offset=idx, kinds=kinds)
            idx += len(res.marks)
            masked_texts[sid] = res.masked
            all_marks[sid] = marks_to_json(res.marks)
            gids_used.update(m.term_id for m in res.marks if m.kind == "TERM")
            items.append({
                "id": sid, "role": s["role"], "page": s["page"], "pages": s.get("pages"),
                "context": s.get("context", "")[:240],
                "masked": res.masked,
                "marks": [{"surface": m.surface, "kind": m.kind, "original": m.original} for m in res.marks],
            })
        gl_subset = {tid: {k: glossary[tid].get(k) for k in ("source", "target", "abbr", "status")}
                     for tid in sorted(gids_used)}
        gl_lines = []
        for tid, t in gl_subset.items():
            gl_lines.append(f"- {t['source']}  →  {t['target'] or '(keep)'}" + (f"  [{t['abbr']}]" if t.get("abbr") else ""))
        glossary_block = "\n".join(gl_lines) if gl_lines else "(no locked terms in this batch)"
        doc = {
            "batch_id": b["id"], "target_lang": target_lang, "n_segments": len(items),
            "est_tokens": b["est_tokens"], "glossary": gl_subset, "segments": items,
            "prompt": PROMPT_TEMPLATE.format(lang_name=lang_name(target_lang), glossary_block=glossary_block),
        }
        (out_dir / f"{b['id']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"{b['id']}.masked.txt").write_text(
            "\n\n".join(f"[{it['id']}|{it['role']}|p{it['page']}]\n{it['masked']}" for it in items), encoding="utf-8")
        batches_out.append({"id": b["id"], "n_segments": len(items), "est_tokens": b["est_tokens"],
                            "segment_ids": b["segment_ids"], "n_placeholders": sum(len(it["marks"]) for it in items)})
    (out_dir / "marks.json").write_text(json.dumps(all_marks, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "masked.json").write_text(json.dumps(masked_texts, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "PROMPT.txt").write_text(
        PROMPT_TEMPLATE.format(lang_name=lang_name(target_lang), glossary_block="<see batch file glossary>"),
        encoding="utf-8")
    return {"n_batches": len(batches_out), "batches": batches_out, "total_placeholders": idx}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="papertrans.translate")
    ap.add_argument("segments_json")
    ap.add_argument("glossary_json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--lang", default="zh")
    a = ap.parse_args(argv)
    seg = json.loads(Path(a.segments_json).read_text(encoding="utf-8"))
    gl = json.loads(Path(a.glossary_json).read_text(encoding="utf-8"))
    info = build_batches(seg, gl, Path(a.out_dir), a.lang)
    print(f"[translate] batches={info['n_batches']} placeholders={info['total_placeholders']} → {a.out_dir}")
    for b in info["batches"]:
        print(f"  {b['id']}: {b['n_segments']} segs, ~{b['est_tokens']} tok, {b['n_placeholders']} placeholders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
