---
name: refmgr-citations
description: 参考文献与引用管理 Skill——对一份真实稿件 + 一份真实文献库做"挂得对 / 编得顺 / 收得净 / 对得上"四件事：识别需来源支撑的论断句并给出引用插入位置；插入/删除/调序后按首次出现重排编号并同步正文、文末列表、图注/附录交叉引用；用可解释判据（DOI / arXiv / 题名 / 作者 / 年份 / 中英题名翻译对）合并重复条目并保留合并依据；在 BibTeX / RIS / CNKI 导出 / JSON 与 GB/T 7714—2015、APA 7 之间转换并补齐字段；离线核验元数据（可选 Crossref DOI 比对）、标出编造/错配条目、逐句生成"论断—引用"核对清单。输出可继续编辑的改稿、同步的文献表、规范化文献库、修改记录和 result.json。触发词："参考文献", "引用", "citation", "去重", "dedup", "编号重排", "renumber", "GB/T 7714", "APA", "BibTeX", "RIS", "CNKI", "核验引用", "文献库整理"。
---

# 参考文献与引用管理（refmgr-citations）

本 Skill 把引用管理拆成**确定性引擎**（脚本，零模型调用、可复现）和**语言判断**（模型，只做两件事：论断句识别、论断↔引用匹配）。核心设计只有一句：

> **一切以稳定 `ref_id` 为键，编号永远是"按正文首次出现顺序"推导出来的结果。** 所以插入、删除、调序之后正文和文末列表不可能不同步。

四件事与题面对应：**挂得对**（引用落在需要支撑的那句话）· **编得顺**（编号连锁更新、双向同步）· **收得净**（去重可解释、不误并）· **对得上**（条目真实、元数据准确、论断与所引文献逐句对应）。

## 0. 硬规则（先读）

1. **输入文件是唯一事实来源。** 读 `/input/case.json`、`/input/task.md`，再读材料和文献库（路径由 case.json 指出；找不到就递归扫描）。不从题目名、领域标签或记忆补造文献、DOI、页码。
2. **不交预制答案。** 每个编号、每条合并、每条核对都由本次运行的脚本 + 模型判断产生。
3. **数字可回溯。** `result.json` 里每条引用记录 `cid / ref_id / 原始标记 / 新标记 / 所在句`；每条合并记录 `signals + score + 被并条目的题名/年份/DOI/来源键`；每处改动进 `changes.json`。
4. **不确定就标注，不猜。** 解析不到的引用、评分带内的合并对、库中缺失的条目、字段缺失——分别进 `unresolved / needs_review / not_in_library / missing_field`，状态为 `partial`。
5. **预算。** 64 次模型请求 / 900 s。脚本阶段不耗请求。先跑脚本写出 `result.json`（早期保存，状态 partial），再用模型补"论断—引用"判断，最后重跑一次脚本把判断合并进去。
6. **不改事实。** 只改引用标记、编号、文献表格式；不动正文论断、数字、术语（除非任务明确要求改写）。

## 1. 输入与输出契约

### 1.1 输入（Harbor 约定，格式容错）

| 路径 | 内容 | 必需 |
|---|---|---|
| `/input/case.json` | `case_id`、材料路径、`output_contract`、任务描述（字段名可能是 `task` / `instruction` / `prompt`） | 否（缺则 `case_id: "unknown"`） |
| `/input/task.md` | 任务说明：要做什么、目标规范（GB/T 7714—2015 / APA 7 / …）、受众、文体 | 是 |
| 稿件 | `.md` / `.txt` / `.docx`，含正文与（通常）文末参考文献表；标记样式自动识别 | 是 |
| 文献库 | `.bib` / `.ris` / `.json` / `.csv` / CNKI 等 `字段: 值` 文本；可多个 | 否（缺则从稿件文末表反向构建） |

**先读 `case.json` 的 `output_contract`**：若它列出的字段与 §6 不同，以 case.json 为准——把本 Skill 的结构块放到同名或最接近的字段下，其余作为附加字段保留。`result.json` 必须含 `case_id` 与 `output_contract` 全部字段。

### 1.2 输出（`/app/output`）

