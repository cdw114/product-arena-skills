---
name: intrograph
description: 引言与相关工作写作——先建四本可核对的账（引用账、分组账、空白账、贡献-证据账），再据此写"研究背景 / 相关工作 / 研究空白 / 主要贡献"，最后用 18 项确定性核对逐条拦截"编造引用、无来源论断、逐篇摘要拼接、无出处空白、无证据贡献、为写作补数字"。适用于给一篇真实论文（材料含稿件+文献库）起草或改写引言与相关工作，中英文、数字制/著者-年份制/LaTeX 均可。触发词：写引言、引言、相关工作、related work、introduction、研究背景、研究空白、research gap、贡献表述、contributions、补引用、核对引用、综述段落、按路线分组、"gap is asserted not derived"、审稿意见说背景空转。
---

# 引言与相关工作写作（intrograph）

本 Skill 只做一件事，把它做实：**让引言的每一句事实性文断都能落到一条具体引用，让相关工作的每一次比较都能落到同一个维度，让研究空白由已引文献的缺口推出，让每条贡献都能回到正文的某个图/表/节/结果。**

实现上分两层，职责不重叠：

| 层 | 谁做 | 做什么 | 为什么这样分 |
|---|---|---|---|
| 判断层 | 模型 | 读材料、定分组与比较维度、推导空白、压缩贡献、写正文 | 这些无法用规则决定 |
| 核对层 | 脚本（0 次模型调用） | 18 条确定性检查，逐条给出可复核的错误/警告 | 判断容易被语言说服，规则不会 |

先把账建好再写，是因为**账是唯一能被独立复核的东西**。基础 Agent 直接成文，引用是装饰；本 Skill 强制先写账，成文后逐条回账。

## 0. 硬规则（先读，违反即返工）

1. **输入文件是唯一事实来源。** 读 `/input/case.json`、`/input/task.md`，再读实际材料；不从题目名、领域标签、记忆里补文献、补数字、补结论。
2. **只用文献库里有的引用。** 引用键必须能在 `library.json` 或稿件文末参考文献表里找到；找不到就是编造，核对会以 error 拦下。
3. **不新增材料外的事实与数字。** 成稿里每个带单位或小数的数字都必须能在稿件或文献库找到；否则核对报 `invented_metric`。
4. **不确定就标注，不猜。** 作者判断写"本文认为/据我们判断/we argue"；材料不足进 `uncertainty`；状态降为 `partial` 并写明 `limits`。
5. **预算。** 64 次模型请求 / 900 秒 / 单次回复 ≤16384 token。脚本阶段不耗请求；成稿按部分分块写，不要一次重写全篇。
6. **早期保存。** `--stage plan` 会立刻写一份 `status=partial` 的 `result.json`，即使后面被截断也留着可核对的东西。

## 1. 何时使用 / 何时不用

**用**：给定一份论文材料（正文 + 文献库，可能还有笔记/图表/任务说明），要产出或改写引言与相关工作；要求"分组比较而不是逐篇罗列""空白要有出处""贡献要对得上图表"；要核对一份已有引言里的引用与论断。

**不用**：只做格式转换或纯翻译（那是别的 Skill）；没有稿件、只有一堆文献（无法核对贡献与证据）；要求生成不存在的实验数据。

## 2. 执行流程（严格按顺序，不要跳步）

### 第 0 步：读输入，不要假设

```bash
ls -la /input
cat /input/case.json
cat /input/task.md 2>/dev/null || true
```
`case.json` 的字段名可能不同（`task` / `instruction` / `prompt`；`manuscript` / `source`；`library` / `bibliography` / `references`）。**先读 `output_contract`**：它列的字段名就是 `result.json` 必须有的字段名。

### 第 1 步：建账（脚本，1 次调用）

```bash
mkdir -p /app/work /app/output
python3 scripts/run_case.py --input /input --out /app/output --work /app/work --stage plan
```

