# 核验规则（verify.py）

每段独立核验，输出 `pass | warn | fail`；有任一 fail 级问题即 `fail`，否则有 warn 即 `warn`。

| 规则 | 级别 | 判定 | 典型原因 |
|-|-|-|-|
| `missing_translation` | fail | 该段 id 不在 translations.json 或译文为空 | 漏段 |
| `placeholder_missing` | fail | 某个 `⟦K#nnnn⟧` 在译文中出现 0 次 | 模型把占位符"翻译"了、删了 |
| `placeholder_unexpected` | fail | 译文出现不属于本段的占位符编号 | 段落错位、复制了别段 |
| `placeholder_duplicated` | fail | 同一占位符出现 ≥2 次 | 模型重复 |
| `placeholder_order_changed` | warn | NUM/CITE/REF/MATH/TERM 占位符在译文中的相对顺序与原文不同（给出互换对） | 多为合法语序调整（中文把年份/状语前移）；**也可能**是数值贴错位置。看 `pairs` 逐对确认 |
| `placeholder_leftover` | fail | 装配后仍残留 `⟦..⟧`（编号不存在） | 模型编造了占位符 |
| `numbers_missing` / `numbers_added` | fail / warn | 原文与译文的**数字多重集**比较（不带符号、排除嵌在单词里的数字如 newstest2014） | 译错数值；`added` 常由"2 → 两个"之外的补充造成，人工看 |
| `units_missing` | warn | 原文紧跟数字的单位在译文中找不到 | 单位被改写（mg → 毫克 允许：中文字"毫克"不在检查集，会误报 warn，可接受） |
| `xref_mismatch` | fail | `Fig. 3 / Table 2 / Eq. (4) / §2.1` 多重集不一致 | 交叉引用被改写/丢失 |
| `citation_mismatch` | fail | `[12]`、`(Smith et al., 2020)` 多重集不一致 | 引用编号被改 |
| `term_source_leaked` | warn | TERM 占位符之外，译文里又出现了术语原形（单复数、大小写、连字符变体都算） | 译者绕过术语表 |
| `negation_possibly_dropped` | warn | 原文否定词数 > 译文中目标语否定词数 | 漏译 not/without/failed to |
| `hedging_possibly_dropped` | warn | 原文 ≥2 个模糊限制词、译文 0 个 | may/suggest 被译成肯定句 |
| `too_short_possible_omission` / `too_long_possible_padding` | warn | 译文/原文长度比超出语言带（zh: 0.22–1.3） | 漏句、加解释 |
| `translator_unsure` | info | `[待确认: …]` / `[UNSURE: …]` | 译者显式标注，进人工清单 |

## 程序核不出来的一类错误

占位符只保证"值不丢、不改、类型不混"，**不保证值贴在正确的名词上**："score of 41.8 after training for 3.5 days" 若译成"训练 41.8 后取得 3.5 days"，占位符完整且顺序一致，所有规则都通过。兜底：prompt 第 7 条要求译者逐个核对 ⟦NUM⟧ 邻接的名词；warn 段进人工清单；`bilingual.json[].marks` 逐项可对照。

## 文档级

| 项 | 说明 |
|-|-|
| `placeholder_integrity` | found/expected，所有段合计 |
| `duplicate_groups` | 译文完全相同（>30 字）的段组，几乎必是复制错误 |
| `term_consistency`（assemble） | 每个 approved 术语：锁定译名出现次数、原形泄漏次数、是否一致；整体 `consistency_rate` |
| `status` | `success`：无 fail、无缺段；`partial`：有 fail/缺段但有译文；`failed`：无译文 |

## 处置顺序

1. 先修 fail（重译该段 → 更新 translations.json → 重新 verify），预算内最多一轮。
2. warn 逐条看：真丢了否定/单位就重译；表达差异就保留并留在 `uncertainty.warn_segments`。
3. `duplicate_groups` 必看，重译其中一段。
4. 仍有 fail 且预算紧张 → 停止，assemble 出 `partial`，fail 段在 `uncertainty.fail_segments` 中逐段可查。

## 阈值可调

- 长度带：`verify.LENGTH_BAND`
- 否定/限制词表：`NEG_SRC / NEG_TGT / HEDGE_SRC / HEDGE_TGT`
- 占位符保护范围：`translate.build_batches(kinds=...)`
