---
name: academic-polishing
description: Polish academic text (Chinese or English; journal paper, thesis, grant application, reviewer response, abstract) with a per-sentence edit ledger and a deterministic "protected span" check so that hedges, numbers, units, citations and claim strength survive the rewrite. Use when asked to 润色 / 改写 / 校对 / 学术语言润色 / polish / revise / improve the wording of a paper, abstract, proposal or response-to-reviewers, or to fix translationese (翻译腔 / 中式英语) in academic prose. Do NOT trigger for pure content Q&A, summarisation, literature search or data analysis with no rewriting request.
---

# 学术语言润色（academic-polishing）

## 这个 Skill 解决什么

整段重写最常见的三类事故：限定词在润色中消失（"可能"→"证明"）、术语在引言与方法之间漂移、中译英直译腔。
本 Skill 用**受保护跨度清单 + 术语表 + 逐句修改台账**把这三件事变成可检查的步骤，而不是靠"写完再通读一遍"。

核心原则：**最小编辑**。只改必须改的；每一处修改能指回原文、改文、类型、理由；改完后跑一次确定性审计，任何未在台账中说明的数据/引用/限定词变化都要处理。

## 何时触发 / 何时不触发

触发：用户要求润色、改写、校对、去 AI 味（学术语境）、改翻译腔、统一术语、调整语气、按期刊/基金/学位论文风格重写一段学术文字。
**不触发**：用户只是问内容问题（"这段实验说明了什么"）、要摘要、要查文献、要分析数据，没有任何改写请求。此时正常回答，不要擅自改写。

## 运行约定（Harbor 评测环境）

- 输入：`/input/case.json`（可能含 `source` 文件路径或内联 `text`、`task`、`target_genre`、`target_lang`、`length_limit` 等）和 `/input/task.md`（任务说明）。**读实际文件，不要根据字段名猜内容。**
- 工作目录：`/app/work`；最终产物：`/app/output/`，含 `result.json`（带 `case_id` 与全部 output_contract 字段）。
- 材料是 PDF 时用 `pdf-text-tool` 提取文本；引用原文时标明页码/段落。
- 预算：64 次模型请求、900 秒、单次回复 ≤ 16384 token（含推理）。**因此流程只有一次前置审计、一次后置校验**；不要多轮往返、不要反复重写。
- 先落一份诚实的 partial 产物，再逐步改进；超时前至少保证 `result.json` 存在。
- 不要伪造：拿不到的材料标"missing"，判断不了的标"uncertain"，审计器不能判断语义的地方如实写入 limits。

## 工作流（5 步）

```
0. init      python scripts/run_case.py init --case /input/case.json --task-md /input/task.md --work /app/work
             → 生成 work/edit_brief.json（受保护跨度清单 + 候选术语 + 风格提示 + 约束）
1. 读题      读 edit_brief.task_excerpt 和完整 /input/task.md；确定文体、语域、长度、禁改项。
             目标文体或语域不明 → 在 result.version_and_boundaries.human_confirmation_needed 中记录，
             按"最小编辑"处理（只修语法/标点/明显病句），不要擅自整体改写。
2. 建表      打开 work/glossary.json：把候选术语的 preferred（中/英）与 variants 填好；
             同一概念全篇只能有一个 preferred。缩写首次出现给全称。
3. 逐句编辑  编辑 work/revised.md：以 edit_brief.hedges_to_preserve / numbers_to_preserve /
             citations_to_preserve 为清单，逐句改。每改一句，向 work/ledger.json 追加一条记录
             （字段见下）。**只改需要改的句子**；没改的句子不记。
             必须改限定词时（任务明确要求"加强/弱化语气"），edit_type 用 hedge_adjust，理由里引用原词。
4. verify    python scripts/run_case.py verify --case /input/case.json --work /app/work --out /app/output
             → 写 /app/output/{revised.md, edit_ledger.json, edit_ledger.md, glossary.json, audit_report.json, result.json}
             exit 2 = 有未在台账说明的受保护跨度变化 → 回到第 3 步：要么恢复原词，要么补台账。
             预算允许时最多修一轮；仍不干净则以 --status partial 提交并在 limits 里说明。
```

