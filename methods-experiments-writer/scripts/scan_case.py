#!/usr/bin/env python3
"""scan_case.py - step 1..3 of the methods-experiments-writer skill.

Reads the case contract and every material file, then writes a provenance
ledger: one row per atomic fact, each with a locator a reviewer can re-open.

    python3 scripts/scan_case.py --input /input --work /app/work

Writes
    <work>/contract.json    what the deliverable must contain (from case.json)
    <work>/inventory.json   every input file, class, size, sha256
    <work>/evidence.json    the ledger
    <work>/scan_report.md   what was found, what conflicts, what is missing

Never invents a value. A fact that is not in a file simply has no row, and
appears in the gap list at the end of scan_report.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mew_lib as L  # noqa: E402

DEFAULT_CONTRACT = {
    "methods_section": "markdown text of the Methods and Experiments section",
    "parameter_table": "table of name / value / unit / target / source",
    "evidence_map": "per-fact source locator",
    "coverage_report": "six-element status and gaps",
    "open_questions": "items the author must confirm",
}

HARDWARE_RE = re.compile(
    r"\b(NVIDIA\s+)?(A100|H100|H800|A800|V100|T4|L4|A10G?|RTX\s?\d{4}|"
    r"Tesla\s+\w+|GeForce\s+\w+|MI\d{3}|EPYC\s+\w+|Xeon\s+\w+|i[579]-\d{4,5}\w*)\b",
    re.I,
)
# (canonical name, pattern, group index holding the version string)
VERSION_RES = [
    ("torch_version", r"\b(?:torch|pytorch)\s*(?:version)?\s*[=:v ]\s*([0-9]+\.[0-9][0-9A-Za-z.\-]*)", 1),
    ("tensorflow_version", r"\btensorflow\s*(?:version)?\s*[=:v ]\s*([0-9]+\.[0-9][0-9A-Za-z.\-]*)", 1),
    ("python_version", r"\bpython\s*(?:version)?\s*[=:v ]\s*([0-9]+\.[0-9][0-9A-Za-z.\-]*)", 1),
    ("cuda_version", r"\bcuda\s*(?:version)?\s*[=:v ]\s*([0-9]+\.[0-9][0-9A-Za-z.\-]*)", 1),
    ("cudnn_version", r"\bcudnn\s*(?:version)?\s*[=:v ]\s*([0-9]+\.[0-9][0-9A-Za-z.\-]*)", 1),
    ("numpy_version", r"\bnumpy\s*(?:version)?\s*[=:v ]\s*([0-9]+\.[0-9][0-9A-Za-z.\-]*)", 1),
    ("framework_version", r"\b([A-Za-z][A-Za-z0-9_\-]{2,30})\s*==\s*([0-9]+\.[0-9][0-9A-Za-z.\-]*)", 2),
]
TS_RE = re.compile(r"\b(20\d\d[-/]\d\d[-/]\d\d([ T]\d\d:\d\d(:\d\d)?)?)\b")
DUR_RE = re.compile(r"\b(?:elapsed|took|time|wall|duration)\D{0,12}((?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s))\b", re.I)
EPOCH_RE = re.compile(r"\b(?:epoch|ep)\s*[=: ]?\s*(\d+)\s*(?:/|of)\s*(\d+)\b", re.I)
KV_RE = re.compile(
    r"(?:^|[\s,;\[\{(])(?P<k>[A-Za-z][A-Za-z0-9_.\-/]{1,48})\s*(?:=|:|\s)\s*"
    r"(?P<v>(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:[eE][-+]?\d+)?%?)(?![0-9])"
)
SPLIT_RE = re.compile(
    r"\b(?:split|train|val|valid|validation|test|dev|holdout|calib\w*)\b[^0-9\n]{0,40}"
    r"((?:\d+(?:\.\d+)?\s*(?:%|[kKmMbB])?\s*[:/]\s*){1,4}\d+(?:\.\d+)?\s*(?:%|[kKmMbB])?)",
    re.I
)
COUNT_RE = re.compile(r"\b(\d[\d,]{2,})\s*(?:samples|records|rows|examples|images|molecules|structures|frames|tokens|documents|entries|items|points)\b", re.I)
RUN_CMD_RE = re.compile(
    r"^\s*(?:\$|>|#)?\s*((?:python3?|bash|sh|torchrun|deepspeed|accelerate|mpirun|srun|nohup|conda|pip|docker)\b[^\n]{0,220})",
    re.M
)
BASELINE_RE = re.compile(r"\b(baseline|baselines|compared with|compared to|对照|基线|对比)\b", re.I)
SPLIT_COUNT_RE = re.compile(
    r"(?:train|training)\s*[=:]\s*(\d[\d,]*)\D{0,24}"
    r"(?:val|valid|validation|dev)\s*[=:]\s*(\d[\d,]*)\D{0,24}"
    r"(?:test)\s*[=:]\s*(\d[\d,]*)",
    re.I,
)
BASELINE_VERSION_RE = re.compile(
    r"\b(?:baseline|基线)[^.\n]{0,40}?(\bv?\d+\.\d+(?:\.\d+)*\b)", re.I)
GPUMEM_RE = re.compile(r"\b(\d{2,3})\s*GB\b")
GPUCOUNT_RE = re.compile(r"\b(?:count|num_gpus|world_size|devices)\s*[=:]\s*(\d+)")
REPEATS_RE = re.compile(
    r"\b(?:averaged\s+over|over|across|repeated|repeats?|runs?|trials?)\s*"
    r"(?:of\s+)?(\d+)\s*(?:repeats?|independent\s+runs?|runs?|trials?|times|seeds)\b",
    re.I,
)

# Keys that look like a parameter but are a counter or an error, not a setting.
# Reading "Epoch 1/120" as epochs=1 is the classic way a results table lies.
LOG_KEY_EXCLUDE = re.compile(
    r"^(epoch|ep|iter|iteration|step)s?$"
    r"|^ver(sion)?$|^loss$|^l$|^val$|^train$|^time$|^elapsed$|^memory$|^mem$"
    r"|^rank$|^pid$|^id$|^n$|^i$|^p$|^k$",
    re.I,
)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def classify(path):
    base = os.path.basename(path).lower()
    ext = os.path.splitext(base)[1]
    low = path.lower()
    # Only the case controls are excluded from evidence: a README is material,
    # and it is usually where the dataset version and the baseline live.
    if base in ("case.json", "case.yaml", "case.yml", "task.md", "instruction.md", "prompt.md"):
        return "control"
    if ext in L.PAPER_SUFFIXES:
        return "paper"
    if ext in L.CONFIG_SUFFIXES:
        return "config"
    if ext in L.TABLE_SUFFIXES:
        return "table"
    if ext in (".log", ".out", ".err") or any(h in base for h in L.LOG_HINTS) and ext in (".txt", ""):
        return "log"
    if ext in L.CODE_SUFFIXES:
        return "code"
    if any(h in base for h in L.DATA_HINTS):
        return "dataset_doc"
    if ext in (".md", ".rst", ".txt", ".tex"):
        return "doc"
    return "other"


def discover(input_dir, work_dir):
    found = []
    work_abs = os.path.abspath(work_dir)
    for root, dirs, files in os.walk(input_dir):
        dirs[:] = [d for d in dirs if d not in L.SKIP_DIRS]
        for name in sorted(files):
            p = os.path.join(root, name)
            if os.path.abspath(p).startswith(work_abs + os.sep):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            found.append({
                "path": p,
                "relpath": os.path.relpath(p, input_dir).replace(os.sep, "/"),
                "bytes": st.st_size,
                "class": classify(p),
            })
    return found


def pick_case_file(input_dir):
    for name in ("case.json", "case.yaml", "case.yml"):
        p = os.path.join(input_dir, name)
        if os.path.isfile(p):
            return p
    return None


def pick_task_text(input_dir):
    for name in ("task.md", "instruction.md", "TASK.md", "prompt.md"):
        p = os.path.join(input_dir, name)
        if os.path.isfile(p):
            return p, L.read_text(p) or ""
    return None, ""


def read_case(path, task_text):
    """Merge case.json with what task.md says; case.json wins on conflicts."""
    case = {}
    if path:
        obj = L.load_json(path)
        if isinstance(obj, dict):
            case = obj
    out = {
        "case_file": path,
        "case_id": None,
        "output_contract": None,
        "deliverable_language": None,
        "audience": None,
        "discipline": None,
        "extra": {},
    }
    if isinstance(case, dict):
        for k in ("case_id", "id", "caseId", "task_id"):
            if isinstance(case.get(k), str) and case[k].strip():
                out["case_id"] = case[k].strip()
                break
        contract = case.get("output_contract") or case.get("outputContract") or case.get("contract")
        if isinstance(contract, dict) and contract:
            out["output_contract"] = contract
        elif isinstance(contract, list) and contract:
            out["output_contract"] = {str(k): "" for k in contract}
        for k in ("deliverable_language", "language", "audience", "discipline", "section", "word_limit", "must_include"):
            if k in case:
                out["extra"][k] = case[k]
    # language of the task text decides the language of the deliverable
    zh = len(re.findall(r"[\u4e00-\u9fff]", task_text))
    en = len(re.findall(r"\b[a-zA-Z]{3,}\b", task_text))
    out["deliverable_language"] = "zh" if zh > en * 0.6 else ("en" if en else "unknown")
    out["output_contract_source"] = "case.json" if out["output_contract"] else "default"
    if not out["output_contract"]:
        out["output_contract"] = dict(DEFAULT_CONTRACT)
    return out, case


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------

def add_config_rows(ledger, path, text, roots):
    obj, parser = L.load_structured(path, text)
    rel = L.norm_path_for_report(path, roots)
    if obj is None:
        return add_raw_line_rows(ledger, path, text, roots, kind="config_value", method="raw_line")
    leaves = L.flatten(obj)
    param_like = []
    plain = []
    for dotted, value, parts in leaves:
        canon, unit = L.canonical_param(dotted)
        row = (dotted, value, parts, canon, unit)
        (param_like if canon else plain).append(row)
    budget = 260
    for dotted, value, parts, canon, unit in (param_like + plain)[:budget]:
        ledger.add(
            kind="config_value",
            name=dotted,
            value=value,
            unit=unit or "",
            applies_to=os.path.splitext(os.path.basename(path))[0],
            source_file=rel,
            source_locator=rel + L.json_pointer(parts),
            method=parser,
            confidence="high" if canon else "medium",
        )


def add_raw_line_rows(ledger, path, text, roots, kind="raw_line", method="raw_line"):
    rel = L.norm_path_for_report(path, roots)
    idx = L.LineIndex(text)
    hits = 0
    for m in KV_RE.finditer(text):
        canon, unit = L.canonical_param(m.group("k"))
        if not canon:
            continue
        lineno = idx.line_of(m.start("k"))
        ledger.add(
            kind=kind,
            name=m.group("k"),
            value=m.group("v"),
            unit=unit or "",
            applies_to=os.path.splitext(os.path.basename(path))[0],
            source_file=rel,
            source_locator="%s:%d" % (rel, lineno),
            method=method,
            confidence="medium",
        )
        hits += 1
        if hits >= 120:
            break
    return hits


ARG_DEFAULT_RE = re.compile(
    r"""add_argument\(\s*['"]{1,2}(?:-{1,2})?(?P<name>[A-Za-z0-9_\-]+)['"]{1,2}"""
    r"""(?P<rest>.*?)\)""",
    re.S,
)
DEFAULT_KW_RE = re.compile(r"default\s*=\s*(?P<v>[^,)\n]+)")
ASSIGN_RE = re.compile(
    r"^\s*(?P<k>[A-Za-z_][A-Za-z0-9_]{1,48})\s*(?::[^=\n]+)?=\s*(?P<v>[-+]?\d[\w.+\-]*)\s*(?:#.*)?$",
    re.M,
)
SEED_CALL_RE = re.compile(
    r"(?:manual_seed|np\.random\.seed|random\.seed|seed_everything|set_seed|pl\.seed_everything)"
    r"\(\s*(?P<v>\d+)\s*\)"
)
FUNC_DEFAULT_RE = re.compile(
    r"\b(?:def|function)\s+\w+\s*\((?P<args>[^)]{0,600})\)"
)
REQ_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_.\-]{1,40})\s*(?:==|>=|<=|~=|=)\s*([0-9][0-9A-Za-z.\-*]*)")


