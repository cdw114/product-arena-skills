# papertrans — 科研文献翻译 Skill

把论文 PDF 翻成**段落级双语对照**，术语、数字、引用、公式由程序保证一致，每段可回溯到页码与位置。

## 安装

```bash
pip install -r requirements.txt      # pymupdf 推荐；缺省自动回退 pypdf / pdftotext
```

Python ≥ 3.9，无其他依赖。脚本在 `papertrans/`，入口 `python3 -m papertrans.cli`。

## 三条命令

```bash
# 1. 解析 + 分段 + 术语候选 + 翻译批次（< 3 s）
python3 -m papertrans.cli prepare paper.pdf --out out --lang zh --case case.json
#    → out/plan.json  out/glossary_candidates.json  out/batches/B01..Bnn.json

# 2.（模型）审核术语 → out/glossary_reviewed.json，重新 prepare 带上 --reviewed
#    （模型）逐批翻译 out/batches/Bnn.json 的 masked 文本，写 out/translations.json

# 3. 核验 + 装配
python3 -m papertrans.cli verify  out
python3 -m papertrans.cli assemble out --case case.json
#    → out/bilingual.md  out/bilingual.json  out/glossary_used.json  out/verify.json  out/result.json
```

完整操作步骤（含预算规划、异常处置）见 `SKILL.md`；规则细节见 `references/`。

## 输入

- 论文 PDF（有文字层最佳；扫描页需外部 OCR，见 `references/segment-rules.md`）。
- `--lang`：`zh`（默认）/ `en` / `ja` …
- 可选 `case.json`：只用于把 `case_id`、`task` 写进 result.json。

## 输出

| 文件 | 内容 |
|-|-|
| `bilingual.md` | 标题 + 作者（原文）+ 统计行 + 每段 `[段号 \| 角色 \| 页 \| bbox \| ✓⚠✗]` + 原文 + 译文 + 核验备注 |
| `bilingual.json` | 同上的结构化形式，含 `marks[]`（每个占位符 原文→译文）与 `issues[]` |
| `glossary_used.json` | 术语表 + 每术语出现次数/泄漏次数/一致性 |
| `verify.json` | 每段核验结论与问题清单 |
| `references.md` | 参考文献（原文，不翻译） |
| `result.json` | `case_id, status, summary, evidence, uncertainty, change_records` |
| `plan.json` | 段数/批数/占位符数/术语数/请求预算估计/解析警告 |
| `segments.json` `doc.json` `batches/` | 中间产物（定位与复现用） |

## 方法

1. **占位符保护**：数字+单位、百分数、`[n]` 引用、图表/公式/章节交叉引用、行内公式、锁定术语 → `⟦NUM#0001⟧` 这类不可翻译标记，模型只能原样复制。
2. **术语锁定回填**：approved 术语译后由程序替换为唯一译名；译文中出现原形即报泄漏。
3. **段落清单即翻译清单**：解析结果直接决定翻译单位，少段/重复译文/错位占位符都能被程序发现。
4. **确定性核验**：占位符完整性、数字多重集、交叉引用与引用一致、单位、否定/限制词数量、长度比、译者不确定标记。
5. **可追溯输出**：每段带页码、bbox、源块 ID；每个占位符带 原文→译文 对照。

## 自检

```bash
bash tests/run_tests.sh            # 需要测试 PDF（见脚本内说明），含 4 种故障注入
```

模拟翻译器 `tests/sim_translate.py` 不需要模型，用于验证核验器能抓住：丢占位符、漏段、复制段、术语泄漏。

## 限制

- 表格只翻译可抽取文本，不重建结构；公式块保留原文不生成 LaTeX。
- 无字体后端时标题/作者识别较弱（有警告）。
- 否定/限制词检查是计数启发式，产生 warn 不产生 fail，需人工看一眼。
- 中文单位译成汉字（"毫克"）时 `units_missing` 会误报 warn。

## 维护

- 术语表可复用：合并上一份 `glossary_reviewed.json` 的 approved/keep 条目。
- 新领域：改 `glossary.py` 的 `SUFFIX`/`STOP`，或直接在审核阶段补条目。
- 阈值：`verify.LENGTH_BAND`、否定/限制词表、`translate.build_batches(kinds)`。
