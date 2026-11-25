# 失败模式清单：缺陷 → 触发规则 → 处置 → 残余风险

下表按题面四个问题分组，共 **41 种情形**（其中 8 种属于运行环境而非内容错误）。**21 条已植入 fixtures** 形成回归题集：`examples/fixtures/defects.json` 逐条给出植入方式与期望命中的 `(规则, 代码)`，`python3 src/reproduce.py` 会跑一遍并断言 21 条全部命中、干净稿 0 error / 0 warning。

## A. 对得上（引用与元数据）

| # | 失败模式 | 触发 | 处置 | 残余风险 |
|---|---|---|---|---|
| A1 | 编造引用：`\cite{}` 的键不在文献库，摘要里"有文献支持"实际不存在 | R01 `invented_citation`（error） | 删掉该引用，或换成库里真实存在的键 | 键存在但内容是另一篇（张冠李戴）规则查不出 |
| A2 | 元数据错误：DOI 形式非法、缺年份/作者/刊名、页码不可信、年份越界 | R04 `metadata_bad_doi` / `metadata_incomplete` / `metadata_bad_pages` / `metadata_year_range`（warn） | 回到文献库修正；来自文末表的条目会标 `unverified_metadata` | 字段齐全但值错误（作者顺序、卷期错）需人工比对原刊 |
| A3 | 引用位置漂移：段落前几句下论断，引用堆在段末 | R03 `citation_anchor_drift`（warn） | 把标记移到它支撑的那一句句末 | 一句多引时"哪个标记支撑哪半句"仍需人判断 |
| A4 | 引用解析歧义：同姓同年多条，或数字制无文末表只能按库序猜 | R01 `ambiguous_citation`（warn）+ `unresolved_citations` | 换成 citekey 形式，或补齐文末参考文献表 | `library_order` 解析可能整表错位，规则只能标记无法纠正 |
| A5 | 引用格式混用：数字制与 `\cite{}` 混排 | R17 `mixed_citation_style`（warn） | 统一成目标格式 | 目标格式未知时按语言兜底，可能与期刊要求不同 |
| A6 | 为写作补出材料里没有的数值 | R13 `invented_metric`（error） | 改回稿件里的值，或删掉数值改定性表述 | **整数捏造查不出**（只核带单位/带小数的数值） |
| A7 | 摘要关键结果没进贡献列表 | R18 `abstract_metric_unclaimed`（warn） | 写进某条贡献的 `text` 或 `claim_in_source` | 摘要无数值时该规则自动跳过 |
| A8 | 文献表编号与正文编号错位 | 自测检查 `refs_cited` 编号 | 由脚本按正文编号排序渲染 | citekey-only 文献的续编号位置可能与期刊习惯不同 |

## B. 说得实（论断与空白）

| # | 失败模式 | 触发 | 处置 | 残余风险 |
|---|---|---|---|---|
| B1 | 无来源论断：文献类断言既无引用也无作者判断标注 | R02 `uncited_claim`（warn） | 补引用，或改写成"本文认为…" | 判据只看三类高精度信号；"A 优于 B"这类纯比较句可能漏掉 |
| B2 | 空白不是由已引文献推出：来源文献正文里根本没引 | R10 `gap_from_uncited_work`（error） | 先在相关工作里引它，再推空白 | 引了但引错位置（不在相关工作里）规则不区分段落语义 |
| B3 | 空白依据的引文在来源里找不到 | R10 `unverifiable_quote`（error） | 改成摘要里逐字存在的句子，或改 `kind=paraphrase` 并标人工确认 | `paraphrase` / `author_judgment` 不做自动核对 |
| B4 | 空白无出处（没有 `derived_from`） | R10 `gap_without_source`（error） | 补来源文献与缺口类型 | — |
| B5 | 空白指向不存在的贡献 | R11 `gap_maps_unknown_contribution`（error） | 改成贡献账里真实存在的 `contribution_id` | — |
| B6 | 有空白账但成稿没有空白段落 | R11 `gap_part_empty`（error） | 写出研究空白部分 | — |
| B7 | 空白段落与本文工作断链（没有"本文/we"） | R11 `gap_not_linked_to_own_work`（warn） | 补一句"本文把 X 当作决策变量…" | — |
| B8 | 标为必须引用的文献没引 | R05 `must_cite_missing`（error） | 补引，或把它从 `must_cite` 撤下 | 库里没有的关键工作无法被查出来（无检索能力） |
| B9 | 近期进展缺失 | R06 `recent_progress_missing`（warn） | 补引近三年条目 | 以文献库最新年份为窗口，库本身偏旧时窗口也偏旧 |
| B10 | 无条件拔高表述 | R15 `unbounded_novelty_claim`（warn） | 在 `scope.stated_limits` 写清适用范围 | "首次"是否真实成立需领域知识判断 |

