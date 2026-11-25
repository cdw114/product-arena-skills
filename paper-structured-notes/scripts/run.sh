#!/usr/bin/env bash
# run.sh — one-command entry point for the paper-structured-notes skill.
#
#   bash scripts/run.sh prepare  [--case /input/case.json] [--work /app/work]
#   bash scripts/run.sh extract  <paper.pdf> <work_dir> [--force-ocr] [--ocr-lang eng]
#   bash scripts/run.sh validate <work_dir> <out_dir> [case.json] [task.md]
#   bash scripts/run.sh check    <out_dir>     # audit a finished output dir
#   bash scripts/run.sh selftest [dir]         # offline script self-test
#
# Requires python3 on PATH. PyMuPDF is needed only for `extract`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

cmd="${1:-}"; shift || true
case "$cmd" in
  prepare)
    "$PY" "$HERE/prepare.py" "$@"
    ;;
  extract)
    pdf="${1:?usage: run.sh extract PAPER.pdf WORK_DIR}"; work="${2:?missing work dir}"
    mkdir -p "$work"
    "$PY" "$HERE/pdf_extract.py" "$pdf" "$work" "${@:3}"
    ;;
  validate)
    work="${1:?usage: run.sh validate WORK_DIR OUT_DIR [case.json] [task.md]}"; out="${2:?missing out dir}"
    args=(--skeleton "$work/skeleton.json" --draft "$work/notes_draft.json" --out "$out")
    [ "${3:-}" != "" ] && args+=(--case-json "$3")
    [ "${4:-}" != "" ] && args+=(--task-md "$4")
    "$PY" "$HERE/build_notes.py" "${args[@]}"
    ;;
  check)
    out="${1:?usage: run.sh check OUT_DIR}"
    "$PY" "$HERE/audit.py" "$out"
    ;;
  selftest)
    "$PY" "$HERE/selftest.py" "${1:-_selftest}"
    ;;
  *)
    sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
