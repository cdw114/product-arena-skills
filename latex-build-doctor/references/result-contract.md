# `result.json` 契约、`output_contract` 映射与状态语义

---

## 一、`output_contract` 的处理规则

`case.json` 里的 `output_contract` 有三种形态，都要能读：

```json
"output_contract": ["status", "diagnostics", "build", "fixes", "sources", "uncertainties"]
"output_contract": {"status": "运行状态", "build": "编译记录"}
"output_contract": "status"
```

`satisfy_contract()` 按下面顺序满足每一个字段，并把结果写进 `result.contract`：

| 情况 | `contract.satisfied[字段]` | 说明 |
|---|---|---|
| 字段名已是 `result.json` 的顶层键 | `native` | 直接用 |
| 字段名在别名表里，且别名对应的键存在 | `mapped_to:<键>` | 例如 `errors` → `diagnostics`、`changes` → `fixes`、`checks` → `static_checks` |
| 两者都不成立 | `stub_declared` | 写入 `{"_contract_field","_status":"not_produced_by_this_skill","_note"}`，并进 `contract.missing` |

**为什么用 stub 而不是硬编内容**：题目明确要求 `result.json` 含 `output_contract` 全部字段。
硬编一段看起来像答案的内容会让字段「有值」，但那个值不是这次运行产生的——那比缺字段更坏。
stub 让字段存在、让缺口可见、让 `contract.missing` 可被自动检查。

别名表（`doctor.CONTRACT_SYNONYMS`）当前覆盖：`case_id`/`status`/`diagnostics`/`errors`/
`compile`/`build`/`compilation`/`project`/`sources`/`source_map`/`evidence`/`fixes`/`changes`/
`change_log`/`patches`/`uncertainties`/`human_review`/`human_confirmation`/`reproducibility`/
`repro`/`environment`/`deliverables`/`artifacts`/`outputs`/`checks`/`static_checks`/`lints`/
`tex`/`document`/`math`/`tables`/`citations`/`references`/`template`/`integrity`/`contract`。
需要扩展时改这一张表即可，不要改调用点。

---

## 二、顶层字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `case_id` | str | 原样取自 `case.json`；缺失时取输入目录名，最后是 `"unknown"` |
| `status` | `success` \| `partial` \| `failed` | 见第三节 |
| `status_reason` | str | 中文，逐条说明为什么不是 `success` |
| `generated_at` | ISO-8601 带时区 | 本次运行时间 |
| `skill` | obj | `name` / `version` / `scope` |
| `inputs` | obj | `input_dir` / `case_json` / `task_files` / `task_excerpt` / `notes` |
| `project` | obj | 工程事实：`main`、`documentclass`、`packages`、`bib_files`、`includes`、`missing_includes`、`magic_engine`、`main_candidates`（含打分依据） |
| `environment` | obj | 引擎探测结果、`resources.yaml` 是否可读、Python 版本 |
| `build` | obj | 见下 |
| `diagnostics` | obj | 见下 |
| `static_checks` | obj | 修前/修后汇总、`findings`、`closure_after`（引用闭包） |
| `fixes` | obj | `applied` / `rejected` / `unresolved` / `files_modified` / `files_added` / `files_removed` / `diff` |
| `integrity` | obj | `findings` + `clean` |
| `reproducibility` | obj | 引擎、后端、pass 命令、输入哈希、PDF 哈希、`repro_dir`、口径说明 |
| `deliverables` | obj | 每个交付物的相对路径 |
| `sources` | list | **逐条可回溯**：`claim` + `evidence`（`compiler log` / `static check` / `source diff` / `build transcripts`）+ `file` + `line` + `rule` |
| `human_review` | list | 必须由人决定的项：`item` / `file` / `line` / `why` |
| `uncertainties` | list | 本次运行的已知不确定与限制（字符串列表） |
| `change_log` | list | `step` + `what`，8 步 |
| `log` | list | 运行日志尾部（调试用） |
| `contract` | obj | `declared` / `satisfied` / `missing` |

### `build`

