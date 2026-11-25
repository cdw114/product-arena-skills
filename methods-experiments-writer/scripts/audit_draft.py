#!/usr/bin/env python3
"""audit_draft.py - step 5..6 of the methods-experiments-writer skill.

Checks a draft against the evidence ledger:

  1. every number in the prose traces to an eid that the same sentence cites
  2. a parameter table, if present, agrees with the ledger value by value
  3. the six mandated elements are actually covered
  4. the reproducibility checklist is stated, not implied
  5. limitations name a concrete failure scenario instead of a platitude

    python3 scripts/audit_draft.py --draft work/draft.md --work work
    python3 scripts/audit_draft.py --draft work/draft.md --work work --strict

Writes work/audit.json and work/audit.md. With --strict it exits 1 when any
number is unsourced, so a caller can gate the emit step on it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mew_lib as L  # noqa: E402

EID_RE = re.compile(r"\[(E\d{4})\]")
TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?%?(?![A-Za-z0-9_])"
)
VERSION_RE = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)*)\b")
DOCREF_RE = re.compile(
    r"(?:Fig(?:ure)?|Tab(?:le)?|Sec(?:tion)?|Eq(?:uation)?|Algorithm|Step|Appendix|"
    r"图|表|节|式|算法|步骤)\s*\.?\s*\d+(?:[.\-]\d+)*",
    re.I,
)
CITEBRACKET_RE = re.compile(r"\[\d+(?:\s*[,-]\s*\d+)*\]")
FENCE_RE = re.compile(r"```.*?```", re.S)
# Version strings and dates are numbers too, but they are not measurements: they
# are audited as strings against the ledger, and masked before the numeric scan
# so that "v1.2" does not leak a bare "2" into the parameter audit.
VERSION_SPAN_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)*\b")
DATE_RE = re.compile(
    r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?\b"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"
)

ELEMENT_SPECS = {
    "steps": {
        "label": "ordered procedure",
        "pieces": {
            "numbered_or_stepped": r"(?:^|\n)\s*(?:\d+[.)]\s|第[一二三四五六七八九十\d]+步|Step\s*\d|Phase\s*\d)",
            "input_stated": r"(?:输入|输入数据|input|takes? as input)",
            "output_stated": r"(?:输出|output|produces?|yields?)",
            "decision_condition": r"(?:如果|若|当|校验|检查|if\b|unless|when\b|verify|assert)",
        },
    },
    "setup": {
        "label": "experimental setup",
        "pieces": {
            "hardware": r"(?:GPU|显卡|加速卡|CPU|CPU cores?|内存|RAM|VRAM|显存|NVIDIA|A100|H100|V100|RTX)",
            "software_versions": r"(?:CUDA|cuDNN|PyTorch|torch|TensorFlow|JAX|Python|驱动|driver|版本|version|==)",
            "random_seed": r"(?:随机种子|seed|种子|random_state)",
        },
    },
    "params": {
        "label": "parameters",
        "pieces": {
            "table_present": r"(?m)^\s*\|.+\|\s*$",
            "learning_rate": r"(?:学习率|learning rate|(?<![A-Za-z])lr(?![A-Za-z])|η)",
            "batch": r"(?:批大小|批(?:次)?大小|batch(?:_size)?|micro[- ]?batch)",
            "epochs_or_steps": r"(?:epoch|轮次|迭代|steps|步数|iterations)",
            "unit_or_target": r"(?:单位|unit|作用对象|applies to|作用于)",
        },
    },
    "datasets": {
        "label": "datasets and splits",
        "pieces": {
            "dataset_named": r"(?:数据集|dataset|corpus|benchmark)",
            "version_stated": r"(?:版本|version|release|tag|revision|v\d+\.\d+)",
            "split_ratios": r"(?:划分|切分|split|训练集|验证集|测试集|train.{0,6}val.{0,6}test|hold[- ]?out)",
            "size_stated": r"(?:\d[\d,]*\s*(?:条|个|例|samples|examples|records|rows|images|molecules|structures|frames|tokens))",
        },
    },
    "baselines": {
        "label": "baselines and comparison",
        "pieces": {
            "baseline_named": r"(?:基线|baseline|对照|compared (?:with|to)|对比|参考方法)",
            "baseline_version": r"(?:版本|version|release|v\d|官方|official|原论文|original)",
            "equal_budget": r"(?:预算|budget|同等|同一(?:计算|显存|时)|same (?:compute|budget|settings)|comparable)",
            "metric_and_statistics": r"(?:指标|metric|均值|标准差|std|±|置信区间|confidence|significant|显著性)",
        },
    },
    "repro": {
        "label": "reproducibility",
        "pieces": {
            "run_command": r"(?:```|\$ |python3? |torchrun|bash |sbatch|srun|命令|command)",
            "code_version": r"(?:commit|git|哈希|hash|版本号|tag|release)",
            "data_access": r"(?:获取|下载|download|申请|access|公开|license|许可|URL|https?://)",
            "environment": r"(?:环境|environment|requirements|conda|pip|docker|镜像|image)",
        },
    },
    "limitations": {
        "label": "limitations",
        "pieces": {
            "limitation_named": r"(?:限制|局限|不足|limitation|caveat|不适用|fails?|失效|风险)",
            "concrete_condition": r"(?:当|一旦|若|如果|when\b|if\b|under .{0,20}conditions?|超过|低于|大于|小于)",
            "scope_of_use": r"(?:适用|scope|仅适用|不推荐|适用场景|范围|applies only|valid only)",
        },
    },
}

REPRO_ITEMS = [
    ("code version", r"(?:commit|git|哈希|hash|版本号|tag)"),
    ("environment", r"(?:环境|environment|requirements|conda|pip|docker|镜像)"),
    ("run command", r"(?:```|\$ |python3? |torchrun|bash |sbatch|命令|command)"),
    ("random seed", r"(?:种子|seed|random_state)"),
    ("data access", r"(?:获取|下载|download|申请|access|https?://)"),
    ("hardware", r"(?:GPU|显卡|加速卡|CPU|NVIDIA|A100|H100|V100|RTX)"),
    ("repeat count", r"(?:次重复|重复|repeats?|runs?|trials?|n\s*=\s*\d)"),
]

PLATITUDES = [
    r"future work", r"further stud", r"more research", r"有待进一步", r"未来工作", r"进一步研究",
    r"limitations exist", r"存在一定(?:的)?局限", r"受到.{0,6}限制",
]


HEADING_NUM_RE = re.compile(r"(?m)^(#{1,6}[ \t]+)(\d+(?:\.\d+)*)")
LIST_NUM_RE = re.compile(r"(?m)^([ \t]{0,8})(\d+)([.)][ \t])")


def strip_docrefs(text, structural=True):
    """Blank out numbers that label structure rather than measure anything.

    Section numbers, ordered-list markers, figure/table/section references and
    citation brackets are all digits, and none of them is a fact. Leaving them
    in would bury the handful of numbers that do need a source under noise,
    which is exactly how a numeric audit gets switched off in practice.

    `structural=False` keeps the list markers, because the coverage check needs
    them: an ordered procedure is recognised by its numbering.
    """
    out = DOCREF_RE.sub(lambda m: " " * len(m.group(0)), text)
    out = CITEBRACKET_RE.sub(lambda m: " " * len(m.group(0)), out)
    if not structural:
        return out

    def blank_group(m, gi):
        s = m.group(0)
        g = m.group(gi)
        start = m.start(gi) - m.start(0)
        return s[:start] + " " * len(g) + s[start + len(g):]

    out = HEADING_NUM_RE.sub(lambda m: blank_group(m, 2), out)
    out = LIST_NUM_RE.sub(lambda m: blank_group(m, 2), out)
    return out


def mask_versions_and_dates(text):
    """Blank out version spans and timestamps, returning the spans separately.

    A version is checked as a string against the ledger, not as a number, so it
    must not also reach the numeric audit.
    """
    spans = []

    def blank(m):
        spans.append((m.start(), m.group(0)))
        return " " * len(m.group(0))

    out = DATE_RE.sub(blank, text)
    out = VERSION_SPAN_RE.sub(blank, out)
    return out, spans


def split_blocks(text):
    """Split into audit blocks: a paragraph, or a single table row.

    Sentence-level locality is too brittle for hard-wrapped markdown: a line
    break inside a sentence would cut a citation away from the number it backs
    and report a false positive, which is the fastest way to get a numeric audit
    ignored. A block is one paragraph, except that each markdown table row is its
    own block, so a table can still be judged row by row.
    """
    blocks = []
    buf_start = None
    buf_end = None
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        is_table = stripped.startswith("|")
        if is_table or not stripped:
            if buf_start is not None:
                blocks.append((buf_start, buf_end))
                buf_start = None
            if is_table:
                blocks.append((offset, offset + len(line)))
        else:
            if buf_start is None:
                buf_start = offset
            buf_end = offset + len(line)
        offset += len(line)
    if buf_start is not None:
        blocks.append((buf_start, buf_end))
    if not blocks:
        blocks = [(0, len(text))]
    return blocks


def build_value_index(rows):
    idx = {}
    for r in rows:
        n = L.norm_number(r.get("value"))
        if n is None:
            continue
        for key in (round(n, 12),):
            idx.setdefault(key, []).append(r)
        if abs(n) <= 1.0:
            idx.setdefault(round(n * 100.0, 12), []).append(r)  # 0.8 <-> 80
        if n > 1.0 and n <= 100.0:
            idx.setdefault(round(n / 100.0, 12), []).append(r)
    return idx


def lookup(idx, n):
    if n is None:
        return []
    for key in (round(n, 12), round(n * 100.0, 12), round(n / 100.0, 12)):
        rows = idx.get(key)
        if rows:
            return rows
    return []


UNIT_CELLS = {"1", "-", "n/a", "na", "none", "dimensionless", "%", "percent"}


def _unit_cell(masked, pos):
    """Classify a numeric token that sits alone in a table cell.

    Returns (is_unit_token, row_has_other_number).

    A parameter table has a unit column, and for a dimensionless parameter that
    column holds "1". Auditing that "1" as a measured value produces one false
    positive per row, so a lone "1" is read as a unit label when the row already
    carries another number, or when the row's citation records a non-numeric
    value such as a precision name. A "1" that is the row's only number and whose
    citation is numeric is still audited.
    """
    line_start = masked.rfind("\n", 0, pos) + 1
    line_end = masked.find("\n", pos)
    if line_end < 0:
        line_end = len(masked)
    line = masked[line_start:line_end]
    if not line.strip().startswith("|"):
        return False, False
    cell_start = masked.rfind("|", 0, pos) + 1
    cell_end = masked.find("|", pos)
    if cell_end < 0:
        return False, False
    cell = masked[cell_start:cell_end].strip()
    others = [c.strip() for c in line.strip().strip("|").split("|")]
    numeric_others = [c for c in others if c != cell and L.norm_number(c) is not None]
    return cell in UNIT_CELLS, bool(numeric_others)


def audit_numbers(draft, rows):
    masked = strip_docrefs(draft)
    numeric_text, _vspans = mask_versions_and_dates(masked)
    idx = build_value_index(rows)
    by_eid = {r["eid"]: r for r in rows}
    code_spans = [(m.start(), m.end()) for m in FENCE_RE.finditer(draft)]
    blocks = split_blocks(masked)
    block_eids = [sorted(set(EID_RE.findall(draft[a:b]))) for a, b in blocks]

    def block_of(pos):
        for i, (a, b) in enumerate(blocks):
            if a <= pos < b:
                return i
        return len(blocks) - 1

    def in_code(pos):
        return any(a <= pos < b for a, b in code_spans)

    findings = []
    for m in TOKEN_RE.finditer(numeric_text):
        raw = m.group(0)
        n = L.norm_number(raw)
        if n is None:
            continue
        pos = m.start()
        bi = block_of(pos)
        local = block_eids[bi] if 0 <= bi < len(block_eids) else []
        local_rows = [by_eid[e] for e in local if e in by_eid]
        ctx = masked[max(0, pos - 90):pos + 90].replace("\n", " ")
        is_code = in_code(pos)

        exact = [r for r in local_rows if L.same_number(L.norm_number(r["value"]), n)]
        if exact:
            continue
        is_unit, row_has_other = _unit_cell(masked, pos)
        if is_unit and (row_has_other or (local_rows and all(
                L.norm_number(r["value"]) is None for r in local_rows))):
            continue
        anywhere = lookup(idx, n)
        if anywhere:
            findings.append({
                "kind": "value_without_local_citation",
                "text": raw, "value": n,
                "context": L.snippet(ctx, 160),
                "candidate_eids": [r["eid"] for r in anywhere][:4],
                "in_code_block": is_code,
                "fix": "cite the eid next to this number, or confirm it is a derived value and mark it [DERIVED]",
            })
            continue
        if re.fullmatch(r"[-+]?\d{1,2}", raw) and not is_code and _is_ordinal_context(ctx, raw):
            findings.append({
                "kind": "ordinal_or_label",
                "text": raw, "value": n, "context": L.snippet(ctx, 160),
                "candidate_eids": [], "in_code_block": is_code,
                "fix": "looks like a step/enumeration label; reword if it could be read as a measurement",
            })
            continue
        findings.append({
            "kind": "unsourced_number",
            "text": raw, "value": n, "context": L.snippet(ctx, 160),
            "candidate_eids": [], "in_code_block": is_code,
            "fix": "remove the number, add the source file/line to the ledger, or mark it TO-CONFIRM",
        })
    return findings, [e for sub in block_eids for e in sub]


def _is_ordinal_context(ctx, raw):
    return bool(re.search(r"(?:第|No\.?\s*|#)\s*$", ctx, re.I)) or bool(
        re.match(r"^\s*(?:个|步|类|种|阶段|group|step|class|case|stage)\b", ctx))


def audit_versions(draft, rows):
    """Check version strings as strings: '2.1.2' must appear in a cited row's value."""
    masked = strip_docrefs(draft)
    _numeric, spans = mask_versions_and_dates(masked)
    blocks = split_blocks(masked)
    by_eid = {r["eid"]: r for r in rows}

    def block_eids_at(pos):
        for a, b in blocks:
            if a <= pos < b:
                return sorted(set(EID_RE.findall(draft[a:b])))
        return []

    ledger_strings = [(r["eid"], str(r.get("display") or r.get("value") or "")) for r in rows]
    code_spans = [(m.start(), m.end()) for m in FENCE_RE.finditer(draft)]
    findings = []
    for pos, raw in spans:
        if re.match(r"^\d{4}[-/.]", raw) or re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", raw):
            continue  # timestamp: not a version
        bare = raw.lstrip("vV")
        local = [by_eid[e] for e in block_eids_at(pos) if e in by_eid]
        if any(bare in str(r.get("display") or "") for r in local):
            continue
        elsewhere = [eid for eid, s in ledger_strings if bare in s]
        findings.append({
            "kind": "version_without_local_citation" if elsewhere else "unsourced_version",
            "text": raw,
            "value": None,
            "context": L.snippet(masked[max(0, pos - 80):pos + 80], 150),
            "candidate_eids": elsewhere[:4],
            "in_code_block": any(a <= pos < b for a, b in code_spans),
            "fix": "cite the eid that records this version, or drop the version from the prose",
        })
    return findings


