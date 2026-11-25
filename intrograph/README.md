# intrograph — 引言与相关工作写作 Skill

> 先建四本可核对的账（引用 / 分组 / 空白 / 贡献-证据），再据此成文，最后用 **18 项确定性核对**逐条拦截：
> 编造引用、无来源论断、逐篇摘要拼接、无出处空白、无证据贡献、为写作补数字。

Playground「写作08｜引言与相关工作写作」参赛作品。对应题面四个问题：

| 题面问题 | 本 Skill 的回答 | 落点 |
|---|---|---|
| **立得住** | 背景必须指向具体技术约束；空转句式被点名 | R16、R02、R06 |
| **分得清** | 分组账强制五字段同维度 + 取舍结论；逐篇拼接可识别 | R07、R08、R09 |
| **说得实** | 空白必须带已引文献与可核对证据；作者判断必须标注 | R10、R11、R02 |
| **对得上** | 贡献必须定位到真实图/表/节/结果；数字可溯源 | R12、R13、R18、R01、R04 |

---

## 1. 快速开始

### 环境
- Python ≥ 3.8，**只用标准库**，无第三方包
- 无网络依赖（不查 Crossref，不做在线核验）

```bash
python3 --version          # 3.8+
python3 scripts/run_case.py --version    # 打印 1.0.0 即可
```

### 三个阶段

```bash
# 1) 建账：读材料 → 文献库 + 稿件索引 + 写作脚手架 + 账本模板 + 早期 partial result.json
python3 scripts/run_case.py --input /input --out /app/output --work /app/work --stage plan

# 2) （模型）填 work/ledgers/ledger_*.json，再按 work/scaffold.md 写 work/draft.md

# 3) 核对（可反复跑）
python3 scripts/run_case.py --input /input --out /app/output --work /app/work --stage audit

# 4) 定稿
python3 scripts/run_case.py --input /input --out /app/output --work /app/work --stage finalize
```

一条命令跑完全流程（有成稿时）：`--stage auto`。

### 产出

```
/app/output/
├── result.json                    契约输出：case_id + output_contract 全部字段 + 状态/四部分/引用映射/核对汇总
├── introduction_related_work.md   可直接进稿的四部分正文（标记已剥离）
├── related_work_table.md          分组比较表：每行一篇，六列同维度 + 每组取舍
├── contribution_table.md          贡献↔证据对照表（含"不主张"）
├── audit_report.json / .md        18 条规则逐条结果 + 按四个问题汇总 + must_fix
├── citation_map.json              每个引用点：部分/段/句、原始标记、解析到的 ref_id
├── refs_cited.bib / .txt          只含正文实际引用的文献，按正文编号排序
└── ledger_*.json                  四本账副本（供复核分组依据/空白推导/贡献对照）
```

---

## 2. 它到底做了什么（与"让模型写篇综述"的差别）

### 2.1 先账后文

直接成文时，引用位置由句子节奏决定；先建账时，引用位置由"这句话支撑哪条论断"决定。

```
ledger_refs  ──►  ledger_groups  ──►  ledger_gaps  ──►  ledger_contributions
 (角色/分组)      (五字段+取舍)        (已引文献+证据)      (证据定位)
                       │                    │                    │
                       ▼                    ▼                    ▼
                   相关工作正文          研究空白正文          主要贡献正文
```

### 2.2 18 项确定性核对（0 次模型调用）

| 问题 | 规则 |
|---|---|
| 对得上 | R01 引用真实 · R04 元数据 · R12 贡献↔证据 · R13 数字溯源 · R17 格式一致 · R18 摘要数值覆盖 |
| 说得实 | R02 无来源论断 · R03 引用位置 · R05 必引覆盖 · R10 空白出处 · R11 空白对接 |
| 分得清 | R07 分组完整 · R08 逐篇拼接 · R09 分组双向一致 |
| 立得住 | R14 四部分结构 · R15 拔高边界 · R16 空转背景 |

完整清单与处置见 [`references/failure-modes.md`](references/failure-modes.md)。

### 2.3 引用解析走链，不靠猜

```
[n]  ──► 稿件文末参考文献表第 n 条 ──► 文献库条目   (resolution: manuscript_reflist)
\cite{key} / [@key]  ──► 键直查文献库              (resolution: citekey)
(Smith, 2020)  ──► 姓 + 年（支持"等/et al."）      (resolution: author-year)
```
解析不到 → `uncertainty.unresolved_citations`，正文标记原样保留，R01 报 error。**不会为了"让稿子看起来完整"而补一个引用。**

### 2.4 空白证据做逐字比对

`evidence.kind=quote` 的引文，做 Unicode NFKC + 去标点后的子串比对；找不到 → `unverifiable_quote` error。这一条拦住的正是"空白的依据是我编的"。

### 2.5 贡献对照是定位，不是措辞

`Fig. 3` / `Table 2` / `4.2` / `0.742` 全部在脚本建好的稿件索引里逐项解析。索引里没有 → error。`result` 类证据要么原文逐字命中，要么数字集合被索引包含。

### 2.6 编号一致性

数字制下，文末列表编号 = 正文编号，**不是发现顺序**。`result.result.reference_numbering` 给出 `ref_id → number`，可逐条核对。这一处错了整篇文献表都错位，所以自测里单列一条检查。

---

## 3. 方法：为什么这些判据可信