```json
{
  "attempted": true,
  "engine": {"engine": "xelatex", "reason": "…", "evidence": ["…"], "confidence": "high"},
  "bib_backend": {"backend": "biber", "reason": "…"},
  "plan_steps": ["xelatex -interaction=… main.tex", "biber main", "…"],
  "iterations": [{"iteration": 0, "passes": 3, "stats": {...},
                  "diag_summary": {...}, "fingerprint": [-3,-7,-3,1], "bib": {...}}],
  "final_stats": {"pages": 9, "output_bytes": 184320, "engine_banner": "XeTeX",
                  "engine_version": "XeTeX 3.141592653-2.6-0.999995 (TeX Live 2023)",
                  "fatal_no_output": false},
  "success": true, "pages": 9, "pdf": "main.pdf", "pdf_sha256": "…",
  "timed_out": false, "budget_seconds": 420, "spent_seconds": 6.4
}
```

`attempted` 与 `success` 必须分开看：`attempted=false` 表示**根本没跑编译器**（无引擎或
`--no-build`），此时 `success` 必为 `false`，且 `status` 必为 `partial`。

### `diagnostics`

```json
{
  "summary": {"total": 10, "live": 3, "suppressed": 7,
              "by_severity": {"error": 2, "warning": 1}, "fatal_errors": 2, "warnings": 1},
  "items": [{
    "id": "D001", "kind": "error", "severity": "error",
    "message": "Undefined control sequence.", "file": "sections/method.tex", "line": 14,
    "rule": "E-UNDEFINED-CS", "confidence": "high", "source": "log",
    "cascade_parent": null, "fix_order": 1,
    "root_cause": {"category": "macro-undefined", "confidence": "high",
                   "explanation": "\\toprule is not defined. In standard LaTeX it comes from package 'booktabs'.",
                   "evidence": ["…"], "macro": "toprule", "package": "booktabs"},
    "context": {"format": "file-line-error", "source_line": "\\toprule"},
    "raw": ["./sections/method.tex:14: Undefined control sequence.", "l.14 \\toprule"]
  }],
  "structural": {"before": [...], "after": [...]}
}
```

**`total` 与 `live` 的差**就是「第一条报错之后那些噪声」的数量。`cascade_parent` 指向
被归并到的根因 `id`。这是「不停在第一条错误上」在数据里的体现。

---

## 三、状态语义

| status | 触发条件 |
|---|---|
| `success` | 编译通过（`pages > 0`）**且** 静态检查无 error **且** 完整性干净 |
| `partial` | 有引擎但未收敛到 PDF；或仍有 error 级诊断；或完整性有阻断；或静检仍有 error；或**无引擎** |
| `failed` | 输入不可恢复：找不到 `.tex`、找不到主文件、`case.json`/`task.md` 都不可读且无法推断 |

规则：
- `partial` **必须**在 `status_reason` 里写清是哪一类限制，不接受「部分完成」这种空话。
- 绝不把「没编译」写成 `success`；绝不为了拿 `success` 去删内容或压警告。
- 退出码：`0` = 已写出 `result.json`（`success`/`partial`）；`2` = `failed`（仍写 `result.json`）。

---

## 四、`sources` 的意义

每条记录把一句结论钉到一个位置：

```json
{"claim": "E-UNDEFINED-CS at Undefined control sequence.",
 "evidence": "compiler log", "file": "sections/method.tex", "line": 14,
 "rule": "E-UNDEFINED-CS", "severity": "error",
 "raw": "./sections/method.tex:14: Undefined control sequence."}
```

来源 `evidence` 有四种，**不要混用**：

1. `compiler log` —— 真的编译过，来自 `build/pass-*.log`；
2. `static check` —— 源码静态分析，不需要编译；
3. `source diff` —— 补丁的前后文本，落在 `fixes/changes.diff`；
4. `build transcripts` —— 汇总性事实（跑了几个 pass）。

人工若要复核，按 `evidence` 去找对应文件即可，不必重跑。

---

## 五、与「示例」的边界

`examples/output/` 是**示例输出**（`examples/README.md` 已声明），用来说明接口形状。
它的 `case_id` 是 `example-01`，**不是**平台固定案例；它的分数、页数、耗时都不存在，
不要引用。正式案例的产物只能由本次运行在 `/app/output` 下生成。