def add_code_rows(ledger, path, text, roots):
    rel = L.norm_path_for_report(path, roots)
    idx = L.LineIndex(text)
    emitted = 0

    for m in ARG_DEFAULT_RE.finditer(text):
        d = DEFAULT_KW_RE.search(m.group("rest") or "")
        if not d:
            continue
        canon, unit = L.canonical_param(m.group("name"))
        if not canon:
            continue
        ledger.add(
            kind="code_default", name=m.group("name"), value=d.group("v").strip(),
            unit=unit or "", applies_to=os.path.basename(path),
            source_file=rel, source_locator="%s:%d" % (rel, idx.line_of(m.start("name"))),
            method="argparse_default", confidence="high",
        )
        emitted += 1

    for m in SEED_CALL_RE.finditer(text):
        ledger.add(
            kind="code_default", name="seed", value=m.group("v"), unit="",
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="seed_call", confidence="high",
        )
        emitted += 1

    for m in ASSIGN_RE.finditer(text):
        canon, unit = L.canonical_param(m.group("k"))
        if not canon:
            continue
        ledger.add(
            kind="code_default", name=m.group("k"), value=m.group("v").rstrip("+,."),
            unit=unit or "", applies_to=os.path.basename(path),
            source_file=rel, source_locator="%s:%d" % (rel, idx.line_of(m.start("k"))),
            method="module_constant", confidence="high",
        )
        emitted += 1
        if emitted > 120:
            break

    for m in FUNC_DEFAULT_RE.finditer(text):
        for piece in re.split(r",(?![^\[\]()]*[\]\)])", m.group("args")):
            if "=" not in piece:
                continue
            k, _, v = piece.partition("=")
            canon, unit = L.canonical_param(k.strip())
            if not canon:
                continue
            ledger.add(
                kind="code_default", name=k.strip(), value=v.strip(),
                unit=unit or "", applies_to=os.path.basename(path),
                source_file=rel, source_locator="%s:%d" % (rel, idx.line_of(m.start())),
                method="signature_default", confidence="medium",
            )
            emitted += 1

    # the command that actually runs the code: the strongest reproducibility fact
    for m in RUN_CMD_RE.finditer(text):
        cmd = m.group(1).strip()
        if not re.search(r"\.(py|sh|R|jl)\b|train|eval|run|--", cmd):
            continue
        ledger.add(
            kind="code_fact", name="run_command", value=L.snippet(cmd, 200),
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="run_command", confidence="high",
        )
    return emitted


