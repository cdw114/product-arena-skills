# literature-kg — 文献知识图谱构建 Skill

从论文语料（JATS 段落 JSON / Markdown / JATS XML）抽取实体与关系，为每个节点和边绑定
`source_id + paragraph_id + 原文短引`，做跨论文别名对齐（不强迫合并、不混合条件），
执行真实图谱查询，输出符合 `case.json.output_contract` 的 `result.json`。

> 本目录是提交物本体。所有脚本仅依赖 Python 3.9+ 标准库，无需 pip 安装。
> `selftest/` 不属于提交物，是作者的端到端自测（mock 语料为虚构示例，非正式案例结果）。

## 目录

```
SKILL.md                     Skill 入口：触发条件、工作流、硬规则、失败处理
references/schema.md         节点/边/证据字段定义，关系类型目录
references/evidence-rules.md 证据规则、跨篇对齐 T1–T4 判定表、示例
references/output-contract.md result.json 字段说明与完成度分级
references/queries.md        查询目录与可复制命令
scripts/kg_common.py         公共库（段落存储、引文校验、图读写）
scripts/inspect_inputs.py    Phase A：输入清点、段落存储、来源注册、重复格式检测
scripts/graph_op.py          增删节点/边，写入前强制校验引文
scripts/align_candidates.py  确定性生成跨篇候选对（exact/containment/jaccard/token）
scripts/apply_alignment.py   应用合并/保持分离决策，重定向边，记录冲突
scripts/query_kg.py          9 种查询，结果自带从图复制的证据
scripts/assemble_result.py   组装 result.json，保证 output_contract 字段齐全
scripts/validate_result.py   E01–E09 硬错误 / W01–W05 警告
scripts/export_graph.py      GraphML / JSON / Cypher / Mermaid / DOT 导出
scripts/find_paragraphs.py   正则定位段落（节省预算）
GITHUB_URL.txt               作品 GitHub 链接（第一行）
```

## 调用方式（Agent 视角）

环境变量 `KG_WORK`（默认 `/app/work`）为工作目录；`/app/output` 放结果。

```bash
python scripts/inspect_inputs.py --input /input --out /app/work/input_inventory.json
python scripts/graph_op.py init
python scripts/graph_op.py add-node --type method --name "fine-tuning of RoBERTa" \
  --source 10.xxxx/primary --paragraph pa-12 --quote "we fine-tune RoBERTa on ..." --alias "RoBERTa fine-tuning"
python scripts/graph_op.py add-edge --type uses --src N:method:... --dst N:dataset:... \
  --source 10.xxxx/primary --paragraph pa-12 --quote "..."
python scripts/graph_op.py check
python scripts/align_candidates.py --graph /app/work/graph.draft.json --out /app/work/align_candidates.json
#  → 逐对判定（LLM）写入 /app/work/alignment.json
python scripts/apply_alignment.py --graph /app/work/graph.draft.json --alignment /app/work/alignment.json --out /app/work/graph.aligned.json
python scripts/query_kg.py --graph /app/work/graph.aligned.json --query cross_paper --out /app/work/queries/Q1.json --question "..."
python scripts/assemble_result.py --work /app/work --out /app/output/result.json
python scripts/validate_result.py --result /app/output/result.json --paragraphs /app/work/paragraphs --case /input/case.json
python scripts/export_graph.py --graph /app/work/graph.aligned.json --format graphml --out /app/output/graph.graphml
```

## 输入 / 输出

**输入**（题目固定包）：`case.json`（含 `output_contract`）、`task.md`、`corpus-manifest.json`、
`material.json`（两篇段落汇总索引）、`primary-material.json`、`secondary-material.json`、
可选 `secondary-publisher.xml`（核对线性化公式）。

**输出**：`result.json`（字段见 `references/output-contract.md`），可选 `graph.graphml/.mmd/.cypher`。

## 关键方法

- **证据先行**：写入节点/边时即校验 quote 是段落文本的精确子串（容忍空白/弯引号/破折号），不合格直接拒绝。
- **来源隔离**：每条证据自带 `source_id`；合并节点时证据只做并集，`first_seen`/`sources` 由脚本计算；
  验证器拦截「证据全来自 B 却标成 A」。
- **对齐两阶段**：脚本生成候选并打标（`exact_alias` / `containment→possible_different_object` /
  `generic_term→class_instance_candidate`），LLM 只按 T1–T4 用引文判定；合并必须写 `merge_basis`。
- **条件不合并**：`reports_value` 边按论文独立，`apply_alignment` 在值冲突且未声明时拒绝合并。
- **位置诚实**：只记 `paragraph_id`，段落无 `page` 时出现页码即报 E09。
- **预算友好**：先存骨架 result，再增量；`find_paragraphs.py` 只读命中段落。

## 适用范围与限制

- 适用：有段落级文本的论文语料（JATS/JSON/MD），1–N 篇，任意学科。
- 不适用：仅有扫描图像的 PDF（需外部 OCR，本 Skill 不含）；补充材料/图表像素中的数值（一律 `unreported`）。
- 对齐判定由 LLM 完成，脚本只保证记录完整与可验证；`uncertain` 决策是被允许且应保留的。

## 失败处理

见 `SKILL.md` §11（文件缺失、XML 不可读、引文校验失败、预算耗尽、查询无结果等）。
所有异常进入 `status_reason` / `uncertainties`，`status` 取 `partial | not_determinable | refused`。

## 自查

`validate_result.py` 退出码 0；≥3 个已执行查询；每个跨篇合并有 `merge_basis`；无自造页码；
`change_log` 记录每步。

## 维护

版本 1.0.0。修改 schema 需同步 `references/schema.md` 与 `validate_result.py`。
