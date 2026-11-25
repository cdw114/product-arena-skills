# examples/ — 手工示例（**不是**平台固定案例的结果）

```
input/    一个真实形状的小论文工程，故意留了 6 类缺陷
output/   用 `--no-build`（静态模式）跑出来的示意输出
```

## 为什么要有这个目录

题目要求「最小调用示例：至少一组输入、调用方式和示意输出；示意输出须标明为示例」。
这里就是那一组。它证明的是**接口与产物形状**，不是任何案例的分数或效果。

## 输入里埋了什么

| 位置 | 缺陷 | 会触发 |
|---|---|---|
| `paper/sections/intro.tex:10` | `{` 没闭合（TeX 会报在文件末尾） | `S-BRACE-UNCLOSED` |
| `paper/sections/intro.tex:7` | `\cite{wang2021}`，但 `refs.bib` 里只有 `chen2019/liu2020/smith2018` | `C-CITE-NO-ENTRY` |
| `paper/main.tex` | `\input{sections/discussion-missing}` 指向不存在的文件 | `I-INCLUDE-MISSING` |
| `paper/sections/method.tex:17` | 表格声明 4 列，该行写了 5 个单元格 | `T-CELL-MISMATCH` |
| `paper/sections/method.tex:35` | `$E = 3.2 J$` 单位排在数学斜体里 | `M-UNIT-ITALIC` |
| `paper/sections/method.tex:40` | `align` 里没有 `&` | `M-ALIGN-NO-AMP` |
| `paper/sections/results.tex:8` | `\includegraphics` 指向不存在的图 | `G-GRAPHIC-MISSING` |
| `paper/sections/results.tex:9` | 浮动体里 `\label` 在 `\caption` 之前 | `X-LABEL-BEFORE-CAPTION`（唯一可自动修的一类） |
| `paper/sections/results.tex:13` | `\ref{tab:param}`，实际标签是 `tab:params` | `X-REF-WITHOUT-LABEL` |

## 怎么跑出来的

```bash
python3 scripts/doctor.py --input examples/input --out examples/output \
    --work .example-work --no-build
```

`--no-build` 是因为**编写这个 Skill 的机器没有 TeX 发行版**（`probe_engines()` 报
`any_engine: false`）。所以：

- `output/result.json` 的 `build.attempted` 是 `false`，`status` 是 `partial`；
- `output/diagnostics.json` 的诊断 `source` 是 `static`，由源码结构推导；
- 没有任何页数、耗时、分数——**这些数字在被真实编译之前不存在**。

在有 `pdflatex` 的镜像里去掉 `--no-build` 重跑，就会多出 `main.pdf`、`preview/`、
`build/pass-*.log` 与 `fixes/` 里被 `verified: true` 标过的补丁。

## 示例输出里值得看的三处

1. `report.md` 的「结构性问题」——**不需要编译器**就能指到 `intro.tex:10`，
   而不是像 TeX 那样报在文件末尾。
2. `result.json` → `contract.satisfied` 全为 `native`，说明 6 个声明字段都被原生满足。
3. `fixes/patches.json` → `applied` 为空、`unresolved` 非空：静态模式下循环不跑，
   脚本没有假装修了什么。这是刻意的诚实默认值。
