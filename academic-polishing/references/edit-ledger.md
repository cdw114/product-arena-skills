# 修改台账（Edit Ledger）

台账让第三方能判断"这处该不该改"。它不是修改日志的堆砌，每条要能独立读懂。

## 文件

- `work/ledger.json`（编辑时追加）→ `verify` 复制为 `/app/output/edit_ledger.json` + `edit_ledger.md`（表格）。
- 结构：`{"version":"edit-ledger/v1","case_id":"…","edits":[…]}`。

## 条目字段

```
edit_id          E01, E02, …（按文中出现顺序）
edit_type        见下表
source_excerpt   原文片段，≤ 60 字，必须能在原文中精确找到（含被改部分）
revised_excerpt  改文片段，必须能在改文中精确找到
reason           一句话说清：错在哪 / 为什么这样改 / 保留了什么
```

**硬约束**（verify 会检查）：五字段非空；`source_excerpt ≠ revised_excerpt`；`edit_type` 在允许列表内。

## 修改类型

| edit_type | 用于 | reason 应写明 |
|---|---|---|
| grammar | 主谓不一致、时态、搭配错误、成分残缺 | 错误类型 |
| syntax | 语序、句式重组、被动→主动、"的"字冗余 | 句式问题 |
| punctuation | 半角→全角、逗号误用、缺失顿号 | 规则 |
| long_sentence_split | 拆分长句 | 原句字数/词数；拆分后主语如何处理 |
| word_choice | 用词替换（非术语） | 原词问题 + 新词理由 |
| terminology | variant → preferred | "统一为术语表 preferred" |
| register | 文体调整（去自我评价、去空泛评价、人称统一） | 目标文体惯例 |
| hedge_adjust | 有意改限定词（仅当任务要求） | **引用原限定词** + 任务依据 |
| connective | 连接词增删换 | 逻辑关系是否改变 |
| translationese | 翻译腔改写 | 直译来源 |
| redundancy | 删冗余（名词化、套话、重复） | 删了什么、信息是否损失 |
| citation_format | 引用格式调整 | 期刊格式依据；编号不变 |
| structure | 段落内顺序、合并/拆分段 | 为什么原顺序有问题 |
| format | 字体标记、标题层级、列表格式 | 格式依据 |
| other | 审计误报说明、无法归类 | 说明 |

## reason 的写法

好的：
- "删冗余'的'，'增加到'改'增至'使句式紧凑；数字、单位与两个'约'均保留。"
- "中文少用被动'被观察到'，改主动句；作者-年份引用与方向'相反'均保留。"
- "删套路化连接'综上所述'；'重要的理论依据'语气过强，改'理论参考'更符合摘要的克制语气。"
- "审计将'近年来'的'近'标为限定词，属误报，未改。"

不好的：
- "优化表达" / "使语言更流畅" / "润色"（没有信息，第三方无法判断该不该改）
- 只写改文不写原因

## 粒度

- **一句一条**：同一句改了两处且理由不同，拆两条；理由相同可合并，`source_excerpt` 覆盖两处。
- 没改的句子不记。
- 一段整体重排 → 一条 `structure`，`source_excerpt` 取段首 40 字。

## 与审计的配合

- `verify` 把 `audit_report.blocking` 中的每一项与台账 `reason + source_excerpt + revised_excerpt` 做字面匹配：
  - 匹配到 → `explained_changes`
  - 没匹配到 → `unexplained_changes`，exit 2，status 降为 partial
- 所以：删了一个限定词（任务允许），台账 `reason` 里必须**原样引用那个词**，否则审计认为未说明。
- 数值/引用变化一般不应出现；若任务要求换算单位或重排引用编号，`reason` 里同时写出旧值与新值。

## 不要做的事

- 不要为了"看起来改得多"而给没改的地方记台账。
- 不要把整段粘贴成 `source_excerpt`。
- 不要事后补台账来"解释"一个并不存在的理由——审计只是核对工具，台账是给人看的。