脚本做四件事，并立刻写 `status=partial` 的 `result.json`：

| 产物 | 内容 |
|---|---|
| `work/intake.json` | 任务文本、识别到的意图（draft/revise）、语言、引用格式、材料清单 |
| `work/library.json` | 规范文献库：每条有稳定 `ref_id`（`R0001`…），DOI/题名/作者年份去重，记录合并依据 |
| `work/manuscript_index.json` | 稿件索引：章节、图号、表号、公式号、摘要、文末参考文献表、全文数字索引 |
| `work/scaffold.md` | **写作脚手架**：可用引用键清单 + 真实存在的证据定位 + 四部分骨架（带 `<!-- part:... -->` 标记） |
| `work/ledgers/ledger_*.template.json` | 四本账的模板 |

读 `scaffold.md` 与 stderr 日志（`materials=`/`library=`/`figures=`/`reflist links:`）再往下走。**日志里出现 `unmatched_new_entry` 意味着文末参考文献表有条目在文献库里找不到**，那些条目会被标 `unverified_metadata`，核对时会报元数据警告——这是真实情况，不要掩盖。

### 第 2 步：写四本账（模型，2–3 次请求）

按 `references/ledgers.md` 的字段表填写。顺序有依赖，不要跳：

1. `ledger_refs.json` — 每篇文献一行：`role`（seminal/representative/recent/baseline/survey/application/other）、`cluster`、`must_cite`、`one_line`（一句话写清"做了什么 + 结论 + 适用条件"）。
2. `ledger_groups.json` — 分组。**每组 ≥2 篇**，`works[].ref_id` 必须来自 `library.json`；每篇填满 `method_route / data_setting / evaluation / conclusion / limitation` 五个字段；`comparison.dimension` 写比较维度，`comparison.tradeoff` 写组内取舍。写法见 `references/grouping.md`。
3. `ledger_gaps.json` — 每条空白：`derived_from`（≥1 篇已引文献 + `limitation_kind` + 证据）、`how_filled.contribution_ids`。`evidence.kind = quote` 时，引文必须能在该文献摘要里逐字找到。写法见 `references/gap-derivation.md`。
4. `ledger_contributions.json` — 每条贡献：`evidence[]` 至少一条可定位（`figure` / `table` / `section` / `result` / `equation`），`result` 类要给 `claim_in_source` 原文；`scope` 写不主张的范围。写法见 `references/contribution-map.md`。

**写账时就去核对**：`scaffold.md` 里列了真实的图号/表号/章节号；账里写 `Fig. 9` 而稿件只有 Fig. 1–2，第 3 步会拦。

### 第 3 步：按账写正文（模型，2–4 次请求）

把 `work/scaffold.md` 复制成 `work/draft.md`，**保留 `<!-- part:background -->` … `<!-- /part:background -->` 四组标记**，在标记之间写正文。四部分：

| 部分 | 要求 |
|---|---|
| 研究背景 | 2–3 段。第 1 段：领域脉络 + 具体技术约束（不要"近年来受到广泛关注""随着……的快速发展"）。第 2 段：现有路线各自卡在哪个具体环节。每段至少 1 个引用 |
| 相关工作 | 每组 1 段，按 `group_id` 顺序。**同组同维度横向比较**（而/相比之下/优于/代价/trade-off），不要逐篇摘要 |
| 研究空白 | 1 段：由各组共同的局限/未覆盖场景/相互冲突的结论推出空白，结尾一句说明本文如何填补（出现"本文/本研究/we/this paper"）。至少 1 个引用 |
| 主要贡献 | 3–5 条要点，每条对应一个真实存在的图/表/节/结果数值；拔高表述（首次/首个/state-of-the-art）必须在 `scope` 里写适用范围 |

分块写：一次写一部分，写完立刻进第 4 步，不要等四部分都完美。

