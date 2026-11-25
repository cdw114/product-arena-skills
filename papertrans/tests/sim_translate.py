#!/usr/bin/env python3
"""Test-only simulated translator. Produces a fake 'translation' per segment that keeps every ⟦..⟧ token
so verify/assemble can be exercised end-to-end without a model. Fault injection modes prove the verifier:
  fault=drop_ph   : drop the first NUM placeholder in one segment
  fault=drop_seg  : omit one segment entirely
  fault=dup       : reuse one segment's translation for another
  fault=leak_term : write the English source term instead of a TERM token in one segment
"""
import json
import random
import re
import sys
from pathlib import Path

PH = re.compile(r"⟦[A-Z]+#\d{4}⟧")


def fake_translate(masked: str, rng: random.Random) -> str:
    # Replace each English word with a pseudo-zh token; keep placeholders and punctuation.
    parts = re.split(r"(⟦[A-Z]+#\d{4}⟧)", masked)
    out = []
    for p in parts:
        if PH.fullmatch(p):
            out.append(p)
        else:
            words = re.findall(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]|\s+", p)
            s = ""
            for w in words:
                if re.fullmatch(r"[A-Za-z]{3,}", w):
                    s += "译" * (1 + len(w) // 5)
                else:
                    s += w
            out.append(s)
    return "".join(out)


def main(out_dir: str, fault: str = "none", seed: int = 7) -> int:
    rng = random.Random(seed)
    out = Path(out_dir)
    masked = json.loads((out / "batches" / "masked.json").read_text(encoding="utf-8"))
    seg = json.loads((out / "segments.json").read_text(encoding="utf-8"))
    tr = {sid: fake_translate(m, rng) for sid, m in masked.items()}
    ids = [s["id"] for s in seg["segments"]]
    if fault == "drop_ph":
        for sid, t in tr.items():
            if "⟦NUM#" in t:
                tr[sid] = t.replace(re.search(r"⟦NUM#\d{4}⟧", t).group(0), "大约三", 1)
                break
    elif fault == "drop_seg":
        del tr[ids[len(ids) // 2]]
    elif fault == "dup":
        tr[ids[5]] = tr[ids[4]]
    elif fault == "leak_term":
        for sid, t in tr.items():
            m = re.search(r"⟦TERM#\d{4}⟧", t)
            if m:
                tr[sid] = t.replace(m.group(0), "attention mechanism", 1)
                break
    (out / "translations.json").write_text(json.dumps({"translations": tr}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[sim] wrote {len(tr)} translations (fault={fault})")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
