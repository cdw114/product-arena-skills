---
name: papertrans
description: "Translate a scientific paper PDF into a paragraph-aligned bilingual document with enforced terminology, protected numbers/units/citations/equations, and deterministic verification. Use when the task is 文献翻译 / translate this paper / 把这篇论文翻译成中文 / 双语对照 / bilingual translation of a PDF, or when a case supplies a paper PDF and asks for translation with traceable evidence. Produces bilingual.md/json, glossary, verify report and result.json; every paragraph carries page/bbox locators and a pass/warn/fail verdict."
---

# papertrans — 科研文献翻译（术语锁定 · 段落对齐 · 关系保护 · 可核验）

本 Skill 把一篇论文 PDF 翻译成**段落级双语对照**，并保证四件事由程序而不是提示词保证：

| 问题 | 机制 | 在哪检查 |
|-|-|-|
| **术语稳** | 术语表 `approved` 的术语在译前被替换为不可翻译的 `⟦TERM#nnnn⟧`，译后由程序回填锁定译名。译文中出现术语原形 = 泄漏，直接报错。 | `verify` + `assemble.term_consistency` |
| **段落全** | 解析器把 PDF 切成段（跨页/跨栏续段合并，标题/题注/公式/参考文献分开），每段一个 ID；分段结果就是翻译清单，少一段就报 `missing_translation`，两段译文相同就报 `duplicate_groups`。 | `verify` |
| **关系准** | 数字+单位、百分数、引用 `[12]`、图表/公式/章节交叉引用、行内公式在译前全部变成占位符 `⟦NUM#⟧ ⟦CITE#⟧ ⟦REF#⟧ ⟦MATH#⟧`，模型只能原样复制；译后程序逐个核对出现次数与数字多重集。否定词/模糊限制词数量突变 → 警告。 | `verify` |
| **可核验** | 每段输出 `[段号 | 角色 | 页码 | bbox | 核验]` 头，附所有占位符的 原文→译文 对照；不确定处由译者标 `[待确认: 原因]`，程序汇总到 `result.json.uncertainty`。 | `assemble` |

## 0. 运行契约（平台评测环境）

- 输入：`/input/case.json` + `/input/task.md`（或 `/app/work/task.md`）+ 论文 PDF（路径在 case/task 中给出）。
- 工作目录 `/app/work`，**最终产物必须写到 `/app/output`**，含 `result.json`（保留 `case_id`、`status`、证据、不确定性）。
- 预算：**64 次模型请求 / 900 s / 每次回复 16k token（含推理）**。本 Skill 的批次切分按 token 预算自动控制，一般 10–20 页论文 8–17 个批次；`plan.json.request_budget_estimate` 给出估算（= 1 + 2×批数 + 1）。
- 脚本位置：本 Skill 目录下的 `papertrans/` 包。**所有命令先 `cd` 到本 SKILL.md 所在目录再执行**（评测环境为 `/skills/weekly-skill`），下文记为 `$SKILL`。输出目录用绝对路径（如 `/app/work/out`），不要写到 Skill 目录里。
- 依赖：Python ≥ 3.9；优先 `pymupdf`（布局/字体），缺失时自动回退 `pypdf` → `pdftotext`，`plan.json.warnings` 会提示 `layout analysis degraded`。`pip install pymupdf` 若不可用不要卡住，直接用回退后端并在 result.json 的 `uncertainty.parser_warnings` 说明。
- Windows 控制台需 `PYTHONUTF8=1`；所有 JSON 读写都用 `utf-8-sig`，模型写出的带 BOM 文件也能读。

## 1. 流程总览（6 步，确定性步骤全部由脚本完成）

```
case.json/task.md/PDF
   │ ① prepare（脚本，<2 s）
   ▼
work/<case>/doc.json · segments.json · glossary_candidates.json · batches/B01..Bnn.json · plan.json
   │ ② 术语表审核（模型 1 次请求：批准/改写/补充，写 glossary_reviewed.json）
   ▼
   │ ③ 重新 prepare --reviewed（脚本）  → 占位符带上 TERM
   │ ④ 逐批翻译（模型：每批 1 次请求，写 translations.json）
   ▼
translations.json
   │ ⑤ verify（脚本）→ verify.json  ；fail 段 → 定向重译（最多 1 轮）
   │ ⑥ assemble（脚本）→ bilingual.md/json · glossary_used.json · references.md · result.json
   ▼
/app/output/
```

模型只做两件事：**审一次术语表**、**按批次翻译**。其余全部是脚本。

## 2. 逐步操作

### ① 读取输入并 prepare

