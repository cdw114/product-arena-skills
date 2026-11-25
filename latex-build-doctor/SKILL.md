---
name: latex-build-doctor
description: LaTeX 编译诊断与修复闭环——把「编不过」拆成可验证的根因与最小补丁：递归识别主文件/子文件/宏包/参考文献后端，选对引擎（pdfLaTeX / XeLaTeX / LuaLaTeX / latexmk）与编译轮次，从 .log 里越过第一条报错读出真正的根因（大括号与环境未闭合、数学模式、缺宏包/缺字体/缺 .cls、宏未定义、& 错位、级联报错），逐条打最小补丁并重新编译验证，验证不通过就自动回滚；拒绝用删内容、缩放表格、\sloppy 等方式「换」编译通过；最后产出可编译的 .tex 源码、PDF 与逐页预览、diff 改动记录、reproducible build 记录（引擎/宏包版本、编译命令、输入哈希）和带 output_contract 字段的 result.json。触发词："LaTeX", "编译", "编译错误", "报错", "pdflatex", "xelatex", "latexmk", "Undefined control sequence", "Missing $", "Runaway argument", "File ended while scanning", "Overfull \hbox", ".tex 编不过", "模板", "cls", ".bib", "BibTeX", "biber", "交叉引用", "表格溢出", "公式对齐", "build failed", "compile error", "reproducible build"。
---

# LaTeX 编译诊断与修复（latex-build-doctor）

一句话：**把「编不过」变成一组可验证的根因 + 每条经重新编译证明有效的最小补丁 + 一份别人能复现的构建记录。**

这个 Skill 的确定性部分（找工程、读日志、结构审计、打补丁、比对、写记录）全部由
`scripts/` 里的 Python 完成，零模型调用、可重复运行；模型只做两件脚本做不了的事：
**判断任务真正要什么**，以及**在脚本给出候选后决定要不要交给人工**。

## 0. 硬规则（先读，违反任一条结果就不可信）

1. **输入文件是唯一事实来源。** 先读 `/input/case.json` 与 `/input/task.md`，再读
   `/input` 下实际存在的工程文件；`environment/resources.yaml` 若存在，用它确认镜像里
   到底装了哪些工具。不从题目名、领域标签或记忆推断源码内容。
2. **不交预制答案。** 每条诊断、每个补丁、每份报告都由本次运行产生；`examples/` 里的
   东西是**示例**（`examples/README.md` 已标明），不得当作正式案例结果提交或引用。
3. **不改写作者的文字。** 补丁只允许动**声明、定界符、转义、加载顺序**；不允许改写句子、
   删公式、删引用、删表格行来换编译通过。`texlib.guard_patch` 与 `checks.anti_cheat`
   两道闸门会在补丁前与交付前各拦一次。
4. **补丁必须被编译证明。** 一条补丁只有在「重新编译后诊断集严格变好」时才保留，否则
   自动回滚并记进 `fixes.rejected`。**没有验证过的修改不算修复。**
5. **不确定就标注，不猜。** 缺 `\cite` 条目、缺图片、缺 `.cls`、缺字体、跨语言判断、
   模板必填项取舍——一律进 `human_review` / `uncertainties`，`status` 相应降到 `partial`。
6. **诚实报告环境。** 镜像里没有引擎就写 `build.attempted: false` 与原因，绝不在没编译的
   情况下声称「编译通过」，也不编造版本号、页数、评分或耗时。
7. **预算。** 64 次模型请求 / 900 s。脚本阶段不耗请求；编译循环有 `--budget`（默认 420 s）
   硬上限，超时立刻停止并保留当前最好结果。**先写出 partial 结果，再迭代改进。**

## 1. 输入与输出契约

### 1.1 输入（Harbor 约定，字段名容错）

