#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reproduce — one-shot local self-test of the introduction / related-work skill.

This is NOT an official case and produces no benchmark score. It runs the Skill
through exactly the entry point the evaluator uses (`scripts/run_case.py`), on
fixtures that ship with the bundle, and writes the evidence under `execution/`:

    run 1  clean case (English)        -> gate must be pass, 0 errors, 0 warnings
    run 2  planted-defect case         -> gate must fail, every declared defect caught
    run 3  Chinese case                -> gate must be pass (bilingual + GB/T output)
    run 4  no reference library        -> must degrade honestly, never invent citations
    run 5  no draft yet                -> plan must leave a status=partial result.json

Run:  python3 src/reproduce.py            # writes execution/results/ and appends execution/run.log
      python3 src/reproduce.py --quick    # skip runs 4 and 5

Every number in characterization.json comes from this script.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
EX = os.path.join(ROOT, "examples")
RESULTS = os.path.join(ROOT, "execution", "results")
RUN_LOG = os.path.join(ROOT, "execution", "run.log")
RUN_CASE = os.path.join(SCRIPTS, "run_case.py")


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #

def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg)
    print(line)
    os.makedirs(os.path.dirname(RUN_LOG), exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path, obj):
    write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def run_stage(input_dir, out, work, stage):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    cp = subprocess.run([sys.executable, RUN_CASE, "--input", input_dir, "--out", out,
                         "--work", work, "--stage", stage],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        env=env, timeout=600)
    tail = [ln for ln in ((cp.stdout or "") + (cp.stderr or "")).splitlines() if ln.strip()][-6:]
    return cp.returncode, tail


def codes_of(audit):
    """{(rule_id, code, severity)} present in a report."""
    out = set()
    for c in audit.get("checks") or []:
        for f in c.get("findings") or []:
            if f["severity"] != "info":
                out.add((c["id"], f["code"], f["severity"]))
    return out


def keep_only(dirpath, names):
    """Delete every file under `dirpath` that is not in `names`.

    The bundle must stay inside the skill resource limit (50 UTF-8 text files), so
    the self-test keeps the evidence a reviewer actually reads -- the result, the
    audit and the prose -- and drops the rest of the run's by-products.
    """
    if not os.path.isdir(dirpath):
        return
    for root, _dirs, files in os.walk(dirpath):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), dirpath).replace(os.sep, "/")
            if rel not in names:
                os.remove(os.path.join(root, fn))
    for root, dirs, _files in os.walk(dirpath, topdown=False):
        for d in dirs:
            full = os.path.join(root, d)
            if os.path.isdir(full) and not os.listdir(full):
                os.rmdir(full)


def prepare(src_input, dst, extra_bib=None):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src_input, dst)
    if extra_bib and os.path.isfile(extra_bib):
        with open(os.path.join(dst, "library.bib"), "a", encoding="utf-8") as f:
            f.write("\n" + read(extra_bib))


# --------------------------------------------------------------------------- #
# Chinese fixture, generated here so the bundle stays small
# --------------------------------------------------------------------------- #

ZH_MANUSCRIPT = """# 谱嵌入覆盖选择：低标注分子性质预测的预训练语料策略

## 摘要

本文提出谱嵌入覆盖选择（SPEC）：在未标注分子库上先做图拉普拉斯谱嵌入，再用贪心覆盖度挑选核心集，最后只在核心集上做掩码预训练。在三个数据集的 100 条标注设置下，平均绝对误差下降 8.2%，预训练成本下降 41.5%。消融显示增益主要来自覆盖度打分而不是掩码目标。

**关键词**：分子性质预测；图神经网络；预训练；核心集选择

## 1 引言

分子性质预测是虚拟筛选与毒性评估的基础环节，标注数据的获取成本是主要限制。

## 2 相关工作

图神经网络已成为分子表示的主流编码器[1]。

## 3 方法

先对未标注分子做谱嵌入，再在嵌入上做贪心覆盖度选择，最后只在核心集上做掩码原子与掩码键预训练。图 1 给出整体流程。

## 4 实验

三个数据集各取 100 条标注，每种设置重复 5 次。表 1 给出平均绝对误差，表 2 给出消融结果。

## 5 结论

选择先于预训练是本文方法的核心。

## 参考文献

[1] 张三, 李四. 基于图卷积的分子表示学习[J]. 计算机学报, 2020, 43(3): 1-12.

[2] 王五. 分子预训练的核心集选择研究[J]. 软件学报, 2024, 35(2): 88-101.
"""

