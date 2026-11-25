#!/usr/bin/env python3
"""run.py — cross-platform entry point (use this when bash is unavailable).

    python scripts/run.py prepare  [--case /input/case.json] [--work /app/work]
    python scripts/run.py extract  paper.pdf WORK_DIR [--force-ocr] [--ocr-lang eng]
    python scripts/run.py validate WORK_DIR OUT_DIR [case.json] [task.md]
    python scripts/run.py check    OUT_DIR
    python scripts/run.py selftest [DIR]

Equivalent to run.sh; both call the same two stages.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def usage() -> int:
    print(__doc__.strip())
    return 2


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    cmd, rest = argv[0], argv[1:]
    if cmd == "prepare":
        return subprocess.call([sys.executable, os.path.join(HERE, "prepare.py"), *rest])
    if cmd == "extract":
        if len(rest) < 2:
            return usage()
        return subprocess.call([sys.executable, os.path.join(HERE, "pdf_extract.py"), rest[0], rest[1], *rest[2:]])
    if cmd == "validate":
        if len(rest) < 2:
            return usage()
        work, out = rest[0], rest[1]
        args = [sys.executable, os.path.join(HERE, "build_notes.py"),
                "--skeleton", os.path.join(work, "skeleton.json"),
                "--draft", os.path.join(work, "notes_draft.json"), "--out", out]
        if len(rest) > 2 and rest[2]:
            args += ["--case-json", rest[2]]
        if len(rest) > 3 and rest[3]:
            args += ["--task-md", rest[3]]
        return subprocess.call(args)
    if cmd == "check":
        out = rest[0] if rest else "."
        return subprocess.call([sys.executable, os.path.join(HERE, "audit.py"), out])
    if cmd == "selftest":
        out = rest[0] if rest else "_selftest"
        return subprocess.call([sys.executable, os.path.join(HERE, "selftest.py"), out])
    return usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