## C. 立得住 / 分得清（背景与分组）

| # | 失败模式 | 触发 | 处置 | 残余风险 |
|---|---|---|---|---|
| C1 | 空转铺垫："has attracted widespread attention""随着…的快速发展" | R16 `vacuous_background`（warn） | 换成具体技术约束：谁卡在哪一步、代价是什么 | 只匹配已知句式；新变体可能漏 |
| C2 | 背景整段无引用却含多处论断 | R16 `background_paragraph_unsourced`（warn） | 每段至少一个引用 | 通用常识段会被误判，可改写成不断言的过渡句 |
| C3 | 逐篇摘要拼接：连续 ≥3 段各讲一篇且无比较词 | R08 `serial_summary_pattern` / `sentence_serial_summary`（warn） | 按 `grouping.md` 重写成同维度比较 | 段内比较词存在即免除；"假装比较"（堆词不比较）仍需人看 |
| C4 | 相关工作通篇无横向比较 | R08 `no_cross_work_comparison`（warn） | 至少一段同时讨论 ≥2 篇 | — |
| C5 | 分组没有比较维度 | R07 `group_no_dimension`（error） | 写 `dimension`：问题/方法/数据评价/代价/理论保证 | 维度写了但选错（按年份分组）需人判断 |
| C6 | 分组没有取舍结论 | R07 `group_no_tradeoff`（error） | 写 `comparison.tradeoff`，回答"只选一篇选哪篇" | — |
| C7 | 组内条目缺比较字段 | R07 `group_work_field_missing`（warn） | 补齐五字段 | 字段写了但内容空泛（"效果更好"）规则不过滤 |
| C8 | 组内只有一篇 | R07 `group_too_small`（warn） | 并入相邻组，或写 `single_work_reason` | — |
| C9 | 正文引了但没进分组 | R09 `cited_but_ungrouped`（error） | 放进某组，或从正文删掉 | — |
| C10 | 进了分组但正文没引 | R09 `grouped_but_uncited`（warn） | 补引，或从分组删掉 | — |

## D. 结构与契约

| # | 失败模式 | 触发 | 处置 | 残余风险 |
|---|---|---|---|---|
| D1 | 四部分不全 | R14 `part_missing`（error） | 补齐 `<!-- part:xxx -->` 段 | — |
| D2 | 没有分部标记也没有可识别小标题 | R14 `structure_not_detected`（error） | 用 `work/scaffold.md` 的骨架 | 改写任务若原稿无小标题，需先加标记 |
| D3 | 相关工作只有一段 | R14 `related_work_too_thin`（warn） | 按组分段 | — |
| D4 | `output_contract` 字段缺失 | `inputs.contract_filling.unfilled` 非空 | 按 §3.3 补齐或走同义词映射 | 同义词表未覆盖的自定义字段会填空值 |
| D5 | 成稿残留 HTML 注释 | 自测检查 `no_html_comment_left` | `finalize` 会剥掉全部注释 | — |

## E. 运行环境类（不是内容错误）

| # | 情况 | 行为 |
|---|---|---|
| E1 | `/input/case.json` 缺失或字段名不认识 | 从 `task.md` + 材料发现继续；`case_id` 取目录名并记 `notes`；state=partial |
| E2 | 找不到稿件 | 写 `status=failed` 并说明；引用与贡献核对无法进行，`limits` 写明 |
| E3 | 文献库为空且无文末参考文献表 | 引用全部无法核验，R01 全报 `invented_citation`；`limits` 写明"library empty" |
| E4 | 文献库为空但有文末参考文献表 | 反推建库，条目标 `unverified_metadata`；R04 报元数据警告 |
| E5 | 稿件是 PDF / docx | 先用 `pdf-text-tool` / `office-*` 转文本；本 Skill 不解析版式 |
| E6 | 目标期刊格式未知 | 按语言兜底（中文 GB/T、英文 IEEE），依据写入 `task.citation_style` 与 `log` |
| E7 | 预算将尽 | 停止新增段落，跑 audit + finalize，以 `partial` 交付并写 `limits` |
| E8 | 账本缺失/JSON 损坏 | 对应规则给出"无法核对"的警告，不假装通过；`uncertainty.notes` 记文件名 |

## 已知盲区（写在前面，避免误信）

1. **不判断文笔**：句子好坏、期刊口吻、领域品味不在规则范围内。
2. **不做文献检索**：只核"库里有的被没被引"，不核"库里该有的有没有"。
3. **整数捏造查不出**：数字核对只覆盖带单位/带小数的值。
4. **`paraphrase` 不自动核**：转述型证据一律进人工确认。
5. **跨语言引文比对可能失效**：中文文献配英文摘要在 `quote` 模式下比对会失败，应改用 `paraphrase`。
6. **R18 只覆盖摘要**：正文实验结果与贡献的对应依赖 R12 的定位检查。
