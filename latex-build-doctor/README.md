# latex-build-doctor — LaTeX 编译诊断与修复闭环

把「这个 `.tex` 编不过」变成一组**可验证的根因**、每条**经重新编译证明有效的最小补丁**、
以及一份**别人能复现的构建记录**。

- 产物是**可继续编辑的源码工程**（`fixed/`），不是 PDF、不是截图、不是一段补丁片段。
- 判断是**可复核**的：每条诊断带 `file:line`，每条补丁带前后文本与 `verified` 标记，
  每条结论带 `sources` 指针。
- 拒绝**用删除换通过**：删 `\cite`、删公式、`\sloppy`、`resizebox` 包表格等一律被闸门拦下。

> 本目录是提交物本体。`examples/` 是**手工示例**（`example-01`），用来说明接口形状，
> 不是平台固定案例的结果。`tests/fixtures/` 是**手写的日志转录**，用于回归测试，
> 不是某次真实运行的捕获（原因见 `tests/fixtures/README.md`）。

---

## 目录

```
SKILL.md                      Skill 入口：硬规则、工作流、I/O 契约、失败处理、自查
README.md                     本文件：安装、调用、方法、增益论证、限制、维护
scripts/doctor.py             主入口：发现工程 → 静态审计 → 编译 → 打补丁 → 写产物
scripts/texlib.py             确定性核心：工程发现、日志解析、根因归类、括号/环境平衡、
                              补丁引擎、aux/bbl/bib、引擎探测、构建计划
scripts/checks.py             静态检查：引用闭包、表格列数、公式、模板必填项、图片/包含、
                              完整性闸门、Overfull 归类
scripts/selftest.py           回归测试（145 条断言，无需 TeX）
references/error-catalog.md   规则表：日志 signature → 根因 → 可做什么（E/W/S/C/X/T/M/P/G/I/A）
references/repair-policy.md   补丁许可白名单、被拒绝的补丁、必须交人的情形、禁止的「修复」
references/build-recipes.md   引擎/后端/轮次判定矩阵、可复现记录格式、缺工具降级矩阵
references/result-contract.md result.json 字段、output_contract 映射规则、状态语义
references/checklist.md       交付清单（可打印）
examples/input/               手工示例工程（含 6 类真实缺陷）
examples/output/              上述示例的示意输出（`--no-build` 静态模式）
tests/fixtures/               日志转录与 .blg 样本（回归用）
```

---

## 依赖与安装

**运行时**：Python ≥ 3.8 标准库。**不需要 pip install，不需要网络。**

```bash
python3 --version     # 3.8+
python3 scripts/selftest.py     # 应输出 145/145 assertions passed
```

**编译器（可选，但决定能否真的「编过」）**：

| 工具 | 用途 | 缺失后果 |
|---|---|---|
| `pdflatex` / `xelatex` / `lualatex` / `latexmk` | 编译 | 降级为静态模式，`status=partial` |
| `bibtex` / `biber` | 参考文献 | 不生成 `.bbl`，`\cite` 编号缺失 |
| `kpsewhich` | 查证宏包/类是否存在 | 打补丁前无法预判，改为靠重编译验证 |
| `pdftoppm` / `mutool` / `magick` / `gs` | PDF→PNG 预览 | 无 `preview/`，PDF 仍交付 |

镜像内清单若存在，先读 `/input/environment/resources.yaml`；与实际 `PATH` 探测冲突时
**以实际探测为准**（两者都记进 `result.json` 的 `environment`）。

---

## 调用方式

### Agent 视角（一次命令）

```bash
python3 /skills/weekly-skill/scripts/doctor.py \
    --input /input --out /app/output --work /app/work
```

先跑这一条，读 stderr 的 6 行摘要与 `result.json`，再决定是否需要人判断（见
`SKILL.md` §2 Step 2）。**不要**先手工 `pdflatex` —— 那样既拿不到结构化诊断，
也丢掉了逐条验证与回滚能力。

### 常用变体

