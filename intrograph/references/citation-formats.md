# 引用标记识别与参考文献渲染

## 1. 四种被识别的标记形式

| 形式 | 正则要点 | 解析路径 | `kind` |
|---|---|---|---|
| 数字制 | `[1]` `[1,2]` `[1-3]` `[1, 2, 5-7]`、全角 `［1］` | 数字 → 稿件文末参考文献表第 n 条 → 文献库条目 | `numeric` |
| citekey | `\cite{}` `\citep{}` `\citet{}` `\citealp{}` `\citeauthor{}` `\citeyear{}`（含 `*` 与可选参数） | 键直接查文献库 | `key` |
| pandoc | `[@key]` `[@a; @b]` | 去 `@` 后查键 | `key` |
| 著者-年份 | `(Smith, 2020)` `(Smith et al., 2020a)` `Smith et al. (2020)` `张三等（2020）` | 姓 + 年；支持"等/et al." | `author-year` |

wikilink `[[key]]` 也识别为 `key`。

**识别顺序**：先排斥区间（Overlap），再按 LaTeX → pandoc → wikilink → 数字 → 著者-年份 匹配，避免 `\cite{a}[1]` 这类混排重复计数。

## 2. 解析的三种方法（记录在 `citation_map[].resolution`）

| 方法 | 何时使用 | 不可靠之处 |
|---|---|---|
| `manuscript_reflist` | 数字制且稿件有文末参考文献表 | 表里条目与文献库对不上时会产生 `unverified_metadata` 条目 |
| `library_order` | 数字制但稿件没有文末表 | **高风险**：假定文献库顺序 = 编号顺序；结果里会标出来 |
| `citekey` | citekey / pandoc / wikilink | 键打错一个字母就是 `invented_citation` |
| `author-year` | 著者-年份制 | 同姓同年不同文献 → `ambiguous_citation` |

解析不到 → `unresolved_citations`，正文标记**原样保留**（不删、不改、不补），R01 报 error。

### 文末参考文献表 → 文献库的匹配链
1. DOI 完全一致
2. 题名归一化后前缀包含或相似度 ≥0.55
3. 第一作者姓 + 年份唯一匹配
4. 都不中 → 作为 `X000n` 新条目入库，标 `unverified_metadata: true`

第 4 种情况是**诚实降级**：条目来自作者排版，可能缺卷期页；核对会给出 `metadata_incomplete` 警告，而不是假装完整。

## 3. 四种渲染格式

### GB/T 7714—2015（顺序编码制）
```
[1] 张三, 李四. 基于图卷积的分子表示学习[J]. 计算机学报, 2020, 43(3): 1-12. DOI: 10.11897/SP.J.1016.2020.00001.
[2] KIPF T N, WELLING M. Semi-supervised classification with graph convolutional networks[C]. International Conference on Learning Representations, 2017. DOI: 10.48550/arXiv.1609.02907.
```
- 作者：中文写全名；西文"姓全大写 + 名首字母"，>3 人加 `, 等` / `, et al`。
- 文献类型标识：`[J]` 期刊 · `[C]` 会议 · `[M]` 专著/章节 · `[D]` 学位论文 · `[R]` 报告 · `[S]` 标准 · `[EB/OL]` 电子资源 · `[J/OL]` 预印本 · `[Z]` 其他。
- 卷(期): 页；有 DOI 写 `DOI: …`，无 DOI 用 arXiv 或 URL。

### IEEE（英文数字制的默认）
```
[1] T. N. Kipf and M. Welling, "Semi-supervised classification with graph convolutional networks," in Proc. International Conference on Learning Representations, 2017. doi: 10.48550/arXiv.1609.02907.
[2] J. Gilmer, S. S. Schoenholz, P. F. Riley, et al., "Neural message passing for quantum chemistry," in Proc. International Conference on Machine Learning, pp. 1263-1272, 2017. doi: 10.48550/arXiv.1704.01212.
```
选择规则：目标语言为英文且引用为数字制 → 用 IEEE，而不是把英文条目塞进 GB/T 的 `[J]/[C]` 形状。

### APA 7（著者-年份制）
```
Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. International Conference on Learning Representations. https://doi.org/10.48550/arXiv.1609.02907
```
缺年份写 `(n.d.)`；≤20 位作者全列，第 21 位起省略。

### BibTeX（机器可读副本）
只包含正文实际引用的条目，`@article` / `@inproceedings` / `@book` / `@phdthesis` / `@techreport` / `@incollection` / `@misc` 按 `type` 映射；页码 `-` → `--`。

## 4. 编号一致性（最容易出错的一处）

**数字制下，文末列表的编号必须等于正文里的编号，不是发现顺序。**

- 稿件的 `[1]` 指哪篇，`refs_cited.txt` 的 `[1]` 就必须是哪篇。
- 只通过 citekey 引入、正文里没有数字编号的文献，排在最大编号之后继续编号。
- `result.result.reference_numbering` 记录 `ref_id → number`，`references_used[].number` 与之对应，供逐条核对。

自测里专门有一条检查（`refs_cited` 编号是否随正文编号），因为这一处错了整篇文献表都错位。

## 5. 格式判定的优先级

1. `case.json` 的 `citation_style` / `target_style`
2. `task.md` 里的明确要求（GB/T 7714 / APA 7 / IEEE / Vancouver / 数字制 / 著者-年份）
3. 稿件正文里已有的标记样式（自动识别）
4. 兜底：中文 → GB/T 数字制；英文 → IEEE 数字制

最终选择与依据写入 `result.task.citation_style` 和 `result.log`。**混用会被 R17 报出**（`mixed_citation_style`）。

## 6. 中英混排的四个坑

1. **全角标点**：`［1］`、`（2020）` 要能识别；渲染时中文条目用全角、西文条目用半角。
2. **"等"与"et al."**：中文条目 >3 人写 `等`，西文写 `et al`；两者都参与著者-年份匹配。
3. **姓名顺序**：`Kipf T N` / `Kipf, Thomas N` / `Thomas N Kipf` 三种都要能取到姓 `Kipf`。
4. **跨语言同一篇**：中文题名 + 英文题名可能是同一篇的翻译，去重时**只在给定翻译对 + 一个佐证信号时才合并**，否则保留两条并标 `ambiguous`。