| 文件 | 内容 |
|---|---|
| `result.json` | **主结果**：状态、输入标识、去重/编号/转换/核验/论断核对五个结构块、人工确认项、变更记录、环境 |
| `manuscript_revised.md` | 可继续编辑的改稿（编号已重排、标记样式统一、文末列表重建） |
| `references_gbt7714.txt`（或 `_apa7` / `.bib` / `.ris`） | 同步的文献表，目标规范 |
| `library_canonical.json` | 去重后的规范化文献库（每条含 `merged_from` + `merge_basis`） |
| `citation_map.json` | 每个引用点：位置、原标记、解析到的 `ref_id`、所在句、锚点类型 |
| `changes.json` | 稿件 diff、标记改写列表、合并记录 |

工作目录 `/app/work/`：`snapshots/` 保存输入快照（稿件 + 文献库原文件），用于回溯。

## 2. 工作流（六步）

### Step 1 — 读入与识别（脚本）

```bash
python scripts/run_case.py --input /input --out /app/output --task "<动作列表>"   # 见 §3
```

脚本自动：发现文件 → 解析稿件（章节、引用标记、文末表）→ 解析文献库 → 解析每个引用到 `ref_id`（数字→文末表条目→库匹配；citekey→库键；著者-年份→作者+年份）→ **写出早期 `result.json`**。

日志（stderr）会打印：`manuscript: N chars, citations=K, style=…`、`library X: N entries (format)`、`resolved …, unresolved …`、`reflist item [n] has no library match → U00n (flagged)`。**读这段日志**决定下一步重点。

### Step 2 — 判断任务要求的动作（模型，1 次请求）

读 `task.md`，映射到六类动作。`run_case.py` 已按关键词预判（`actions` 字段），核对并修正：

| 任务措辞 | 动作 | 脚本参数 |
|---|---|---|
| 补引用 / 插入 / 哪些句子需要来源 / 挂得对 | `insert` | 由模型产出 `insertions.json`（Step 4） |
| 重排 / 编号 / 删除后 / 调序 / 同步 / 编得顺 | `renumber` | `--task renumber` |
| 去重 / 归并 / 重复 / 中英文题名 / 预印本 vs 正式版 / 收得净 | `dedup` | `--task dedup --translations translations.json` |
| 转换 / 格式 / GB/T 7714 / APA / BibTeX / RIS / CNKI | `convert` | `--task convert:gbt7714`（或 `apa7` / `bibtex` / `ris`） |
| 核验 / DOI / 真实性 / 编造 / 元数据 / 对得上 | `verify` | `--task verify [--online]` |
| 一致性 / 论断与所引 / 逐句 / 匹配 | `consistency` | 由模型产出 `claim_matches.json`（Step 5） |

目标规范：任务写了就按任务（GB/T 7714—2015 顺序编码制 / APA 7 / IEEE / Vancouver）；没写则沿用稿件原有标记样式；再没有默认 GB/T 7714 数字制。`result.target_style` 记录最终选择及依据。

### Step 3 — 翻译对（模型，仅当任务涉及去重且有中英混排库）

扫描库中"一条中文题名、一条英文题名、作者/年份相近"的候选对，由模型判断是否同一篇的翻译，写成 `translations.json`：

```json
[["基于注意力机制的中文文本分类研究", "Chinese Text Classification Based on Attention Mechanism"]]
```

没有把握的对**不要写进去**——写入即视为"题名等价"的强证据。写完重跑 Step 1 并加 `--translations translations.json`。

### Step 4 — 引用插入与定位（模型，仅当动作含 `insert`）

输入：`citation_map.json` + 去掉已有引用的正文。模型逐段找出**需要来源支撑的论断句**（具体事实、数字、他人观点、方法来源、比较结论），并为每句从库中选条目：

```json
[{"paragraph": 3, "sentence": "深度学习方法在诸多领域取得了突破。",
  "anchor": "sentence-end",              // sentence-end | mid-sentence | after-claim
  "ref_keys": ["lecun2015"],              // 库键或 ref_id
  "form": "numeric",                      // numeric | author-year | footnote
  "why": "该句为综述性论断，LeCun 2015 为深度学习综述", "confidence": "high"}]
```

