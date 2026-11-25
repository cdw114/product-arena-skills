# 受保护跨度（Protected Spans）

润色时**不得无意改变**的词句。改前提取清单，改后逐条核对；有意改动必须在台账说明。

## 1. 限定词（hedges）——承载作者的主张强度

| 类型 | 中文 | 英文 |
|---|---|---|
| 认识情态 | 可能、或许、似乎、推测、我们认为、提示、暗示、有望 | may, might, could, likely, appears, suggests, we hypothesize, presumably |
| 程度/范围 | 部分、主要、大约、约、左右、通常、往往、在某些情况下、多数、显著、略微、较 | partially, mainly, approximately, roughly, typically, often, in some cases, most, slightly, largely |
| 留有余地 | 尚不明确、有待、需要进一步、 remains unclear | remains unclear, warrants further study, not fully understood |
| 证据强度 | 表明 / 暗示 / 证实 / 证明 是四个不同等级 | suggests / indicates / demonstrates / proves / confirms |

守恒规则：
- 不得升级：可能 → 证明，提示 → 证实，部分 → 全部，约 → 精确。
- 不得降级，除非任务要求"弱化语气"。
- 不得删除：一个"可能"没了，句子就从假设变成断言。
- 同义替换可以（"约 120 nm" → "大约 120 nm"），但要记台账，`edit_type=word_choice`。

常见事故：整段重写时模型倾向于把"我们推测 X 可能 Y"写成"X 通过 Y 实现"，三处限定词一起消失，且作者察觉不到。审计 `hedge_words_dropped` 就是为此而设。

## 2. 绝对词（absolutes）——同样受保护

必然、一定、完全、所有、任何、从不、毫无 / always, never, all, every, none, certainly, undoubtedly, proves。
增加绝对词 = 偷偷加强结论；删除 = 削弱。两者都要在台账说明。

## 3. 否定与范围（negation / scope）

不、未、无、非、没有、无法、尚未、并非 / not, no, never, neither, nor, without, cannot, fails to。
**否定丢失是语义反转**，是所有事故中最严重的。
注意：中文"不断""不仅""非常"中的"不"不是否定，审计会误报；在台账 `other` 里记一句即可。

## 4. 数字、单位、范围

- 数值 + 单位整体是一个跨度：`3.2 mg/mL`、`15.3%`、`p < 0.05`、`12.4 ns`、`18.5 ± 0.6%`、`1.2 × 10⁻³`。
- 范围 `120–250 nm`、`约 3–5 倍` 不拆开。
- 单位不得换算（mg → g、nm → μm），除非任务明确要求统一单位。
- 百分号、正负号、误差范围（±）不得丢。
- 中文数字与阿拉伯数字不互换（"三组" ≠ "3 组"），除非期刊格式要求且任务说明。

## 5. 引用与交叉引用

| 格式 | 例 | 守恒要求 |
|---|---|---|
| 数字编号 | `[12]`、`[12,15]`、`[12–14]` | 编号一字不改；顺序可按期刊要求调整但需台账 |
| 作者-年份 | `Smith 等 (2019)`、`(Smith et al., 2019)`、`Smith and Lee, 2020` | 姓名、年份、"et al."/"等" 不改 |
| LaTeX | `\cite{key}`、`\citep{key}`、`\ref{fig:1}` | 键名不改；命令本身不改 |
| Markdown/Pandoc | `[@key]`、`[@a; @b]` | 同上 |
| 图表指向 | `图 3`、`表 2`、`Fig. 3`、`Table 2`、`式 (4)` | 编号不改；"图/Fig."写法全篇统一 |

引用**只能删错不能删漏**：润色不删引用。若原文一处引用明显放错位置，只在 `human_confirmation_needed` 中提出。

## 6. 术语（见 terminology.md）

术语替换只能按术语表 variants → preferred 方向进行。

## 核对流程（在 verify 之前）

1. 打开 `edit_brief.json`，把 `hedges_to_preserve`、`numbers_to_preserve`、`citations_to_preserve`、`author_year_to_preserve`、`bracket_refs_to_preserve` 当作勾选清单。
2. 逐句改完后，用搜索确认每个跨度仍在改文中（或已在台账说明）。
3. 运行 `verify`；`unexplained_changes` 必须为空才能标 complete。

## 审计器的已知边界

- 漏报：罕见限定词（"在很大程度上归因于"）可能不在词表；数字后无空格的单位（"3.2mg"）可能漏抓。
- 误报：`近`（近年来）、`表明`、`非`（非辐射）、`较`（比较）会出现在 hedges 里。
- 处理原则：**清单辅助人，不替代人**。漏报靠通读补，误报靠台账说明。
