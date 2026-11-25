# 评测运行约定（Harbor）

本 Skill 在 Harbor 评测容器内由 DeepSeek Harness 调用。以下是路径、预算与产物约定。**以实际 `/input/task.md` 为准**；本文件是摘要，冲突时以任务说明为准。

## 路径

| 位置 | 内容 |
|---|---|
| `/skills/weekly-skill/` | 本 Skill 安装位置（`SKILL.md`、`scripts/`、`references/`） |
| `/input/case.json` | 案例：`case_id`、`task`、`source`（文件路径或内联 `text`）、`target_genre`、`target_lang`、`length_limit` 等 |
| `/input/task.md` | 任务说明；与 case.json 冲突时以此为准 |
| `/input/`（其他） | 材料文件：原文（txt/md/tex/docx/pdf）、术语表、style guide、参考样本 |
| `/app/work/` | 工作目录：`run_case.py init` 生成 `edit_brief.json`、`revised.md`、`ledger.json`、`glossary.json`、`state.json` |
| `/app/output/` | 最终产物：`revised.md`、`edit_ledger.json/.md`、`glossary.json`、`audit_report.json`、`result.json` |
| `/logs/agent/` | Harness 原生会话日志（trace，平台自动记录，不要伪造） |

## 预算

- 模型请求：64 次
- 墙钟：900 秒
- 单次回复：≤ 16384 token（含推理）

本 Skill 的流程设计为**两次脚本调用 + 一次编辑**：
1. `init`（0 次模型请求，< 2 秒）
2. 读 brief + task.md → 编辑 + 写台账（主要消耗；按章节分块，每块一次回复）
3. `verify`（0 次模型请求）；若 exit 2，最多再一轮修正

预算分配建议：读题与建表 ≤ 6 次请求；编辑按每 1500 字一块；校验与修正 ≤ 6 次；留 ≥ 10 次余量。

## 时间纪律

- 开始工作后**先写一份 partial 产物**：把原文复制到 `/app/output/revised.md`，写一个最小 `result.json`（`status: partial`，`limits: ["work in progress"]`）。之后每次 `verify` 覆盖它。
- 剩余 < 120 秒时停止编辑，跑最后一次 `verify`，以 `--status partial` 提交。
- 不要把时间花在反复重写同一段；一遍改好，审计兜底。

## 诚实性要求

- `result.json.status`：所有受保护跨度核对通过且台账完整 → `complete`；否则 `partial`。
- `limits` 写清楚：哪些章节未处理、哪些判断不确定、审计的边界。
- `human_confirmation_needed` 列出需人工确认的事项（数据疑问、文体不明、术语冲突）。
- 不伪造材料、不编造术语表来源、不虚构 style guide。
- trace 由平台记录；不要创建或修改 `/logs/` 下的文件。

## 输入是 PDF 时

- 用 `pdf-text-tool` 提取；保留页码。
- 扫描件用 `ocr-tool`；OCR 置信度低的段落在台账 `other` 里标 `uncertain`。
- 从 PDF 提取的文本常有断行、连字符、页眉页脚；编辑前先清理，但**不改实质内容**。

## 输出是 Office/可编辑格式时

任务若要求 `.docx` 输出：用 `office-docx` 相关工具生成，并附 `revised.md` 作为纯文本版本与 PNG/PDF 预览（`office-renderer`）。`result.json.outputs` 里写出实际路径。

## 异常速查

| 现象 | 动作 |
|---|---|
| `/input/case.json` 缺 `source` | 在 `/input/` 找 doc 类文件；找不到 → partial，limits 注明 |
| `init` 报 "no source material" | 同上 |
| `verify` exit 2 | 看 `unexplained_changes`：恢复原词或补台账；预算紧则 partial |
| `polish_audit` 异常 | 看 stderr；通常是非 UTF-8 输入 → `iconv` 或重新提取 |
| 原文 > 10k 字 | 分块处理，优先摘要/引言/结论；partial |
