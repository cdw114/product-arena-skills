# 修复许可：什么可以自动改，什么必须交给人

这个 Skill 的价值一半在「能修」，另一半在「知道什么时候不该修」。本文是自动补丁的
许可边界，代码里由两道闸门执行：`texlib.guard_patch()`（补丁前）与
`checks.anti_cheat()`（交付前）。

---

## 一、自动补丁白名单（`auto_fixable = true`）

只允许动**声明、定界符、转义、加载顺序**。当前实现有 6 条：

| 规则 | 动作 | 前提 | 风险 |
|---|---|---|---|
| `R-ADD-PACKAGE` | 在导言区最后一个 `\usepackage` 之后插入 `\usepackage{pkg}` | `kpsewhich` 能找到该宏包；且未加载过 | 低 |
| `R-CLOSE-BRACE` | 在第一个未闭合 `{` 所在行行尾补 `}` | 该文件括号深度为正，且未闭合栈非空 | 中（补的位置可能不对，靠重编译验证） |
| `R-REMOVE-EXTRA-BRACE` | 删掉行内最后一个未被转义的 `}` | 该文件括号深度为负 | 中 |
| `R-WRAP-MATH` | 把行内数学片段包进 `$...$` | **整行没有任何 `$`** | 中，`confidence: low` |
| `R-ESCAPE-AMP` | 把 `&` 改成 `\&` | 该行不在 `tabular`/`align` 上下文 | 低 |
| `R-LABEL-AFTER-CAPTION` | 把 `\label` 移到 `\caption{...}` 之后 | 浮动体内 label 位置早于 caption | 低 |

**每一个都必须通过重编译验证**（见下节）。白名单里没有的东西，脚本不会去改。

---

## 二、被拒绝的补丁（`guard_patch` 直接返回 false）

1. **删掉含关键标记的整行。** 若 `replace_line` 的新内容为空且旧行含
   `\cite` / `\citep` / `\citet` / `\ref` / `\eqref` / `\autoref` / `\label` /
   `\begin{equation` / `\begin{align` / `\includegraphics` / `\section` /
   `\subsection` / `\caption` —— 拒绝。
2. **格式非法的 `\usepackage`。** 例如插入内容里出现 `\usepackage{a\b}`。
3. **空改动。** 新旧相同的 `replace_line`。
4. **行内容不匹配。** `replace_line` 要求旧行文本与文件当前内容一致；不一致就拒绝，
   **绝不覆盖**——这是「不在别人刚改过的文件上盲写」的保护。

---

## 三、验证式接受/回滚（核心机制）

```
S0 = 当前诊断指纹
apply(patch) → 重编译 → S1 = 新指纹
S1 > S0  ?  保留，记 applied[].verified = true
         :  回滚文件，记 rejected[].why = "no improvement in the diagnostic set"
```

指纹 `diag_fingerprint()` 是四元组，按字典序比较：

```
(-阻断性错误数, -警告数, -错误数, 是否产出 PDF)
```

设计意图：**先把「编不过」变成「编得过」**（第 4 位），再逐层减少错误与警告。
一条补丁即使「在道义上正确」但没让指纹变好，也会被回滚——因为它没被证明。

已被回滚的补丁记入 `tried` 集合，后续迭代**不再尝试**，所以不会出现
「改一下、又改回去」的抖动。

---

## 四、必须交给人（`auto_fixable = false`）及理由

| 情形 | 为什么不能自动改 |
|---|---|
| 缺 `.bib` 条目（`C-CITE-NO-ENTRY`） | 生成文献条目等于伪造来源。只能报告缺哪个键、在哪一行引的。 |
| 缺图片（`G-GRAPHIC-MISSING`） | 不能凭空造图；也不能静默删掉 `\includegraphics`。 |
| 缺 `\input` 子文件（`I-INCLUDE-MISSING`） | 缺的是正文，补一段就是编造内容。 |
| 缺 `.cls`（`P-CLASS-UNAVAILABLE`） | 换成 `article` 等于换模板，版式全部改变。 |
| 缺字体（`E-FONT-NOT-FOUND`） | 换字体同样改变版式与度量。 |
| 单元格数与列数不符（`T-CELL-MISMATCH`） | 多余单元格是「该删数据」还是「该加一列」由作者决定。 |
| 宽表（`T-WIDTH-RISK`） | 改 `tabular`→`tabularx`、换 `p{}`、转 `sidewaystable` 是三种不同版面决策。 |
| `\left`/`\right` 不平衡（`M-LEFT-RIGHT`） | 补哪一侧、补什么定界符需要看公式语义。 |
| 单位写成斜体（`M-UNIT-ITALIC`） | 是否引入 `siunitx` 取决于模板是否允许额外宏包。 |
| 宏重定义（`E-MACRO-REDEFINED`） | 谁赢取决于模板约定。 |
| `TeX capacity exceeded`（`E-CAPACITY`） | 报的位置不是根因，需要看宏展开链。 |
| 模板必填项缺失（`P-*`） | 缺的是作者信息、基金号、关键词等**事实**，不能编。 |

这些一律进入 `result.json` 的 `human_review`（带 `file`/`line`/`why`）与
`uncertainties`，同时把 `status` 降到 `partial`。

---

## 五、明确禁止的「修复」手段

这些手段会「让编译过去」，但都是把问题藏起来。`anti_cheat()` 会检测**新引入**的这些命令：

| 手段 | 后果 | 检测 |
|---|---|---|
| 删掉报错的那段内容 / 用 `\iffalse ... \fi` 注释掉 | 正文缺失，产物不可用 | `A-CONTENT-REMOVED`、`A-SUPPRESSION-INTRODUCED` |
| `\resizebox{\textwidth}{!}{...}` 包表格 | 溢出仍在，字号与全文不一致 | `T-SCALED-TO-FIT`（且本 Skill 从不自动引入） |
| `\sloppy`、`\tolerance=9999`、`\hbadness=10000` | 只让警告消失，断行更差 | `A-SUPPRESSION-INTRODUCED` |
| 源码里写 `\nonstopmode` / `\batchmode` | 让编译器不再停下来报错 | `A-SUPPRESSION-INTRODUCED` |
| 删 `\cite` 让其对应的 undefined citation 消失 | 引用丢失 | `A-CONTENT-REMOVED` |
| 删 `\label` 让 duplicate label 消失 | 交叉引用失效 | `A-CONTENT-REMOVED` |
| 交 PDF / 截图给「源码」 | 无法继续编辑 | 交付物必须是 `fixed/*.tex`（PDF 是附带产物，不是替代品） |

---

## 六、升级路径（什么情况下应该停下来）

满足任一条就停止自动修复，写清原因并交人工：

1. 连续 `--max-iter` 轮没有任何补丁让指纹变好（`REPAIR-EXHAUSTED`）。
2. 剩余错误全部属于「必须交给人」那张表。
3. 某条补丁被回滚过，且它是某类错误唯一的候选（再试只是抖动）。
4. 编译超时或触及 `--budget`。
5. 完整性检查报错（先解决「内容去哪了」，再谈编译）。

停下来不是失败：`partial` + 明确的 `status_reason` + 可继续工作的 `fixed/` 与
`report.md`，比一个「看起来编过了但内容少了三行」的 `success` 有价值得多。