ZH_LIBRARY = """@article{zhang2020gcn,
  title = {基于图卷积的分子表示学习},
  author = {张三 and 李四},
  journal = {计算机学报},
  year = {2020},
  volume = {43},
  number = {3},
  pages = {1--12},
  doi = {10.11897/SP.J.1016.2020.00001},
  abstract = {图卷积网络已成为分子表示学习的主流方法。我们提出一种基于局部谱滤波的分子编码器，在多个公开数据集上取得较好效果。然而该方法只在一个固定的表示空间内给出覆盖保证，无法迁移到仍在学习中的表示。}
}

@article{wang2024coreset,
  title = {分子预训练的核心集选择研究},
  author = {王五},
  journal = {软件学报},
  year = {2024},
  volume = {35},
  number = {2},
  pages = {88--101},
  doi = {10.13328/j.cnki.jos.2024.00088},
  abstract = {预训练已成为低标注分子性质预测的默认做法。我们按分子对下游标注预算的信息量排序，报告相对随机预训练最多 8.6% 的提升。该方法只按标注稀缺程度排序，忽略了预训练语料本身的成本。}
}
"""

ZH_CASE = {
    "case_id": "zh-example-001",
    "task": "为这篇中文论文写引言与相关工作：研究背景、相关工作（按方法路线分组比较）、研究空白、主要贡献四部分，中文，数字制引用。",
    "target_lang": "zh",
    "citation_style": "numeric",
    "output_contract": {"required": ["case_id", "status", "result", "introduction_related_work",
                                     "related_work", "research_gap", "contributions",
                                     "citation_map", "references_used", "evidence",
                                     "uncertainty", "changes"]},
}

ZH_TASK_MD = """# 任务

为 `manuscript.md` 写**引言与相关工作**，中文期刊投稿用，四部分：研究背景、相关工作（按路线分组比较）、研究空白、主要贡献。数字制引用，只用 `library.bib` 里的文献；不得引入原稿中没有的数值；属作者判断的断言要标注。
"""

ZH_REFS = {
    "case_id": "zh-example-001",
    "note": "zh fixture reference ledger",
    "entries": [
        {"ref_id": "R0001", "role": "seminal", "cluster": "G1", "must_cite": True,
         "one_line": "图卷积分子编码器，只在固定表示空间内保证覆盖"},
        {"ref_id": "R0002", "role": "recent", "cluster": "G1", "must_cite": True,
         "one_line": "按标注预算的信息量选核心集，忽略语料成本"},
    ],
}

ZH_GROUPS = {
    "case_id": "zh-example-001",
    "groups": [{
        "group_id": "G1",
        "label": "按什么信号去选语料",
        "dimension": "选择信号，以及它优化的量",
        "works": [
            {"ref_id": "R0001",
             "method_route": "局部谱滤波的图卷积编码器",
             "data_setting": "公开分子数据集，固定表示空间",
             "evaluation": "下游分子性质回归误差",
             "conclusion": "谱滤波编码器在多个数据集上有效，覆盖界成立",
             "limitation": "覆盖保证只在固定表示空间内成立，无法迁移到仍在学习的表示"},
            {"ref_id": "R0002",
             "method_route": "按下游标注预算的信息量排序选核心集",
             "data_setting": "未标注分子库 + 100 条标注的下游任务",
             "evaluation": "相对随机预训练的下游提升",
             "conclusion": "按信息量排序最多提升 8.6%",
             "limitation": "只按标注稀缺排序，忽略预训练语料本身的成本"},
        ],
        "comparison": {
            "dimension": "选择信号 vs 它优化的量",
            "tradeoff": "一篇优化固定空间内的覆盖，另一篇优化标注预算的信息量，两篇都没有把预训练成本作为优化对象。",
            "best_for": "预训练算力充裕、只缺标注的场景",
        },
    }],
}

