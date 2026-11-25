# LaTeX 编译诊断与修复报告

| 项 | 值 |
|---|---|
| case_id | `example-01` |
| 状态 | **partial** |
| 主文件 | `main.tex` |
| 引擎 | `pdflatex`（default for Latin-script documents） |
| 参考文献后端 | `bibtex` |
| 是否编译成功 | 否 |
| 页数 | - |
| 编译轮次 | 0 |
| 补丁：应用 / 回滚 / 未解决 | 0 / 0 / 1 |

## 状态说明

没有可用的 TeX 引擎，本次只做了静态诊断与结构审计，未实际编译。 静态检查仍有 6 条 error 级问题（多为无法自动修的引用/表格/字体问题）。

## 诊断：修前 vs 修后

| 指标 | 修前 | 修后 |
|---|---|---|
| 结构性问题（大括号/环境/数学定界） | 1 | 1 |
| 日志诊断条目 | - | 9 |
| 其中级联（归并到根因） | - | 0 |
| 静态检查 error / warning | 6 / 2 | 6 / 2 |

### 结构性问题（不需要编译器就能看到）

- **S-BRACE-UNCLOSED** `sections/intro.tex` 第 10 行起 — 1 '{' never closed. TeX reports this at end of file, not here.
  - 未闭合：第 10 行 `The classical model assumes a continuous medium {and neglects interface scatteri`

### 日志诊断（按修复顺序）

本次未编译（环境无 TeX 引擎），诊断由源码结构推导，见下表与「静态检查明细」。

## 补丁（每条都经重新编译验证）

无。

## 完整性（防止“用删除换编译通过”）

通过：没有 \cite/\ref/\label/公式/图表被删除，也没有引入 \sloppy、\iffalse 这类掩盖手段。

## 静态检查明细（不依赖编译器）

| 规则 | 级别 | 位置 | 说明 |
|---|---|---|---|
| `C-CITE-NO-ENTRY` | error | `sections/intro.tex:8` | \cite{wang2021} but no .bib entry has that key; BibTeX leaves it as [?] |
| `G-GRAPHIC-MISSING` | error | `sections/results.tex:8` | \includegraphics{figures/conductivity-vs-thickness} resolves to no file; pdfTeX stops with 'File not found' |
| `I-INCLUDE-MISSING` | error | `main.tex:-` | \input/\include{sections/discussion-missing} names a file that is neither in the project nor on the TeX search path |
| `T-CELL-MISMATCH` | error | `sections/method.tex:17` | row 3 has 5 cells but the preamble declares 4 columns; the extra '&' shifts every later column and usually pushes the table past the margin |
| `X-LABEL-BEFORE-CAPTION` | error | `sections/results.tex:9` | \label comes before \caption inside a float, so it captures the enclosing section counter and every \ref to the figure prints the wrong number |
| `X-REF-WITHOUT-LABEL` | error | `sections/results.tex:13` | \ref{tab:param} has no \label{tab:param} anywhere in the project, so the compiled PDF prints '??' |
| `M-ALIGN-NO-AMP` | warning | `sections/method.tex:40` | align without '&' produces one right-aligned column instead of aligned relations |
| `M-UNIT-ITALIC` | warning | `sections/method.tex:35` | a number-with-unit appears inside math mode, so the unit is typeset in italic math font and the spacing is wrong |

## 还需要人确认的（Skill 不猜）

- **C-CITE-NO-ENTRY** `sections/intro.tex:8` — \cite{wang2021} but no .bib entry has that key; BibTeX leaves it as [?]
- **G-GRAPHIC-MISSING** `sections/results.tex:8` — \includegraphics{figures/conductivity-vs-thickness} resolves to no file; pdfTeX stops with 'File not found'
- **I-INCLUDE-MISSING** `main.tex:-` — \input/\include{sections/discussion-missing} names a file that is neither in the project nor on the TeX search path
- **T-CELL-MISMATCH** `sections/method.tex:17` — row 3 has 5 cells but the preamble declares 4 columns; the extra '&' shifts every later column and usually pushes the table past the margin
- **X-LABEL-BEFORE-CAPTION** `sections/results.tex:9` — \label comes before \caption inside a float, so it captures the enclosing section counter and every \ref to the figure prints the wrong number
- **X-REF-WITHOUT-LABEL** `sections/results.tex:13` — \ref{tab:param} has no \label{tab:param} anywhere in the project, so the compiled PDF prints '??'

## 不确定与限制

- 本机没有 TeX 引擎，编译结论未经实际运行验证；静态诊断基于源码结构与 TeX 日志语法。
- 有 1 个 \cite 键在任何 .bib 里都找不到：wang2021。这需要作者或文献库补齐，Skill 不会凭空生成条目。
- ENV-NO-ENGINE: No TeX engine is installed in this environment, so the compile loop could not run. Everything below is static analysis on the sources; the diagnostics are what a compiler would report, derived from th

## 怎么复现这份产物

```bash
cd fixed
bash ../repro/build.sh
```

引擎、宏包版本与每个输入文件的 sha256 记在 `repro/versions.txt`。
