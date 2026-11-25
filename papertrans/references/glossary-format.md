# 术语表格式（glossary.json / glossary_reviewed.json）

```json
{
  "T001": {
    "source": "attention mechanism",
    "target": "注意力机制",
    "abbr": "",
    "pos": "noun",
    "domain": "NLP",
    "note": "weight=9 count=7 roles=abstract,body,title pages=[1,2,4]",
    "status": "approved"
  },
  "T002": {
    "source": "Transformer",
    "target": "",
    "abbr": "",
    "pos": "noun",
    "domain": "NLP",
    "note": "model name — keep as is",
    "status": "keep"
  }
}
```

## 字段

| 字段 | 必填 | 说明 |
|-|-|-|
| `source` | ✓ | 原文术语，**单数形式、小写**（专有名词除外）。匹配时不区分大小写，末尾允许 `s` 复数，词间 `-`/空格互通 |
| `target` | approved 必填 | 唯一译名。同一 `target` 不能被两个不同 `source` 使用（校验会报 `one-to-one violated`） |
| `abbr` | | 原文缩写（程序自动从 "long form (ABBR)" 抽取）。译文若需保留缩写，直接写进 `target`，如 `"图神经网络（GNN）"` |
| `pos` | | 词性提示，当前仅记录 |
| `domain` | | 子领域标签，便于复用 |
| `note` | | 候选自动生成：`weight`（角色加权和）、`count`（出现次数）、`roles`、`pages` |
| `status` | ✓ | `approved` / `keep` / `proposed` / `rejected` |

## status 语义

- `approved`：译前全部替换为 `⟦TERM#nnnn⟧`，译后由程序回填 `target`。译文中出现 `source` 原形 → `term_source_leak` 警告 + `term_consistency` 不一致。
- `keep`：同样占位，但回填原文（专有名词、模型名、数据集名）。
- `proposed`：候选默认状态，**不参与**占位（prepare 未给 `--reviewed` 时，候选表里没有 approved 项，等于不锁术语）。
- `rejected`：忽略。

## 审核规则（模型执行，一次）

1. 看 `note.roles`：出现在 title/abstract/heading 的高权重候选优先处理。
2. 删除：人名、机构名、地名、通用搭配（"training data" 之类视领域而定）。
3. 一个概念只保留一个 `source`（最常见写法），其他写法并入 `note`；不要为同一概念建两个条目——否则 `one-to-one` 校验失败。
4. 补漏：标题、摘要、各节标题里出现而候选里没有的术语，新增 `T1xx`。
5. `target` 不能等于 `abbr`（如 target 写成 "GNN"）；需要缩写就写 `"图神经网络（GNN）"`。

## 维护

- 术语表可跨论文复用：把 `glossary_reviewed.json` 的 `approved/keep` 条目合并进下一份候选表（同 `source` 以人工表为准），再按本篇补漏。
- 校验命令：`python3 -m papertrans.glossary segments.json --out x.json --apply --reviewed glossary_reviewed.json`