| 路径 | 内容 | 必需 |
|---|---|---|
| `/input/case.json` | `case_id`、`output_contract`、工程路径（`project` / `source_dir` / `manuscript` 等）、任务描述（`task` / `instruction` / `prompt`） | 否 |
| `/input/task.md` | 任务说明：要修什么、目标模板、受众、验收口径 | 是 |
| LaTeX 工程 | `*.tex` / `*.cls` / `*.sty` / `*.bib` / `*.bst` / 图片；可以是单文件，也可以是主文件+`\input` 子树 | 是 |
| `environment/resources.yaml` | 镜像内预装工具清单 | 否 |

**先读 `output_contract`。** 它通常是字段名列表。若它列出的字段名与本 Skill 的字段不同，
以 case.json 为准：`doctor.py` 会把同名块直接用上，别名用 `CONTRACT_SYNONYMS` 映射，
实在没有对应物的字段写成显式 stub（`_status: not_produced_by_this_skill`），
并在 `contract.missing` 里列出来——**不静默缺字段，也不编造内容填进去。**

### 1.2 输出（`/app/output`）

| 文件 | 内容 |
|---|---|
| `result.json` | **主结果**：`case_id` + `output_contract` 全部字段 + 状态/来源/不确定性/改动记录 |
| `fixed/` | 可编译、可继续编辑的 `.tex` 工程（原结构、原文件名、原正文） |
| `<job>.pdf` | 编译产物（有引擎且编译成功时） |
| `preview/page-*.png` | PDF 逐页预览（需 `pdftoppm`/`mutool`/`magick`/`gs` 之一） |
| `report.md` | 人能直接读的报告：修前/修后、根因、补丁、完整性、待人工项、限制 |
| `diagnostics.json` | 结构化诊断：每条含 `rule / file / line / severity / root_cause / cascade_parent / fix_order` |
| `static-checks.json` | 静态检查修前/修后汇总、引用闭包、Overfull 明细 |
| `fixes/patches.json` | 应用/回滚/未解决的补丁，每条带 `reason` 与 `verified` |
| `fixes/changes.diff` | 统一 diff（可 `git apply` 复核） |
| `build/pass-*.log` | 每个编译 pass 的原始转录 |
| `repro/` | `build.sh`、`latexmkrc`、`versions.txt`（引擎/宏包版本 + 输入 sha256）、`README.md` |

工作目录 `/app/work`：`snapshots/`（输入快照，用于回溯）、`tree/`（修补中的工作树）、
`build/`（转录与日志）。

## 2. 工作流（六步）

### Step 1 — 一次命令跑完确定性部分

```bash
python3 /skills/weekly-skill/scripts/doctor.py --input /input --out /app/output --work /app/work
```

它依次做：读 case/task → 找工程与主文件（`\documentclass` 打分）→ 建 `\input`/`\include`
包含图 → 探测引擎（`latexmk/pdflatex/xelatex/lualatex/tectonic` 是否存在及版本）→
选引擎与参考文献后端 → 静态检查 + 结构审计 → 编译循环 → 补丁循环 → 写全部产物。

**读它打到 stderr 的这几行**，它们决定你下一步该关注什么：

```
case_id=…  output_contract=[…]
project root=… main=main.tex files=12
engines: pdflatex, xelatex, bibtex, biber, kpsewhich
engine=xelatex (fontspec loaded (requires XeTeX/LuaTeX))  bib=biber
static: 13 findings (6 errors), 2 structural
iteration 0: (-3, -7, -3, 0) pages=None errors=3
  keep P001 (R-ADD-PACKAGE): (-3, -7, -3, 0) -> (-1, -4, -1, 1)
status=partial  pages=9  applied=2 rejected=1
```

### Step 2 — 判定任务类型，决定要不要额外动作

`result.json` 的 `static_checks` 与 `diagnostics` 已经覆盖了「编译得通」；剩下的按
`task.md` 归属：