def add_log_rows(ledger, path, text, roots):
    rel = L.norm_path_for_report(path, roots)
    idx = L.LineIndex(text)
    emitted = 0
    lines = text.splitlines()
    # config dumps usually sit in the first lines; scan early lines with a looser rule
    for n, line in enumerate(lines[:400], start=1):
        if len(line) > 400:
            continue
        for m in KV_RE.finditer(line):
            k = m.group("k")
            if LOG_KEY_EXCLUDE.match(k):
                continue
            canon, unit = L.canonical_param(k)
            if not canon:
                continue
            raw_v = m.group("v")
            end = m.end("v")
            # "torch 2.1.2" -> keep the whole dotted version, not "2.1"
            while re.match(r"\.\d", line[end:end + 2]):
                ext = re.match(r"\.\d+", line[end:])
                raw_v += ext.group(0)
                end += ext.end()
            ledger.add(
                kind="log_value", name=k, value=raw_v,
                unit=unit or "", applies_to=os.path.basename(path),
                source_file=rel, source_locator="%s:%d" % (rel, n),
                method="log_kv", confidence="high",
            )
            emitted += 1
            if emitted > 200:
                break
        for m in HARDWARE_RE.finditer(line):
            ledger.add(
                kind="log_value", name="gpu_model", value=m.group(0).strip(),
                applies_to=os.path.basename(path), source_file=rel,
                source_locator="%s:%d" % (rel, n), method="hardware_line",
                confidence="high",
            )
            emitted += 1
            mem = GPUMEM_RE.search(line)
            if mem:
                ledger.add(
                    kind="log_value", name="gpu_memory", value=mem.group(1), unit="GB",
                    applies_to=os.path.basename(path), source_file=rel,
                    source_locator="%s:%d" % (rel, n), method="hardware_line",
                    confidence="high",
                )
                emitted += 1
        cnt = GPUCOUNT_RE.search(line)
        if cnt:
            ledger.add(
                kind="log_value", name="num_gpus", value=cnt.group(1), unit="GPUs",
                applies_to=os.path.basename(path), source_file=rel,
                source_locator="%s:%d" % (rel, n), method="hardware_line",
                confidence="high",
            )
            emitted += 1
        for name, rx, gi in VERSION_RES:
            for m in re.finditer(rx, line, re.I):
                ledger.add(
                    kind="log_value", name=name, value=m.group(gi),
                    applies_to=os.path.basename(path),
                    source_file=rel, source_locator="%s:%d" % (rel, n),
                    method="version_line", confidence="high",
                )
                emitted += 1
        if emitted > 220:
            break

    seen_epoch_totals = set()
    for m in EPOCH_RE.finditer(text):
        total = m.group(2)
        if total in seen_epoch_totals:
            continue  # "Epoch 3/120" repeated every line is one fact, not 120 facts
        seen_epoch_totals.add(total)
        ledger.add(
            kind="log_value", name="epochs_completed", value=total,
            unit="epochs", applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="epoch_line", confidence="medium",
        )
    for m in DUR_RE.finditer(text):
        ledger.add(
            kind="log_value", name="wall_time", value=m.group(1),
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="duration_line", confidence="medium",
        )
    stamps = TS_RE.findall(text)
    if stamps:
        first = TS_RE.search(text)
        ledger.add(
            kind="log_value", name="run_started_at", value=first.group(1),
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(first.start())),
            method="timestamp_line", confidence="medium",
        )
    for m in SPLIT_COUNT_RE.finditer(text):
        for label, gi in (("train_count", 1), ("val_count", 2), ("test_count", 3)):
            ledger.add(
                kind="log_value", name=label, value=m.group(gi), unit="samples",
                applies_to=os.path.basename(path), source_file=rel,
                source_locator="%s:%d" % (rel, idx.line_of(m.start())),
                method="split_count_line", confidence="high",
            )
    seen_repeats = set()
    for m in REPEATS_RE.finditer(text):
        v = m.group(1)
        if v in seen_repeats:
            continue
        seen_repeats.add(v)
        ledger.add(
            kind="log_value", name="repeats", value=v, unit="runs",
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="repeats_line", confidence="medium",
        )
    return emitted


