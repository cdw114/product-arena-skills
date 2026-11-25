# paper-structured-notes

一个把真实论文 PDF 变成**与原文结构对齐、可回溯到页码/文本块**的结构化笔记的 Agent Skill。

问题不是"总结得不够长"，而是三件事经常同时坏掉：

1. **对不上** —— 输出套用通用摘要模板，和论文自己的章节与论证顺序脱节；
2. **找不回** —— 结论只给一个笼统出处（"见论文"），没有页码/段落，无法复核；
3. **留不住** —— 研究问题、数据、方法条件、限制没被记录，让结论成立的前提被丢掉。

本 Skill 的做法：把**确定性工作交给脚本**（解析、切分、锚点校验、覆盖率核算），
只把**阅读与措辞交给模型**。所以每一条关键笔记都能被机器重新打开原文核验，
而不是只能相信笔记作者。

## 目录

```
SKILL.md                      技能本体（触发条件、流程、输入输出、异常处理）
references/
  field_dictionary.md         论文卡片与知识点的字段字典
  anchor_format.md            锚点格式与校验语义
  notes_draft_schema.md       Agent 要写的 notes_draft.json 结构
  output_contract.md          result.json 结构，以及如何并入案例自带的契约
  troubleshooting.md          扫描件/加密/双栏/超长/非中文/图表缺失
  example.md                  完整示例（明确标注为示例，非案例答案）
scripts/
  pdf_extract.py              PDF → skeleton（章节、块、图表、阅读顺序）
  build_notes.py              draft → result.json / notes.md / validation.json
  audit.py                    运行后审计（check 子命令）
  selftest.py                 离线自测（12 项断言）
  run.sh                      一键入口（bash）
  run.py                      同上一键入口（无 bash 环境）
```

`run.sh` 与 `run.py` 等价：`extract` / `validate` / `check` / `selftest`。

## 安装与依赖

| 组件 | 依赖 | 说明 |
|---|---|---|
| `validate` / `check` | Python 3.9+ | 纯标准库，无需安装任何东西 |
| `extract` | `pymupdf` | `pip install pymupdf`（≥1.24 提供 `pymupdf` 模块名；旧版 `fitz`） |
| OCR（可选） | `pytesseract` + `Pillow` + tesseract 二进制 | 仅扫描件需要 |

```bash
pip install pymupdf                 # 仅 extract 阶段需要
python3 scripts/run.py selftest _selftest   # 12/12 通过即环境正常
```

不需要网络、不需要 API key、不写任何个人路径。

## 快速开始

```bash
# 1) 解析（不消耗模型调用）
bash scripts/run.sh extract paper.pdf /app/work

# 2) 先看抽取报告：状态、章节数、异常
cat /app/work/extract_report.json

# 3) 按 references/notes_draft_schema.md 写 /app/work/notes_draft.json

# 4) 校验并产出
bash scripts/run.sh validate /app/work /app/output /input/case.json /input/task.md

# 5) 收尾自检
bash scripts/run.sh check /app/output
```

没有 `case.json` / `task.md` 时省略后两个参数即可。

## 输入与输出

**输入**：`/input/case.json`（案例标识与题目要求）、`/input/task.md`、以及案例引用的 PDF。
案例若自带 `output_contract`，其字段优先（见 `output_contract.md` §3）。

**输出**：

| 文件 | 内容 |
|---|---|
| `/app/output/result.json` | 机器契约：`case_id`、`run_status`、`result`（卡片/章节/知识点/问答）、`evidence`（锚点校验与覆盖率）、`uncertainty`、`change_log` |
| `/app/output/notes.md` | 同一内容的人类可读版，标题层级与论文一致 |
| `/app/output/validation.json` | 锚点与覆盖率的审计记录 |

`result.json` **在拒答时也会写出**，所以输出目录不会是空的。

## 关键方法

1. **章节对齐**：书签（outline）优先；缺失时退到字号/正则启发式；两者合并以补
   书签常漏的 References / Acknowledgements / Appendix。抽取方法记录在
   `extract_report.json.heading_method`，可复核。
2. **阅读顺序**：逐页检测栏数，按列优先排序，通栏标题与图带作为分带边界——解决双栏错序。
3. **锚点回链**：`p{page}:b{block}` + 逐字引文。页码 1-based，块号按该页阅读顺序；
   引文经空白/连字符归一化后必须是该块文本的子串。任何一条不成立即判失败。
4. **字段化**：卡片固定 8 个字段，全部要有值或显式 `not_reported`；
   `scope_conditions` 专门记录"让结论成立的前提"。
5. **知识点去重**：同义/缩写并入 `aliases`；校验器报告重复 `id` 与重复 `term`。
6. **诚实状态**：有失败锚点或缺章节 → 强制 `partial`，不允许自称 `success`。

## 适用与不适用

**适用**：单篇论文的章节摘要、论文卡片（多篇可并排比较）、知识点清单、
带出处问答、参数/条件抽取。

**不适用**：复现论文数值、重画论文图、代码审查、跨论文综述写作。
后者需要的是检索与综合，不是单篇结构性笔记。

## 失败处理

| 情况 | 行为 |
|---|---|
| 加密 PDF | `refused`，原因写明需要密码 |
| 扫描件 + 无 OCR | `refused`，原因写明；有 OCR 则 `--force-ocr` |
| 无法识别标题 | 按单节处理，`heading_method` 记录 `none`，状态降为 `partial` |
| 图表无法解析 | 锚点退到最近段落，`uncertainty` 注明"图表不可机读" |
| 预算耗尽 | 已写的部分仍可 `validate`，产出完整 `partial` 结果 |
| 锚点校验失败 | 修正 anchor 或 quote 后重跑，**不允许绕过** |

## 自测

```bash
python3 scripts/selftest.py _selftest
```

覆盖 12 项断言：健康草稿通过、错引文被捕获、越界页码被捕获、重复知识点被标记、
拒答仍写出 `result.json`、缺章节被报告等。报告写入 `_selftest/selftest_report.json`。

真实论文端到端验证（15 页双栏论文，23 节 / 9 图 / 4 表）：23/23 节覆盖，
37/37 锚点通过，8/8 字段填充。

## 维护

- 章节识别规则集中在 `pdf_extract.py` 顶部正则（`NUM_HEADING`、`CAPTION_RE`、
  `NUM_PREFIX` 等），换语种/换出版社模板时优先改这里。
- 字段与锚点语义的改动必须同步 `references/` 四份文档，否则文档与实现会分叉。
- 版本：v1.0。行为变更请写进 `change_log` 字段，便于复核。

## 许可

MIT。示例与自测夹具为合成内容，不含任何论文原文。