脚本调用方式：`python <skill_dir>/scripts/run_case.py ...`，`<skill_dir>` 是本 SKILL.md 所在目录。两个脚本只依赖 Python 3.9+ 标准库。

## 输入 / 输出

**输入**：`case.json`（见上）+ 原文（txt/md/tex/docx；docx 用 python-docx 或标准库 zip+xml 读取）。
**输出**（`/app/output/`）：

| 文件 | 内容 |
|---|---|
| `revised.md` | 润色后全文（可直接使用，无注释、无占位符） |
| `edit_ledger.json` / `.md` | 逐句修改台账（表格形式，人可读） |
| `glossary.json` | 术语表：preferred（zh/en）、variants、状态 |
| `audit_report.json` | 确定性审计：跨度对比、术语违规、剩余风格提示 |
| `result.json` | 结构化结果，字段见下 |

`result.json` 字段（output_contract）：

```
case_id, status(complete|partial), generated_at
input{case_path, source_path, source_sha256, source_format, lang}
outputs{revised_text, revised_sha256, edit_ledger, edit_ledger_md, glossary, audit_report}
main_result{chars, sentences, hedges, negation, absolute, edits_recorded, edits_by_type}
fact_and_source_mapping{numbers_changed, citations_changed, author_year_changed, bracket_refs_changed,
                        hedge_words_dropped/added, glossary_violations_in_revised, explanation}
version_and_boundaries{ledger_errors, unexplained_changes, explained_changes,
                       style_hints_remaining_in_revised, human_confirmation_needed, limits}
```

台账条目（`edit_ledger.json` 的 `edits[]`）：

```
edit_id          "E01"
edit_type        grammar | syntax | punctuation | long_sentence_split | word_choice | terminology |
                 register | hedge_adjust | connective | translationese | redundancy | citation_format |
                 structure | format | other
source_excerpt   原文片段（≤ 60 字，含被改部分）
revised_excerpt  改文片段
reason           为什么改：错误类型 / 语域惯例 / 理由；若改了限定词必须引用原词
```

## 关键方法

1. **受保护跨度守恒**：hedges/numbers/citations 是清单不是建议。改完必须逐条核对；详见 `references/protected-spans.md`。
2. **术语表驱动的一致性回扫**：先建表再编辑；编辑时任何 variants 出现都改 preferred；详见 `references/terminology.md`。
3. **语域优先**：期刊论文 / 学位论文 / 基金申请 / 审稿回复 / 英文摘要的语气和句长不同；先判断文体再决定改动力度；详见 `references/register.md`。
4. **最小编辑 + 可追溯**：每处修改要能让第三方判断"该不该改"；详见 `references/edit-ledger.md`。
5. **约束处理**：语法、标点、长句切分、格式；详见 `references/constraints.md`。

## 审计器能做什么、不能做什么

`scripts/polish_audit.py` 是词法层（正则 + 规则表）工具：
- **能**：提取并比对数字+单位、百分数、p 值、`\cite{}`/`[@key]`/`[12]`/作者-年份引用；提取限定词/绝对词/否定词并比对增删；术语表 variant 检测；中文半角标点、长句、常见翻译腔模式提示；LaTeX/Markdown 标记剥离。
- **不能**：判断一句话改写后语义是否保持；识别所有罕见限定词（会有漏报）；区分"不断"的"不"与否定（会有误报）。
- 因此：审计结果中的 `dropped/added` 是**给编辑的核对清单**，不是判决。每一条要么在台账里有对应说明，要么恢复原词。误报（如"近年来"的"近"）在台账 `other` 类型里记一句"审计误报，未改"即可。

## 自查方法（提交前）