DATASET_TAG_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)*\b")


def add_dataset_rows(ledger, path, text, roots):
    rel = L.norm_path_for_report(path, roots)
    idx = L.LineIndex(text)
    emitted = 0
    for m in SPLIT_RE.finditer(text):
        ledger.add(
            kind="dataset_fact", name="split_ratio", value=m.group(1).strip(),
            unit="ratio", applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="split_line", confidence="medium",
        )
        emitted += 1
    for m in COUNT_RE.finditer(text):
        ledger.add(
            kind="dataset_fact", name="num_samples", value=m.group(1),
            unit="samples", applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="count_line", confidence="medium",
        )
        emitted += 1
    for m in REPEATS_RE.finditer(text):
        ledger.add(
            kind="dataset_fact", name="repeats", value=m.group(1), unit="runs",
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="repeats_line", confidence="high",
        )
        emitted += 1
    for n, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        if BASELINE_RE.search(line) and len(line) < 400:
            bm = BASELINE_VERSION_RE.search(line)
            if bm:
                ledger.add(
                    kind="dataset_fact", name="baseline_version", value=bm.group(1),
                    applies_to=os.path.basename(path), source_file=rel,
                    source_locator="%s:%d" % (rel, n),
                    method="baseline_line", confidence="high",
                )
                emitted += 1
            ledger.add(
                kind="dataset_fact", name="baseline_statement", value=L.snippet(line, 240),
                applies_to=os.path.basename(path), source_file=rel,
                source_locator="%s:%d" % (rel, n),
                method="baseline_line", confidence="medium",
            )
            emitted += 1
        if any(k in low for k in ("dataset", "data set", "corpus")) and len(line) < 300:
            if re.search(r"\b(v?\d+\.\d+|version|release|20\d\d[-_]\d\d)\b", low):
                # Store the tag, not the sentence it sat in: a table cell holding
                # a whole line with backticks in it is unreadable and unsortable.
                tag = DATASET_TAG_RE.search(line)
                ledger.add(
                    kind="dataset_fact", name="dataset_version",
                    value=(tag.group(0) if tag else L.snippet(line, 120)),
                    applies_to=os.path.basename(path),
                    source_file=rel, source_locator="%s:%d" % (rel, n),
                    method="version_line", confidence="medium",
                    note="" if tag else "no tag token on the line; the snippet is the surrounding text",
                )
                emitted += 1
        if emitted > 120:
            break
    return emitted


