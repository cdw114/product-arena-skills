# 四本账：字段、判据与填写范例

账是脚本能核对、人能复核的唯一载体。四本账的字段名是**契约**，改动会让核对失效。

## 1. `ledger_refs.json` — 引用账

一篇文献一行。目的不是罗列，而是**先声明这篇在本文论证里承担什么角色**。

| 字段 | 类型 | 取值 | 说明 |
|---|---|---|---|
| `ref_id` | str | `R0001` | 必须来自 `work/library.json` |
| `role` | str | `seminal` / `representative` / `recent` / `baseline` / `survey` / `application` / `ambiguous` / `irrelevant` / `other` | 这篇在论证里的位置 |
| `cluster` | str | 与 `ledger_groups.json` 的 `group_id` 一致 | 允许多组共享；不一致会在 R09 暴露 |
| `must_cite` | bool | true/false | true 而正文没引 → R05 **error** |
| `one_line` | str | 一句话 | 做了什么 + 结论 + 适用条件。写不出来说明还没读透，先别引 |

**判据**：`one_line` 里必须能看出"结论"和"适用条件"，只有"提出了 X"不算。例：

- 差：`提出了图对比学习框架 MolCLR。`
- 好：`用原子掩码/键删除/子图构造对比正样本，低标注下优于监督训练；代价是全库逐轮扫过，算力随库规模线性增长。`

**role 的用法**：`seminal` 与 `representative` 是"必须在场"的（R05 会追）；`recent` 触发 R06 的近期覆盖检查；`baseline` 是本文要对比的对象，通常要在相关工作里点名；`irrelevant` 是显式排除，写进去比默默不引更诚实。

## 2. `ledger_groups.json` — 分组账（分得清）

```jsonc
{
  "groups": [{
    "group_id": "G1",
    "label": "按什么信号选择预训练语料",
    "dimension": "选择信号，以及它优化的量",          // 必填，R07 error
    "works": [{
      "ref_id": "R0007",
      "method_route": "在固定嵌入上做 k-centre 贪心选择",
      "data_setting": "图像分类/分割数据集",
      "evaluation": "子集训练误差相对全集的上界",
      "conclusion": "有界子集可复现全集误差",
      "limitation": "界只在固定特征空间成立，不能迁移到仍在学习的表示"   // 必填
    }],
    "comparison": {
      "dimension": "选择信号 vs 它优化的量",
      "tradeoff": "…组内的取舍结论，必须写成比较句…",                    // 必填，R07 error
      "best_for": "预训练算力充裕、只缺标注的场景"
    }
  }]
}
```

**硬性判据（脚本会查）**
1. 每组 `works` ≥2；只有 1 篇必须在 `single_work_reason` 写理由。
2. `works[].{method_route, data_setting, evaluation, conclusion, limitation}` 五个都不能空——缺一个就不是"同维度可比"，R07 warn。
3. `dimension` 与 `comparison.dimension` 至少填一个；`comparison.tradeoff`（或 `takeaway`）必填。
4. `ref_id` 必须来自 `library.json`，否则 R09 无法对账。

**语义判据（脚本查不了，靠你）**
- 一个组是"同一维度上互相竞争/互补的路线"，不是"同一个实验室的几篇论文"。
- `dimension` 写的是**比较的轴**（问题设定 / 方法路线 / 数据与场景 / 评价方式 / 计算代价），不是主题名。
- `tradeoff` 必须能回答"如果只能选一个，选哪个、代价是什么"。

## 3. `ledger_gaps.json` — 空白账（说得实）

```jsonc
{
  "gaps": [{
    "gap_id": "PG1",
    "statement": "现有选择规则优化标注预算或固定特征空间，没有一条优化预训练语料本身的成本。",
    "derived_from": [{
      "ref_id": "R0009",
      "limitation_kind": "shared_limitation",
      "evidence": {"kind": "quote", "text": "ignores the cost of the pretraining corpus itself, which dominates the budget at scale"}
    }],
    "how_filled": {"contribution_ids": ["C1", "C2"],
                   "mechanism": "先选后训，把语料成本变成显式预算"},
    "confidence": "high"
  }]
}
```

`limitation_kind`：`shared_limitation`（多篇共同局限）· `uncovered_scenario`（未覆盖场景）· `conflicting_conclusions`（结论互相冲突）· `evaluation_gap`（评价方式缺项）· `method_gap`（方法路线缺环）· `data_gap`（数据条件缺项）。

`evidence.kind`：`quote`（逐字引文，**脚本会核**）· `paraphrase`（转述，需人工确认）· `author_judgment`（作者判断，正文须标注）。

**硬性判据**
- `derived_from` 至少一条；每条 `ref_id` 必须**已在相关工作正文里被引用**（否则 R10 error：空白凭空出现）。
- `kind=quote` 的 `text` 必须能在该文献的摘要/笔记里逐字（忽略大小写与标点）找到；找不到 → R10 `unverifiable_quote` error。
- `how_filled.contribution_ids` 必须非空且指向存在的贡献（R10/R11）。
- 空白段落里至少 1 个引用（R10 warn），且出现"本文/本研究/we/this paper"（R11 warn）。

详细推导方法见 `gap-derivation.md`。

## 4. `ledger_contributions.json` — 贡献账（对得上）

```jsonc
{
  "contributions": [{
    "contribution_id": "C2",
    "text": "固定标注预算下的收益：11.3% 精度提升，62.4% 预训练成本下降。",
    "kind": "experiment",
    "evidence": [
      {"locator_type": "table",  "locator": "Table 1", "claim_in_source": "GCP reaches 0.742 on ESOL"},
      {"locator_type": "result", "locator": "abstract",
       "claim_in_source": "improves accuracy by 11.3% over the strongest self-supervised baseline"}
    ],
    "scope": {"stated_limits": "只在三个数据集、100 条标注下验证",
              "not_claimed": "任意蛋白家族的泛化"}
  }]
}
```

`kind`：`method` · `experiment` · `analysis` · `data` · `system` · `theory`。
`locator_type`：`figure` · `table` · `section` · `result` · `equation`。

**硬性判据**
- `evidence` 非空（否则 R12 `contribution_without_evidence` error）。
- `figure` / `table` 的 `locator` 必须含真实存在的编号（稿件索引里查）；`section` 可以是编号（`4.2`）或标题片段；`equation` 的编号要存在。
- `result` 必须给 `claim_in_source`：要么与稿件正文逐字一致，要么其数字集合被稿件数字索引包含。否则 R12 error。
- 出现"首次/首个/最优/state-of-the-art/first to"时，`scope.stated_limits` 必须非空，否则 R15 warn。
- 摘要里带单位的数值应至少落入某条贡献（R18 warn）。

详细写法见 `contribution-map.md`。

## 5. 填写顺序的依赖图

```
ledger_refs (role/cluster)
      │
      ▼
ledger_groups (分组 + 五字段 + 取舍)  ──► 相关工作正文
      │
      ▼
ledger_gaps (derived_from 已引文献) ──► 研究空白正文
      │
      ▼
ledger_contributions (证据定位)     ──► 主要贡献正文
```

倒着写会失败：先写正文再补账，账就会迁就正文的措辞，R09 的双向一致立刻报错——这正是它该报的。