| task.md 要求 | 追加动作 |
|---|---|
| 只要求修到能编过 | 不需要追加动作，直接 Step 5 自查 |
| 公式符号/编号/对齐、单位正斜体 | 看 `M-LEFT-RIGHT`、`M-ALIGN-NO-AMP`、`M-UNIT-ITALIC`、`M-DUPLICATE-LABEL`，按 `suggestion` 手工改，改完重跑 Step 1 |
| 表格列宽/合并/跨页、三线表 | 看 `T-CELL-MISMATCH`、`T-WIDTH-RISK`、`T-SCALED-TO-FIT`、`T-LONGTABLE-NO-HEAD`；**优先 tabularx / p{} / sidewaystable，不用 resizebox** |
| 引用与参考文献 | 看 `closure`：`citations_without_entry` / `references_without_label` / `unused_bib_entries`；缺条目一律交人工，不改正文论断 |
| 迁入期刊/会议/学位模板 | 看 `P-CLASS-UNAVAILABLE`、`P-CLASS-OPTION-UNKNOWN`、`P-CORE-MISSING`、`P-BIB-NOT-WIRED`；模板必填项缺失要在 `human_review` 里逐条写 |
| 可重复构建 | 已经自动产出 `repro/`；核对其中的版本号与 `pass_commands` 与本次运行一致 |

### Step 3 — 处理脚本交不出来的那部分（模型，1–3 次请求）

只做三类判断，且必须落到 `human_review` / `uncertainties`：

1. **缺条目/缺文件**：`C-CITE-NO-ENTRY`、`G-GRAPHIC-MISSING`、`I-INCLUDE-MISSING`、
   `P-CLASS-UNAVAILABLE` —— 缺的东西**不能凭空生成**，写清「缺什么、在哪一行、谁来补」。
2. **取舍类**：模板要求与原文意图冲突（例如模板强制 `\section` 编号但原文用 `\section*`），
   列出两种做法的影响，交人决定，不自作主张。
3. **级联归并的复核**：`diagnostics.summary.suppressed > 0` 时，确认被归并的条目在
   修掉根因后确实消失（重跑 Step 1 即可）；若仍存在，它们会作为新的活诊断出现。

### Step 4 — 复跑确认幂等

```bash
python3 /skills/weekly-skill/scripts/doctor.py --input /input --out /app/output --work /app/work
```

同输入 + 同环境 → 同 `diagnostics`、同 `fixes`、同 `fixed/` 哈希。若两次结果不同，
说明有环境噪声（时间戳、字体替换），把它写进 `uncertainties`。

### Step 5 — 自查（交付前必做）

```bash
python3 /skills/weekly-skill/scripts/selftest.py           # 145 条断言，应为 145/145
```

再对照 §7 的清单逐条核。

### Step 6 — 报告

`report.md` 已经是人可读版本；**不要再写一份文字自述去替代它**。若你追加了人工修改，
把每一条追加进 `fixes/patches.json` 的 `applied`（或 `human_review`），并重跑 Step 1
让 `changes.diff` 与 `patches.json` 保持同步。

## 3. `doctor.py` 参数与退出码

```
--input DIR         Harbor 输入目录（默认 /input）
--out DIR           输出目录（默认 /app/output）
--work DIR          工作目录（默认 /app/work）
--project DIR       直接指定工程根目录（跳过发现）
--engine NAME       auto|pdflatex|xelatex|lualatex|latexmk（默认 auto）
--max-iter N        补丁迭代上限（默认 4）
--budget SECONDS    所有编译 pass 的墙钟上限（默认 420）
--no-build          只做静态诊断与结构审计，不调编译器
--quiet             不往 stderr 打进度
```

退出码：`0` = 已写出 `result.json`（`success` 或 `partial`）；`2` = 输入不可恢复（仍会写出
`status: failed` 的 `result.json`，并说明缺什么）。

`engine=auto` 的判定顺序：`% !TEX program` 魔法注释 → `\documentclass` 专属要求
（`ctexart`→xelatex、`beamer`→pdflatex）→ `fontspec`/`xeCJK`/`ctex` 宏包 → 源码含 CJK
但没装 CJK 宏包 → 上一次日志的引擎横幅 → 默认 `pdflatex`。**每个结论都记录依据**
（`build.engine.evidence`），不是黑箱。

## 4. 关键方法（为什么这样做）

### 4.1 越过第一条报错：级联归并与根因定位

TeX 的报错位置常常不是出错位置。三种典型：