```bash
# 镜像里没有 TeX，或只想先看源码问题
python3 scripts/doctor.py --input /input --out /app/output --work /app/work --no-build

# 模板明确要求 XeLaTeX，而工程里没有魔法注释
python3 scripts/doctor.py … --engine xelatex

# 大文档，放宽编译预算；或收紧迭代次数
python3 scripts/doctor.py … --budget 600 --max-iter 6
```

### 人类视角（看结果）

1. `report.md` —— 从这看起，一页看完现状、根因、补丁、待人工项、限制。
2. `result.json` → `contract` / `status` / `build` / `diagnostics.summary`。
3. `fixes/changes.diff` —— `git apply --check` 可复核，全部改动只有声明/定界符/转义。
4. `fixed/` —— 拷走即可继续编辑；`repro/build.sh` 可在别的机器重建。

---

## 输入 / 输出

**输入**：`/input/case.json`（`case_id`、`output_contract`、工程路径、任务描述）、
`/input/task.md`、LaTeX 工程（`.tex/.cls/.sty/.bib/.bst` + 图片）、
可选 `environment/resources.yaml`。

**输出**（`/app/output`）：

```
result.json                主结果（含 output_contract 全部字段）
fixed/                     可编译、可编辑的源码工程（原结构）
main.pdf                   PDF（有引擎且成功时）
preview/page-*.png         逐页预览
report.md                  人可读报告
diagnostics.json           结构化诊断（含 root_cause / cascade_parent / fix_order）
static-checks.json         静态检查修前/修后 + 引用闭包 + Overfull 明细
fixes/patches.json         应用/回滚/未解决补丁
fixes/changes.diff         统一 diff
build/pass-*.log           每个 pass 的原始转录
repro/                     build.sh / latexmkrc / versions.txt / README.md
```

---

## 关键方法（四句话）

1. **越过第一条报错。** TeX 的报错位置常不是出错位置：`File ended while scanning use of \X`
   报在文件末尾，真正原因是前面某个未闭合的 `{`；`Emergency stop` 只是前一条错误的回声。
   `texlib.annotate()` 用 `cascade_parent` 归并级联、用括号平衡把根因指回具体行号，
   `summary.total` 与 `summary.live` 的差就是被消掉的噪声数。
2. **补丁必须被编译证明。** `S0 →(patch)→ 重编译 → S1`，`S1` 严格优于 `S0`
   （`diag_fingerprint` 四级字典序）才保留，否则**回滚**并记入 `rejected`；
   试过的补丁不再重试，避免抖动。没有验证过的修改不算修复。
3. **不许用删除换通过。** `anti_cheat()` 对比输入快照与产出：关键标记数量不得减少、
   不得新引入压制命令、单文件字符数不得缩水 >3%。命中即 `integrity.clean=false`、
   `status` 降为 `partial`。
4. **可复现记录是产物的一部分。** 引擎/宏包版本（`--version` 与 `\listfiles`）、
   实际执行过的 pass 命令、每个输入文件的 sha256，全部落进 `repro/versions.txt`；
   并明确写下「PDF 字节哈希不保证相同，判据是版本+输入哈希+页数」。

对应题面的四个问题：

| 题面 | 本 Skill 的落点 |
|---|---|
| 编译得通 | 引擎/后端判定 + 收敛式 pass 计划 + 日志根因定位 + 验证式补丁 |
| 改得对 | `M-*`（公式/单位/对齐）、`T-*`（列数/宽表/缩放）、`C-*`/`X-*`（引用与文献闭包）、`P-*`（模板必填项） |
| 交得可用 | 交 `fixed/*.tex` 源码工程 + `changes.diff`，不交 PDF/截图代替源码 |
| 复现得了 | `repro/`（版本、命令、输入哈希）+ 幂等运行 |

---

## 相对基础 Agent 的差别（机制层面，不含未实测的分数）

题目要求「公平对照」，对照由平台生成；这里只说明**机制差异**，不报告任何未经实测的
成功率或提速数字。