**位置规则（挂得对）**：① 标记放在**它所支撑的那个论断句**的句末标点前（数字制）/ 括号紧随论断（著者-年份制），不放整段末尾；② 一句多引合成一个标记 `[3,4]`（GB/T）或 `(A, 2020; B, 2021)`；③ 多句一引：若连续多句都只依赖同一文献且无其他来源，可在首句引用并在后续句用"同上"/不重复——但若中间插入了其他文献的论断，必须重新引用；④ 图表注里的引用只在图注本身需要来源时保留，不作为正文论断的引用；⑤ 脚注制：脚注编号与文献表独立，脚本不处理，模型需在 `insertions.json` 中用 `form: footnote` 并输出脚注文本。

把 `insertions.json` 交给脚本（`run_case.py --insertions insertions.json`）：脚本在 `anchor` 位置插入占位标记 `\cite{key}` 并立即进入 Step 6 重排。**插入位置由模型决定，编号由脚本决定。**

### Step 5 — 论断↔引用一致性（模型，仅当动作含 `consistency`）

读 `result.claim_citation.pairs`（每个引用点一条：`cid, ref_id, claim 句, ref_title, ref_year, ref_abstract, ref_keywords`）。对每条给出判定：

| verdict | 含义 | 何时用 |
|---|---|---|
| `supports` | 所引文献的主题/结论支持该论断 | 有摘要/关键词佐证，或题名与论断主题明确一致 |
| `mismatch` | 文献真实存在但与论断不对应 | 题名/主题明显不符 |
| `insufficient` | 证据不足，无法判定 | 库中只有题名、无论断所需的细节；或论断含库中文献未报告的具体数字 |
| `not_in_library` | 引用指向库中不存在的条目 | 脚本已标 `U00n` |

写成 `claim_matches.json`：`[{"cid": "C003", "ref_id": "R002", "verdict": "supports", "basis": "BERT 论文（NAACL 2019）提出预训练双向 Transformer，与句中'预训练模型'论断一致"}]`。`basis` 必须能**逐句说清**——这是"对得上"评分的直接证据。**不要给 `insufficient` 的句子硬凑 `supports`。**

### Step 6 — 重跑脚本，合并判断（脚本）

```bash
python scripts/run_case.py --input /input --out /app/output \
  --task "insert+renumber+dedup+convert:gbt7714+verify+consistency" \
  --translations translations.json --insertions insertions.json --claim-matches claim_matches.json
```

脚本重跑全流程、把模型判断合并进 `result.json`、重算状态。重复运行结果**幂等**（同一输入 + 同一判断 → 同一输出）。

## 3. `run_case.py` 参数

```
--input DIR            Harbor 输入目录（递归发现 case.json / task.md / 稿件 / 文献库）
--manuscript FILE      直接指定稿件（跳过发现）
--library FILE         直接指定文献库，可重复
--task TEXT            任务文本 或 动作列表 "a+b+c:style"；动作 = insert|renumber|dedup|convert|verify|consistency
--translations FILE    翻译对 JSON（Step 3）
--insertions FILE      插入位置 JSON（Step 4）
--claim-matches FILE   论断判定 JSON（Step 5）
--online               允许请求 api.crossref.org 比对 DOI（默认离线；任何失败自动降级为离线）
--out DIR / --work DIR 输出 / 工作目录（默认 /app/output、/app/work；非 Harbor 环境回退到 out/../work）
```

退出码：`0` = 已写出 result.json（success 或 partial）；`2` = 输入不可恢复（仍写出 status=failed 的 result.json）。

## 4. 关键方法（为什么这样做）

### 4.1 编号是推导量，不是存储量（编得顺）
`refmgr.resolve_citations` 把每个标记解析到 `ref_id`；`engines.renumber` 按**正文首次出现顺序**（排除文末表）生成 `numbering`，再统一改写正文标记、重建文末表。插入/删除/调序只需重跑，不会出现"列表有 7 条正文只引 6 条"。图注/附录中的 `数据来源[2]`、`引自[1]` 一并改写（它们也是正文标记）。未被引用的条目**追加到表尾**并列入 `uncited`，不静默丢弃。