| 日志特征 | TeX 报在哪 | 真正的原因 | 本 Skill 的动作 |
|---|---|---|---|
| `! File ended while scanning use of \X` | 文件末尾 | 前面某处 `{` 或 `\begin{...}` 没闭合 | 对该文件做括号平衡，报**第一个未闭合的 `{` 的行号**，并允许 `R-CLOSE-BRACE` 补丁 |
| `Runaway argument?` + `! Paragraph ended before …` | 参数吞掉的最后一行 | 同上，或 `}` 多了一个 | 同上 / `R-REMOVE-EXTRA-BRACE` |
| `! Emergency stop.` + `Fatal error occurred` | 最后一行 | 前面第一条真实错误 | `cascade_parent` 指向根因，**不单独修**，`summary.suppressed` 里计数 |

除此之外，`! LaTeX Error: File 'x.sty' not found` 这类「缺文件」不会靠改正文解决，
`E-MISSING-CLASS`/`E-FONT-NOT-FOUND` 会被明确标成**环境缺口**而不是源码缺陷。

### 4.2 每条补丁都要被编译证明

```
现状诊断集 S0 --(补丁)--> 重编译 --> S1
S1 严格优于 S0 ?  保留并记 verified:true  :  回滚文件并记进 rejected
```

「优于」用 `diag_fingerprint` 判定：**阻断性错误数 → 警告数 → 错误数 → 是否出 PDF**，
字典序比较。已试过且被回滚的补丁记进 `tried`，后续迭代**不再重试**（避免反复抖动）。
这让「修复」有了可反驳的定义，而不是「看起来应该能行」。

### 4.3 拒绝「用删除换通过」

`checks.anti_cheat` 在交付前对比输入快照与产出：

- `\cite` / `\ref` / `\label` / `\includegraphics` / `\begin{equation}` / `\caption` 的出现次数**不得减少**；
- 不得新引入 `\sloppy`、`\tolerance=9999`、`\hbadness`、`\iffalse`、`\nonstopmode` 等压制手段；
- 单个文件非空白字符**不得减少超过 3%**。

命中即 `integrity.clean=false`，`status` 降为 `partial`，并写进 `report.md` 的「完整性」一节。
这条是本题「改得对 / 不把 PDF 当结果」的直接落点。

### 4.4 多轮收敛不是「跑三遍」

编译轮次由工程推导：`build_plan()` 按「引擎 → (bibtex/biber) → 引擎 → 引擎」生成，
并在出现致命错误时**立即停止后续 pass**（后面的 pass 只会重复同一个错误）。
参考文献后端由 `\usepackage{biblatex}` 的 `backend=` 选项、`natbib`、`\bibliography` 判定，
而不是假定 bibtex。`build.pass_commands` 记录实际跑过的命令，`repro/build.sh` 可原样重放。

### 4.5 可复现记录是产物的一部分

`repro/versions.txt` 里记：引擎与版本（`--version` 首行）、bib 后端、每个 pass 的命令、
Python 版本、`\listfiles` 解析出的宏包名/日期/版本、**每个输入文件的 sha256**。

诚实说明写在 `repro/README.md`：同版本 + 同输入 → 版面与页数可复现；
**PDF 字节哈希不保证相同**（时间戳、字体子集顺序会变）。所以本 Skill 比对的是
页数与输入哈希，不是 PDF 哈希。

### 4.6 没有引擎时仍然有用

镜像缺 TeX 时 `build.attempted=false`，但静态层依然给出可执行结论：
括号/环境/`$` 平衡（`S-*`）、引用与文献闭包（`C-*`、`X-*`）、表格列数（`T-*`）、
公式与单位（`M-*`）、模板必填项与类选项（`P-*`）、图片与 `\input` 存在性（`G-*`、`I-*`）。
**这些不需要编译器就能判定，也是「编不过」的一半原因。** 状态会明确写成 `partial`。

## 5. 失败与异常处理

