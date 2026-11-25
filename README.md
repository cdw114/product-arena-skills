# Product Arena Skills

本仓库收录我在 [Bohrium Playground](https://play.bohrium.com) 产品竞技场各题目中提交的 Skill 作品。
每个子目录是一道题的完整提交内容：`SKILL.md`（入口）、`scripts/`、`references/`、`examples/` 等。

## 作品索引

| 题目 | Skill | 中文名 | 做什么 |
|-|-|-|-|
| `写作02` | [`academic-polishing`](./academic-polishing) | 学术语言润色 | Polish academic text (Chinese or English; journal paper, thesis, grant application, reviewer respons |
| `阅读03` | [`papertrans`](./papertrans) | 文献翻译 | Translate a scientific paper PDF into a paragraph-aligned bilingual document with enforced terminolo |
| `写作04` | [`refmgr-citations`](./refmgr-citations) | 参考文献与引用管理 | 参考文献与引用管理 Skill——对一份真实稿件 + 一份真实文献库做"挂得对 / 编得顺 / 收得净 / 对得上"四件事：识别需来源支撑的论断句并给出引用插入位置； |
| `写作08` | [`intrograph`](./intrograph) | 引言与相关工作写作 | 引言与相关工作写作——先建四本可核对的账（引用账、分组账、空白账、贡献-证据账），再据此写"研究背景 / 相关工作 / 研究空白 / 主要贡献"，最后用 18 项确定性核对逐条拦截"编造引用、无来源论 |
| `写作09` | [`methods-experiments-writer`](./methods-experiments-writer) | 方法与实验章节写作 | Turn scattered research materials (config files, training logs, code, dataset notes, README, paper)  |
| `阅读10` | [`paper-structured-notes`](./paper-structured-notes) | 文献总结与结构化 | >- |
| `写作13` | [`latex-build-doctor`](./latex-build-doctor) | LaTeX 写作与编译 | LaTeX 编译诊断与修复闭环——把「编不过」拆成可验证的根因与最小补丁：递归识别主文件/子文件/宏包/参考文献后端，选对引擎（pdfLaTeX / XeLaTeX / LuaLaTeX / late |
| `阅读14` | [`nanopublication`](./nanopublication) | Nanopublication | Extract atomic scientific claims (nanopublications) from a paper passage. |
| `阅读15` | [`literature-kg`](./literature-kg) | 文献知识图谱构建 | Build an evidence-backed literature knowledge graph from one or more paper corpora (JATS paragraph t |

另有一道题的 Skill 位于独立仓库：[`weekly-skill`](https://github.com/cdw114/weekly-skill)（阅读01 文献文档解析）。

## 怎么用这些 Skill

这些 Skill 采用 Agent Skills 通用格式：一个目录 + 带 `name` / `description` 的 `SKILL.md`。

**方式一：让 AI 直接读**（任何能联网的 AI）
```
读取 https://github.com/cdw114/product-arena-skills/raw/main/<skill>/SKILL.md
```

**方式二：安装到本地 skills 目录**（Claude Code / Cursor / Codex / DSH 等）
```bash
git clone https://github.com/cdw114/product-arena-skills.git
cp -r product-arena-skills/<skill> ~/.claude/skills/
```

**方式三：只取文本**（AI 不能联网时）
直接打开对应目录的 `SKILL.md`，整段粘贴给 AI。

## 目录约定

每个子目录都包含：

- `SKILL.md` —— Skill 入口，YAML frontmatter + 执行流程 + 输出契约 + 失败处理
- `GITHUB_URL.txt` —— 指回本目录的公开链接
- `scripts/` / `references/` / `examples/` / `tests/` / `templates/` —— 该 Skill 实际依赖的资源

## 说明

- 各 Skill 的输入输出、限制与失败处理都写在自己的 `SKILL.md` 与 `references/limitations.md` 里。
- 本仓库只存放作品本身，不含任何平台 token、密钥或评测结果。
- 各目录下的示例输出均在文件中标明为「示例」，不代表正式测试结果。