1. `result.json` 存在，`status` 诚实（有 unexplained 即 partial）。
2. 抽 3 条台账，确认 `source_excerpt` 确实出现在原文、`revised_excerpt` 确实出现在改文。
3. 所有数字、单位、引用编号与原文逐一对得上（看 `fact_and_source_mapping`，全为空数组）。
4. 改文中不再有原文的风格提示（`style_hints_remaining_in_revised` 为空或均为有意保留）。
5. 通读改文一遍：仍然像同行写的学术文本，不是"更华丽的版本"。

## 异常处理

| 情况 | 处理 |
|---|---|
| 找不到原文材料 | `result.status=partial`，`limits` 写明 "source material missing"；不要凭字段名编造原文 |
| `task.md` 与 `case.json` 冲突 | 以 `task.md` 为准（它是任务说明），在 `human_confirmation_needed` 记录冲突 |
| 目标文体/语域不明 | 按最小编辑处理（只修硬错误），记录需人工确认 |
| 术语表内部冲突（同一 preferred 对应多个概念） | 保留原文用词，标记 `status: conflict`，记录需人工确认 |
| 原文超长（> 10k 字）且预算不足 | 按章节分块，优先处理摘要/引言/结论；`status=partial`，`limits` 列出未处理章节 |
| 审计 exit 2 且预算将尽 | 恢复被删的受保护词比补台账更安全；以 `--status partial` 提交 |
| 输入是 PDF/扫描件 | `pdf-text-tool` 提取；OCR 置信度低的段落标记 `uncertain` |
| 用户只要建议不要改文 | 只输出台账（`edit_type`+`source_excerpt`+建议），`revised.md` 保持原文，`status=partial` |

## 适用范围与限制

- 中、英文学术文本；支持 txt / md / tex / docx 输入。
- 不做事实核查、不补文献、不改数据；发现疑似数据错误只在 `human_confirmation_needed` 中提出。
- 术语候选来自词频，不是领域词典；`glossary.json` 需编辑确认。
- 审计器是词法层工具，存在漏报与误报（见上）。

## 最小调用示例（示意输出，非正式案例结果）

输入 `/input/case.json`：
```json
{"case_id": "demo-001", "target_genre": "学位论文", "target_lang": "zh",
 "task": "润色摘要：修正语法与标点，消除翻译腔，拆分过长句；不得改变数据、限定强度与引用编号。",
 "source": "abstract.md"}
```

```bash
python <skill_dir>/scripts/run_case.py init   --case /input/case.json --task-md /input/task.md --work /app/work
# → work/edit_brief.json 列出：hedges ['可能','尚不明确','我们推测',…], numbers ['3.2 mg','15.3%','18.7%'],
#   author_year ['Smith 等 (2019)'], bracket_refs ['[12]'], style_hints ['得到了广泛的提升','综上所述', …]
# 编辑 work/revised.md，逐句追加 work/ledger.json
python <skill_dir>/scripts/run_case.py verify --case /input/case.json --work /app/work --out /app/output
# → {"status":"complete","edits":6,"unexplained":0,"hedges":{"source":8,"revised":8}}
```

一条台账记录示例：
```json
{"edit_id":"E04","edit_type":"connective",
 "source_excerpt":"这一提升可能源于缺陷态密度的降低，但具体机制尚不明确",
 "revised_excerpt":"这一提升可能源于缺陷态密度的降低，但其具体机制尚不明确",
 "reason":"补主语'其'使转折句主语明确；限定词'可能''尚不明确'原样保留。"}
```

## 资源

- `scripts/run_case.py` — init / verify，I/O 契约与 result.json 生成
- `scripts/polish_audit.py` — 确定性审计（extract / compare），exit 2 表示有需核对的变化
- `references/protected-spans.md` — 受保护跨度的识别与守恒规则
- `references/terminology.md` — 术语表、中英对齐、缩写、漂移检测
- `references/register.md` — 文体与语域差异
- `references/edit-ledger.md` — 台账格式、修改类型、理由写法
- `references/constraints.md` — 语法、标点、长句切分、格式
- `references/harbor-runtime.md` — 评测运行约定、路径、预算、产物位置
