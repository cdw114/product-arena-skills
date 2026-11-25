# 贡献与证据：让贡献表述"对得上"

## 1. 一条要求

> 每条贡献都必须能在正文里指出一个**具体位置**（图号 / 表号 / 节号 / 结果数值），且该位置真实存在。

"提出了一个框架"不是贡献，是摘要；"框架对应 Fig. 1，增益来自 Table 2 的消融"才是。

## 2. 贡献的六种类型（`kind`）

| kind | 内容 | 通常的证据定位 |
|---|---|---|
| `method` | 新的机制、流程、目标函数 | 方法节 + 框架图 |
| `experiment` | 新的实验结果或基准对比 | 结果表 / 主图 |
| `analysis` | 归因、消融、诊断 | 消融表 |
| `data` | 新数据集、新标注、新划分 | 数据表 / 附录节 |
| `system` | 工程实现、可复现流水线、开源 | 代码/流程节 |
| `theory` | 界、收敛性、可识别性 | 定理/公式编号 |

## 3. 证据定位的五种类型（`locator_type`）

| 类型 | `locator` 写法 | 脚本如何核 |
|---|---|---|
| `figure` | `Fig. 1` / `图 1` / `Figure 2` | 从稿件索引取真实图号集合，编号必须在内 |
| `table` | `Table 2` / `表 2` | 同上（表号集合） |
| `section` | `3` / `4.2` / `Method` / `方法` | 与章节编号或标题片段匹配 |
| `result` | 任意（`abstract` / `Table 1` / `4.3`） | `claim_in_source` 必须与稿件逐字一致，或其数字集合被稿件数字索引包含 |
| `equation` | `(1)` / `1` | 公式编号必须存在 |

**`result` 是最强也最容易写错的一类**：`claim_in_source` 要抄稿件原句，别自己总结。

```jsonc
{"locator_type": "result", "locator": "abstract",
 "claim_in_source": "improves accuracy by 11.3% over the strongest self-supervised baseline and reduces pretraining cost by 62.4%"}
```

## 4. 三条撰写规则

### 规则一：一条贡献一个证据簇
一条贡献里塞三件事，证据就挂不住。拆开：

- 差：`提出了新框架并在三个数据集上取得 SOTA，还做了充分消融。`（三件事、零定位）
- 好：三条，分别挂 `Fig. 1`、`Table 1`、`Table 2`。

### 规则二：机制在前，效果在后
`method` 类贡献写机制（`先选后训`），`experiment` 类写效果（`11.3%`）。混在一句里，读者分不清哪部分是新的。

### 规则三：边界必须写（`scope`）
```jsonc
"scope": {"stated_limits": "覆盖度打分没有理论保证",
          "not_claimed": "任意蛋白家族的泛化"}
```
- 出现"首次 / 首个 / 最优 / 最高 / state-of-the-art / SOTA / first to / unprecedented"时，`scope.stated_limits` 空 → R15 warn。
- `not_claimed` 不是免责声明，是**防止审稿人把你的贡献读大**：明确写出不主张的范围，比事后解释便宜。

## 5. 贡献与正文的对照表（`contribution_table.md`）

每行：`贡献 | 类型 | 证据定位 | 原文依据 | 不主张`。审稿人可以直接逐行核对。示例：

| 贡献 | 类型 | 证据定位 | 原文依据 | 不主张 |
|---|---|---|---|---|
| 先选后训的处理流程 | method | section:3; figure:Fig. 1 | "A greedy coverage score then selects molecules that maximise the distance to the already-selected set" | 选择规则的最优性 |
| 固定标注预算下的收益 | experiment | table:Table 1; result:abstract | "improves accuracy by 11.3% over the strongest self-supervised baseline" | 任意蛋白家族的泛化 |

## 6. 数字：唯一不许"润色"的东西
- 贡献里出现的带单位或带小数的数值，必须能在稿件或文献库找到（R13 `invented_metric`）。
- 不要把 `0.742` 写成 `0.74`，也不要把 `11.3%` 写成"约 11%"——数值精度是结果的一部分。
- 需要强调时加语境，不加数字：`在 100 条标注下` 可以说，`显著优于` 需要数据支持。

## 7. 摘要数值的反向检查（R18）

稿件摘要里每个带单位的数值，应该至少落进一条贡献或在引言里被提到。否则读者会问："摘要里这个数，贡献列表里怎么没有？"

处置：要么把它写进某条贡献的 `text` 或 `claim_in_source`，要么在正文里明确它属于哪个结论。

## 8. 自查五问

1. 每条贡献都有 ≥1 条能定位的证据吗？（R12）
2. 指向的图/表/节/公式在稿件里真的存在吗？（R12）
3. `result` 类证据的 `claim_in_source` 是抄的还是编的？抄的哪个句子？（R12）
4. 有拔高表述的贡献写了 `scope.stated_limits` 吗？（R15）
5. 摘要里的关键数值进贡献了吗？（R18）