| 情形 | 行为 | status |
|---|---|---|
| `/input/case.json` 缺失 | 从 `task.md` + 文件发现继续；`case_id` 取输入目录名 | partial |
| `task.md` 缺失 | 用 case.json 的 `task`/`instruction`/`prompt`；都没有则继续但记入 uncertainties | partial |
| 找不到 `.tex` | 写出 `status: failed` 的 result.json，列出输入目录实际内容 | failed (exit 2) |
| 有 `.tex` 但无 `\documentclass` | 取第一个 `.tex` 并记 warning；`P-NO-MAIN` | partial |
| 镜像无任何 TeX 引擎 | 静态模式：`build.attempted=false`，`ENV-NO-ENGINE` 进 uncertainties | partial |
| 编译超时 | 该 pass 记 `timed_out`，停止循环，保留已得产物 | partial |
| `kpsewhich` 说宏包没装 | **不打补丁**，给出 `tlmgr install <pkg>`；记 `ENV-*` | partial |
| 缺 `.cls` / 缺字体 | 不改用替代模板或替代字体（会改变版式），交人工 | partial |
| 编译通过但有 warning | 保留产物；`Overfull \hbox` 按 pt 排序给处置建议 | success/partial |
| 补丁全部被回滚 | `REPAIR-EXHAUSTED`：停止猜测，保留当前最好结果并说明 | partial |
| 完整性检查发现内容减少 | 不删产物，但 `status=partial` 且写进报告 | partial |
| 预算耗尽 | 用已有结果收尾，`status_reason` 写明未完成项 | partial |

## 6. `result.json` 结构

```json
{
  "case_id": "…", "status": "success|partial|failed", "status_reason": "…",
  "generated_at": "ISO-8601",
  "skill": {"name": "latex-build-doctor", "version": "1.0.0", "scope": "…"},
  "inputs": {"input_dir", "case_json", "task_files", "task_excerpt", "notes"},
  "project": {"root","main","documentclass","packages","bib_files","bib_style","includes",
              "missing_includes","magic_engine","encodings","main_candidates"},
  "environment": {"engines": {...}, "resources_yaml": {...}, "python": "3.11"},
  "build": {"attempted","engine":{"engine","reason","evidence","confidence"},
            "bib_backend","plan_steps","iterations","final_stats","success","pages",
            "pdf","pdf_sha256","timed_out","budget_seconds","spent_seconds"},
  "diagnostics": {"summary":{"total","live","suppressed","by_severity","fatal_errors","warnings"},
                  "items":[{"id","kind","severity","message","file","line","rule",
                            "root_cause":{"category","explanation","confidence","evidence"},
                            "cascade_parent","fix_order","confidence","source"}],
                  "structural":{"before":[…],"after":[…]}},
  "static_checks": {"before","after","findings","closure_after"},
  "fixes": {"applied":[{"id","rule","file","line","old","new","reason","verified"}],
            "rejected":[…], "unresolved":[…], "files_modified","files_added","files_removed","diff"},
  "integrity": {"findings":[…], "clean": true},
  "reproducibility": {"engine","bib_backend","pass_commands","input_hashes","pdf_sha256",
                      "repro_dir","note"},
  "deliverables": {"fixed_sources","main_tex","pdf","preview_png","build_logs",
                   "diagnostics","static_checks","patches","diff","report","repro"},
  "sources": [{"claim","evidence","file","line","rule","severity","raw"}],
  "human_review": [{"item","file","line","why"}],
  "uncertainties": ["…"], "change_log": [{"step","what"}], "log": ["…"],
  "contract": {"declared":[…],"satisfied":{"字段":"native|mapped_to:X|stub_declared"},"missing":[…]}
}
```

状态判定：`failed`（无源码/无法开始）< `partial`（有未解决阻断项、无引擎、完整性有阻断、
仍有 error 级静态问题）< `success`（编译通过且静态无 error）。**`partial` 必须在
`status_reason` 里写清限制。**

## 7. 交付前自查