### 4.2 去重是规则表 + 证据账本（收得净）
`engines.dedupe` 对每对条目计算信号并加权：`doi_exact 5 · arxiv_exact 4.5 · title_exact 3 · title_translated 2 · title_similar 1.5·r · authors_overlap 1·ratio · authors_same_first 1 · year_same 0.5 · year_close 0.3 · venue_same 0.5 · volume_pages_same 1`。**≥5 合并，3–5 进人工复核，<3 分开**；硬阻断：不同 DOI 且题名不近似、题名明显不同、同作者同年不同题名。跨语言题名只有在给定翻译对 + 一个佐证信号时才合并。合并后保留**最早 ref_id** 为规范 id，`merged_from` 记录被并条目，`merge_basis` 逐条写明信号。规范记录优先取"正式发表版 > 预印本"，缺字段从被并条目补齐（不覆盖非空）。中文姓名与拼音姓的桥接用 `references/surnames_zh_en.json`，**只作提示，权重减半，必须配合其他信号**。

### 4.3 格式转换保留关键字段（格式转换与字段补齐）
`refmgr.Entry` 是规范模型；BibTeX / RIS / JSON / CNKI 导入到模型，再渲染为 GB/T 7714—2015、APA 7、BibTeX、RIS。字段映射表见 `references/format-map.md`。DOI / 卷期页 / 文献类型标识（`[J] [C] [M] [D] [R] [EB/OL] …`）/ ISBN / ISSN / arXiv id 全程保留；中英文混排按条目语言分别用全角/半角标点；中文作者写全名，西文作者"姓 + 首字母缩写"（GB/T）或"姓, 首字母."（APA）。

### 4.4 核验分层（对得上）
离线：DOI 形式、年份范围、页码含数字、URL 协议、必填字段缺失、稿件引用但库中不存在（`not_in_library` → error）。在线（`--online`）：Crossref 比对题名/刊名/年份/卷/作者，不一致记 `crossref_mismatch`。编造条目的典型信号：库中无、DOI 无法解析、年份越界、作者缺失——全部标出，不删除。

## 5. 失败与异常处理

| 情形 | 行为 | 状态 |
|---|---|---|
| `/input/case.json` 缺失 | 从 task.md + 文件发现继续；`case_id` 取目录名或 `unknown` | partial |
| 找不到稿件 | 写 result.json 说明 | failed (exit 2) |
| 文献库缺失/格式未知 | 从稿件文末表反向构建库（每条标 `fallback-reflist`），日志 WARN | partial |
| 稿件格式不支持（如 PDF） | 若环境有 pdf 工具则先转文本再跑；否则 failed 并说明 | failed/partial |
| docx 损坏 | 捕获异常 → 尝试解压读 `word/document.xml`；仍失败 → failed | failed |
| 引用解析不到（数字超出表长、citekey 不在库、作者年份无匹配） | 进 `unresolved`，正文标记**原样保留**，列表不补 | partial |
| 文末表条目在库中无匹配 | 作为 `U00n` 条目保留进输出列表并标 `⚠ 未在文献库中找到对应条目`，verify error | partial |
| 去重评分在复核带 | 不合并，进 `needs_review` 列出信号，交人确认 | success/partial |
| 编号冲突（同一数字对应多条） | 以文末表顺序为准，记录 warning | partial |
| DOI 解析失败 / 网络不通 | 降级为离线核验，`verification.online = null`，不中断 | success/partial |
| 同名作者不同文献 | `same_author_same_year_different_title` 阻断，绝不合并 | — |
| 预算接近耗尽 | 停止模型步骤；用已有 judgments 重跑脚本；status=partial 并写明未完成项 | partial |

## 6. `result.json` 结构