| 设计选择 | 理由 |
|---|---|
| 只把"数字 / 文献归属 / 拔高表述"作为无来源论断的触发信号 | 比较连接词（`however`、`相比之下`）几乎出现在每段好文章里，作为触发会淹没报告 |
| 数字核对只覆盖"带单位或带小数"的数值 | 整数（"3 类方法"、序号）误报率高；这一取舍换取报告可读性，代价是漏掉整数捏造，已在 `failure-modes.md` 写明 |
| `quote` 才自动核，`paraphrase` / `author_judgment` 进人工确认 | 转述没有唯一正确文本，自动判定会产生假阳性 |
| 分组双向往返检查（引了必须分组、分组必须引） | 这是"分组账"存在的意义；只查单向会留下孤立引用 |
| 逐篇拼接只在"整段无任何比较词"时触发 | 正常学术写作本就一句一引，贸然判定会把好稿判坏 |
| 三个阶段各自可重跑且幂等 | 预算内可反复 audit，除 `generated_at` 外同输入同输出 |

---

## 4. 适用范围与限制

**适用**：单篇论文的引言与相关工作起草或改写；中文 / 英文；数字制、著者-年份制、`\cite{}`、`[@key]`；文献库 10–500 条；有文末参考文献表或独立文献库；学科不限（化学、材料、生物、计算机、社科皆可，规则不依赖领域词汇）。

**限制**（同时写进 `result.json.status.limits`）：
- 不判断文笔好坏、期刊口吻、领域品味。
- 不做文献检索：只核"库里有的被没被引"，不核"库里该有的有没有"。
- 不解析 PDF 版式：PDF/docx 需先转文本（`pdf-text-tool` / `office-*`）。
- 整数捏造查不出（数字核对只覆盖带单位/带小数的值）。
- `paraphrase` 型证据不自动核，进人工确认。
- 跨语言引文（中文文献配英文摘要）在 `quote` 模式下会比对失败，应改用 `paraphrase`。
- 脚注制引用只定位不排版。

---

## 5. 最小调用示例（**示例**，非正式案例结果）

见 [`examples/README.md`](examples/README.md)：一个虚构的分子预训练论文（稿件 + 10 条文献库）→ `case.json` → 三条命令 → 示意输出片段。示例输出在 `execution/results/clean_en/`，明确标注为示例。

---

## 6. 本地自测（可复现的证据）

```bash
python3 src/reproduce.py           # 写 execution/results/ 并追加 execution/run.log
```

四个场景，全部用与评测相同的入口 `scripts/run_case.py`：

| 场景 | 断言 | 当前结果 |
|---|---|---|
| 干净英文稿 | gate=pass、0 error、0 warning、四个产物齐全、契约字段齐全 | **9/9** |
| 植入 21 条缺陷 | gate=fail，21 条 `(规则, 代码)` 全部命中 | **21/21** |
| 中文稿 | gate=pass、CJK 识别、GB/T 7714 渲染 | **9/9** |
| 无文献库 | 诚实降级：编造引用被标记、`limits` 写明 library empty | **6/6** |

合计 **28/28 自测项 + 21/21 植入缺陷**。`characterization.json` 里的数字全部来自这次自测，**不是**隐藏用例的得分。

---

## 7. 目录

```
SKILL.md                        入口：触发条件、六步流程、契约、失败处理、自查
README.md                       本文件
requirements.txt                依赖（标准库，无第三方包）
scripts/run_case.py             CLI：plan / audit / finalize
scripts/introlib.py             材料发现、文献库解析去重、稿件索引、草稿解析、引用解析、账本模型
scripts/audit_rules.py          18 条确定性核对
scripts/render.py               成稿清洗、比较表、贡献表、参考文献渲染（GB/T · APA · IEEE · BibTeX）
references/ledgers.md           四本账字段与填写范例
references/grouping.md          五种比较维度、组内五字段写法、逐篇拼接的四种形状
references/gap-derivation.md    六类缺口、三种取证、四步写法、置信度
references/contribution-map.md  六种贡献类型、五种定位、三条撰写规则
references/citation-formats.md  四种标记识别、三种解析方法、四种渲染格式
references/failure-modes.md     21 种失败模式 + 环境类失败 + 已知盲区
examples/README.md              最小示例说明（标明为示例）
examples/input/                 示例输入：case.json / task.md / manuscript.md / library.bib / notes.md
examples/ledgers/               示例账本（模型判断的示意结果）
examples/fixtures/              干净稿、缺陷稿、缺陷账本、植入缺陷题集
src/reproduce.py                本地自测：4 场景 / 28 项 / 21 条植入缺陷
characterization.json           自测结果表征（明确标注为本地素材）
execution/run.log               自测日志
execution/results/              自测产物（clean_en / defective / zh / no_library）
```

---

## 8. 维护

- **版本**：`1.0.0`（`scripts/run_case.py --version`）。
- **改规则的流程**：改 `scripts/audit_rules.py` → `python3 src/reproduce.py` → 必须仍是 28/28 与 21/21；新增规则要同时加进 `examples/fixtures/defects.json` 与 `references/failure-modes.md`。
- **改渲染的流程**：改 `scripts/render.py` → 检查 `execution/results/clean_en/refs_cited.txt`（IEEE）与 `.../zh/refs_cited.txt`（GB/T），以及 `result.result.reference_numbering` 与正文编号是否仍一致。
- **资源上限**：Skill 资源 ≤50 个 UTF-8 文本文件、单文件 ≤500KB、合计 ≤2MB、无符号链接。`_work/` 不进包。
- **公开镜像**：建议把本目录镜像到一个公开仓库，便于别人下载试用；本包不依赖任何外部 URL。