def audit_table(draft, rows):
    """Check markdown-table rows against the ledger.

    A row that cites eids is checked against exactly those rows: at least one
    cited value has to be corroborated by the row's own cells. That is stronger
    than matching on the parameter name, because a table row and the sentence it
    summarises must agree on the value, not merely on the label. Rows with no
    citation fall back to name matching and are reported as unbacked.
    """
    by_name = {}
    for r in rows:
        canon, _ = L.canonical_param(r["name"])
        if canon:
            by_name.setdefault(canon, []).append(r)
    by_eid = {r["eid"]: r for r in rows}
    problems = []
    checked = 0
    for line_no, line in enumerate(draft.splitlines(), start=1):
        s = line.strip()
        if not s.startswith("|") or set(s) <= set("|-: "):
            continue
        cells = [c.strip().strip("`*") for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        cited = [by_eid[e] for e in EID_RE.findall(s) if e in by_eid]
        numeric = [L.norm_number(c) for c in cells]
        numeric = [n for n in numeric if n is not None]
        if cited:
            checked += 1
            ok = False
            for r in cited:
                v = L.norm_number(r.get("value"))
                if v is not None:
                    if any(L.same_number(v, n) for n in numeric):
                        ok = True
                        break
                else:
                    needle = str(r.get("display") or "").strip()
                    if needle and needle.lower() in s.lower():
                        ok = True
                        break
            if not ok:
                problems.append({
                    "line": line_no,
                    "parameter": cited[0]["name"],
                    "table_values": [c for c in cells if L.norm_number(c) is not None],
                    "ledger": {r["eid"]: L.norm_number(r.get("value")) for r in cited},
                    "fix": ("the row cites %s but no cell repeats that value: fix the table or the "
                            "citation, and say which source won" % ", ".join(r["eid"] for r in cited)),
                })
            continue
        name_led = None
        for c in cells[:1]:
            canon, _ = L.canonical_param(c)
            if canon and canon in by_name:
                name_led = canon
                break
        if not name_led or not numeric:
            continue
        checked += 1
        ledger_vals = {r["eid"]: L.norm_number(r["value"]) for r in by_name[name_led]}
        if any(v is not None and any(L.same_number(v, lv) for lv in ledger_vals.values() if lv is not None)
               for v in numeric):
            continue
        problems.append({
            "line": line_no,
            "parameter": name_led,
            "table_values": [c for c in cells if L.norm_number(c) is not None],
            "ledger": ledger_vals,
            "fix": ("the row has no [E####] citation and its value matches no ledger row for "
                    "'%s': add the citation or correct the value" % name_led),
        })
    return problems, checked


def audit_coverage(draft):
    body = strip_docrefs(draft, structural=False)
    out = {}
    for key, spec in ELEMENT_SPECS.items():
        matched, missing = [], []
        for piece, pattern in spec["pieces"].items():
            if re.search(pattern, body, re.I | re.M):
                matched.append(piece)
            else:
                missing.append(piece)
        if len(matched) == len(spec["pieces"]):
            status = "complete"
        elif matched:
            status = "partial"
        else:
            status = "missing"
        out[key] = {
            "label": spec["label"],
            "status": status,
            "matched": matched,
            "missing": missing,
        }
    return out


def audit_repro(draft):
    body = strip_docrefs(draft)
    return [{"item": name, "present": bool(re.search(pat, body, re.I))} for name, pat in REPRO_ITEMS]


def audit_limitations(draft):
    body = strip_docrefs(draft)
    plat = [p for p in PLATITUDES if re.search(p, body, re.I)]
    has_cond = bool(re.search(r"(?:当|一旦|若|如果|when\b|if\b|超过|低于|大于|小于)", body))
    lim = audit_coverage(draft)["limitations"]
    return {
        "status": lim["status"],
        "has_failure_condition": has_cond,
        "platitudes_found": plat,
        "ok": lim["status"] != "missing" and has_cond and not plat,
        "fix": ("state when the method fails (input size, distribution shift, missing metadata) "
                "and delete boilerplate about future work"),
    }


def audit_citations(draft, rows):
    cited = set(EID_RE.findall(draft))
    high_value = [r for r in rows if L.canonical_param(r["name"])[0] and r["confidence"] == "high"]
    uncited = [r for r in high_value if r["eid"] not in cited]
    unknown = sorted(e for e in cited if not any(r["eid"] == e for r in rows))
    return {
        "cited_eids": len(cited),
        "unknown_eids": unknown,
        "uncited_high_value": [
            {"eid": r["eid"], "name": r["name"], "value": r["display"], "source": r["source_locator"]}
            for r in uncited[:40]
        ],
        "uncited_high_value_count": len(uncited),
    }


def render_md(report):
    zh = report.get("language") == "zh"
    T = (lambda a, b: a + " / " + b) if zh else (lambda a, b: b)
    o = ["# Draft audit\n"]
    o.append("%s: `%s`" % (T("草稿", "Draft"), report["draft"]))
    o.append("")
    nums = report["numbers"]
    counts = {}
    for f in nums:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    o.append("## " + T("数字溯源", "Number provenance"))
    o.append("")
    o.append("%s: %d   " % (T("发现条目", "Findings"), len(nums)) + "  ".join(
        "- %s: %d" % (k, v) for k, v in sorted(counts.items())))
    o.append("")
    if nums:
        o.append("| " + T("类型", "kind") + " | " + T("值", "value") + " | " + T("上下文", "context") + " | " + T("建议", "fix") + " |")
        o.append("|---|---|---|---|")
        for f in nums[:60]:
            o.append("| %s | `%s`%s | %s | %s |" % (
                f["kind"], f["text"], " (code)" if f.get("in_code_block") else "",
                f["context"].replace("|", "\\|"), f["fix"]))
    else:
        o.append(T("正文中的每个数字都能在同一句的 [E####] 标注里找到对应取值。",
                   "Every number in the prose matches a value named by an [E####] tag in its own sentence."))
    o.append("")
    o.append("## " + T("参数表对齐", "Parameter table alignment"))
    o.append("")
    t = report["table"]
    o.append("%s: %d, %s: %d" % (T("已核对行", "rows checked"), t["checked"],
                                 T("不一致", "mismatched"), len(t["problems"])))
    for p in t["problems"]:
        o.append("- line %d `%s`: table says %s, ledger says %s — %s" % (
            p["line"], p["parameter"], ", ".join(p["table_values"]), p["ledger"], p["fix"]))
    o.append("")
    o.append("## " + T("六要素覆盖", "Six-element coverage"))
    o.append("")
    o.append("| " + T("要素", "element") + " | " + T("状态", "status") + " | " + T("缺口", "missing pieces") + " |")
    o.append("|---|---|---|")
    for k, v in report["coverage"].items():
        o.append("| %s | %s | %s |" % (v["label"], v["status"], ", ".join(v["missing"]) or "-"))
    o.append("")
    o.append("## " + T("可复现清单", "Reproducibility checklist"))
    o.append("")
    for item in report["repro"]:
        o.append("- [%s] %s" % ("x" if item["present"] else " ", item["item"]))
    o.append("")
    o.append("## " + T("限制条件", "Limitations"))
    o.append("")
    lim = report["limitations"]
    o.append("%s: %s; %s: %s; %s: %s" % (
        T("状态", "status"), lim["status"],
        T("有具体失效条件", "has a failure condition"), lim["has_failure_condition"],
        T("套话", "platitudes"), lim["platitudes_found"] or "-"))
    o.append("")
    o.append("## " + T("引用覆盖", "Citation coverage"))
    o.append("")
    o.append("%s: %d; %s: %d" % (T("被引用 eid", "cited eids"), report["citations"]["cited_eids"],
                                 T("未引用的高置信参数", "uncited high-confidence parameters"),
                                 report["citations"]["uncited_high_value_count"]))
    if report["citations"]["unknown_eids"]:
        o.append("")
        o.append("**" + T("台账中不存在的 eid", "eids that do not exist in the ledger") + "**: " +
                 ", ".join(report["citations"]["unknown_eids"]))
    o.append("")
    must = report["must_fix"]
    o.append("## " + T("必须修复", "Must fix"))
    o.append("")
    if must:
        for item in must:
            o.append("1. " + item)
    else:
        o.append(T("无。", "None."))
    o.append("")
    o.append("## " + T("结论", "Verdict"))
    o.append("")
    o.append("`%s`" % report["verdict"])
    o.append("")
    return "\n".join(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit a methods/experiments draft against its evidence ledger.")
    ap.add_argument("--draft", required=True)
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any number is unsourced")
    ap.add_argument("--language", default=None, choices=["zh", "en"])
    args = ap.parse_args(argv)

    if not os.path.isfile(args.draft):
        print(json.dumps({"status": "failed", "error": "draft not found: %s" % args.draft}), file=sys.stderr)
        return 2
    draft = L.read_text(args.draft)
    if draft is None:
        print(json.dumps({"status": "failed", "error": "draft is not readable text: %s" % args.draft}), file=sys.stderr)
        return 2

    ledger_path = os.path.join(args.work, "evidence.json")
    ledger = L.load_json(ledger_path) or {}
    rows = ledger.get("rows", [])
    contract = L.load_json(os.path.join(args.work, "contract.json")) or {}
    lang = args.language or contract.get("deliverable_language") or (
        "zh" if len(re.findall(r"[\u4e00-\u9fff]", draft)) > 40 else "en")

    findings, _ = audit_numbers(draft, rows)
    findings += audit_versions(draft, rows)
    table_problems, table_checked = audit_table(draft, rows)
    coverage = audit_coverage(draft)
    repro = audit_repro(draft)
    limitations = audit_limitations(draft)
    citations = audit_citations(draft, rows)

    must_fix = []
    unsourced = [f for f in findings
                 if f["kind"] in ("unsourced_number", "unsourced_version") and not f.get("in_code_block")]
    if unsourced:
        must_fix.append("replace or source %d number/version(s) that appear nowhere in the ledger: %s" % (
            len(unsourced), ", ".join(sorted({f["text"] for f in unsourced})[:12])))
    if table_problems:
        must_fix.append("reconcile %d table row(s) that disagree with the ledger" % len(table_problems))
    for key, val in coverage.items():
        if val["status"] != "complete":
            must_fix.append("complete the %s element (missing: %s)" % (val["label"], ", ".join(val["missing"])))
    missing_repro = [i["item"] for i in repro if not i["present"]]
    if missing_repro:
        must_fix.append("state reproducibility items: " + ", ".join(missing_repro))
    if not limitations["ok"]:
        must_fix.append(limitations["fix"])
    if citations["unknown_eids"]:
        must_fix.append("remove eids that are not in the ledger: " + ", ".join(citations["unknown_eids"][:8]))

    blocking = bool(unsourced or table_problems or citations["unknown_eids"])
    verdict = "blocked" if blocking else ("needs_revision" if must_fix else "ready")
    report = {
        "schema": "mew-draft-audit/v1",
        "draft": os.path.abspath(args.draft),
        "language": lang,
        "verdict": verdict,
        "numbers": findings,
        "table": {"checked": table_checked, "problems": table_problems},
        "coverage": coverage,
        "repro": repro,
        "limitations": limitations,
        "citations": citations,
        "must_fix": must_fix,
        "counts": {
            "unsourced_numbers": len(unsourced),
            "value_without_local_citation": sum(
                1 for f in findings if f["kind"] in ("value_without_local_citation",
                                                     "version_without_local_citation")),
            "table_mismatches": len(table_problems),
            "elements_complete": sum(1 for v in coverage.values() if v["status"] == "complete"),
            "elements_total": len(coverage),
        },
    }
    L.ensure_dir(args.work)
    L.write_json(os.path.join(args.work, "audit.json"), report)
    L.write_text(os.path.join(args.work, "audit.md"), render_md(report))
    print(json.dumps({
        "status": "ok", "verdict": verdict, "counts": report["counts"],
        "must_fix": must_fix, "artifacts": [
            os.path.join(args.work, "audit.json"), os.path.join(args.work, "audit.md")],
    }, ensure_ascii=False, indent=2))
    if args.strict and blocking:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
