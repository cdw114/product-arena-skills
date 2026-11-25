#!/usr/bin/env python3
"""Find paragraphs by regex / keyword — read only what you need (budget-friendly).

Usage:
  python scripts/find_paragraphs.py --pattern "fine-tun|learning rate" [--source ID] [--section "Methods"] [--max 40] [--width 220]
  python scripts/find_paragraphs.py --section "Abstract" --source ID          # whole section listing
  python scripts/find_paragraphs.py --id pa-12                                # print one paragraph in full
  python scripts/find_paragraphs.py --sections                               # list section paths per source with counts
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import load_paragraphs, WORK  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern")
    ap.add_argument("--id")
    ap.add_argument("--section")
    ap.add_argument("--source")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--width", type=int, default=220)
    ap.add_argument("--sections", action="store_true")
    ap.add_argument("--para-dir", default=None)
    a = ap.parse_args()
    paras = load_paragraphs(a.para_dir or WORK / "paragraphs")

    if a.sections:
        agg = {}
        for (sid, pid), p in paras.items():
            agg.setdefault(sid, {}).setdefault(p.get("section_path") or "(none)", 0)
            agg[sid][p.get("section_path") or "(none)"] += 1
        for sid, secs in agg.items():
            print(f"== {sid}")
            for s, c in secs.items():
                print(f"   {c:>3}  {s}")
        return

    rows = list(paras.values())
    if a.source:
        rows = [p for p in rows if p["source_id"] == a.source]
    if a.id:
        rows = [p for p in rows if p["paragraph_id"] == a.id]
    if a.section:
        rx = re.compile(a.section, re.I)
        rows = [p for p in rows if rx.search(p.get("section_path") or "")]
    if a.pattern:
        rx = re.compile(a.pattern, re.I)
        hits = []
        for p in rows:
            m = rx.search(p["text"])
            if m:
                s = max(0, m.start() - a.width // 2)
                hits.append((p, p["text"][s:s + a.width]))
        print(f"{len(hits)} hit(s)")
        for p, snip in hits[: a.max]:
            print(f"\n[{p['source_id']} / {p['paragraph_id']}] § {p.get('section_path') or '-'}")
            print("   ..." + snip.replace("\n", " ") + "...")
    else:
        print(f"{len(rows)} paragraph(s)")
        for p in rows[: a.max]:
            print(f"\n[{p['source_id']} / {p['paragraph_id']}] § {p.get('section_path') or '-'}  ({len(p['text'])} chars)")
            print("   " + p["text"][: a.width * 3].replace("\n", " ") + (" ..." if len(p["text"]) > a.width * 3 else ""))


if __name__ == "__main__":
    main()