| 能力 | 不加载 Skill 的常见做法 | 本 Skill 的做法 | 可核验位置 |
|---|---|---|---|
| 找工程结构 | 逐个 `cat` `.tex`，靠猜主文件 | `\documentclass` 打分 + `\input` 图 + 打分依据留档 | `project.main_candidates` |
| 读日志 | 停在第一条 `!`，通读全文 | 解析双格式日志、括号栈归属文件、`cascade_parent` 归并 | `diagnostics.items[].root_cause` |
| 修 | 想到什么改什么，改完不知道是否更好 | 白名单补丁 + 重编译验证 + 自动回滚 | `fixes.applied[].verified` / `fixes.rejected[].why` |
| 「修好了」的判据 | 这次没报错就算好 | 指纹严格变好才保留；完整性闸门单独把关 | `build.iterations[].fingerprint` / `integrity.clean` |
| 没编译器时 | 直接说做不到 | 静态层仍给出结构/引用/表格/公式/模板结论 | `--no-build` + `diagnostics.source=static` |
| 换机器复现 | 「我用的是 TeX Live 2023」 | 引擎/宏包版本 + pass 命令 + 输入 sha256 | `repro/versions.txt` |
| 诚实性 | 「已修复」 | `status` 三档 + `human_review` + `uncertainties` | `result.json` 顶层 |

**边界**：本 Skill 不解数学题、不改写论文内容、不生成文献条目、不从图里读数据。
它把「能不能编过、为什么编不过、改了什么、别人能不能重现」这四件事做实。

---

## 适用范围与限制

**适用**：单文件/多文件 LaTeX；pdfLaTeX / XeLaTeX / LuaLaTeX；BibTeX / Biber /
手写 `thebibliography`；期刊、会议、学位论文模板；中英文混排。

**不适用**：ConTeXt；纯 Word→PDF 流程；需要实验数据才能生成的图表数值。

**已知限制（如实列出）**：

1. **日志语法覆盖**按 pdfLaTeX/XeLaTeX/LuaLaTeX/BibTeX/Biber 的公开格式实现，
   未覆盖所有宏包的自定义报错；未识别的会落到 `E-OTHER` 并标 `confidence: low`。
2. **`M-*` / `T-*` 多数是建议性**（`auto_fixable=false`）。自动重排公式与表格会改变作者
   意图，所以只给 `suggestion`。
3. **本机无 TeX 时无法验证编译路径**。作者环境（编写本 Skill 的机器）没有 TeX 发行版，
   `probe_engines()` 报 `any_engine: false`，`examples/output/` 因此是 `--no-build`
   静态模式的产物。确定性层（145 条断言）不依赖 TeX，全部实测通过；**编译闭环在
   有 `pdflatex` 的镜像里才会被真正执行**，`build/pass-*.log` 会留下真实转录。
4. **不做「试遍所有引擎取能过的那个」**：换引擎会改变字体与断行，那是另一份产物。
5. **不用 PDF 字节哈希判可复现**：TeX 会写入时间戳与字体子集顺序，同输入不同字节是正常的。

---

## 自查

```bash
python3 scripts/selftest.py        # 期望：145/145 assertions passed
```

再对照 `references/checklist.md`（A–I 九组）逐条核。重点看：

- `result.json` 里 `contract.missing` 是否为空；
- `build.attempted` 是否真实；
- `fixes.applied[].verified` 是否全为 `true`；
- `integrity.clean` 是否为 `true`；
- `uncertainties` 是否把限制说清了。

---

## 维护

版本 `1.0.0`。

- 新增一条日志规则：在 `texlib.classify()` 加分支 → 在 `texlib.MACRO_PACKAGES` /
  `ENV_PACKAGES` 补映射 → 在 `references/error-catalog.md` 补一节 →
  在 `tests/fixtures/` 加一个转录 → 在 `selftest.py` 加断言。
- 新增一条静态检查：在 `checks.py` 加 `check_*` 并在 `run_static_checks()` 注册，
  返回值必须含 `rule/severity/explanation/auto_fixable`。
- 新增一条自动补丁：在 `doctor.plan_repairs()` 加分支，**必须**同时给出
  `confidence` 与 `risk`，并确认 `guard_patch()` 不会放行删除类改动。
- 改 `result.json` 字段：同步 `references/result-contract.md` 与 `CONTRACT_SYNONYMS`。

改完必跑 `scripts/selftest.py`。