STMT_RE = re.compile(
    r"[^.\n]*(?:we (?:use|used|set|train|trained|adopt|apply|split|run|ran)|"
    r"采用|设置|使用|训练|划分|我们)[^.\n]*\d[^.\n]*[.\n]",
    re.I,
)


def add_prose_rows(ledger, path, text, roots, kind="paper_statement"):
    rel = L.norm_path_for_report(path, roots)
    idx = L.LineIndex(text)
    emitted = 0
    for m in STMT_RE.finditer(text):
        s = L.snippet(m.group(0), 260)
        if len(s) < 20:
            continue
        ledger.add(
            kind=kind, name="prose_claim", value=s,
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, idx.line_of(m.start())),
            method="prose_sentence", confidence="low",
            note="prose sentence; confirms wording, not a machine-checked value",
        )
        emitted += 1
        if emitted >= 60:
            break
    return emitted


def add_table_rows(ledger, path, text, roots):
    rel = L.norm_path_for_report(path, roots)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 0
    header = [c.strip() for c in re.split(r"[,\t;]", lines[0])]
    for col in header[:20]:
        if not col:
            continue
        ledger.add(
            kind="table_fact", name="column", value=col,
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:1" % rel, method="csv_header", confidence="medium",
        )
    for n, line in enumerate(lines[1:6], start=2):
        ledger.add(
            kind="table_fact", name="row", value=L.snippet(line, 200),
            applies_to=os.path.basename(path), source_file=rel,
            source_locator="%s:%d" % (rel, n), method="csv_row", confidence="medium",
        )
    return len(header)


