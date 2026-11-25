# 错误目录：每条规则的日志签名、根因与可采取的动作

规则 id 是稳定标识，出错时看 `result.json` → `diagnostics.items[].rule` 或
`static-checks.json` → `findings[].rule`。分两类：

- **`E-*` / `W-*`**：来自编译日志，需要真实编译才会出现。
- **`S-*` / `C-*` / `G-*` / `I-*` / `T-*` / `M-*` / `P-*` / `X-*` / `A-*`**：来自源码静态分析，
  不需要编译器。**「编不过」有一半原因在这一类里**，基础 Agent 通常完全看不到它们。

---

## 一、编译期：阻断性错误

### `E-FILE-ENDED-SCANNING`
日志签名：`! File ended while scanning use of \X.`（或 `<file>:N: File ended while scanning use of \X`）
TeX 报的位置：文件末尾。
根因：某个 `{`、`[` 或 `\begin{...}` 没闭合，TeX 一直读到 EOF 还在找参数结尾。
本 Skill 的处理：对该文件做括号平衡，报**第一个未闭合 `{` 的行号**（`brace_balance()`），
并允许 `R-CLOSE-BRACE` 在该行行尾补 `}`。
**要点**：不要照着日志的「末尾」去改；那只是症状。

### `E-EXTRA-CLOSE-BRACE`
日志签名：`! Too many }'s.`、`! Argument of \@array has an extra }.`、
`Parse error ... extra }`。
根因：`}` 关了一个从未打开的组；第一个「多出来的 `}`」通常才是原因。
处理：`brace_balance()` 返回负深度时，由 `brace_extra_closes()` 定位到具体行，
`R-REMOVE-EXTRA-BRACE` 删掉这一个字符。

### `E-RUNAWAY-ARGUMENT`
日志签名：`Runaway argument?` 后接被吞掉的内容，再 `! Paragraph ended before \X was complete.`
根因：与上两条同源（少了 `}` 或多了 `{`），但 TeX 把它当成「参数太长」。
处理：归到 brace 修复；**不要**去改 `\X` 的定义或加 `\long`。

### `E-MISSING-PKG`
日志签名：`! LaTeX Error: File `foo.sty' not found.`
根因：宏包未安装，或 `\usepackage` 拼错。
处理：`kpsewhich foo.sty` 查证。
- 查得到 → `R-ADD-PACKAGE` 在导言区末尾插 `\usepackage{foo}`，**重编译验证**。
- 查不到 → **不打补丁**，输出 `tlmgr install foo` 作为环境动作；记 `unresolved`。
  往源码里加一个不存在的宏包只会把错误推迟一行。

### `E-UNDEFINED-CS`
日志签名：`! Undefined control sequence.` + `l.<n> \macro`（或 `-file-line-error` 形式）。
根因三分：① 宏来自未加载的宏包；② 拼写错误；③ `\newcommand` 定义丢了。
处理：`MACRO_PACKAGES` 表把常见宏映射到宏包（`\toprule`→booktabs、`\SI`→siunitx、
`\mathbb`→amssymb、`\cref`→cleveref、`\bm`→bm、`\multirow`→multirow…约 120 条）。
有映射 → 走 `E-MISSING-PKG` 的流程；无映射 → `confidence: medium`，交人工。

### `E-ENV-UNDEFINED`
日志签名：`! LaTeX Error: Environment foo undefined.`
根因：环境由未加载的宏包提供（`align`→amsmath、`tikzpicture`→tikz、
`longtable`→longtable、`theorem`→amsthm…）。
处理：同 `E-MISSING-PKG`。

### `E-MATH-MODE`
日志签名：`! Missing $ inserted.`、`! Extra }, or forgotten $.`
根因：`_`、`^`、希腊字母、数学算符出现在数学模式之外，或 `$` 没成对。
处理：只在**该行完全没有 `$`** 时才尝试 `R-WRAP-MATH`（把数学片段包进 `$...$`），
`confidence: low`，必须重编译验证；行内已有 `$` 则交人工——成对关系要人看上下文。

### `E-ALIGNMENT-TAB`
日志签名：`! Misplaced alignment tab character &.`
根因：`&` 在表格/`align` 之外被当成单元格分隔符，或该用转义 `\&`。
处理：该行不含 `tabular`/`align` 时 `R-ESCAPE-AMP`；否则交人工（可能真是对齐制表符）。

### `E-MACRO-REDEFINED`
日志签名：`! LaTeX Error: Command \foo already defined.`
根因：两个宏包定义同名宏，加载顺序或选项决定谁生效。
处理：只报告，给出冲突双方；改加载顺序属于模板决策，交人工。