### 第 4 步：核对（脚本，0 次请求；可反复跑）

```bash
python3 scripts/run_case.py --input /input --out /app/output --work /app/work --stage audit
```

输出 `work/audit.json` 与 `/app/output/audit_report.{json,md}`。`audit_report.md` 按四个问题汇总，`must_fix` 列出必须先修的错误。**逐条修 ERROR，再跑一次**；剩余 WARNING 可以保留但要理解它。

18 条规则与对应的失败模式见 `references/failure-modes.md`。最常见的四类：

| 现象 | 规则 | 处置 |
|---|---|---|
| `invented_citation` | R01 | 删掉该引用，或换成文献库里真实存在的键（不要改文献库去迁就正文） |
| `cited_but_ungrouped` | R09 | 把它放进某个分组，或从相关工作里删掉；不要留"孤立引用" |
| `gap_from_uncited_work` / `unverifiable_quote` | R10 | 先在相关工作里引它，再把引文改成摘要里逐字存在的那句 |
| `evidence_figure_missing` / `invented_metric` | R12 / R13 | 定位改到真实存在的图/表，数字改回稿件里的值 |

### 第 5 步：定稿（脚本，0 次请求）

```bash
python3 scripts/run_case.py --input /input --out /app/output --work /app/work --stage finalize
```

`--stage audit` 之后再 `--stage finalize`；`--stage auto` 会在有成稿时一次跑完 plan→audit→finalize。产出见 §3。

### 第 6 步：交付前自查

```bash
python3 - <<'EOF'
import json; r=json.load(open('/app/output/result.json',encoding='utf-8'))
print(r['status']['state'], r['status'].get('gate'), r['audit'])
print('parts:', {k:v['present'] for k,v in r['result']['parts'].items()})
print('refs:', r['result']['n_distinct_refs'], 'groups:', r['result']['n_groups'])
EOF
```
必须核对的 5 件事：
1. `status.state`：`success` 只在 gate=pass 且 0 error 时出现；否则必须是 `partial` 并在 `status.limits` 写明未解决项。
2. 四部分都在，且 背景→相关工作→空白→贡献 顺序成立（`result.parts`）。
3. `result.json` 含 `case_id` 与 `output_contract` 全部字段（`inputs.contract_filling.unfilled` 应为空）。
4. `introduction_related_work.md` 里没有残留 `<!--` 注释；`related_work_table.md` 每行 6 列。
5. `refs_cited.txt` 的编号与正文里的 `[n]` 一致（`result.result.reference_numbering`）。

## 3. 输入与输出契约

### 3.1 输入

| 路径 | 内容 | 必需 |
|---|---|---|
| `/input/case.json` | `case_id`、`task`、`output_contract`、可选 `target_lang` / `citation_style` | 否（缺则 `case_id` 取目录名并记 notes） |
| `/input/task.md` | 任务说明：体裁、受众、语言、引用格式、篇幅 | 建议 |
| 稿件 | `.md` / `.txt` / `.tex`；含章节、图注、文末参考文献表 | 是（缺则无法核对贡献） |
| 文献库 | `.bib` / `.ris` / `.json` / `.csv` / `字段: 值` 文本；可多个 | 否（缺则从文末参考文献表反推，标 `unverified_metadata`） |
| 其他 | 作者笔记、图表说明（`kind: notes`，只作背景，不作事实来源） | 否 |

### 3.2 输出（`/app/output`）

