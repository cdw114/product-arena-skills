# 分段与对齐规则（parse.py / segment.py）

## 1. PDF → 块（parse）

- 后端优先 `pymupdf`（字体、坐标、字号）→ `pypdf`（layout 文本）→ `pdftotext`。
- 同列、纵向间距 ≤ 1.2 行高、字号相同、无角色边界的连续块合并为**段落**；空行、标题、题注、列表、公式、缩进新段都会打断合并。
- 角色：`title / author / heading / abstract / body / caption / equation / list / footnote / table / reference / pageheader / pagefooter / boilerplate`。
  - 标题：字号 ≥ 1.25×正文且粗体；或字号 ≥ 1.15×正文且短；或全大写；或关键词（Introduction / Methods / Results …）。
  - 作者：第 1 页标题之后、含邮箱或机构词的块。
  - 参考文献：`References` 标题之后到下一个标题之前的所有块。
  - 幽灵文本（PDF 生成器埋入的纯虚词填充）→ `boilerplate`，丢弃。
- 双栏页阅读顺序：左栏自上而下，再右栏。宽跨栏块（题注、标题）先于栏内块。

## 2. 段（segment）

| 角色 | 处理 |
|-|-|
| title / heading / caption / equation / footnote / list / abstract / body | 进入翻译清单，一段一个 ID `S001…` |
| author | 不翻译，原样进 `verbatim_blocks`，装配时列在标题下 |
| reference | 不翻译，原样进 `references.md` |
| pageheader / pagefooter / boilerplate | 丢弃（记录在 `excluded_blocks`） |

- **跨页/跨栏续段**：上一个正文段结尾无终止标点，且下一块以小写或 `(` 开头 → 合并为同一段，`pages` 记录跨的页，`flags.continued=true`。
- **长段切分**：> `max_chars`（默认 1400）在句边界切成 `S012a / S012b`，单句超 2× 在分号边界硬切；`parent` 指回原段。
- **列表合并**：同页相邻 list 块合并为一段，行间用换行分隔。
- 每段携带：`page, pages, bbox, source_blocks[]`（原 PDF 块 ID，如 `P03B07`）。

## 3. 批次（batch）

- 按 token 预算贪心装包：`(字符数 + 上下文 240) / 3.6 ≈ tokens`，默认 3000 token/批、最多 12 段/批。
- 每段带 `context` = 上一段最后 240 字符（只为衔接，不翻译）。
- 批内只带该批命中的术语子集，减小提示词体积。

## 4. 定位约定

- 段头：`[S003 | 正文 | p.1,2 | 72.0,254.1,297.6,486.3 | ✓]` —— 段号、角色、页码（跨页全列）、bbox（左,上,右,下；pt）、核验结论。
- `bilingual.json[].marks` 列出该段每个占位符：`⟦K#nnnn⟧ → kind → src → tgt → action(restore/backfill/keep)`。
- 任何结论都能回到 `source_blocks` → PDF 块 → bbox。

## 5. 已知限制

- 无字体后端（pypdf/pdftotext）时标题/作者/脚注识别变弱，`plan.json.warnings` 提示 `layout analysis degraded`。
- 表格：表格文本若可抽取，按普通块翻译（数字受保护）；表格结构不重建。
- 公式：可抽取文本的公式块作为 `equation` 段保留原文（占位符覆盖数字），不生成 LaTeX。
- 扫描页：需外部 OCR，结果写入 `ocr_dir/P{n}.txt` 后 `--ocr-dir` 带入；无 OCR 则该页标 `not_translated`。
