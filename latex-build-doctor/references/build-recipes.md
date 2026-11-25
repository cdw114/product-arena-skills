# 构建配方：引擎、后端、轮次与可复现记录

本文回答「凭什么用这个引擎、跑这几遍、别人怎么得到同一份产物」。

---

## 一、引擎选择（`detect_engine()`）

按以下顺序判定，**第一个命中的就是结论**，并把依据写进
`build.engine.evidence`：

| 优先级 | 信号 | 结论 | confidence |
|---|---|---|---|
| 1 | `% !TEX program = xelatex` 之类魔法注释 | 注释指定的引擎 | high |
| 2 | `\documentclass{ctexart/ctexrep/ctexbook/ctexbeamer}` | `xelatex`（ctex 需要 Unicode 引擎） | high |
| 3 | `\documentclass{beamer}` | `pdflatex` | high |
| 4 | `\usepackage{fontspec}` | `xelatex`（fontspec 只能在 XeTeX/LuaTeX 下用） | high |
| 5 | `\usepackage{xeCJK}` / `\usepackage{ctex}` | `xelatex` | high |
| 6 | 源码含 CJK 码点但无任何 CJK 宏包 | `xelatex` + 提示补 CJK 宏包 | medium |
| 7 | 上一次日志的引擎横幅 | 沿用 | medium |
| 8 | 以上都没有 | `pdflatex` | medium |

`--engine NAME` 可强制覆盖（记录 `reason: forced by --engine`）。
选了 `latexmk` 但镜像里没有 → 自动回落到 `pdflatex` 并记录 `fallback`。

**为什么不用「试一遍所有引擎取能过的那个」**：换引擎会改变字体与断行，产物不同；
「能编过」不等于「编对了」。引擎必须是**从工程事实推出的**，不是撞出来的。

---

## 二、参考文献后端（`detect_bib_backend()`）

| 信号 | 后端 |
|---|---|
| `\usepackage[backend=bibtex]{biblatex}` | `bibtex` |
| `\usepackage{biblatex}`（无 backend 选项） | `biber`（biblatex 默认） |
| `\usepackage{natbib}` | `bibtex` |
| 有 `\bibliography{...}` | `bibtex` |
| 有 `\addbibresource{...}` | `biber` |
| 以上都没有 | `none`（不跑 bib pass） |

---

## 三、编译轮次（`build_plan()`）

不是固定「跑三遍」，而是由工程推导：

```
pass 1 : <engine> -interaction=nonstopmode -file-line-error -halt-on-error -synctex=1 main.tex
         ← 生成 .aux，建立 \label/\ref 骨架
bib    : bibtex main  或  biber main            （仅当后端不是 none）
         ← 把 .aux 的 \citation 变成 .bbl
pass 2 : <engine> ...  main.tex
         ← 从 .bbl 取 \bibitem 编号
pass 3 : <engine> ...  main.tex
         ← 定页码、收敛交叉引用
```

两个提前退出条件：

1. **致命错误 → 立即停止后续 pass。** 后面几遍只会重复同一条错误，白耗预算。
   判定：`severity in (fatal, missing-file)` 的诊断存在。
2. **`--budget`（默认 420 s）耗尽 → 停止并保留当前最好结果。**

`build.iterations[]` 记录每一轮：执行的 pass 数、`final_stats`（页数/字节/引擎横幅）、
诊断摘要、指纹、bib 命令与返回码。`build.pass_commands` 是**实际执行过**的命令。

`-file-line-error` 是刻意加的：它把 `! Undefined control sequence.` 变成
`./sections/x.tex:14: Undefined control sequence.`，**文件名与行号直接可用**，
不必再从括号栈里推断。解析器两种格式都支持（见 `texlib.FILE_LINE_ERROR_RE`）。

---

## 四、可复现记录（`repro/`）

`write_build_repro()` 生成四个文件：

### `versions.txt`（JSON）

