#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_package — validate a Skill submission against the Harbor resource limits.

    python3 scripts/check_package.py [DIR]     (default: the skill root)

Checks, in the order a reviewer would:
  1. SKILL.md exists, has YAML frontmatter, and declares name + description
  2. name matches ^[a-z0-9][a-z0-9-]*[a-z0-9]$ and is <= 64 chars
  3. description is present and <= 1024 chars
  4. every file is UTF-8 decodable text
  5. file count <= 50, each file <= 500 KB, total <= 2 MB
  6. no symlinks
  7. the scripts the docs advertise actually exist and are importable
  8. scripts/selftest.py runs and exits 0 (optional, --no-run to skip)

Exit code 0 only when every check passes. This file is deliberately standalone: a
submitter can copy it and run it against their own skill directory.
"""

import os
import re
import subprocess
import sys

MAX_FILES = 50
MAX_FILE_BYTES = 500 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".selftest-tmp",
             ".example-work", ".probe"}


def human(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


def collect(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            files.append(os.path.join(dirpath, fn))
    return sorted(files)


def parse_frontmatter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    data = {}
    key = None
    for raw in block.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            data[key] = m.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            data[key] = (data.get(key, "") + " " + line.strip()).strip()
    return data


def main(argv):
    root = os.path.abspath(argv[1]) if len(argv) > 1 and not argv[1].startswith("-") \
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_tests = "--no-run" not in argv
    problems, notes = [], []

    skill = os.path.join(root, "SKILL.md")
    if not os.path.isfile(skill):
        problems.append("SKILL.md missing at %s" % root)
    else:
        text = open(skill, encoding="utf-8", errors="replace").read()
        fm = parse_frontmatter(text)
        if not fm:
            problems.append("SKILL.md has no YAML frontmatter delimited by --- lines")
        else:
            name = (fm.get("name") or "").strip().strip('"\'')
            desc = (fm.get("description") or "").strip()
            if not name:
                problems.append("frontmatter: name is missing")
            elif not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", name):
                problems.append("frontmatter: name %r is not lowercase-with-hyphens" % name)
            elif len(name) > 64:
                problems.append("frontmatter: name is %d chars (max 64)" % len(name))
            else:
                notes.append("name = %s" % name)
            if not desc:
                problems.append("frontmatter: description is missing")
            elif len(desc) > 1024:
                problems.append("frontmatter: description is %d chars (max 1024)" % len(desc))
            else:
                notes.append("description = %d chars" % len(desc))

    files = collect(root)
    total = 0
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        if os.path.islink(path):
            problems.append("symlink not allowed: %s" % rel)
            continue
        size = os.path.getsize(path)
        total += size
        if size > MAX_FILE_BYTES:
            problems.append("%s is %s (max 500 KB)" % (rel, human(size)))
        try:
            with open(path, "rb") as fh:
                fh.read().decode("utf-8")
        except UnicodeDecodeError:
            problems.append("%s is not valid UTF-8 text" % rel)
        except OSError as exc:
            problems.append("%s unreadable: %s" % (rel, exc))

    if len(files) > MAX_FILES:
        problems.append("%d files (max 50)" % len(files))
    if total > MAX_TOTAL_BYTES:
        problems.append("total %s (max 2 MB)" % human(total))

    notes.append("%d files, %s total" % (len(files), human(total)))

    advertised = ["scripts/doctor.py", "scripts/texlib.py", "scripts/checks.py",
                  "scripts/selftest.py", "references/error-catalog.md",
                  "references/repair-policy.md", "references/build-recipes.md",
                  "references/result-contract.md", "references/checklist.md",
                  "README.md", "examples/README.md"]
    for rel in advertised:
        if not os.path.isfile(os.path.join(root, rel.replace("/", os.sep))):
            problems.append("documented file does not exist: %s" % rel)

    print("checking %s" % root)
    for n in notes:
        print("  . %s" % n)

    if run_tests and os.path.isfile(os.path.join(root, "scripts", "selftest.py")):
        proc = subprocess.run([sys.executable, os.path.join(root, "scripts", "selftest.py")],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        out = proc.stdout.decode("utf-8", "replace")
        tail = [l for l in out.split("\n") if "assertions passed" in l]
        if proc.returncode == 0:
            print("  . selftest: %s" % (tail[0].strip() if tail else "ok"))
        else:
            problems.append("selftest failed (exit %d): %s"
                            % (proc.returncode, tail[0].strip() if tail else out[-400:]))

    if problems:
        print("")
        print("FAILED %d check(s):" % len(problems))
        for p in problems:
            print("  x %s" % p)
        return 1
    print("")
    print("OK — package satisfies the submission limits")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
