#!/usr/bin/env python3
"""selftest.py - prove the chain works, on the bundled toy case.

There is no point shipping a reproducibility skill whose own pipeline has never
been run. This runs the exact three commands the SKILL.md tells an agent to run,
against `examples/input/` (a fixture written for this purpose, not a real
experiment), and checks three things:

  positive   the reference draft reaches verdict `ready` with every element covered
  negative   a fabricated number makes the audit block instead of passing quietly
  contract   result.json carries case_id and every field the case's
             output_contract names, plus sources, uncertainty and a change log

    python3 scripts/selftest.py
    python3 scripts/selftest.py --keep ./selftest_out

Exit code 0 means the pipeline works. Anything else means it does not, and the
failing assertion is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
EXAMPLE_INPUT = os.path.join(SKILL_ROOT, "examples", "input")
EXAMPLE_DRAFT = os.path.join(SKILL_ROOT, "examples", "reference", "draft.md")

FABRICATED = "\n\nWe also trained for 9000 epochs on 7 nodes with 512 workers.\n"

# A draft in Chinese, used only to prove the coverage patterns are bilingual.
# Cases arrive in both languages, and an audit that silently scores 0/7 on a
# Chinese draft would look like a broken case rather than a broken skill.
ZH_DRAFT = """# 方法与实验

## 步骤

1. **读取配置。** 输入：config.yaml。操作：解析嵌套配置并校验必需键。输出：配置对象。
   如果缺少训练键则在分配显卡前中止，因此不完整的配置不会进入训练循环。
2. **固定随机性。** 输入：配置对象。操作：设置 Python、NumPy 与 PyTorch 的随机种子 42，
   并在建模之前设置 CUDA 种子。输出：确定性的随机状态。

## 实验设置

硬件：一张 NVIDIA A100-40GB。软件：Python 3.10.13、torch 2.1.2、CUDA 12.1。
随机种子：训练 42，划分 7。重复次数：每个配置训练 3 次，报告中位数与四分位距。

## 参数

| 参数 | 取值 | 单位 | 作用对象 | 来源 |
|---|---|---|---|---|
| 学习率 | 0.0003 | 1 | 优化器 | config.yaml |
| 批大小 | 64 | 样本 | 数据加载器 | config.yaml |
| 轮次 | 120 | 轮 | 训练循环 | config.yaml |

## 数据集与划分

数据集 PolymerSplit 的版本 v1.2 共 10000 条样本。按 0.8 / 0.1 / 0.1 划分为训练集、
验证集与测试集，划分比例为 8000 / 1000 / 1000 条，按骨架划分并使用独立的划分种子。

## 基线对比

基线为 GNN-baseline 的 v0.9 版本。对照时保持预算相同：同一张显卡、同样的轮次、
同样的划分。评价指标为测试集 MAE，报告均值与标准差，区间重叠时不作排序。

## 可复现性

代码通过 commit 7a1f3c9 固定，运行命令为 `python train.py --config config.yaml`。
环境依赖见 requirements.txt 与 docker 镜像。数据可从 https://example.org 下载。

## 限制条件

