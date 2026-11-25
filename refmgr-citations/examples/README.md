# 最小调用示例（示意，非正式案例结果）

目录内容：
```
examples/
├── README.md              本文件
├── input/
│   ├── case.json          Harbor 风格 case 定义（示意）
│   ├── task.md            任务：去重 + 重排 + 转 GB/T 7714 + 核验
│   ├── manuscript.md      稿件：乱序编号 [3][1][2,4]，一条编造引用 [7]
│   └── library.bib        文献库：6 条，含 Brown 2020 的正式版与 arXiv 版重复
├── model/
│   └── claim_matches.json 模型 Step 5 的论断判定（示意）
└── output/                运行后的产物（示意输出，由本示例输入真实生成）
```

## 调用
```bash
# Harbor 环境
python /skills/weekly-skill/scripts/run_case.py --input /input --out /app/output \
    --task "renumber+dedup+convert:gbt7714+verify+consistency" \
    --claim-matches /app/work/claim_matches.json

# 本地复现本示例
python scripts/run_case.py --input examples/input --out examples/output \
    --task "renumber+dedup+convert:gbt7714+verify+consistency" \
    --claim-matches examples/model/claim_matches.json
```

## 这份输入里埋了什么
| 现象 | 位置 | 期望处置 |
|---|---|---|
| 乱序编号 | 正文首段 `[3]…[1]…[2,4]` | 按首次出现重排为 `[1]…[2]…[3,4]`，列表重建 |
| 重复条目 | `brown2020`（NeurIPS）与 `brown2020arxiv`（arXiv） | 合并（title_exact + authors + year），保留正式版，`merge_basis` 记录 |
| 中英文混排 | `zhang2020` 中文条目 | GB/T 用全角标点、作者写全名 |
| `and others` | Brown 的作者字段 | 丢弃 `others`，GB/T 输出 `BROWN TB` |
| 图注引用 | `图 1 …（引自[1]）` | 作为正文引用参与重排 |
| 编造条目 | 正文 `[7]` → 文末表第 7 条，库中无 | 保留进列表为 `U007`，标 ⚠，verify error，status=partial |
| 一句多引 | `[2,4]` | 保留为一个标记，重排为 `[3,4]` |

## 示意输出（节选，实际由 `examples/output/result.json` 生成）
```
dedup:    {'input': 7, 'output': 6, 'merged': 1}
renumber: order ['R003','R001','R002','R004','R005','U007'] → 1..6 ; 9 marker edits
verify:   errors=1 (U007 not_in_library) warnings=3 (missing volume/pages)
claims:   10 pairs → supported/mismatch/insufficient 由 claim_matches.json 决定
status:   partial — 编造条目与字段缺失需人工确认
```

改稿正文：
```
深度学习方法在诸多领域取得了突破[1]。Transformer 架构摒弃了循环结构[2]，并已成为主流骨架。许多后续工作对其进行了扩展[3,4]。
近年来，大规模预训练模型[2] 引起了广泛关注。图注中的引用如图 1 所示（数据来源[3]）。
图 1 示意图（引自[2]）
…
[6] Unknown Author. Nonexistent Paper on Efficiency[J]. Journal of Nothing, 2099  [⚠ 未在文献库中找到对应条目，需人工核验]
```