def add_pdf_rows(ledger, path, roots, gaps):
    """Best-effort PDF text. No silent success: a failed extract is a recorded gap."""
    rel = L.norm_path_for_report(path, roots)
    text = None
    tool = None
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        tool = "pymupdf"
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore
            text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
            tool = "pypdf"
        except Exception:
            try:
                import pdfminer.high_level as hl  # type: ignore
                text = hl.extract_text(path)
                tool = "pdfminer"
            except Exception:
                text = None
    if not text or len(text.strip()) < 40:
        gaps.append({
            "id": "pdf_text_not_extracted",
            "what": "no readable text layer for %s" % rel,
            "why": "a scanned PDF, or no PDF text library in this image",
            "resolve_by": "run a PDF text tool (pdftotext / pdf-text-tool) on %s and re-run scan_case.py with --extra-text" % rel,
        })
        return 0
    ledger.add(
        kind="paper_statement", name="pdf_text_layer", value="extracted %d chars" % len(text),
        source_file=rel, source_locator="%s:1" % rel, method=tool, confidence="high",
    )
    return add_prose_rows(ledger, path, text, roots)


def add_ipynb_rows(ledger, path, text, roots):
    rel = L.norm_path_for_report(path, roots)
    try:
        nb = json.loads(text)
    except ValueError:
        return 0
    emitted = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        emitted += add_code_rows(ledger, path, src, roots)
    return emitted


# ---------------------------------------------------------------------------
# coverage prefill and gaps
# ---------------------------------------------------------------------------

def essential_coverage(ledger):
    names = {(r["name"] or "").lower() for r in ledger.rows}
    kinds = {r["kind"] for r in ledger.rows}
    has = lambda *frags: any(any(f in n for f in frags) for n in names)  # noqa: E731
    cov = {}
    cov["steps"] = "partial" if ("code_fact" in kinds or "code_default" in kinds) else "missing"
    cov["setup"] = "partial" if (has("gpu", "hardware", "cuda", "torch", "python") and has("seed")) else (
        "partial" if has("gpu", "hardware", "cuda", "torch", "python") else "missing")
    cov["params"] = "complete" if sum(1 for r in ledger.rows if L.canonical_param(r["name"])[0]) >= 5 else (
        "partial" if any(L.canonical_param(r["name"])[0] for r in ledger.rows) else "missing")
    cov["datasets"] = "partial" if has("dataset", "split", "num_samples") else "missing"
    cov["baselines"] = "partial" if any("baseline" in r["name"].lower() or BASELINE_RE.search(r["display"] or "")
                                        for r in ledger.rows) else "missing"
    cov["repro"] = "partial" if has("run_command") else "missing"
    cov["limitations"] = "missing"
    return cov


GAP_TEMPLATES = {
    "steps": "No ordered procedure is recoverable from the files: list step -> input -> operation -> output -> exit condition, and name the file each step comes from.",
    "setup": "Hardware / software version / seed coverage is incomplete. Ask the author for GPU model and count, framework and CUDA versions, and every random seed used.",
    "params": "Fewer than five named parameters were found. Ask the author which configuration actually ran, or whether defaults in the code were used unmodified.",
    "datasets": "Dataset name, version, size or split is not fully stated. Ask for the exact release tag and how the split was drawn (random seed, stratification, or fixed file list).",
    "baselines": "No baseline identity, version or equal-budget statement was found. Ask which baseline release was used and whether it received the same compute budget.",
    "repro": "No run command was found in the materials. Ask the author for the exact command, the commit hash, and how to obtain the data.",
    "limitations": "Limitations cannot be read off files. Ask the author which concrete scenario makes this method fail, and record that scenario, not a generic caveat.",
}


