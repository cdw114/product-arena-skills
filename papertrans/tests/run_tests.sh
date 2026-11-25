#!/usr/bin/env bash
# Self-check for papertrans. Usage: bash tests/run_tests.sh path/to/paper.pdf
set -euo pipefail
export PYTHONUTF8=1
export PYTHONPATH="$(cd "$(dirname "$0")/.." && pwd)${PYTHONPATH:+:$PYTHONPATH}"
PDF="${1:-tests/attention.pdf}"
OUT="${2:-work/_selftest}"
cd "$(dirname "$0")/.."
python -m papertrans.cli prepare "$PDF" --out "$OUT" --lang zh > /dev/null
for fault in none drop_ph drop_seg dup leak_term; do
  python tests/sim_translate.py "$OUT" "$fault" > /dev/null
  python -m papertrans.cli verify "$OUT" > "$OUT/verify_$fault.json" || true
  python -m papertrans.cli assemble "$OUT" > "$OUT/assemble_$fault.json" || true
  python - "$OUT" "$fault" <<'EOF'
import json, sys
out, fault = sys.argv[1], sys.argv[2]
v = json.load(open(f"{out}/verify_{fault}.json", encoding="utf-8"))["summary"]
a = json.load(open(f"{out}/assemble_{fault}.json", encoding="utf-8"))
ok = (fault == "none" and v["verdicts"]["fail"] == 0) or (fault != "none" and v["verdicts"]["fail"] >= 1)
print(f"{fault:10s} pass/warn/fail={v['verdicts']['pass']}/{v['verdicts']['warn']}/{v['verdicts']['fail']} "
      f"ph={v['placeholder_integrity']['found']}/{v['placeholder_integrity']['expected']} "
      f"missing={v['missing']} dups={len(v['duplicate_groups'])} status={a['status']} "
      f"termcons={a['summary']['term_consistency_rate']}  {'OK' if ok else 'UNEXPECTED'}")
sys.exit(0 if ok else 1)
EOF
done
echo "ALL OK"
