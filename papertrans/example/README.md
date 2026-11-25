# 最小调用示例（示意输出，非正式案例）

输入：一篇公开论文（arXiv 1706.03762v7《Attention Is All You Need》）的前 3 段：标题 / "Abstract" / 摘要正文。
译文是人工写的示意译文，用来说明接口、产物格式和核验器行为；**不是正式案例结果**。

## 命令

```bash
# 1) prepare：解析 → 分段 → 术语候选 → 批次
python3 -m papertrans.cli prepare paper.pdf --out out --lang zh

# 2) 模型审核术语表 → out/glossary_reviewed.json（本例批准 9 条，见 out/glossary_reviewed.json），重新 prepare
python3 -m papertrans.cli prepare paper.pdf --out out --lang zh --reviewed out/glossary_reviewed.json

# 3) 模型按 out/batches/B01.json 的 masked 文本翻译，写 out/translations.json（本例只翻 S001–S003）

# 4) 核验 + 装配
python3 -m papertrans.cli verify  out
python3 -m papertrans.cli assemble out
```

## 输入片段（B01.json 的 `segments[]`，节选 S003）

```json
{"id": "S003", "role": "body", "page": 1,
 "masked": "The dominant ⟦TERM#0001⟧ models are based on complex recurrent or ⟦TERM#0002⟧ … Our model achieves ⟦NUM#0006⟧ BLEU on the WMT ⟦NUM#0007⟧ English-to-German translation task … score of ⟦NUM#0009⟧ after training for ⟦NUM#0010⟧ on eight GPUs …",
 "marks": [{"surface": "⟦TERM#0001⟧", "kind": "TERM", "original": "sequence transduction"},
           {"surface": "⟦NUM#0006⟧",  "kind": "NUM",  "original": "28.4"},
           {"surface": "⟦NUM#0010⟧", "kind": "NUM",  "original": "3.5 days"}, …]}
```

模型输出（`translations.json` 节选）：

```json
{"translations": {"S003": "主流的⟦TERM#0001⟧模型基于复杂的⟦TERM#0002⟧……我们的模型在 WMT ⟦NUM#0007⟧ 英德翻译任务上取得 ⟦NUM#0006⟧ BLEU……在 8 块 GPU 上训练 ⟦NUM#0010⟧ 后，取得了 ⟦NUM#0009⟧ 的单模型最佳 BLEU 分数……"}}
```

## 示意输出（`out/bilingual.md` 节选）

```
### [S003 | 正文 | p.1 | 143.6,413.3,469.8,576.1 | ⚠]

The dominant sequence transduction models are based on complex recurrent or convolutional neural networks ...

主流的序列转换模型基于复杂的循环或卷积神经网络……我们的模型在 WMT 2014 英德翻译任务上取得 28.4 BLEU……
在 8 块 GPU 上训练 3.5 days 后，取得了 41.8 的单模型最佳 BLEU 分数……

> 核验: placeholder_order_changed(2); numbers_added(8); translator_unsure
```

怎么读这条核验：

| 标记 | 含义 | 处置 |
|-|-|-|
| `⟦TERM#0001⟧` → "序列转换" | approved 术语由程序回填；全篇 9 个锁定术语一致率 100% | 自动 |
| `⟦NUM#0006⟧` → `28.4` | 数字原样还原 | 自动 |
| `placeholder_order_changed(2)` | `28.4`↔`2014`、`41.8`↔`3.5 days` 在译文中相对顺序互换 | **合法**：中文习惯"在 WMT 2014 任务上取得 28.4"、"训练 3.5 天后取得 41.8"。warn 级，人工确认即可 |
| `numbers_added(8)` | 译文出现源文没有的数字 `8`（"eight GPUs"→"8 块 GPU"） | 正确翻译，warn 级 |
| `translator_unsure` | 译者标了 `[待确认: 模型名 Transformer 按原文保留]` | 进人工清单 |

`out/result.json`：`status=success`，`summary.coverage=1.0`，`term_consistency_rate=1.0`，`uncertainty.warn_segments=["S003"]`，`translator_unsure_markers=1`。
`out/bilingual.json[].marks` 给出该段 11 个占位符各自的 `原文 → 译文 → 动作(backfill/restore)`。

## 方法的已知边界（用这个示例说清楚）

占位符保证的是"值不丢、不改、不重排到错误类型"，**不保证"值贴在正确的名词上"**。如果把示意译文故意写成"训练 41.8 后，取得了 3.5 days"——占位符完整、顺序一致——程序核验不会报错。兜底靠三层：prompt 第 7 条要求译者逐个核对 ⟦NUM⟧ 邻接的名词；`warn` 段进入人工复核清单；`marks` 逐项可对照。