### `E-CAPACITY`
日志签名：`! TeX capacity exceeded, sorry [main memory size=…]`
根因：宏递归，或单页内容过大。报的行号是「撞上限的地方」，不是循环起点。
处理：只报告。**不要**建议调大 `main_memory` 了事。

### `E-FONT-NOT-FOUND`
日志签名：`! Font \foo=x not loadable: Metric (TFM) file not found.` /
`! Package fontspec Error: The font "X" cannot be found.`
根因：字体或字体度量未安装 —— **环境缺口，不是源码缺陷**。
处理：只报告，给出候选回退方案供人决定；**不自动换字体**（会改变版式）。

### `E-MISSING-CLASS`
日志签名：`! LaTeX Error: File `journal.cls' not found.`
根因：模板类文件既不在工程里也不在发行版里 —— 这是模板类投稿最常见的「换台机器就编不过」。
处理：查工程内是否有同名 `.cls`（有则建议 `\documentclass` 改为本地引用），否则交人工。
**绝不自动换成 `article`**：那等于换了模板。

### `E-BIB-MISSING`
日志签名：`! I can't find file `main.bbl'.` / `Package biblatex Error: File 'main.bbl' not created`
根因：参考文献后端没跑过，或 `.bib` 路径错。
处理：这是**构建计划**问题，不是源码问题 —— 改 `build_plan()` 加 bibtex/biber pass，
不改 `.tex`。

### `E-FATAL`
日志签名：`! Emergency stop.`、`!  ==> Fatal error occurred, no output PDF file produced!`
根因：几乎总是跟在一条真实错误之后。
处理：`cascade_parent` 指向前面第一条真实错误，**不单独修**；`summary.suppressed` 计数。

---

## 二、compile 期：警告（不阻断，但影响「改得对」）

| 规则 | 日志签名 | 含义 / 处置 |
|---|---|---|
| `W-UNDEF-REF` | `LaTeX Warning: Reference `x' on page N undefined` | 有 `\ref` 没 `\label`，PDF 会印 `??`。配合 `X-REF-WITHOUT-LABEL`。 |
| `W-UNDEF-CITE` | `LaTeX Warning: Citation `k' undefined` | `.bib` 里没有该键。配合 `C-CITE-NO-ENTRY`。 |
| `W-OVERFULL` | `Overfull \hbox (37.2pt too wide) in paragraph at lines a--b` | 溢出。`analyse_overfull()` 按 pt 降序，并区分 `paragraph` 与 `table-or-alignment`。**表格溢出不要 resizebox**。 |
| `W-MISSING-CHAR` | `Missing character: There is no X in font Y!` | 字体缺字（常见于 CJK 与特殊符号）。换字体或补字形，交人工。 |
| `W-FONT` | `LaTeX Font Warning: Font shape ... undefined` | 版式回退（如粗斜体缺失），通常可忽略但要记录。 |
| `W-PACKAGE` | `Package foo Warning: ...` | 宏包级警告，按宏包语义处理，不统一套用。 |

`summary.suppressed` 与 `cascade_parent` 让「1 个根因 + 9 条噪声」和「10 个独立错误」
在报告里长得不一样——这是「不停在第一条报错」的落地方式。

---

## 三、静态：结构（不需要编译器，`--no-build` 也有）

| 规则 | 证据 | 说明 |
|---|---|---|
| `S-BRACE-UNCLOSED` | `brace_balance()` 正深度 | 报每个未闭合 `{` 的行号与片段。跳过注释、`\%`、verbatim 类环境。 |
| `S-BRACE-EXTRA` | `brace_balance()` 负深度 | `}` 多于 `{`。 |
| `S-ENV-UNCLOSED` | `env_balance()` | `\begin{x}` 没有配对 `\end{x}`。 |
| `S-ENV-STRAY-END` | `env_balance()` | `\end{x}` 没有配对 `\begin{x}`。 |
| `S-MATH-UNBALANCED` | `math_balance()` | 未转义 `$` 为奇数个。 |
| `S-DISPLAY-UNBALANCED` | `math_balance()` | `\[` 与 `\]` 数量不等。 |

---

## 四、静态：引用与文献

