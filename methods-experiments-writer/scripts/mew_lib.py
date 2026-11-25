#!/usr/bin/env python3
"""mew_lib.py - shared helpers for the methods-experiments-writer skill.

Standard library only. No network access. Nothing is written outside the paths
you pass on the command line.

Provenance is the point of this module: every helper that reads a source file
returns a locator a reviewer can re-open by hand.

    text file   ->  "<path>:<line>"          (1-based line number)
    json config ->  "<path>#/a/b/0/c"        (RFC 6901 JSON pointer)
    log file    ->  "<path>:<line>"          (the exact log line)

Nothing here decides what a number means. It only records where the number was
found and how confident the extraction rule is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ipynb_checkpoints", "dist", "build",
    ".idea", ".vscode", "site-packages",
}

TEXT_SUFFIXES = {
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".env", ".txt", ".log", ".md", ".rst", ".csv", ".tsv", ".py", ".sh",
    ".bash", ".zsh", ".ipynb", ".tex", ".bib", ".r", ".jl", ".m", ".c",
    ".h", ".cc", ".cpp", ".java", ".go", ".rs", ".js", ".ts", ".yaml5",
    ".dockerfile", ".gitignore", ".mod", ".xml", ".html", ".sql",
}

CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env"}
CODE_SUFFIXES = {".py", ".sh", ".bash", ".r", ".jl", ".m", ".c", ".cc", ".cpp", ".java", ".go", ".rs", ".js", ".ts", ".ipynb"}
LOG_HINTS = ("log", "stdout", "stderr", "train", "run", "output", "console", "terminal")
DATA_HINTS = ("dataset", "data", "split", "corpus", "benchmark", "loader")
PAPER_SUFFIXES = {".pdf", ".tex", ".bib"}
TABLE_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}

# Parameter vocabulary. (canonical, unit, aliases-as-regex)
# Keep aliases lowercase; matching is done on lowercased keys with separators
# normalised to "_".
PARAM_VOCAB = [
    ("learning_rate", "1", r"(^|_)(lr|learn(ing)?_?rate|base_lr|init_lr|peak_lr)(_|$)"),
    ("batch_size", "samples", r"(^|_)(batch_?size|train_batch_?size|micro_?batch|per_device_train_batch_size)(_|$)"),
    ("epochs", "epochs", r"(^|_)(epoch|epochs|num_epochs|n_epochs|max_epochs)(_|$)"),
    ("steps", "steps", r"(^|_)(steps|max_steps|num_steps|train_steps|total_steps|iters|iterations)(_|$)"),
    ("warmup", "steps", r"(^|_)(warmup|warmup_steps|warmup_ratio|warm_up)(_|$)"),
    ("seed", "1", r"(^|_)(seed|random_seed|manual_seed|torch_seed|np_seed|rng_seed)(_|$)"),
    ("weight_decay", "1", r"(^|_)(weight_?decay|wd|wd_?ratio)(_|$)"),
    ("optimizer", "name", r"(^|_)(optim|optimizer|opt_name|optimiser)(_|$)"),
    ("scheduler", "name", r"(^|_)(scheduler|sched|lr_scheduler|lr_sched|schedule)(_|$)"),
    ("momentum", "1", r"(^|_)(momentum|beta1|beta_1|beta2|beta_2)(_|$)"),
    ("dropout", "1", r"(^|_)(dropout|drop_?out|p_drop)(_|$)"),
    ("precision", "name", r"(^|_)(precision|fp16|bf16|amp|mixed_precision|dtype)(_|$)"),
    ("grad_accum", "steps", r"(^|_)(grad_?accum|gradient_accumulation_steps|accum_steps)(_|$)"),
    ("num_gpus", "GPUs", r"(^|_)(num_gpus|n_gpus|gpu_count|world_size|devices|nproc_per_node)(_|$)"),
    ("gpu_model", "name", r"(^|_)(gpu|gpu_model|device_name|accelerator)(_|$)"),
    ("framework_version", "version", r"(^|_)(torch|pytorch|tensorflow|jax|version|pkg_version|framework)(_|$)"),
    ("cuda_version", "version", r"(^|_)(cuda|cuda_version|cudnn)(_|$)"),
    ("python_version", "version", r"(^|_)(python|python_version|py_version)(_|$)"),
    ("split_ratio", "ratio", r"(^|_)(split|split_ratio|train_?val_?test|val_?split|test_?split|val_?size|test_?size|holdout)(_|$)"),
    ("dataset_name", "name", r"(^|_)(dataset|data_?name|dataset_?name|corpus)(_|$)"),
    ("dataset_version", "version", r"(^|_)(dataset_?version|version_tag|data_?version|revision)(_|$)"),
    ("num_samples", "samples", r"(^|_)(num_samples|n_samples|n_rows|rows|train_size|dataset_size|total_samples)(_|$)"),
    ("metric", "name", r"(^|_)(metric|metrics|eval_metric|eval|score)(_|$)"),
    ("repeats", "runs", r"(^|_)(repeat|repeats|n_runs|num_runs|trials|num_seeds)(_|$)"),
    ("threshold", "1", r"(^|_)(threshold|thresholds|tau|cutoff)(_|$)"),
]

# Essential items a methods/experiments section must answer. Used by both the
# scan (to build the question list) and the audit (to score coverage).
ESSENTIALS = [
    ("steps",        "ordered procedure with input/operation/output per step"),
    ("setup",        "hardware, software versions, environment, seeds, repeats"),
    ("params",       "named parameter values with units and target"),
    ("datasets",     "dataset name, version, size, split ratios and split method"),
    ("baselines",    "baseline identity, version, equal-budget statement, metric, statistics"),
    ("repro",        "code version, command, data access, and concrete failure limits"),
    ("limitations",  "limitation tied to a specific failure scenario, not boilerplate"),
]

NUM_RE = re.compile(
    r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
)


# ---------------------------------------------------------------------------
# io helpers
# ---------------------------------------------------------------------------

def ensure_dir(path):
    if path:
        os.makedirs(path, exist_ok=True)
    return path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path, max_bytes=4_000_000):
    """Return decoded text, or None when the file is binary / too large.

    Binary is decided by NUL bytes in the first 8 KiB, not by suffix: a .log
    can be binary and a .bin can be a text table.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size > max_bytes:
        return None
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
            if b"\x00" in head:
                return None
            rest = f.read()
    except OSError:
        return None
    data = head + rest
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def load_json(path):
    txt = read_text(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except ValueError:
        return None


def write_json(path, obj):
    ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def write_text(path, text):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# locators
# ---------------------------------------------------------------------------

class LineIndex:
    """Map a character offset to a 1-based line number, cheaply."""

    __slots__ = ("_starts", "text")

    def __init__(self, text):
        self.text = text
        starts = [0]
        find = text.find
        i = 0
        while True:
            i = find("\n", i)
            if i < 0:
                break
            i += 1
            starts.append(i)
        self._starts = starts

    def line_of(self, offset):
        lo, hi = 0, len(self._starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    def line_text(self, lineno):
        if 1 <= lineno <= len(self._starts):
            start = self._starts[lineno - 1]
            end = self._starts[lineno] - 1 if lineno < len(self._starts) else len(self.text)
            return self.text[start:end].rstrip("\r")
        return ""


def json_pointer(parts):
    """RFC 6901 pointer from a list of path segments."""
    out = []
    for p in parts:
        out.append(str(p).replace("~", "~0").replace("/", "~1"))
    return "#/" + "/".join(out) if out else "#"


# ---------------------------------------------------------------------------
# config parsing (json / yaml-subset / toml / ini / env)
# ---------------------------------------------------------------------------

def _yaml_scalar(raw):
    v = raw.strip()
    if v == "" or v in ("~", "null", "Null", "NULL"):
        return None
    if v in ("true", "True", "TRUE", "yes", "on"):
        return True
    if v in ("false", "False", "FALSE", "no", "off"):
        return False
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_yaml_scalar(x) for x in inner.split(",")]
    try:
        if re.fullmatch(r"[-+]?\d+", v):
            return int(v)
        if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", v):
            return float(v)
    except ValueError:
        pass
    return v


def parse_yaml(text):
    """Minimal indentation-based YAML reader.

    Handles nested mappings, scalars, inline lists and block lists of scalars.
    It does NOT handle anchors, multi-document streams, block scalars or flow
    mappings - on those a config file falls back to the raw line scanner, and
    the ledger says so through method="raw_line". PyYAML is used when present.
    """
    try:  # prefer a real parser when the image ships one
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except Exception:
        pass

    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("- "):
            continue  # block list item: handled by the raw scanner
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip().strip("\"'")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        parent = stack[-1][1]
        if not isinstance(parent, dict):
            continue
        if rest.strip() == "":
            child = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _yaml_scalar(rest)
    return root


def parse_toml(text):
    try:
        import tomllib
        return tomllib.loads(text)
    except Exception:
        pass
    root = {}
    cur = root
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = root
            for part in line[1:-1].split("."):
                cur = cur.setdefault(part.strip(), {})
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            cur[k.strip()] = _yaml_scalar(v)
    return root


def parse_ini(text):
    root = {}
    cur = root
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = root.setdefault(line[1:-1].strip(), {})
            continue
        if "=" in line or ":" in line:
            sep = "=" if "=" in line else ":"
            k, _, v = line.partition(sep)
            cur[k.strip()] = _yaml_scalar(v)
    return root


def parse_env(text):
    root = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:]
        if "=" in line:
            k, _, v = line.partition("=")
            root[k.strip()] = _yaml_scalar(v)
    return root


