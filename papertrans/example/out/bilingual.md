# Attention Is All You Need

> 作者（按原文保留，不翻译）：Ashish Vaswani∗ Google Brain avaswani@google.com · Noam Shazeer∗ Google Brain noam@google.com · Niki Parmar∗ Google Research nikip@google.com
- 源文件: `tests\attention.pdf` · 页数 1 · 解析后端 pymupdf
- 目标语言: zh · 段落 3 · 已译 3 · 结论 pass/warn/fail = 2/1/0
- 占位符完整性: 11/11 · 术语一致率: 100% (9/9) · 译者标注不确定: 1

每段格式：`[段号 | 角色 | 页 | 位置 | 核验]`，原文在前，译文在后。`⟦..⟧` 为保护标记（数字/引用/交叉引用/公式/锁定术语），译文中原样还原。

### [S001 | 标题 | p.1 | 211.5,148.8,399.9,166.0 | ✓]

Attention Is All You Need

注意力就是你所需要的一切

### [S002 | 小标题 | p.1 | 283.8,385.6,328.2,397.6 | ✓]

Abstract

摘要

### [S003 | 正文 | p.1 | 143.6,413.3,469.8,576.1 | ⚠]

The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train. Our model achieves 28.4 BLEU on the WMT 2014 Englishto-German translation task, improving over the existing best results, including ensembles, by over 2 BLEU. On the WMT 2014 English-to-French translation task, our model establishes a new single-model state-of-the-art BLEU score of 41.8 after training for 3.5 days on eight GPUs, a small fraction of the training costs of the best models from the literature. We show that the Transformer generalizes well to other tasks by applying it successfully to English constituency parsing both with large and limited training data.

主流的序列转换模型基于复杂的循环或卷积神经网络，包含一个编码器和一个解码器。表现最好的模型还通过注意力机制连接编码器和解码器。我们提出一种新的简单网络架构——Transformer，它仅基于注意力机制，完全摒弃了循环和卷积。在两项机器翻译任务上的实验表明，这些模型质量更优，同时更易并行化，训练时间显著减少。我们的模型在 WMT 2014 英德翻译任务上取得 28.4 BLEU，比包括集成模型在内的现有最佳结果高出 2 BLEU 以上。在 WMT 2014 英法翻译任务上，我们的模型在 8 块 GPU 上训练 3.5 days 后，取得了 41.8 的单模型最佳 BLEU 分数，仅相当于文献中最佳模型训练成本的一小部分。我们通过将 Transformer 成功应用于英语成分句法分析（在大规模和有限训练数据下均如此），证明它能很好地泛化到其他任务。[待确认: 模型名 Transformer 按原文保留]

> 核验: placeholder_order_changed; numbers_added(8); translator_unsure
