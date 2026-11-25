# 术语一致性（Terminology）

术语漂移是整段重写的第二大事故：引言叫"钙钛矿太阳能电池"，方法里变"钙钛矿电池"，讨论里又成"PeSCs"。读者以为是三个东西。

## 1. 先建表，再编辑

`run_case.py init` 会把词频候选写进 `work/glossary.json`。编辑前把它补完整：

```json
{
  "version": "glossary/v1",
  "lang": "zh",
  "terms": [
    {"preferred": {"zh": "钙钛矿太阳能电池", "en": "perovskite solar cells"},
     "variants": ["钙钛矿电池", "PeSCs", "PSCs", "perovskite solar cell device"],
     "count": 7, "status": "confirmed"}
  ]
}
```

规则：
- 一个概念**只有一条** `preferred`；其他写法全放 `variants`。
- 候选术语只是起点，来自词频，不保证是术语。缩写、方法名、材料名、性能指标优先确认。
- 任务给了术语表/期刊词汇表 → 直接采用，`status: provided`。
- 原文内部两种写法都在用且无法判断哪个是作者本意 → 保留出现次数多的，标记 `status: conflict`，记录需人工确认。

## 2. 中英对齐

- 中文稿：`preferred.zh` 必填；`preferred.en` 填通用英文名（摘要常要双语）。
- 英文稿：`preferred.en` 必填；`preferred.zh` 可空。
- 中文稿夹用英文缩写是常态（PLQY、XRD、DFT），保持原样，首次出现给中文全称 + 英文全称 + 缩写。
- 不要把英文缩写"翻译"成中文（DFT → 密度泛函理论 可以，但之后全篇用 DFT 还是中文要统一）。

## 3. 缩写首次出现

格式：中文全称（English full name, ABBR）。例：`密度泛函理论（density functional theory, DFT）`。
首次出现之后只用缩写；摘要与正文各自算一次首次（摘要里定义过，正文第一次仍需再定义，多数期刊如此；以 style guide 为准）。
审计不检查缩写首次出现，需人工看一遍。

## 4. 一致性回扫（编辑后、verify 前）

1. `glossary.json` 填好后运行 `verify`，看 `audit_report.json` 的 `glossary_violations_revised`：每个条目是一次 variant 残留。
2. 对每条残留：改回 preferred，台账 `edit_type=terminology`，`reason` 写"统一为术语表 preferred"。
3. 再跑一次 `verify`，直到 `glossary_violations_revised` 为空。

预算提示：如果 `verify` 已经跑过两次且预算紧张，残留的 variant 在 `limits` 里列出，`status=partial`。

## 5. 什么算术语、什么不算

算：材料名、方法名、仪器名、性能指标、模型/数据集名、领域专有概念（"缺陷态密度"、"非辐射复合"）。
不算：普通动词名词（"研究表明"、"性能提升"）、连接词、评价词。这些归 register / word_choice。

## 6. 跨章节漂移检测（人工）

英文候选术语由大写短语和全大写缩写组成，中文由 2–6 字重复字串组成。编辑后用 `edit_brief.candidate_terms` 快速扫一遍改文：
- 同一候选在改文中是否出现了大小写不同的变体（`Perovskite` / `perovskite` 在句中位置不同是正常的，句中一律小写）。
- 连字符变体（`thin-film` vs `thin film`）要统一，按 style guide。
- 英文复数/单数（`devices` vs `device`）按语法需要，不算漂移。