- [ ] `result.json` 含 `case_id` 与 `output_contract` **全部**字段；`contract.missing` 为空或已解释
- [ ] `status` 与内容一致；`partial` 有 `status_reason`
- [ ] `build.attempted` 真实：没编译就是 `false`，**没有把「没编译」写成「编译通过」**
- [ ] `fixed/` 能编（有引擎时）；文件名与目录结构与输入一致，正文未被改写
- [ ] 每条 `applied` 补丁都有 `verified: true` 与 `reason`；`rejected` 有回滚原因
- [ ] `integrity.clean == true`，或已被明确标为待人工确认
- [ ] `diagnostics.items` 每条都有 `file`/`line` 或明确 `source`；`suppressed` 数量已解释
- [ ] `sources` 能逐条回溯（文件+行号 或 日志行）
- [ ] `repro/` 三个文件齐备，`versions.txt` 的版本号来自真实探测
- [ ] 没有新增材料外的事实；没有编造版本、页数、评分
- [ ] `preview/` 有 PNG 时说明是逐页预览，不是「用截图代替产物」
- [ ] `python3 scripts/selftest.py` 全绿

## 8. 最小调用示例（示例，非正式案例结果）

输入：`examples/input/`（一个小论文工程，`case.json` 声明
`output_contract: [status, diagnostics, build, fixes, sources, uncertainties]`）。

```bash
python3 scripts/doctor.py --input examples/input --out examples/output \
    --work .example-work --no-build
```

示意输出（节选，实际文件在 `examples/output/`）：

```
case_id=example-01  output_contract=['status','diagnostics','build','fixes','sources','uncertainties']
project root=…/examples/input/paper main=main.tex files=5
engine=pdflatex (default for Latin-script documents)  bib=bibtex
static: 13 findings (6 errors), 1 structural
no engine: static-only mode
status=partial  pages=None  applied=0 rejected=0
```

它交出的判断（`examples/output/report.md` 原文）：

```
S-BRACE-UNCLOSED  sections/intro.tex 第 10 行起 — 1 '{' never closed.
T-CELL-MISMATCH   sections/method.tex:17 — row 3 has 5 cells but the preamble declares 4 columns
X-REF-WITHOUT-LABEL sections/results.tex:13 — \ref{tab:param} has no \label{tab:param}
C-CITE-NO-ENTRY   sections/intro.tex:7 — \cite{wang2021} but no .bib entry has that key
G-GRAPHIC-MISSING sections/results.tex:8 — .includegraphics{figures/…} resolves to no file
```

**这是示例，不是平台固定案例的结果。** 输出仅用于说明接口与产物的形状。

## 9. 适用范围与限制

- **适用**：单文件或多文件 LaTeX 工程；pdfLaTeX / XeLaTeX / LuaLaTeX；BibTeX / Biber /
  手写 `thebibliography`；期刊/会议/学位论文模板；中英文混排。
- **不适用**：ConTeXt、纯 Word→PDF 流程、需要外部数据才能生成的图表数值（本 Skill 不会
  从图片像素反推数字）。
- **依赖**：Python ≥ 3.8 标准库，无第三方包。编译与预览依赖镜像内工具：
  `pdflatex`/`xelatex`/`lualatex`/`latexmk`、`bibtex`/`biber`、`kpsewhich`（可选）、
  `pdftoppm`/`mutool`/`magick`/`gs` 之一（预览用，可选）。全部缺失时降级为静态模式。
- **已知限制**：日志语法按 pdfLaTeX/XeLaTeX/LuaLaTeX/BibTeX/Biber 的公开格式实现，
  未覆盖全部宏包的自定义报错；`M-*` / `T-*` 的多数问题是**建议性**的，`auto_fixable=false`，
  需要人或模型按 `suggestion` 处理——这是刻意的，自动重排公式与表格会改变作者意图。

参考文档：`references/error-catalog.md`（规则表：日志signature→根因→可做什么）、
`references/repair-policy.md`（补丁许可与禁止、升级人工的条件）、
`references/build-recipes.md`（引擎/后端/轮次矩阵与可复现记录格式）、
`references/result-contract.md`（result.json 字段与 output_contract 映射规则）、
`references/checklist.md`（交付清单，可打印）。