```json
{
  "case_id": "…", "status": "success | partial | failed", "status_reason": "…", "generated_at": "ISO-8601",
  "inputs": {"manuscript": "…", "libraries": [{"path","format","n"}], "task_excerpt": "…"},
  "actions": ["renumber","dedup",…], "target_style": {"citation": "numeric|author-year", "label": "gbt|apa7|ieee|bibtex|ris"},
  "dedup": {"stats": {"input","output","merged"}, "merge_log": [{"canonical","merged","basis":[{signals,score,title,year,doi,type,source_key}]}],
            "needs_review": [{"a","b","signals","score","blockers"}]},
  "renumber": {"order": ["R003","R001",…], "numbering": {"R003":1,…}, "edits": [{"cid","before","after","ref_ids","numbers"}],
               "uncited": [...], "unresolved": [{"cid","keys","raw"}]},
  "consistency": {"issues": [{"kind","detail","severity"}], "anchor_positions": {"sentence-end":n,"mid-sentence":n,"paragraph-end":n,"caption":n},
                 "crossrefs_in_captions": [...], "multi_citation_count": n},
  "conversion": {"style": "gbt7714", "items": [{"n","ref_id","text","entry"}], "field_report": [{"ref_id","missing","type","language"}]},
  "verification": {"entries": [{"ref_id","status","problems":[{"field","issue","severity",…}],"fabrication_risk"}],
                   "summary": {"n","errors","warnings","verified","mismatch","unverified"}},
  "claim_citation": {"pairs": [{"cid","ref_id","claim","anchor","ref_title","ref_year","verdict","basis"}],
                     "pending": n, "supported": n, "mismatch": n, "insufficient_evidence": n},
  "insertions": [...],                       // 仅当做了 insert
  "human_review": [...], "uncertainties": [...],
  "change_log": [{"step","what"}], "artifacts": {...}, "stats": {...}, "environment": {...}, "log": [...]
}
```

状态判定：有 `unresolved` 或 verify `error` → partial；有 `claim_citation.pending`（模型未提供判断）→ partial；否则 success。**partial 必须在 `status_reason` 里写明限制。**

## 7. 自查清单（交付前）

- [ ] `result.json` 含 `case_id` 与 `output_contract` 全部字段；status 与内容一致
- [ ] 重排后：正文编号集合 = {1..N} 连续（或 gaps 已在 `consistency.issues` 说明），文末表条数 = 编号数，`uncited` 已列出
- [ ] 每条合并都有 `signals` + `score` + 被并条目题名；复核带的对没被合并
- [ ] 所有 `U00n` 条目在列表中可见且带 ⚠ 标记；`verification.errors` 与之对应
- [ ] `claim_citation.pairs` 每条 `verdict` ≠ pending（或 pending 数已在 status_reason 说明）；`mismatch`/`insufficient` 的句子在 `human_review` 中
- [ ] 文献表格式符合目标规范：GB/T 有 `[J]/[C]/[M]…` 类型标识、`DOI:`；APA 有斜体刊名、`https://doi.org/`
- [ ] `changes.json` 的 marker_edits 与 `renumber.edits` 一致；`snapshots/` 有输入原件
- [ ] 没有新增材料外的事实；没有改动正文论断、数字

## 8. 最小调用示例（示例，非正式案例结果）

输入：`input/manuscript.md`（含 `[3]…[1]…[2,4]` 乱序引用、一条编造的 `[7]`）、`input/library.bib`（6 条，含 Brown 2020 正式版与 arXiv 版重复）、`input/task.md`（去重 + 重排 + GB/T 7714 + 核验）。

```bash
python scripts/run_case.py --input input --out output --task "renumber+dedup+convert:gbt7714+verify"
```

示意输出（节选）：

```
dedup: {'input': 7, 'output': 6, 'merged': 1}
renumber: order R003→1, R001→2, R002→3, R004→4, R005→5, U007→6 ; 9 marker edits
verify: errors=1 (U007 not_in_library) warnings=3 (missing volume/pages)
status=partial
```

改稿中 `[3]…[1]…[2,4]` → `[1]…[2]…[3,4]`，文末表按新序重建为 GB/T 7714，`U007` 行尾带 `⚠ 未在文献库中找到对应条目，需人工核验`。完整示例见 `examples/`。

## 9. 适用范围与限制

- **适用**：数字顺序编码制、著者—出版年制、citekey/pandoc/LaTeX `\cite` 稿件；中英文混排库；BibTeX/RIS/JSON/CSV/CNKI 风格导出。
- **限制**：脚注制引用只定位不排版；PDF 稿件需先转文本；在线核验依赖 Crossref（中文 DOI 覆盖有限）；去重的跨语言合并依赖翻译对；"论断是否被文献支持"最终是模型判断，脚本只负责把证据摆到一起并强制写 `basis`。
- **依赖**：Python ≥ 3.8 标准库，无第三方包。资源文件：`references/surnames_zh_en.json`（拼音姓氏提示表）。

参考文档：`references/rules.md`（引用位置与形式规则、去重判据细则）、`references/format-map.md`（字段映射与 GB/T 7714—2015 / APA 7 渲染规则）、`references/failure-modes.md`（已知失败模式与处置）。