def load_structured(path, text):
    """Parse a config file by suffix; return (object, parser_name) or (None, None)."""
    low = path.lower()
    if low.endswith(".json") or low.endswith(".jsonl"):
        try:
            return json.loads(text), "json"
        except ValueError:
            return None, None
    if low.endswith((".yaml", ".yml")):
        try:
            obj = parse_yaml(text)
            return (obj, "yaml") if isinstance(obj, (dict, list)) else (None, None)
        except Exception:
            return None, None
    if low.endswith(".toml"):
        try:
            return parse_toml(text), "toml"
        except Exception:
            return None, None
    if low.endswith((".ini", ".cfg", ".conf")):
        return parse_ini(text), "ini"
    if low.endswith(".env") or os.path.basename(low) in (".env", "env"):
        return parse_env(text), "env"
    return None, None


def flatten(obj, prefix=(), out=None, max_items=2000):
    """Flatten nested containers into [(dotted_key, value, pointer_parts)]."""
    if out is None:
        out = []
    if len(out) >= max_items:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                flatten(v, prefix + (k,), out, max_items)
            else:
                out.append((".".join(str(p) for p in prefix + (k,)), v, prefix + (k,)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                flatten(v, prefix + (i,), out, max_items)
            else:
                out.append((".".join(str(p) for p in prefix + (i,)), v, prefix + (i,)))
    return out


# ---------------------------------------------------------------------------
# numbers and names
# ---------------------------------------------------------------------------

_UNIT_RE = re.compile(
    r"^\s*(%|percent|s|sec|secs|seconds|ms|min|mins|minutes|h|hr|hrs|hours|"
    r"kb|mb|gb|tb|k|m|b|gpus?|cpus?|cores?|steps?|iters?|epochs?|samples?|"
    r"tokens?|images?|px|dpi|mm|cm|nm|um|ev|kv|v|w|kw|kwh|usd|rmb|cny)\b",
    re.I,
)


def norm_number(value):
    """Turn a value from a file into a float, or None.

    1e-4 -> 0.0001, "3,000" -> 3000.0, "80%" -> 80.0, 32 -> 32.0,
    "0.5 " -> 0.5, "1.5x" -> 1.5. Percentages keep their scale: the caller
    decides whether 0.8 and 80% are the same fact.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip().replace(",", "")
    m = NUM_RE.match(s)
    if not m:
        return None
    token = m.group(0)
    rest = s[m.end():]
    if rest.strip() and not _UNIT_RE.match(rest) and not rest.strip().startswith(("x", "X", "*")):
        # "v1.2.3" or "a100" style - not a bare measurement
        if re.match(r"^[\w.\-]", rest.strip()):
            return None
    try:
        return float(token)
    except ValueError:
        return None


def same_number(a, b, rel=1e-9):
    if a is None or b is None:
        return False
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale <= rel


_DATASET_SCOPE = re.compile(r"(^|_)(data|dataset|corpus|benchmark)(_|$)")
_SPLIT_LEAVES = {"train", "val", "valid", "validation", "test", "dev", "holdout"}


def canonical_param(dotted_key):
    """Return (canonical_name, unit) for a config key, or (None, None).

    The parent path matters: `data.version` is a dataset version, not a
    framework version, and `data.train` is a split ratio, not a column name.
    Reading only the leaf silently files both of them under the wrong name.
    """
    full = str(dotted_key)
    leaf = full.split(".")[-1]
    key = re.sub(r"[^a-z0-9]+", "_", leaf.lower()).strip("_")
    # A baseline version is not a runtime version. Both leaves read "version",
    # and filing v0.9 of a baseline under `runtime` sends a reader looking at
    # the wrong part of the pipeline.
    if re.search(r"baseline|基线", full, re.I):
        if "version" in key or re.fullmatch(r"v?\d+[.\d]*", str(dotted_key)):
            return "baseline_version", "version"
        return "baseline_statement", ""
    if _DATASET_SCOPE.search(re.sub(r"[^a-z0-9]+", "_", full.lower())):
        if "seed" in key:
            return "seed", "1"
        if leaf.lower() in _SPLIT_LEAVES or re.search(r"split|ratio", key):
            return "split_ratio", "ratio"
        if "version" in key or key in ("tag", "revision"):
            return "dataset_version", "version"
        if re.search(r"(name|dataset)$", key):
            return "dataset_name", "name"
        if re.search(r"(size|samples|count|rows|n)$", key):
            return "num_samples", "samples"
    for canon, unit, pattern in PARAM_VOCAB:
        if re.search(pattern, key):
            return canon, unit
    return None, None


def param_leaf(dotted_key):
    """The leaf of a key, normalised, used to keep distinct parameters apart."""
    leaf = str(dotted_key).split(".")[-1]
    return re.sub(r"[^a-z0-9]+", "_", leaf.lower()).strip("_")


# What a parameter acts on, by canonical meaning. The source column already says
# where a value was found; repeating the filename there would waste the one
# column a reader uses to work out which part of the pipeline to change.
TARGET_BY_CANON = {
    "learning_rate": "optimiser",
    "weight_decay": "optimiser",
    "optimizer": "optimiser",
    "momentum": "optimiser",
    "grad_accum": "optimiser step",
    "warmup": "LR schedule",
    "scheduler": "LR schedule",
    "batch_size": "dataloader",
    "epochs": "training loop",
    "steps": "training loop",
    "precision": "autocast context",
    "dropout": "model",
    "seed": "RNG",
    "repeats": "evaluation",
    "gpu_model": "hardware",
    "num_gpus": "hardware",
    "cuda_version": "runtime",
    "framework_version": "runtime",
    "python_version": "runtime",
    "dataset_name": "data",
    "dataset_version": "data",
    "split_ratio": "data",
    "num_samples": "data",
    "metric": "evaluation",
    "threshold": "evaluation",
    "baseline_version": "comparison",
    "baseline_statement": "comparison",
}


def target_of(name, fallback=""):
    """Semantic target for a parameter name, or the fallback when unknown."""
    canon, _ = canonical_param(name)
    if canon and canon in TARGET_BY_CANON:
        return TARGET_BY_CANON[canon]
    leaf = param_leaf(name)
    if re.search(r"(count|rows|samples)$", leaf):
        return "data"
    if re.search(r"(started_at|timestamp|finished_at)$", leaf):
        return "run metadata"
    if "version" in leaf:
        return "runtime"
    return fallback or "-"


def looks_like_param_key(dotted_key):
    canon, _ = canonical_param(dotted_key)
    return canon is not None


def fmt_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    if v is None:
        return "null"
    return str(v)


def snippet(text, limit=160):
    s = re.sub(r"\s+", " ", str(text)).strip()
    return s[:limit] + ("..." if len(s) > limit else "")


def norm_path_for_report(path, roots):
    """Make a locator readable by stripping the longest matching root prefix."""
    best = path
    for root in roots:
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            continue
        if not rel.startswith(".."):
            if len(rel) < len(best):
                best = rel.replace(os.sep, "/")
    return best


# ---------------------------------------------------------------------------
# evidence ledger
# ---------------------------------------------------------------------------

class Ledger:
    """Append-only evidence ledger with stable E-ids and no silent duplicates."""

    def __init__(self):
        self.rows = []
        self._seen = {}

    def add(self, *, kind, name, value, source_file, source_locator,
            unit="", applies_to="", method="", confidence="high",
            status="ok", note=""):
        key = (kind, name, fmt_value(value), source_file, source_locator)
        if key in self._seen:
            return self._seen[key]
        eid = "E%04d" % (len(self.rows) + 1)
        row = {
            "eid": eid,
            "kind": kind,
            "name": name,
            "value": value,
            "display": fmt_value(value),
            "unit": unit,
            "applies_to": applies_to,
            "source_file": source_file,
            "source_locator": source_locator,
            "method": method,
            "confidence": confidence,
            "status": status,
            "note": note,
            "cited_in_draft": False,
            "used_evidence_in_draft": None,
        }
        self.rows.append(row)
        self._seen[key] = eid
        return eid

    def get(self, eid):
        for r in self.rows:
            if r["eid"] == eid:
                return r
        return None

    def mark_conflicts(self, rel_tol=1e-9):
        """Flag rows that are the same parameter with different numbers.

        Grouping is by (canonical meaning, leaf key), not by canonical meaning
        alone: `experiment.seed` and `data.split_seed` are two different seeds,
        and calling that a conflict would train the reader to ignore real ones.
        """
        by_name = {}
        for r in self.rows:
            if not _is_param_row(r):
                continue
            canon, _ = canonical_param(r["name"])
            leaf = param_leaf(r["name"])
            key = (canon or leaf, leaf)
            by_name.setdefault(key, []).append(r)
        conflicts = []
        for key, rows in by_name.items():
            nums = [(r, norm_number(r["value"])) for r in rows]
            have = [(r, n) for r, n in nums if n is not None]
            if len(have) < 2:
                continue
            base_r, base_v = have[0]
            differ = [(r, n) for r, n in have[1:] if not same_number(base_v, n, rel_tol)]
            if differ:
                group = [base_r] + [r for r, _ in differ]
                for r in group:
                    r["status"] = "conflict"
                    r["note"] = (r.get("note") or "") + (
                        " | same parameter also appears with a different value in: "
                        + ", ".join(x["source_locator"] for x in group if x is not r)
                    ).strip()
                conflicts.append({
                    "parameter": "%s (%s)" % (key[0], key[1]) if key[0] != key[1] else key[0],
                    "eids": [r["eid"] for r in group],
                    "values": [
                        {"eid": r["eid"], "value": r["display"], "source": r["source_locator"]}
                        for r in group
                    ],
                    "question": (
                        "Which source is authoritative for '%s'? %s "
                        "Report both until the author confirms; do not pick one silently."
                        % (key[1], "; ".join(
                            "%s says %s (%s)" % (r["eid"], r["display"], r["source_locator"])
                            for r in group))
                    ),
                })
        return conflicts

    def to_dict(self):
        return {
            "schema": "mew-evidence-ledger/v1",
            "storage_convention": {
                "text_file": "<path>:<line> (1-based)",
                "json_config": "<path>#/<json-pointer>",
                "log_file": "<path>:<line> (the exact log line)",
            },
            "rows": self.rows,
        }


def _is_param_row(row):
    if row.get("kind") in ("config_value", "code_default", "log_value", "paper_statement"):
        if canonical_param(row.get("name"))[0]:
            return True
    return False


def is_binary_path(path):
    ext = os.path.splitext(path)[1].lower()
    return ext not in TEXT_SUFFIXES and ext not in {".pdf"}