```json
{
  "generated_by": "latex-build-doctor 1.0.0",
  "generated_at": "2026-01-01T00:00:00+08:00",
  "engine_chosen": {"engine": "xelatex", "reason": "fontspec loaded …", "evidence": ["…"]},
  "bib_backend": {"backend": "biber", "reason": "biblatex default backend is biber"},
  "tool_versions": {
    "xelatex": {"available": true, "path": "/usr/bin/xelatex",
                "version": "XeTeX 3.141592653-2.6-0.999995 (TeX Live 2023)"},
    "biber":   {"available": true, "version": "biber version: 2.19"}
  },
  "python": "3.11.6",
  "pass_commands": ["xelatex … main.tex", "biber main", "xelatex … main.tex"],
  "pass_seconds": [1.8, 0.4, 1.6],
  "packages": [{"file": "amsmath.sty", "name": "amsmath",
                "date": "2023/05/05", "version": "v2.17k"}]
}
```

`packages` 来自 `\listfiles` 块（`parse_listfiles()`）：`*pkg.sty` 行 + 后续
`Package: name date version`。这是**版本级**证据，比「我用了 TeX Live」有用得多。

### `build.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ENGINE="${ENGINE:-xelatex}"
"$ENGINE" -interaction=nonstopmode -file-line-error main.tex
biber main
"$ENGINE" -interaction=nonstopmode -file-line-error main.tex
"$ENGINE" -interaction=nonstopmode -file-line-error main.tex
echo "built: main.pdf"
```

### `latexmkrc`

```perl
$pdf_mode = 5;                                    # 5 = xelatex
$pdflatex = 'xelatex -interaction=nonstopmode -file-line-error %O %S';
$bibtex_use = 2;                                  # biber 后端时
$biber = 'biber %O %S';
```

### `README.md`

写明「同版本 + 同输入 → 版面与页数可复现；**PDF 字节哈希不保证相同**」，
并指出比对依据是 `versions.txt` 里的版本与 `reproducibility.input_hashes`。

---

## 五、`input_hashes` 与「同一份产物」的判据

`reproducibility.input_hashes` 对每个 `.tex/.cls/.sty/.bib/.bst` 与图片资源记 sha256；
`pdf_sha256` 只作参考。判断两次构建是否等价，看：

1. `tool_versions` 里引擎与关键宏包版本相同；
2. `input_hashes` 全部相同；
3. 产出 `final_stats.pages` 相同。

**不**看 PDF 字节哈希：TeX 会把时间戳、字体子集顺序、`\pdfcreationdate` 写进文件，
同样的输入在不同时间跑出不同字节是正常的。把 PDF 哈希当「可复现」的判据是错的。

---

## 六、缺工具时的降级矩阵

| 缺什么 | 影响 | 降级行为 |
|---|---|---|
| 所有引擎 | 不能编译 | `build.attempted=false`，静态模式，`status=partial`，`ENV-NO-ENGINE` |
| `kpsewhich` | 不能查证宏包是否安装 | `R-ADD-PACKAGE` 仍尝试，靠重编译验证；`P-CLASS-UNAVAILABLE` 不做断言 |
| `bibtex`/`biber` | 参考文献不生成 | `run_bib()` 返回 `skipped` 并记录；正文的 `\cite` 仍在 |
| `pdftoppm`/`mutool`/`magick`/`gs` | 没有预览 PNG | `preview.rendered=false` 并说明；PDF 仍交付 |
| `pdflatex` 有但 `xelatex` 没有 | 选了 xelatex 但无法执行 | `build.engine_missing`，`status=partial`，明确写出缺哪个引擎 |

---

## 七、镜像内工具发现顺序

1. `/input/environment/resources.yaml`（若存在）—— 题目声明的预装工具清单；
2. `PATH` 上实际可执行 + `--version` 探测（`probe_engines()`）；
3. 两者冲突时以**实际探测**为准，并在 `environment` 里同时记录两边的说法。