| 文件 | 内容 |
|---|---|
| `result.json` | **主结果**：`case_id` + `output_contract` 全部字段 + 状态、四部分、引用映射、四本账回执、核对汇总、不确定项、变更记录 |
| `introduction_related_work.md` | 可直接进稿的四部分正文（标记已剥离，中英文按目标语言） |
| `related_work_table.md` | 由分组账渲染的比较表：每行一篇，六列同维度对齐 + 每组取舍结论 |
| `contribution_table.md` | 贡献↔证据对照表（含"不主张"列） |
| `audit_report.json` / `audit_report.md` | 18 条规则的逐条结果、按四个问题汇总、must_fix 清单 |
| `citation_map.json` | 每个引用点：所在部分/段/句、原始标记、解析到的 `ref_id`、未解析项 |
| `refs_cited.bib` / `refs_cited.txt` | **只含正文实际引用**的文献，按正文编号排序；英文数字制按 IEEE，中文数字制按 GB/T 7714—2015，著者-年份制按 APA 7 |
| `ledger_*.json` | 四本账的副本（便于复核"分组依据/空白推导/贡献对照"） |

### 3.3 `result.json` 关键字段

```jsonc
{
  "case_id": "…",
  "status": {"state": "success|partial|failed", "gate": "pass|fail", "reason": "…",
             "limits": ["未解决项…"], "notes": []},
  "task": {"text": "…", "intent": {"intents": ["draft"], "mode": "draft"}, "lang": "zh|en",
           "citation_style": "numeric|author-year|key", "genre": "…", "length_limit": null},
  "inputs": {"manuscript": {…}, "library": {"n": 10, "fallback": "none", "sources": […]},
             "output_contract": {…}, "output_contract_fields": […], "contract_filling": {"unfilled": []}},
  "result": {"introduction_related_work_file": "introduction_related_work.md",
             "parts": {"background": {"present": true, "paragraphs": 3, "text": "…"}, …},
             "part_order": ["background","related_work","gap","contributions"],
             "chars": 6611, "n_distinct_refs": 10, "n_groups": 3, "n_gaps": 2, "n_contributions": 4,
             "reference_numbering": {"R0001": 1, …}},
  "related_work": {"text": "…", "groups": [{"group_id":"G1","dimension":"…","ref_ids":[…]}], "table_file": "…"},
  "research_gap": {"text": "…", "gaps": [{"gap_id":"PG1","derived_from":[…],"how_filled":{…}}]},
  "contributions": {"text": "…", "items": [{"contribution_id":"C1","evidence":[…],"scope":{…}}]},
  "citation_map": [{"part":"related_work","para":0,"sentence":"…","markers":["[3, 4]"],"ref_ids":[…]}],
  "contribution_map": [{"contribution_id":"C1","evidence":[…] }],
  "references_used": [{"ref_id":"R0001","number":1,"title":"…","ieee":"…","gbt7714":"…","apa7":"…"}],
  "evidence": {"group_ledger": […], "gap_provenance": […], "manuscript_locators": {…}},
  "audit": {"gate":"pass","errors":0,"warnings":0,"report_file":"audit_report.md","rules_failed":[]},
  "uncertainty": {"unresolved_citations": [], "author_judgments": [], "notes": [], "not_done": []},
  "changes": [{"step":"plan|draft|audit|finalize","what":"…"}],
  "sources": [{"path":"/input/x.md","sha256":"…"}],
  "artifacts": {"introduction_related_work":"…","audit_report_md":"…"}
}
```

`output_contract` 里的字段名会按同义词表映射到上述结构（`introduction`→`introduction_related_work`、`gap`→`research_gap`、`references`→`references_used` 等），映射不上的填空值并把名字记进 `inputs.contract_filling.unfilled`——**不静默丢字段**。

## 4. 脚本参数

```
python3 scripts/run_case.py --input DIR --out DIR --work DIR --stage {auto,plan,audit,finalize}
  --input   输入目录（默认 /input；非 Harbor 环境回退到 /app/input、./input、.）
  --out     输出目录（默认 /app/output）
  --work    工作目录（默认 /app/work）
  --stage   plan=建账；audit=核对；finalize=定稿；auto=plan + (有成稿则 audit+finalize)
```
退出码：`0` = 已写出 `result.json`（success 或 partial）；`2` = 输入不可恢复（仍写出 `status=failed` 的 `result.json`）。