ZH_GAPS = {
    "case_id": "zh-example-001",
    "gaps": [{
        "gap_id": "PG1",
        "statement": "已引的选择规则都没有把预训练语料成本当作优化对象。",
        "derived_from": [
            {"ref_id": "R0001", "limitation_kind": "method_gap",
             "evidence": {"kind": "quote", "text": "覆盖保证，无法迁移到仍在学习中的表示"}},
            {"ref_id": "R0002", "limitation_kind": "shared_limitation",
             "evidence": {"kind": "quote", "text": "忽略了预训练语料本身的成本"}},
        ],
        "how_filled": {"contribution_ids": ["C1", "C2"],
                       "mechanism": "选择先于预训练，把语料成本变成显式预算"},
        "confidence": "high",
    }],
}

ZH_CONTRIBS = {
    "case_id": "zh-example-001",
    "contributions": [
        {"contribution_id": "C1",
         "text": "选择先于预训练的处理流程：在谱嵌入上按贪心覆盖度选核心集，只在该核心集上预训练。",
         "kind": "method",
         "evidence": [
             {"locator_type": "section", "locator": "3",
              "claim_in_source": "再在嵌入上做贪心覆盖度选择"},
             {"locator_type": "figure", "locator": "图 1",
              "claim_in_source": "图 1 给出整体流程"},
         ],
         "scope": {"stated_limits": "覆盖度打分没有理论保证", "not_claimed": "选择规则的最优性"}},
        {"contribution_id": "C2",
         "text": "固定标注预算下的收益：平均绝对误差下降 8.2%，预训练成本下降 41.5%。",
         "kind": "experiment",
         "evidence": [
             {"locator_type": "table", "locator": "表 1",
              "claim_in_source": "表 1 给出平均绝对误差"},
             {"locator_type": "result", "locator": "摘要",
              "claim_in_source": "平均绝对误差下降 8.2%，预训练成本下降 41.5%"},
         ],
         "scope": {"stated_limits": "只在三个数据集与 100 条标注设置下验证",
                   "not_claimed": "任意蛋白家族的泛化"}},
    ],
}

ZH_DRAFT = """<!-- part:background -->
## 1 研究背景

分子性质预测是虚拟筛选与毒性评估的基础环节，真正的限制在标注一侧：一次可靠测量往往需要数周湿实验，多数实际任务只能提供数百条标注。图卷积网络[1]把分子的局部拓扑编码为可学习表示，这一表示空间决定了模型能拟合什么，却决定不了需要多少标注。

预训练是缓解标注稀缺的常规做法：先在未标注分子库上做掩码或对比学习，再在下游少量标注上微调。问题在于语料一侧从未被当作决策变量——[2] 把整个未标注分子库视为给定且免费的资源，逐轮扫过全部分子，成本随库规模线性增长。
<!-- /part:background -->

<!-- part:related_work -->
## 2 相关工作

第一类路线优化表示空间本身。图卷积编码器[1]在固定谱滤波下获得线性可扩展的传播规则，代价是每层只看一跳邻域；这条路线的取舍落在表示能力与感受野上，而不在花多少算力去读语料。

第二类路线优化用哪些分子。按下游标注预算的信息量排序，可比随机预训练提升约 8.6%[2]；相比之下，覆盖度驱动的选择在固定表示空间内给出可证明的界。两者都停在“选哪些”这一层，而把“读多少遍”留给默认设置。
<!-- /part:related_work -->

<!-- part:gap -->
## 3 研究空白

两条路线共同留下同一个缺口：覆盖保证只在固定表示空间内成立，无法迁移到仍在学习中的表示[1]，而按标注预算排序的做法忽略了预训练语料本身的成本[2]。真正决定低标注预训练是否可行的量是预训练成本，已引工作没有一条把它当作优化对象。

本文把未标注分子库当作决策变量：先做谱嵌入、在嵌入上按贪心覆盖度选择，再只在核心集上预训练。因为选择发生在预训练之前，[1] 的覆盖论证第一次可以落在固定空间上；因为预算显式，[2] 报告的规模效应变成可以提前触达的量。
<!-- /part:gap -->

<!-- part:contributions -->
## 4 主要贡献

- **选择先于预训练的处理流程。** 在谱嵌入上按贪心覆盖度选核心集，只在该核心集上做掩码预训练，语料成本从固定开销变成可调预算（第 3 节，图 1）。
- **固定标注预算下的收益。** 每数据集 100 条标注时，平均绝对误差下降 8.2%，预训练成本下降 41.5%（表 1）。

本文的主张限于未标注分子库充足、标注预算很小的分子性质预测；覆盖度打分没有理论保证，这一点不作声称。
<!-- /part:contributions -->
"""