def build_gaps(ledger, conflicts, coverage, extra_gaps):
    gaps = list(extra_gaps)
    for element, status in coverage.items():
        if status in ("missing", "partial"):
            sev = "blocking" if status == "missing" and element in ("params", "datasets", "repro") else "important"
            gaps.append({
                "id": "coverage_%s_%s" % (element, status),
                "element": element,
                "severity": sev,
                "what": GAP_TEMPLATES[element],
                "status": status,
            })
    for c in conflicts:
        gaps.append({
            "id": "conflict_%s" % c["parameter"],
            "element": "params",
            "severity": "blocking",
            "what": c["question"],
            "eids": c["eids"],
        })
    for r in ledger.rows:
        if r["kind"] == "paper_statement" and r["confidence"] == "low":
            continue
    return gaps


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def render_report(contract, inventory, ledger, conflicts, coverage, gaps, input_dir):
    zh = contract.get("deliverable_language") == "zh"
    T = (lambda a, b: ("%s / %s" % (a, b)) if zh else b)
    out = []
    out.append("# Scan report\n")
    out.append(T("**案例**", "**Case**") + ": `%s`" % (contract.get("case_id") or "(no case_id in case.json)"))
    out.append(T("**输入目录**", "**Input directory**") + ": `%s`" % input_dir)
    out.append(T("**交付契约来源**", "**Output contract source**") + ": `%s`" % contract.get("output_contract_source"))
    out.append("")
    out.append("## " + T("材料清单", "Materials"))
    out.append("")
    out.append("| " + T("文件", "File") + " | " + T("类别", "Class") + " | " + T("字节", "Bytes") + " |")
    out.append("|---|---|---|")
    for it in inventory:
        out.append("| `%s` | %s | %d |" % (it["relpath"], it["class"], it["bytes"]))
    out.append("")
    out.append("## " + T("证据台账", "Evidence ledger"))
    out.append("")
    out.append(T("共 %d 条，按类别：" % len(ledger.rows), "%d rows by kind:" % len(ledger.rows)))
    out.append("")
    by_kind = {}
    for r in ledger.rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    out.append("| kind | n |")
    out.append("|---|---|")
    for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        out.append("| %s | %d |" % (k, v))
    out.append("")
    out.append("### " + T("参数类证据（可直接写进参数表）", "Parameter-like rows (usable in the parameter table)"))
    out.append("")
    out.append("| eid | name | value | unit | source |")
    out.append("|---|---|---|---|---|")
    shown = 0
    for r in ledger.rows:
        if not L.canonical_param(r["name"])[0]:
            continue
        out.append("| %s | `%s` | `%s` | %s | `%s` |" % (
            r["eid"], r["name"], r["display"], r["unit"] or "-", r["source_locator"]))
        shown += 1
        if shown >= 40:
            out.append("| ... | | | | |")
            break
    out.append("")
    out.append("## " + T("冲突", "Conflicts"))
    out.append("")
    if conflicts:
        for c in conflicts:
            out.append("- **%s** — %s" % (c["parameter"], c["question"]))
    else:
        out.append(T("未发现同一参数在不同来源中取值不同。",
                     "No parameter was found with two different values across sources. "
                     "That is not proof of consistency: it only means every value we reached agreed."))
    out.append("")
    out.append("## " + T("六要素覆盖（预填）", "Six-element coverage (prefill)"))
    out.append("")
    out.append("| " + T("要素", "Element") + " | " + T("状态", "Status") + " |")
    out.append("|---|---|")
    for k, v in coverage.items():
        out.append("| %s | %s |" % (k, v))
    out.append("")
    out.append("## " + T("缺口与待确认项", "Gaps and author questions"))
    out.append("")
    for g in gaps:
        out.append("- `%s` (%s) — %s" % (g["id"], g.get("severity", "important"), g["what"]))
    out.append("")
    out.append("## " + T("下一步", "Next"))
    out.append("")
    out.append("1. " + T("把 `work/evidence.json` 读进上下文，只引用其中的 eid；没有 eid 的数字不写进正文。",
                        "Open `work/evidence.json`. Cite only its eids. A number with no eid does not enter the prose."))
    out.append("2. " + T("按 `templates/section_outline.md` 起草到 `work/draft.md`，正文用 `[E0001]` 标注来源。",
                        "Draft into `work/draft.md` following `templates/section_outline.md`, tagging facts `[E0001]`."))
    out.append("3. " + T("运行 `python3 scripts/audit_draft.py --draft work/draft.md --work work`，修到无 unsourced 数字。",
                        "Run `python3 scripts/audit_draft.py --draft work/draft.md --work work` until no unsourced number remains."))
    out.append("4. " + T("运行 `python3 scripts/emit_outputs.py --input /input --work work --out /app/output`。",
                        "Run `python3 scripts/emit_outputs.py --input /input --work work --out /app/output`."))
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan a methods/experiments case and build an evidence ledger.")
    ap.add_argument("--input", default="/input", help="case input directory (contains case.json, task.md, materials)")
    ap.add_argument("--work", default="/app/work", help="scratch directory for ledger and draft")
    ap.add_argument("--extra-text", default=None,
                    help="optional file with text you extracted yourself (e.g. from a PDF); merged as prose evidence")
    ap.add_argument("--max-files", type=int, default=400)
    args = ap.parse_args(argv)

    if not os.path.isdir(args.input):
        print(json.dumps({"status": "failed", "error": "input directory not found: %s" % args.input},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    L.ensure_dir(args.work)

    case_path = pick_case_file(args.input)
    task_path, task_text = pick_task_text(args.input)
    contract, raw_case = read_case(case_path, task_text)
    contract["task_path"] = task_path
    roots = [args.input, os.path.dirname(args.input) or "/"]

    inventory = discover(args.input, args.work)[:args.max_files]
    ledger = L.Ledger()
    extra_gaps = []

    for item in inventory:
        p = item["path"]
        cls = item["class"]
        item["sha256"] = None
        if cls == "control":
            continue
        try:
            item["sha256"] = L.sha256_file(p) if item["bytes"] < 50_000_000 else None
        except OSError:
            pass
        if cls == "paper" and p.lower().endswith(".pdf"):
            add_pdf_rows(ledger, p, roots, extra_gaps)
            continue
        text = L.read_text(p)
        if text is None:
            extra_gaps.append({
                "id": "unreadable_%s" % item["relpath"].replace("/", "_"),
                "what": "could not read %s as text (%d bytes)" % (item["relpath"], item["bytes"]),
                "why": "binary, compressed or over the size limit",
                "resolve_by": "convert it to text (or CSV/JSON) and re-run scan_case.py",
            })
            continue
        item["chars"] = len(text)
        if cls == "config":
            add_config_rows(ledger, p, text, roots)
        elif cls == "code":
            if p.lower().endswith(".ipynb"):
                add_ipynb_rows(ledger, p, text, roots)
            else:
                add_code_rows(ledger, p, text, roots)
        elif cls == "log":
            add_log_rows(ledger, p, text, roots)
        elif cls == "table":
            add_table_rows(ledger, p, text, roots)
        elif cls == "dataset_doc":
            add_dataset_rows(ledger, p, text, roots)
            add_prose_rows(ledger, p, text, roots, kind="dataset_fact")
        elif cls in ("doc", "paper"):
            add_dataset_rows(ledger, p, text, roots)
            add_prose_rows(ledger, p, text, roots)
            add_code_rows(ledger, p, text, roots)
        elif cls == "other":
            add_raw_line_rows(ledger, p, text, roots, kind="raw_line", method="raw_line")

    if args.extra_text and os.path.isfile(args.extra_text):
        text = L.read_text(args.extra_text) or ""
        add_prose_rows(ledger, args.extra_text, text, roots)

    if not ledger.rows:
        extra_gaps.append({
            "id": "no_evidence_found",
            "what": "no machine-readable fact was recovered from any material file",
            "why": "the materials may be images, scans, or outside the patterns this scanner knows",
            "resolve_by": "read the files yourself in the session and add rows to work/evidence.json by hand with real locators",
        })

    conflicts = ledger.mark_conflicts()
    coverage = essential_coverage(ledger)
    gaps = build_gaps(ledger, conflicts, coverage, extra_gaps)

    L.write_json(os.path.join(args.work, "contract.json"), contract)
    L.write_json(os.path.join(args.work, "inventory.json"), {
        "input": args.input, "files": inventory, "count": len(inventory),
    })
    L.write_json(os.path.join(args.work, "evidence.json"), ledger.to_dict())
    L.write_json(os.path.join(args.work, "conflicts.json"), {
        "count": len(conflicts), "conflicts": conflicts,
    })
    L.write_json(os.path.join(args.work, "gaps.json"), {"count": len(gaps), "gaps": gaps})
    L.write_text(os.path.join(args.work, "scan_report.md"),
                 render_report(contract, inventory, ledger, conflicts, coverage, gaps, args.input))

    summary = {
        "status": "ok",
        "case_id": contract.get("case_id"),
        "contract_source": contract.get("output_contract_source"),
        "contract_fields": list(contract.get("output_contract", {}).keys()),
        "materials": len(inventory),
        "evidence_rows": len(ledger.rows),
        "param_rows": sum(1 for r in ledger.rows if L.canonical_param(r["name"])[0]),
        "conflicts": len(conflicts),
        "gaps": len(gaps),
        "coverage": coverage,
        "artifacts": [
            os.path.join(args.work, "evidence.json"),
            os.path.join(args.work, "scan_report.md"),
            os.path.join(args.work, "gaps.json"),
        ],
        "next": "read work/scan_report.md, then draft into work/draft.md citing [E####] only",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