```bash
SKILL=/skills/weekly-skill; OUT=/app/work/out; mkdir -p "$OUT" /app/output
cd "$SKILL"
PDF=$(python3 -c "import json;c=json.load(open('/input/case.json'));print(c.get('pdf') or (c.get('input') or {}).get('pdf') or c.get('file') or '')")
# 若 case.json 没有 pdf 字段：读 task.md 找 *.pdf 路径；再不行 ls /input /app/work 找唯一的 .pdf
python3 -m papertrans.cli prepare "$PDF" --out "$OUT" --case /input/case.json --lang zh
```

看 `$OUT/plan.json`：`n_segments`、`n_batches`、`n_placeholders`、`glossary_candidates`、`glossary_notes`、`warnings`、`request_budget_estimate`。
**请求预算规划**：`1（术语审核）+ n_batches（翻译）+ 允许 1 轮 fail 段重译（≤ n_batches）+ 1（终检）≤ 64`。若 `request_budget_estimate > 60`，加大 `--budget-tokens 4200` 重跑 prepare（每次回复上限 16k token，批内源文 ~4k token 时译文+JSON 开销约 6–8k，安全）。

`warnings` 里出现 `empty_pages` 或 `very little extractable text` → 该页是扫描图/无文字层。**不要猜内容**。若平台给了 OCR 工具就对那几页 OCR，把文本写进 `$OUT/ocr_pages/P{n}.txt`（n 为页码），再跑 `prepare ... --ocr-dir "$OUT/ocr_pages"`；没有 OCR 就在 result.json 里把这些页标为 `not_translated: no text layer`，继续翻译其余页。

### ② 术语表审核（模型，1 次请求）

打开 `out/glossary_candidates.json`。这是程序按"标题×5 / 摘要×3 / 小标题×3 / 题注×2 / 正文×1"加权抽出的候选，含缩写配对。你的任务：

1. 删除明显不是术语的（人名、机构名、通用词组），`status` 设 `rejected`。
2. 对保留的每条给出**唯一**中文译名写入 `target`，`status` 设 `approved`。专有名词/模型名（如 Transformer、BERT）设 `keep`（译文中保留原文）。
3. 补充候选里漏掉但标题/摘要里出现的关键术语（新增 `T0xx` 条目）。
4. 目标语言不是中文时，把 `target` 写成目标语言；`--lang` 也要一致。

写出 `$OUT/glossary_reviewed.json`（格式见 `references/glossary-format.md`）。然后：

```bash
cd "$SKILL" && python3 -m papertrans.cli prepare "$PDF" --out "$OUT" --case /input/case.json --lang zh --reviewed "$OUT/glossary_reviewed.json"
```

`plan.json.glossary_errors` 非空（如 target 为空、一词多译）→ 按提示改术语表再跑一次；`glossary_notes` 提示 "term locking is OFF" 说明没有 approved 条目，术语不会被锁——回到上一步。

### ③ 逐批翻译（模型，每批 1 次请求）

对 `$OUT/batches/B01.json … Bnn.json` 依次：

- 读 `segments[].masked`（已含占位符）和 `segments[].context`（上一段结尾，只为衔接）。
- 用文件内 `prompt` 字段的规则翻译：**只输出 JSON `{"S001": "…", "S002": "…"}`**，每个 `⟦..⟧` 原样复制到对应位置，不增删改编号；拿不准的地方保留原文并紧跟 `[待确认: 原因]`。
- 把结果合并进 `$OUT/translations.json`（格式 `{"translations": {"S001": "...", ...}}`，可逐批追加；纯 `{"S001": …}` 也能读）。

**硬性规则**：一次请求只翻一个批次；不要合并批次；不要改写 `masked` 里的非占位符内容；列表段保持一行一条。

### ④ 核验与定向重译（脚本 + 最多 1 轮模型请求）

```bash
cd "$SKILL" && python3 -m papertrans.cli verify "$OUT" --lang zh
```

输出 `verdicts.pass/warn/fail` 与 `issue_counts`。处理原则：

| issue | 级别 | 处理 |
|-|-|-|
| `missing_translation` / `placeholder_*` / `numbers_missing` / `xref_mismatch` / `citation_mismatch` / `placeholder_leftover` | fail | **必须**重译该段：把该段 `masked` 单独重翻，更新 translations.json，再 verify |
| `placeholder_order_changed` | warn | 看 `pairs`：年份/状语前移这类合法语序调整可保留；数值与名词配对可疑就重译 |
| `numbers_added` / `units_missing` / `negation_possibly_dropped` / `hedging_possibly_dropped` / `too_short_*` / `too_long_*` | warn | 看一眼该段，确实丢了否定/单位就重译；是译文表达差异（如"两"vs"2"）就保留，它会进入 result.json.uncertainty.warn_segments |
| `translator_unsure` | info | 保留，汇总到人工确认清单 |
| `duplicate_groups` | 任意 | 两段译文完全相同 → 几乎必是复制错误，重译其中一段（源文本身相同的图表标签除外） |