| 规则 | 说明 | auto_fixable |
|---|---|---|
| `C-CITE-NO-ENTRY` | `\cite{k}` 但任何 `.bib` 都没有 `k`。**不生成条目**，交人工。 | 否 |
| `C-BIB-MISSING` | `\bibliography{refs}` 指向的 `refs.bib` 不存在 | 否 |
| `C-BIB-MALFORMED` | `.bib` 大括号不平衡或条目截断 —— bibtex 会直接失败 | 否 |
| `C-BIB-FIELD-MISSING` | 条目缺 `author`/`title`/`year` 等必填字段 | 否 |
| `X-REF-WITHOUT-LABEL` | `\ref{k}` 但全工程无 `\label{k}` | 否 |
| `X-DUPLICATE-LABEL` | 同一 `\label` 出现多次 | 否 |
| `X-LABEL-UNUSED` | 有 `\label` 没人 `\ref` | 否 |
| `X-LABEL-BEFORE-CAPTION` | 浮动体里 `\label` 在 `\caption` 之前 → 引用到的是节号而非图表号 | **是**（`R-LABEL-AFTER-CAPTION`） |

---

## 五、静态：表格与浮动体

| 规则 | 说明 | auto_fixable |
|---|---|---|
| `T-CELL-MISMATCH` | 某行单元格数与列声明不符（`\multicolumn{n}` 按 n 折算）。会让列整体错位并溢出。 | 否（要人决定多余单元格去哪） |
| `T-WIDTH-RISK` | 列数 ≥9 或最长行 >260 字符 → 极可能超 `\textwidth`。建议 tabularx / `p{}` / `sidewaystable`。 | 否 |
| `T-SCALED-TO-FIT` | `\resizebox`/`\scalebox`/`\adjustbox` 包住表格 → **把溢出藏起来**，字号也不再统一。 | 否（但从不自动引入） |
| `T-LONGTABLE-NO-HEAD` | `longtable` 无 `\endfirsthead`/`\endhead`，跨页续表没有表头 | 否 |
| `T-UNCLOSED` | `\begin{tabular}` 无 `\end{tabular}` | 否 |
| `T-NO-COLSPEC` | 列声明读不出来，单元格数无法核对 | 否 |

---

## 六、静态：公式

| 规则 | 说明 | auto_fixable |
|---|---|---|
| `M-LEFT-RIGHT` | `\left` 与 `\right` 数量不等 | 否 |
| `M-UNIT-ITALIC` | 数学模式里出现「数字+单位」（`$E = 3.2 J$`）→ 单位被排成斜体数学体，间距也不对。建议 `\SI{}{}` | 否 |
| `M-ALIGN-NO-AMP` | `align`/`eqnarray` 里没有 `&` → 只有一列右对齐，不是关系对齐 | 否 |
| `M-DUPLICATE-LABEL` | 公式环境里重复 `\label`，`\eqref` 取哪一个取决于 `.aux` 顺序 | 否 |

---

## 七、静态：模板与文件存在性

| 规则 | 说明 | auto_fixable |
|---|---|---|
| `P-NO-MAIN` | 没有含 `\documentclass` 的入口文件 | 否 |
| `P-CORE-MISSING` | 缺 `\documentclass` / `\begin{document}` / `\end{document}` | 部分 |
| `P-TITLE-MISSING` / `P-AUTHOR-MISSING` | 用了 `\maketitle` 但没设标题/作者 | 否 |
| `P-CLASS-UNAVAILABLE` | `.cls` 既不在工程也不在发行版（`kpsewhich` 查证） | 否 |
| `P-CLASS-OPTION-UNKNOWN` | `\documentclass` 的选项不在该类文件 `\DeclareOption` 里 → 被静默忽略，版式与模板意图不同 | 否 |
| `P-BIB-NOT-WIRED` | 有 `\cite` 但没有 `\bibliography`/`\printbibliography` | 否 |
| `P-ABSTRACT-NOT-ENV` | 出现 "abstract" 字样但不是 `abstract` 环境 | 否 |
| `G-GRAPHIC-MISSING` | `\includegraphics` 解析不到文件（按 `.pdf/.png/.jpg/.eps` 与 `\graphicspath` 逐一试） | 否 |
| `I-INCLUDE-MISSING` | `\input`/`\include` 指向的文件不存在 | 否 |

---

## 八、完整性（交付前闸门）

| 规则 | 含义 |
|---|---|
| `A-CONTENT-REMOVED` | `\cite`/`\ref`/`\label`/`\includegraphics`/公式/`\caption` 出现次数**减少** |
| `A-SUPPRESSION-INTRODUCED` | 新引入 `\sloppy`、`\tolerance=9999`、`\hbadness`、`\vfuzz`、`\iffalse`、`\tracingall`、源码内 `\nonstopmode`/`\batchmode`/`\scrollmode` |
| `A-TEXT-SHRUNK` | 单文件非空白字符减少 >3% |

命中任何一条 → `integrity.clean = false`、`status = partial`。这三条规则存在的原因只有
一个：**「编过」不能靠把内容删掉或把警告压掉来获得。**
