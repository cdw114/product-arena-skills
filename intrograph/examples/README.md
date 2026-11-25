# 最小示例（**示例**，不是正式案例结果）

这里的输入是**虚构**的，输出是**示意**的。它只用来展示接口和完整使用流程，不代表任何真实论文，也不是平台的正式测试结果。

## 1. 输入

```
examples/input/
├── case.json       case_id / task / target_lang / citation_style / output_contract
├── task.md         任务说明：四部分、分组比较、空白要有出处、贡献要对图表、英文数字制、900-1200 词
├── manuscript.md   虚构论文：Graph Coreset Pretraining（含摘要、5 节、2 图 3 表、10 条文末参考文献）
├── library.bib     10 条文献（含 1 对 arXiv/正式版重复，用于演示去重），每条带 abstract
└── notes.md        作者笔记（只作背景，不作事实来源）
```

关键点：`manuscript.md` 的**文末参考文献表有 10 条**，与 `library.bib` 一一对应——这是数字制 `[n]` 能被解析成具体文献的前提。

## 2. 调用

```bash
# 第 1 步：建账（0 次模型调用，约 0.1 s）
python3 scripts/run_case.py --input examples/input --out /tmp/out --work /tmp/work --stage plan

# 第 2 步：把示例账本放进工作目录（真实使用时这一步由模型填写）
cp examples/ledgers/ledger_*.json /tmp/work/ledgers/
#         把示例成稿放进工作目录
cp examples/fixtures/draft_good.md /tmp/work/draft.md

# 第 3 步：核对 + 定稿
python3 scripts/run_case.py --input examples/input --out /tmp/out --work /tmp/work --stage finalize
```

## 3. 示意输出（节选）

`/tmp/out/result.json`（节选）：

```jsonc
{
  "case_id": "gcp-example-001",
  "status": {"state": "success", "gate": "pass",
             "reason": "18 项确定性核对全部通过（0 error，0 warning）。", "limits": []},
  "task": {"lang": "en", "citation_style": "numeric", "intent": {"mode": "draft"}},
  "result": {"parts": {"background": {"present": true, "paragraphs": 3},
                       "related_work": {"present": true, "paragraphs": 3},
                       "gap": {"present": true, "paragraphs": 2},
                       "contributions": {"present": true, "paragraphs": 6}},
             "chars": 6611, "n_distinct_refs": 10, "n_groups": 3, "n_gaps": 2, "n_contributions": 4,
             "reference_numbering": {"R0001": 1, "R0002": 2, "...": "..."}},
  "audit": {"gate": "pass", "errors": 0, "warnings": 0, "report_file": "audit_report.md"},
  "inputs": {"library": {"n": 10, "fallback": "none"},
             "contract_filling": {"aliased": [], "unfilled": []}}
}
```

`/tmp/out/related_work_table.md`（节选，一组）：

```markdown
### Selecting a subset of the unlabelled pool

Dimension: what signal drives selection, and what it optimises

| Work | Method route | Data / setting | Evaluation | Conclusion | Limitation |
|---|---|---|---|---|---|
| Sener 2018 | k-centre greedy selection in a fixed embedding | image classification and segmentation | error bound relative to the full set | a bounded k-centre subset reproduces full-set error | the guarantee holds for a fixed feature space only |
| Liu 2024 | per-molecule informativeness for the label budget | unlabelled pool + 100-label downstream task | downstream accuracy vs random pretraining | label-aware selection gains up to 8.6% | selection ignores the cost of the corpus itself |

**Trade-off**: R0007 optimises coverage of a feature space that does not yet exist, R0009 optimises for the label budget but treats the corpus as free — none optimises the cost of pretraining itself.
```

`/tmp/out/refs_cited.txt`（节选，英文数字制 → IEEE，编号与正文一致）：

```
[1] T. N. Kipf and M. Welling, "Semi-supervised classification with graph convolutional networks," in Proc. International Conference on Learning Representations, 2017. doi: 10.48550/arXiv.1609.02907.
[2] J. Gilmer, S. S. Schoenholz, P. F. Riley, et al., "Neural message passing for quantum chemistry," in Proc. International Conference on Machine Learning, pp. 1263-1272, 2017. doi: 10.48550/arXiv.1704.01212.
```

自测运行的关键产物在 `execution/results/clean_en/`（由 `python3 src/reproduce.py` 生成）：`result.json`、`audit_report.json`、`introduction_related_work.md`、`related_work_table.md`、`refs_cited.txt`。自己按上面三条命令跑一遍，会得到完整的一套（含 `citation_map.json`、`contribution_table.md`、`refs_cited.bib`、四本账副本）。

## 4. 缺陷稿对照（题集的用法）

```bash
# 同一份输入，换成缺陷稿 + 缺陷账本
python3 src/reproduce.py        # 场景 2 会自动组装并跑这一组
```

`examples/fixtures/defects.json` 里 21 条缺陷逐条给出植入方式与期望命中的 `(规则, 代码)`。缺陷稿会得到 `gate=fail`、21 error / 12 warning，例如：

| 植入 | 命中 |
|---|---|
| `\cite{zhang2024phantom}` | R01 `invented_citation` |
| 相关工作连续 3 段各讲一篇、无比较词 | R08 `serial_summary_pattern` |
| 空白 PG1 的依据引文是编的 | R10 `unverifiable_quote` |
| 贡献 C2 指向 `Table 9` | R12 `evidence_table_missing` |
| 贡献段出现 `27.4%`（稿件里没有） | R13 `invented_metric` |
| 缺 `<!-- part:gap -->` 段 | R14 `part_missing` |

## 5. 文件

```
examples/
├── README.md                          本文件
├── input/                             示例输入（虚构论文 + 文献库 + 笔记）
├── ledgers/                           示例账本：refs / groups / gaps / contributions
├── fixtures/
│   ├── draft_good.md                  干净稿（自测期望 0 error / 0 warning）
│   ├── draft_defective.md             缺陷稿（植入 21 条缺陷）
│   ├── ledger_groups.json             缺陷分组账（G1 无维度、R0004 缺 limitation）
│   ├── ledger_gaps.json               缺陷空白账（引文编造、来源未引）
│   ├── ledger_contributions.json      缺陷贡献账（表/图不存在、无证据、无 scope）
│   ├── library_extra_defective.bib    额外一条 DOI 非法的文献
│   └── defects.json                   植入缺陷题集（21 条 + 期望代码）
```