重译一轮后仍有 fail 且预算紧张：停止，`status` 会自动是 `partial`，fail 段列在 `result.json.uncertainty.fail_segments`。**不要为了变绿而删掉 fail 段或伪造译文。**

### ⑤ 装配输出（脚本）

```bash
cd "$SKILL" && python3 -m papertrans.cli assemble "$OUT" --case /input/case.json --lang zh
cp "$OUT"/bilingual.md "$OUT"/bilingual.json "$OUT"/glossary_used.json "$OUT"/verify.json "$OUT"/plan.json "$OUT"/result.json "$OUT"/translations.json /app/output/
[ -f "$OUT/references.md" ] && cp "$OUT/references.md" /app/output/
[ -f "$OUT/glossary_reviewed.json" ] && cp "$OUT/glossary_reviewed.json" /app/output/
```

`result.json` 字段：`case_id, task, status(success|partial|failed), target_lang, summary, result{文件}, evidence{源文件/解析器/作者/定位方式}, uncertainty{missing_segments, translator_unsure_markers, warn/fail_segments, term_inconsistencies, excluded_blocks_not_translated, parser_warnings}, change_records, generated_at`。

`change_records` 记录你做过的重译/术语修改（时间、段号、原因）。可在 assemble 后用 python 补写：

```bash
python3 - <<'EOF'
import json;p='/app/output/result.json';r=json.load(open(p))
r['change_records'].append({"step":"retranslate","segments":["S045"],"reason":"placeholder_missing","before":"...","after":"..."})
json.dump(r,open(p,'w'),ensure_ascii=False,indent=2)
EOF
```

## 3. 时间与预算

- 脚本步骤全部 < 3 s，不要为脚本计时。
- 模型步骤：术语审核 1 次；翻译 n 次（≈8–16）；重译 ≤ n 次；总请求 ≤ 1+2n+1，n ≤ 28 时满足 64。
- 若 900 s 快到期而批次未完：先 `verify` + `assemble`（未译段自动 fail → partial），把产物写进 `/app/output`，再继续；**任何时候 /app/output 都要有一份可交付的 result.json**。

## 4. 异常处置

| 情况 | 处置 |
|-|-|
| 无文字层 / 扫描件 | 见 ①：OCR 可用则 OCR，否则标 `not_translated: no text layer`，继续其余页 |
| 公式/表格是图片 | 公式块保留图片位置描述（`[公式图: p.5 bbox …]`），不要臆造 LaTeX；表格文本若可抽取照常翻译，表头数字受占位符保护 |
| 参考文献无法解析 | 参考文献默认不翻译、原样写入 `references.md`；解析失败不进入 segments，不影响正文 |
| 原文残缺 / 语言混杂 | 残缺处保留原文 + `[待确认: 原文残缺]`；非目标语言片段（如德语引文）保留原文并标注 |
| pymupdf 不可用 | 自动回退 pypdf/pdftotext，无字体信息 → 标题/作者识别变弱，`plan.json.warnings` 会提示；在 result.json 说明 |
| 术语表校验失败 | 按 `glossary_errors` 修；一词多译必须拆成两个 term_id |
| 译文 JSON 解析失败 | 该批模型输出不是合法 JSON → 重试该批一次，仍失败则把该批段落标 fail 继续 |

## 5. 输出示例（示意，非正式案例）

```
### [S003 | 正文 | p.1 | 72.0,254.1,297.6,486.3 | ✓]
The dominant sequence transduction models are based on complex recurrent or convolutional neural networks ...
占位符: ⟦TERM#0001⟧=sequence transduction→序列转换, ⟦NUM#0004⟧=28.4 BLEU
主流的序列转换模型基于复杂的循环或卷积神经网络……在 WMT 2014 英德翻译任务上取得 28.4 BLEU ……
```

完整最小示例见 `example/`（含 输入 → 命令 → 示意输出，已标明为示例）。

## 6. 文件

- `papertrans/` — 代码：`parse.py`（PDF→段落）、`segment.py`（分段/续段合并/批次）、`glossary.py`（候选抽取/校验/应用）、`protect.py`（占位符保护/还原）、`translate.py`（批次与提示词）、`verify.py`（核验）、`assemble.py`（回填/装配）、`cli.py`（入口）。
- `references/glossary-format.md` — 术语表 JSON 格式与规则。
- `references/verification-rules.md` — 每条核验规则的阈值、级别、处置。
- `references/segment-rules.md` — 分段/续段/切分规则与定位约定。
- `README.md` — 使用与方法说明；`requirements.txt`；`GITHUB_URL.txt`。
- `tests/` — 自检脚本与模拟翻译器（含故障注入），`run_tests.sh`。
- `example/` — 最小调用示例（示意输出）。