当评测集来自比划分器更细粒度的骨架分布时，验证集不再预测测试集表现，此时的模型选择
优化的是错误的目标。本方法仅适用于骨架划分与训练集同分布的场景，改变有效批大小需要
重新扫描学习率。
"""


class Failed(Exception):
    pass


def run(args, cwd):
    # encoding is pinned: the child writes UTF-8 (it can emit Chinese), while
    # subprocess would otherwise decode with the platform default, which is gbk
    # on a Chinese Windows install and raises UnicodeDecodeError mid-run.
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable] + args, cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)


def step(label, args, cwd, expect_code=0):
    r = run(args, cwd)
    if r.returncode != expect_code:
        raise Failed("%s: exit %d (expected %d)\nstdout:\n%s\nstderr:\n%s"
                     % (label, r.returncode, expect_code, r.stdout[-3000:], r.stderr[-3000:]))
    print("PASS  %s" % label)
    return r


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check(cond, label, detail=""):
    if not cond:
        raise Failed("%s%s" % (label, ("\n" + detail) if detail else ""))
    print("PASS  %s" % label)


def pick_base():
    """A writable scratch directory.

    The platform temp directory is not always writable: under a workspace-scoped
    sandbox an OS temp dir may exist and even accept mkdtemp while refusing a
    nested makedirs, which is a confusing way to fail. Prefer a directory beside
    the working tree, and fall back to the platform temp only if that is refused.
    """
    cand = os.path.join(os.getcwd(), ".mew-selftest")
    try:
        shutil.rmtree(cand, ignore_errors=True)
        os.makedirs(cand, exist_ok=True)
        probe = os.path.join(cand, ".write-probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return cand
    except OSError:
        return tempfile.mkdtemp(prefix="mew-selftest-")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", default=None, help="write the work and output dirs here instead of a temp dir")
    args = ap.parse_args(argv)

    base = args.keep or pick_base()
    work = os.path.join(base, "work")
    out = os.path.join(base, "out")
    for d in (work, out):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    print("selftest root: %s" % base)
    print("fixture input: %s" % EXAMPLE_INPUT)
    if not os.path.isdir(EXAMPLE_INPUT):
        raise Failed("fixture input directory is missing: %s" % EXAMPLE_INPUT)

    # ---- positive run ----------------------------------------------------
    step("scan the fixture", [os.path.join(HERE, "scan_case.py"),
                              "--input", EXAMPLE_INPUT, "--work", work], SKILL_ROOT)

    evidence = load(os.path.join(work, "evidence.json"))
    check(len(evidence["rows"]) >= 30,
          "ledger has at least 30 rows (found %d)" % len(evidence["rows"]))
    check(all(r.get("source_locator") for r in evidence["rows"]),
          "every ledger row carries a source locator")

    conflicts = load(os.path.join(work, "conflicts.json"))
    check(conflicts["count"] == 1,
          "exactly one real conflict is found (found %d)" % conflicts["count"])
    check(conflicts["conflicts"][0]["parameter"].startswith("weight_decay"),
          "the conflict is the planted weight-decay disagreement",
          json.dumps(conflicts["conflicts"][0], ensure_ascii=False)[:400])

    check(os.path.isfile(EXAMPLE_DRAFT), "reference draft exists: %s" % EXAMPLE_DRAFT)
    shutil.copyfile(EXAMPLE_DRAFT, os.path.join(work, "draft.md"))

    step("audit the reference draft", [os.path.join(HERE, "audit_draft.py"),
                                       "--draft", os.path.join(work, "draft.md"),
                                       "--work", work, "--strict"], SKILL_ROOT)
    audit = load(os.path.join(work, "audit.json"))
    check(audit["verdict"] == "ready", "reference draft verdict is ready (got %r)" % audit["verdict"],
          json.dumps(audit["must_fix"], ensure_ascii=False))
    check(audit["counts"]["unsourced_numbers"] == 0,
          "reference draft has no unsourced number")
    check(audit["counts"]["elements_complete"] == audit["counts"]["elements_total"],
          "reference draft covers all %d elements" % audit["counts"]["elements_total"])

    step("emit the deliverables", [os.path.join(HERE, "emit_outputs.py"),
                                   "--input", EXAMPLE_INPUT, "--work", work, "--out", out], SKILL_ROOT)

    result = load(os.path.join(out, "result.json"))
    case = load(os.path.join(EXAMPLE_INPUT, "case.json"))
    check(result.get("case_id") == case.get("case_id"),
          "result.json carries case_id %r" % case.get("case_id"), repr(result.get("case_id")))
    for key in case["output_contract"]:
        check(key in result["outputs"] and result["outputs"][key],
              "output_contract field %r is filled" % key)
    for key in ("status", "sources", "uncertainty", "change_log", "fact_source_map"):
        check(key in result, "result.json carries %r" % key)
    check(result["status"] == "success", "status is success (got %r)" % result["status"],
          result.get("status_detail", ""))
    check(len(result["fact_source_map"]) == len(evidence["rows"]),
          "fact_source_map carries every ledger row")
    unresolved = [u for u in result["uncertainty"] if u["kind"] == "partial"]
    check(not unresolved, "no unresolved contract field is reported",
          json.dumps(unresolved, ensure_ascii=False))
    check(len(result["uncertainty"]) >= 2,
          "the conflict and the environment note are both surfaced as uncertainty")

    # ---- negative run: a number with no source must block ----------------
    # Run against its own copy of the work directory: writing audit.json over the
    # good run would leave the kept artifacts describing a draft they do not hold.
    neg_work = os.path.join(base, "work_negative")
    shutil.rmtree(neg_work, ignore_errors=True)
    shutil.copytree(work, neg_work)
    bad_draft = os.path.join(neg_work, "draft_bad.md")
    with open(os.path.join(neg_work, "draft.md"), encoding="utf-8") as f:
        text = f.read()
    with open(bad_draft, "w", encoding="utf-8") as f:
        f.write(text + FABRICATED)
    r = run([os.path.join(HERE, "audit_draft.py"), "--draft", bad_draft,
             "--work", neg_work, "--strict"], SKILL_ROOT)
    check(r.returncode == 1,
          "a fabricated number makes --strict exit 1 (got %d)" % r.returncode,
          r.stdout[-1500:] + r.stderr[-1500:])
    bad_audit = load(os.path.join(neg_work, "audit.json"))
    check(bad_audit["verdict"] == "blocked", "negative run verdict is blocked")
    check("9000" in json.dumps(bad_audit["must_fix"]),
          "the fabricated value 9000 is named in must_fix",
          json.dumps(bad_audit["must_fix"], ensure_ascii=False))
    check(load(os.path.join(work, "audit.json"))["verdict"] == "ready",
          "the good run's audit is untouched by the negative run")

    # ---- bilingual: a Chinese draft must reach the same coverage ---------
    sys.path.insert(0, HERE)
    import audit_draft as A  # noqa: E402
    from mew_lib import canonical_param as L_canonical  # noqa: E402

    zh_cov = A.audit_coverage(ZH_DRAFT)
    incomplete = {k: v["missing"] for k, v in zh_cov.items() if v["status"] != "complete"}
    check(not incomplete,
          "a Chinese draft covers all %d elements" % len(zh_cov),
          json.dumps(incomplete, ensure_ascii=False, indent=1))
    detect = load(os.path.join(work, "contract.json")).get("deliverable_language")
    check(detect in ("zh", "en"), "language was detected as %r" % detect)

    # ---- a Chinese case: language detection and Chinese contract keys ----
    # Cases arrive in either language, and the output_contract keys may be
    # Chinese. A contract key that fails to resolve becomes a null field, which
    # is honest but scores as a partial deliverable, so it needs a test.
    zh_in = os.path.join(base, "zh_input")
    zh_work = os.path.join(base, "zh_work")
    os.makedirs(os.path.join(zh_in, "materials"), exist_ok=True)
    zh_contract = ["方法与实验章节", "参数表", "证据映射", "覆盖报告", "待确认问题"]
    with open(os.path.join(zh_in, "case.json"), "w", encoding="utf-8") as f:
        json.dump({"case_id": "ZH-0001",
                   "output_contract": {k: k for k in zh_contract}},
                  f, ensure_ascii=False, indent=2)
    with open(os.path.join(zh_in, "task.md"), "w", encoding="utf-8") as f:
        f.write("# 任务\n\n请依据材料撰写方法与实验章节。所有数字都要能追溯到文件。\n")
    with open(os.path.join(zh_in, "materials", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"训练": {"随机种子": 42, "学习率": 0.0003, "批大小": 64,
                           "训练轮次": 120}, "数据": {"名称": "PolymerSplit", "版本": "v1.2"}},
                  f, ensure_ascii=False, indent=2)
    with open(os.path.join(zh_in, "materials", "训练记录.log"), "w", encoding="utf-8") as f:
        f.write("2026-03-02 09:14:02 显卡 NVIDIA A100-SXM4-40GB count=1\n"
                "2026-03-02 09:14:02 torch 2.1.2 CUDA Version: 12.1\n"
                "2026-03-02 09:14:03 学习率=0.0003 批大小=64 训练轮次=120 随机种子=42\n"
                "2026-03-02 13:41:55 训练完成 elapsed 4h27m\n")
    with open(os.path.join(zh_in, "materials", "README.md"), "w", encoding="utf-8") as f:
        f.write("# 数据说明\n\n数据集 PolymerSplit 的版本 v1.2 共 10000 条样本。\n"
                "按 8000 / 1000 / 1000 条划分训练集、验证集与测试集。\n")
    step("scan a Chinese case", [os.path.join(HERE, "scan_case.py"),
                                 "--input", zh_in, "--work", zh_work], SKILL_ROOT)
    zh_ledger = load(os.path.join(zh_work, "evidence.json"))
    zh_contract_out = load(os.path.join(zh_work, "contract.json"))
    check(len(zh_ledger["rows"]) > 0,
          "a Chinese case yields evidence rows (found %d)" % len(zh_ledger["rows"]))
    check(any(r["source_locator"] for r in zh_ledger["rows"]),
          "Chinese-case rows still carry locators")
    check(any(L_canonical(r["name"])[0] for r in zh_ledger["rows"] if r.get("name")),
          "a parameter is still recognised under Chinese keys",
          json.dumps([r["name"] for r in zh_ledger["rows"]], ensure_ascii=False))
    check(zh_contract_out.get("deliverable_language") == "zh",
          "a Chinese case is detected as zh (got %r)" % zh_contract_out.get("deliverable_language"))
    check(list(zh_contract_out.get("output_contract", {})) == zh_contract,
          "Chinese output_contract keys survive the scan")

    step("emit for the Chinese case", [os.path.join(HERE, "emit_outputs.py"),
                                       "--input", zh_in, "--work", zh_work,
                                       "--out", os.path.join(base, "zh_out")], SKILL_ROOT)
    zh_result = load(os.path.join(base, "zh_out", "result.json"))
    # Without a draft the section field is correctly null, so give the case one
    # before asserting that resolution works end to end.
    with open(os.path.join(zh_work, "draft.md"), "w", encoding="utf-8") as f:
        f.write(ZH_DRAFT)
    step("emit for the Chinese case with a draft",
         [os.path.join(HERE, "emit_outputs.py"), "--input", zh_in, "--work", zh_work,
          "--out", os.path.join(base, "zh_out")], SKILL_ROOT)
    zh_result = load(os.path.join(base, "zh_out", "result.json"))
    unresolved_zh = [k for k, v in zh_result["field_manifest"].items() if not v.get("deliverable")]
    check(not unresolved_zh,
          "every Chinese contract key resolves to a deliverable", repr(unresolved_zh))
    check(all(zh_result["outputs"].get(k) for k in zh_contract),
          "every Chinese contract field carries content",
          json.dumps({k: bool(zh_result["outputs"].get(k)) for k in zh_contract}, ensure_ascii=False))
    check(zh_result["case_id"] == "ZH-0001", "Chinese case carries its case_id")

    # ---- resource budget -------------------------------------------------
    limits = {"max_files": 50, "max_file_bytes": 500 * 1024, "max_total_bytes": 2 * 1024 * 1024}
    EXCLUDE_DIRS = {"work_test", "out_test", "selftest_out", ".mew-selftest", ".git", "__pycache__"}
    text_files = []
    for root, dirs, files in os.walk(SKILL_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            p = os.path.join(root, name)
            rel = os.path.relpath(p, SKILL_ROOT).replace(os.sep, "/")
            with open(p, "rb") as f:
                head = f.read(8192)
            if b"\x00" in head:
                continue
            text_files.append((rel, os.path.getsize(p)))
    total = sum(s for _, s in text_files)
    check(len(text_files) <= limits["max_files"],
          "skill ships %d text files (limit %d)" % (len(text_files), limits["max_files"]))
    biggest = max(text_files, key=lambda t: t[1])
    check(biggest[1] <= limits["max_file_bytes"],
          "largest file is %s at %d bytes (limit %d)" % (biggest[0], biggest[1], limits["max_file_bytes"]))
    check(total <= limits["max_total_bytes"],
          "total text payload is %d bytes (limit %d)" % (total, limits["max_total_bytes"]))

    skill_md = os.path.join(SKILL_ROOT, "SKILL.md")
    check(os.path.isfile(skill_md), "SKILL.md exists")
    with open(skill_md, encoding="utf-8") as f:
        head = f.read(2000)
    check(head.startswith("---"), "SKILL.md starts with YAML frontmatter")
    front = head.split("---", 2)[1] if head.count("---") >= 2 else ""
    check("name:" in front and "description:" in front,
          "SKILL.md frontmatter declares name and description")

    print("\nSELFTEST OK - %d text files, %d bytes total" % (len(text_files), total))
    if not args.keep:
        shutil.rmtree(base, ignore_errors=True)
    else:
        print("artifacts kept under %s" % base)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failed as exc:
        print("\nSELFTEST FAILED: %s" % exc, file=sys.stderr)
        sys.exit(1)