单文件也可独立使用：`import introlib` 解析文献库/稿件/引用，`import audit_rules` 单独跑 18 条检查，`import render` 单独渲染参考文献与比较表。

## 5. 关键方法（为什么这样做）

1. **先账后文。** 直接成文时，引用位置由句子节奏决定；先建账则引用位置由"这句话支撑哪条论断"决定。R09 的双向一致检查（正文引的必须进分组、进分组的必须被引）只有账存在时才能做，这是本 Skill 与"让模型写篇综述"最实质的差别。
2. **引用解析走链而不是靠猜。** 数字制 `[n]` → 稿件文末参考文献表第 n 条 → 文献库条目；`\cite{key}`/`[@key]` → 键直查；著者-年份 → 姓+年（含"等/et al."）。每步记录 `resolution` 方法；解析不到的进 `unresolved` 而不是被当成"新文献"凭空造出来。
3. **空白必须带证据。** `evidence.kind=quote` 的引文要做 Unicode NFKC + 去标点的子串比对；比对不上就是 error。这拦住的正是"空白的依据是我编的"。`author_judgment` 是合法选项，但必须显式标。
4. **贡献对照是定位而不是措辞。** `Fig. 3` / `Table 2` / `4.2` / `0.742` 都在脚本建好的稿件索引里逐项解析；索引里没有就是 error。`result` 类证据要么原文逐字命中，要么数字集合被索引包含。
5. **数字可追溯。** 只有"带单位或带小数"的数字会被核对（`11.3%`、`0.742`、`15.4 GPU-hours`），整数与小序号不参与——这一取舍把误报压到很低，代价是漏掉纯整数捏造。
6. **判据保守。** 比较连接词（`however`、`相比之下`）本身不触发 R02；只有"数字 / 文献归属 / 拔高表述"三类高精度信号才触发。宁可漏报，也不要让评审在报告里跟规则吵架。
7. **分块 + 幂等。** 三个阶段各自可重跑；同一输入 + 同一账 + 同一稿 → 同一 `result.json`（除 `generated_at`）。

## 6. 失败与异常处理（必须如实）

| 情况 | 行为 | state |
|---|---|---|
| `case.json` 缺失或字段名不认识 | 从 `task.md` + 材料发现继续；`case_id` 取目录名并记 notes | partial |
| 找不到稿件 | 写 `result.json` 说明；建账仍尽量完成 | failed（plan 后仍可 audit） |
| 文献库为空 | 从文末参考文献表反推（标 `unverified_metadata`）；仍空则引用全部无法核验，`limits` 写明 | partial |
| 引用解析不到 | 进 `unresolved_citations`，正文标记**原样保留**，不补、不改 | partial（R01 error） |
| 空白引文核对不上 | `unverifiable_quote` error；改引文或改 `kind=paraphrase`（后者降级为需人工确认） | partial |
| 稿件是 PDF/docx | 先用 `pdf-text-tool` / `office-*` 转文本再喂入；本 Skill 不解析 PDF 版式 | partial |
| 目标期刊格式未知 | 沿用稿件已有标记样式；没有则中文默认 GB/T 数字制、英文默认 IEEE 数字制；记入 `task.citation_style` 的依据 | success/partial |
| 预算将尽（>780 s 或请求将尽） | 停止新增段落，跑 audit + finalize，以 partial 交付并写 `limits` | partial |
| 账本缺失/格式错 | 对应规则给出"无法核对"的警告而不是假装通过 | partial |

## 7. 适用范围与限制

**适用**：单篇论文的引言与相关工作起草或改写；中文/英文；数字制、著者-年份制、`\cite{}`、`[@key]`；文献库 10–500 条；有文末参考文献表或独立文献库。