NO_LIB_MANUSCRIPT = """# A short manuscript with no reference list

## Abstract

We report a baseline for molecular solubility prediction. Error falls by 4.4% when the
descriptor set is pruned.

## 1 Introduction

Solubility prediction is a standard benchmark task.

## 2 Method

We fit a gradient-boosted model on 12 descriptors.
"""


def make_zh_fixture(dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    write_json(os.path.join(dst, "case.json"), ZH_CASE)
    write(os.path.join(dst, "task.md"), ZH_TASK_MD)
    write(os.path.join(dst, "manuscript.md"), ZH_MANUSCRIPT)
    write(os.path.join(dst, "library.bib"), ZH_LIBRARY)
    return dst


def install_fixture(work, ledgers_dir, draft_path, overrides=None, fallback_dir=None):
    """Put the example ledgers + draft where the runner expects them.

    `fallback_dir` is searched for any ledger the primary directory does not
    carry, so a defective fixture can override only the ledgers it changes.
    """
    ldir = os.path.join(work, "ledgers")
    os.makedirs(ldir, exist_ok=True)
    for fn in ("ledger_refs.json", "ledger_groups.json", "ledger_gaps.json", "ledger_contributions.json"):
        for d in (ledgers_dir, fallback_dir):
            src = os.path.join(d, fn) if d else None
            if src and os.path.isfile(src):
                shutil.copy2(src, os.path.join(ldir, fn))
                break
    for fn, obj in (overrides or {}).items():
        write_json(os.path.join(ldir, fn), obj)
    if draft_path:
        shutil.copy2(draft_path, os.path.join(work, "draft.md"))


# --------------------------------------------------------------------------- #
# runs
# --------------------------------------------------------------------------- #

def run_clean(tmp, summary):
    log("--- run 1: clean English case ---")
    src = os.path.join(EX, "input")
    work, out = os.path.join(tmp, "w_clean"), os.path.join(RESULTS, "clean_en")
    if os.path.isdir(work):
        shutil.rmtree(work)
    if os.path.isdir(out):
        shutil.rmtree(out)
    rc, tail = run_stage(src, out, work, "plan")
    install_fixture(work, os.path.join(EX, "ledgers"), os.path.join(EX, "fixtures", "draft_good.md"))
    rc, tail = run_stage(src, out, work, "finalize")
    log("run_case exit=%d %s" % (rc, tail[-1] if tail else ""))
    audit = read_json(os.path.join(work, "audit.json"))
    res = read_json(os.path.join(out, "result.json"))
    checks = {
        "gate_pass": audit["gate"] == "pass",
        "no_errors": audit["summary"]["errors"] == 0,
        "no_warnings": audit["summary"]["warnings"] == 0,
        "status_success": res["status"]["state"] == "success",
        "four_parts_present": all((res["result"]["parts"].get(p) or {}).get("present")
                                  for p in ("background", "related_work", "gap", "contributions")),
        "all_refs_cited": res["result"]["n_distinct_refs"] == 10,
        "contract_fields_present": all(k in res for k in
                                       read_json(os.path.join(src, "case.json"))["output_contract"]["required"]),
        "outputs_written": all(os.path.isfile(os.path.join(out, f)) for f in
                               ("introduction_related_work.md", "related_work_table.md",
                                "contribution_table.md", "audit_report.md", "refs_cited.bib",
                                "citation_map.json")),
        "no_html_comment_left": "<!--" not in read(os.path.join(out, "introduction_related_work.md")),
    }
    summary["clean_en"] = {"gate": audit["gate"], "errors": audit["summary"]["errors"],
                           "warnings": audit["summary"]["warnings"],
                           "state": res["status"]["state"],
                           "chars": res["result"]["chars"],
                           "refs": res["result"]["n_distinct_refs"],
                           "groups": res["result"]["n_groups"],
                           "gaps": res["result"]["n_gaps"],
                           "contributions": res["result"]["n_contributions"],
                           "checks": checks, "passed": sum(checks.values()), "total": len(checks)}
    keep_only(out, {"result.json", "audit_report.json", "introduction_related_work.md",
                    "related_work_table.md", "refs_cited.txt"})
    log("clean_en: %d/%d checks passed; failed=%s"
        % (sum(checks.values()), len(checks), [k for k, v in checks.items() if not v]))
    return summary["clean_en"]


def run_defective(tmp, summary):
    log("--- run 2: planted-defect case ---")
    src = os.path.join(tmp, "input_defective")
    prepare(os.path.join(EX, "input"), src, os.path.join(EX, "fixtures", "library_extra_defective.bib"))
    work, out = os.path.join(tmp, "w_def"), os.path.join(RESULTS, "defective")
    if os.path.isdir(work):
        shutil.rmtree(work)
    if os.path.isdir(out):
        shutil.rmtree(out)
    run_stage(src, out, work, "plan")
    install_fixture(work, os.path.join(EX, "fixtures"), os.path.join(EX, "fixtures", "draft_defective.md"),
                    fallback_dir=os.path.join(EX, "ledgers"))
    rc, tail = run_stage(src, out, work, "audit")
    audit = read_json(os.path.join(work, "audit.json"))
    spec = read_json(os.path.join(EX, "fixtures", "defects.json"))
    present = codes_of(audit)
    rows, missed = [], []
    for d in spec["defects"]:
        want = (d["rule"], d["code"], d["severity"])
        ok = want in present
        rows.append({"defect": d["id"], "mode": d["mode"], "rule": d["rule"],
                     "code": d["code"], "severity": d["severity"], "caught": ok})
        if not ok:
            missed.append(d["id"] + ":" + d["code"])
    checks = {
        "gate_fail": audit["gate"] == "fail",
        "every_defect_caught": not missed,
        "distinct_codes": len({(r["rule"], r["code"]) for r in rows}) >= 18,
        "errors_dominate": audit["summary"]["errors"] >= 15,
    }
    summary["defective"] = {"gate": audit["gate"], "errors": audit["summary"]["errors"],
                            "warnings": audit["summary"]["warnings"],
                            "defects_declared": len(rows), "defects_caught": sum(r["caught"] for r in rows),
                            "missed": missed, "checks": checks,
                            "passed": sum(checks.values()), "total": len(checks),
                            "per_defect": rows}
    write_json(os.path.join(RESULTS, "defective", "defects_detected.json"),
               {"n_declared": len(rows), "n_caught": sum(r["caught"] for r in rows),
                "missed": missed, "rows": rows})
    keep_only(out, {"audit_report.json", "defects_detected.json"})
    log("defective: %d/%d defects caught; %d/%d checks passed; missed=%s"
        % (sum(r["caught"] for r in rows), len(rows), sum(checks.values()), len(checks), missed))
    return summary["defective"]


def run_zh(tmp, summary):
    log("--- run 3: Chinese case ---")
    src = make_zh_fixture(os.path.join(tmp, "input_zh"))
    work, out = os.path.join(tmp, "w_zh"), os.path.join(RESULTS, "zh")
    if os.path.isdir(work):
        shutil.rmtree(work)
    if os.path.isdir(out):
        shutil.rmtree(out)
    # run 5 is folded in here: plan alone must leave an honest partial result
    rc_plan, _ = run_stage(src, out, work, "plan")
    plan_res = read_json(os.path.join(out, "result.json"))
    early = {"plan_written": os.path.isfile(os.path.join(out, "result.json")),
             "plan_status_partial": plan_res.get("status", {}).get("state") == "partial",
             "plan_has_case_id": plan_res.get("case_id") == "zh-example-001",
             "scaffold_written": os.path.isfile(os.path.join(work, "scaffold.md"))}
    install_fixture(work, os.path.join(tmp, "input_zh_ledgers"), None,
                    overrides={"ledger_refs.json": ZH_REFS, "ledger_groups.json": ZH_GROUPS,
                               "ledger_gaps.json": ZH_GAPS, "ledger_contributions.json": ZH_CONTRIBS})
    write(os.path.join(work, "draft.md"), ZH_DRAFT)
    rc, tail = run_stage(src, out, work, "finalize")
    audit = read_json(os.path.join(work, "audit.json"))
    res = read_json(os.path.join(out, "result.json"))
    gbt = read(os.path.join(out, "refs_cited.txt"))
    checks = {
        "zip_plan_checks": all(early.values()),
        "gate_pass": audit["gate"] == "pass",
        "no_errors": audit["summary"]["errors"] == 0,
        "status_success": res["status"]["state"] == "success",
        "lang_zh_detected": res["task"]["lang"] == "zh",
        "gbt7714_rendered": "[1]" in gbt and "[J]" in gbt,
        "cjk_output": any("\u4e00" <= ch <= "\u9fff" for ch in res["introduction_related_work"]),
        "four_parts_present": all((res["result"]["parts"].get(p) or {}).get("present")
                                  for p in ("background", "related_work", "gap", "contributions")),
        "contract_fields_present": all(k in res for k in ZH_CASE["output_contract"]["required"]),
    }
    summary["zh"] = {"gate": audit["gate"], "errors": audit["summary"]["errors"],
                     "warnings": audit["summary"]["warnings"],
                     "state": res["status"]["state"], "early_partial": early,
                     "checks": checks, "passed": sum(checks.values()), "total": len(checks)}
    keep_only(out, {"result.json", "refs_cited.txt", "introduction_related_work.md"})
    log("zh: %d/%d checks passed; failed=%s"
        % (sum(checks.values()), len(checks), [k for k, v in checks.items() if not v]))
    return summary["zh"]


def run_no_library(tmp, summary):
    log("--- run 4: no reference library (honest degradation) ---")
    src = os.path.join(tmp, "input_nolib")
    if os.path.isdir(src):
        shutil.rmtree(src)
    os.makedirs(src, exist_ok=True)
    write_json(os.path.join(src, "case.json"),
               {"case_id": "nolib-001", "task": "write the introduction and related work",
                "output_contract": {"required": ["case_id", "status", "introduction_related_work"]}})
    write(os.path.join(src, "manuscript.md"), NO_LIB_MANUSCRIPT)
    work, out = os.path.join(tmp, "w_nolib"), os.path.join(RESULTS, "no_library")
    if os.path.isdir(work):
        shutil.rmtree(work)
    if os.path.isdir(out):
        shutil.rmtree(out)
    run_stage(src, out, work, "plan")
    write(os.path.join(work, "draft.md"),
          "<!-- part:background -->\n## 1 Background\n\nSolubility prediction is a standard "
          "benchmark task. Previous work has reported that descriptor pruning reduces error "
          "by 4.4% [1].\n<!-- /part:background -->\n\n"
          "<!-- part:related_work -->\n## 2 Related Work\n\nPrior work on descriptor selection "
          "reports gains [1].\n<!-- /part:related_work -->\n\n"
          "<!-- part:gap -->\n## 3 Research Gap\n\nNo cited work measures the cost of the "
          "descriptor set itself [1], and this paper addresses that.\n<!-- /part:gap -->\n\n"
          "<!-- part:contributions -->\n## 4 Contributions\n\n- We prune the descriptor set "
          "(Section 2).\n<!-- /part:contributions -->\n")
    rc, tail = run_stage(src, out, work, "finalize")
    audit = read_json(os.path.join(work, "audit.json"))
    res = read_json(os.path.join(out, "result.json"))
    invent = [f for c in audit["checks"] for f in c["findings"]
              if f["code"] == "invented_citation" and f["severity"] == "error"]
    checks = {
        "ran": rc == 0,
        "library_empty_reported": res["inputs"]["library"]["n"] == 0,
        "unresolved_citation_flagged": len(invent) >= 1,
        "honest_state": res["status"]["state"] in ("partial", "success"),
        "limits_mention_empty_library": "library empty" in json.dumps(res["status"], ensure_ascii=False),
        "result_written": os.path.isfile(os.path.join(out, "result.json")),
    }
    summary["no_library"] = {"gate": audit["gate"], "state": res["status"]["state"],
                             "invented_citations_flagged": len(invent),
                             "checks": checks, "passed": sum(checks.values()), "total": len(checks)}
    keep_only(out, {"result.json"})
    log("no_library: state=%s gate=%s flagged=%d | %d/%d checks passed"
        % (res["status"]["state"], audit["gate"], len(invent), sum(checks.values()), len(checks)))
    return summary["no_library"]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip runs 4")
    a = ap.parse_args()
    t0 = time.time()
    os.makedirs(RESULTS, exist_ok=True)
    tmp = os.path.join(RESULTS, "_tmp")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp, exist_ok=True)

    log("=== reproduce start (python %s, skill=%s) ===" % (sys.version.split()[0], ROOT))
    summary = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "python": sys.version.split()[0],
               "note": ("LOCAL SELF-TEST on fixtures that ship with the bundle. Not an official "
                        "case, not a benchmark score. Regenerate with `python3 src/reproduce.py`."),
               "runs": {}}
    try:
        summary["runs"]["clean_en"] = run_clean(tmp, summary)
        summary["runs"]["defective"] = run_defective(tmp, summary)
        summary["runs"]["zh"] = run_zh(tmp, summary)
        if not a.quick:
            summary["runs"]["no_library"] = run_no_library(tmp, summary)
    except Exception:
        log("FATAL " + traceback.format_exc()[-1500:])
        summary["fatal"] = traceback.format_exc()[-1500:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(r["passed"] for r in summary["runs"].values())
    total = sum(r["total"] for r in summary["runs"].values())
    summary["totals"] = {"passed": passed, "total": total,
                         "defects_caught": (summary["runs"].get("defective") or {}).get("defects_caught", 0),
                         "defects_declared": (summary["runs"].get("defective") or {}).get("defects_declared", 0)}
    out_path = os.path.join(RESULTS, "selftest_summary.json")
    write_json(out_path, summary)
    # Measure after every artifact has been written, then re-stamp the summary: the ARM
    # manifest reuses wall_time_s to bound artifact mtimes, so the window has to end
    # after the last write rather than after the last computation.
    summary["wall_time_s"] = round(time.time() - t0 + 0.2, 2)
    # ran_at is rounded UP to the next whole second, so that for every artifact
    #   mtime - ran_at <= wall_time_s
    # holds even though the timestamps are second-resolution. arm_manifest.json copies
    # these two values verbatim.
    start = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc)
    ran_at = (start.replace(microsecond=0) + datetime.timedelta(seconds=1))
    summary["execution_window"] = {"ran_at": ran_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                   "wall_time_s": summary["wall_time_s"]}
    write_json(out_path, summary)
    log("=== reproduce done in %.2fs: %d/%d self-test checks passed, %d/%d planted defects caught ==="
        % (summary["wall_time_s"], passed, total,
           summary["totals"]["defects_caught"], summary["totals"]["defects_declared"]))
    return 0 if (passed == total and "fatal" not in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
