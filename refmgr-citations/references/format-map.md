# format-map.md — 字段映射与目标规范渲染规则

规范模型 `Entry`（`refmgr.py`）字段：`ref_id, type, title, authors[], year, journal, volume, issue, pages, publisher, address, doi, url, isbn, issn, language, arxiv_id, note, abstract, keywords[], source_file, source_key, extra{}`。

## 1. 导入映射（外部格式 → `Entry`）

| Entry | BibTeX | RIS | JSON（常见键） | CNKI / 标签文本 |
|---|---|---|---|---|
| type | `@article` `@inproceedings` `@book` `@incollection` `@phdthesis` `@mastersthesis` `@techreport` `@misc` `@online` `@unpublished` | `TY - JOUR/CPAPER/BOOK/CHAP/THES/RPRT/UNPB/ELEC/DATA/COMP/GEN` | `type` `entry_type` `document_type` `item_type` | `Type` `文献类型` |
| title | `title` | `TI` `CT` | `title` `Title` | `Title` `题名` `篇名` |
| authors | `author`（` and ` 分隔；`others` 丢弃） | `AU` `A1`…（重复行） | `authors[]`（字符串或 `{family,given}`） | `Author` `作者` `Inventor`（`;` 分隔） |
| year | `year` | `PY`（取前 4 位） | `year` `date` `issued` | `Published` `出版年` `Date` |
| journal | `journal`；会议用 `booktitle` | `T2` `JO` `JF` `BT` | `journal` `container_title` `source` `booktitle` `venue` | `Source` `刊名` `Journal` `Conference` |
| volume / issue | `volume` / `number` | `VL` / `IS` | `volume` / `issue` `number` | `Vol` `卷` / `Issue` `期` |
| pages | `pages`（`--` → `-`） | `SP`+`-`+`EP` | `pages` `page` `page_range` | `Pages` `页码` |
| publisher / address | `publisher` / `address`；`institution` → publisher | `PB` / `CY` | `publisher` / `address` `city` | `Publisher` `出版者` / `Address` |
| doi | `doi` | `DO` | `doi`（去 `https://doi.org/`） | `DOI` |
| url | `url`；`howpublished` 含 http | `UR` | `url` `link` | `URL` `Link` |
| isbn / issn | `isbn` / `issn` | `SN`（ISSN 形态判定） | `isbn` / `issn` | `ISBN` / `ISSN` |
| arxiv_id | `eprint` + `archiveprefix=arXiv` | `UR` 含 arxiv.org | `arxiv_id` `eprint` | url 含 arxiv |
| language | `language`，缺省按题名+作者检测 | `LA` | `language` `lang` | `Language` `语种` |
| keywords | `keywords`（`;` 或 `,`） | `KW`（重复行） | `keywords[]` | `Keyword` `关键词` |
| school（学位授予单位） | `school` → journal | `PB` 或 `T2` | `school` | `School` `学校` |
| note | `note` | `N1` | `note` `notes` | `Notes` `备注` |

类型推断顺序：显式类型字段 → BibTeX 类型名 → RIS `TY` → 启发式（有 journal 无 publisher → journal-article；有 booktitle → conference-paper；url 含 arxiv → preprint；含 school → thesis）。

## 2. 文献类型标识（GB/T 7714—2015）

| 规范类型 | BibTeX | RIS | GB/T 代码 | APA |
|---|---|---|---|---|
| journal-article 期刊论文 | article | JOUR | `[J]` | 期刊 |
| conference-paper 会议论文 | inproceedings | CPAPER | `[C]` | Proceedings paper |
| book 专著 | book | BOOK | `[M]` | Book |
| book-chapter 析出文献 | incollection | CHAP | `[M]//` | Chapter |
| thesis-phd / masters 学位论文 | phdthesis / mastersthesis | THES | `[D]` | Dissertation / Master's thesis |
| tech-report 报告 | techreport | RPRT | `[R]` | Report |
| preprint 预印本 | misc(eprint) | UNPB | `[Z]` 或 `[J/OL]`（有 DOI 时） | Preprint |
| webpage 电子资源 | online | ELEC | `[EB/OL]` | Webpage |
| dataset 数据集 | dataset | DATA | `[DS]` | Data set |
| software 软件 | software | COMP | `[CP]` | Computer software |
| other 其他 | misc | GEN | `[Z]` | — |

## 3. 渲染规则

### 3.1 GB/T 7714—2015 顺序编码制
```
主要责任者. 题名[文献类型标识]. 其他责任者(可选). 出处信息. 年, 卷(期): 页码. DOI.
```
- 作者：≤3 全列，>3 列前 3 + `, et al`（英文）/ `, 等`（中文）。英文 `姓 首字母`（`VASWANI A, SHAZEER N`），中文写全名（`张英, 李明`）。
- 期刊：`题名[J]. 刊名, 年, 卷(期): 页.` → `Deep learning[J]. Nature, 2015, 521(7553): 436-444.`
- 会议：`题名[C]//会议录名. 地点: 出版者, 年. 页.` → `…[C]// NeurIPS. 2017.`
- 专著：`题名[M]. 地点: 出版者, 年. 页.`
- 析出：`题名[M]//书名. 地点: 出版者, 年. 页.`
- 学位论文：`题名[D]. 城市: 学校, 年.`
- 电子资源：`题名[EB/OL]. (年). URL.`
- DOI 在末尾 `DOI: 10.xxxx/yyy.`；中文条目用全角标点，西文半角。
- 文末列表每条前缀 `[n] `。

### 3.2 APA 7
```
姓, 首字母., 姓, 首字母., & 姓, 首字母. (年). 题名. *刊名*, 卷(期), 页. https://doi.org/…
```
- 1 作者 `Vaswani, A.`；2 作者 `Vaswani, A., & Shazeer, N.`；3–20 作者全列最后一个前 `&`；>20 前 19 + `. . . ` + 最后。
- 期刊：题名句式大写，刊名斜体、标题式大写，卷斜体。会议：`In 会议名 (页).` 书：`*书名*. 出版社.` 学位：`*题名* [Doctoral dissertation, 学校].` 预印本：`[Preprint]. 服务器.` 网页：`题名. URL`
- 无年份 `(n.d.)`。
- 列表按第一作者姓氏排序，无编号（著者—出版年制正文标记为 `(Vaswani, 2017)`）。

### 3.3 BibTeX / RIS 导出
由 `Entry.to_bibtex()` / `to_ris()` 按 §1 逆映射生成；DOI、arXiv（`eprint` + `archiveprefix`）、ISBN/ISSN、关键词全部保留；BibTeX 键用原 `source_key`，无则 `ref_id`。

## 4. 字段补齐策略
- 从被并条目补齐（去重时），不覆盖非空。
- 不从网络补齐（除非 `--online` 且 Crossref 返回了本地缺失的卷/期/页——当前版本**只比对不回填**，避免引入未经核验的数据）。
- 缺失字段进 `conversion.field_report[].missing`，由人决定是否补。