**限制（写在 `status.limits` 里，不藏）**：
- **不判断"这段写得好不好"**。规则只判断可核对的项；行文节奏、领域品味、期刊口吻仍需人。
- **不做文献检索**。只用给定材料；文献库覆盖不足时 R05/R06 只能报告"库里有的没被引"，无法报告"库里没有的关键工作"。
- **不解析 PDF 版式**。PDF/docx 需先转文本。
- **不保证 `paraphrase` 型空白证据**。只有 `quote` 能逐字核对；`paraphrase` 与 `author_judgment` 需人工确认。
- **整数捏造查不出来**。数字核对只看带单位/带小数的数值。
- **跨语言引文比对可能失效**。中文文献的英文摘要与引文语言不同时，`quote` 比对会失败——此时应改用 `paraphrase` 并标人工确认。
- **R18 只覆盖摘要里的带单位数值**；摘要没写数值时该规则自动跳过。

## 8. 生态与复用

- `references/` 下六份可单独复用：`ledgers.md`（四本账字段与填写范例）、`grouping.md`（分组维度与比较句式）、`gap-derivation.md`（五种缺口类型的推导与取证）、`contribution-map.md`（贡献↔证据对照与边界写法）、`citation-formats.md`（四种标记识别与 GB/T 7714—2015 / APA 7 / IEEE 渲染规则）、`failure-modes.md`（21 种失败模式 → 触发规则 → 处置 → 残余风险）。
- `examples/` 是最小示例（输入 / 账本 / **示意**输出，明确标为示例，不是正式案例结果）。
- `examples/fixtures/defects.json` 是**可复用的评测题集**：21 条植入缺陷 + 期望命中的 `(规则, 代码)`。任何人改了规则都能用它回归。
- `src/reproduce.py` 一键复现全部自测（见 §9）。

## 9. 自查清单（交付前）

- [ ] `python3 src/reproduce.py` 全绿（当前 28/28 自测项 + 21/21 植入缺陷）
- [ ] `--stage plan` 后 `result.json` 立刻存在且 `state=partial`
- [ ] 干净稿 `gate=pass`、`errors=0`、`warnings=0`；缺陷稿 `gate=fail` 且 21 条全部命中
- [ ] 中文案例 `gate=pass`，`refs_cited.txt` 是 GB/T 7714 形式；英文案例是 IEEE 形式
- [ ] `result.json` 含 `case_id` 与 `output_contract` 全部字段
- [ ] `refs_cited.txt` 编号与正文 `[n]` 一致；`references_used[].number` 与之对应
- [ ] 没有新增材料外的文献、数字、结论；`unresolved_citations` 已列出未核验项

## 10. 文件

```
SKILL.md                        本文件（入口：触发、流程、契约、失败处理、自查）
README.md                       使用与方法说明（安装、调用、方法、范围、限制、维护）
requirements.txt                依赖（标准库，无第三方包）
scripts/run_case.py             入口 CLI：plan / audit / finalize
scripts/introlib.py             解析与模型：材料发现、文献库、稿件索引、草稿、引用解析、账本
scripts/audit_rules.py          18 条确定性核对
scripts/render.py               成稿清洗、比较表、贡献表、参考文献渲染（GB/T · APA · IEEE · BibTeX）
references/ledgers.md           四本账的字段与填写范例
references/grouping.md          分组维度、比较句式、常见拼错
references/gap-derivation.md    五类缺口、取证方式、空白与本文的对应写法
references/contribution-map.md  贡献类型、证据定位、边界与不主张
references/citation-formats.md  标记识别与四种引用格式渲染规则
references/failure-modes.md     21 种失败模式 → 规则 → 处置 → 残余风险
examples/                       最小示例（输入 / 账本 / 示意输出 / 植入缺陷题集）
src/reproduce.py                本地自测：4 个场景、28 项检查、21 条植入缺陷
characterization.json           自测结果表征（明确标注为本地素材，不是隐藏用例得分）
execution/                      自测日志与产物（run.log、results/）
```
