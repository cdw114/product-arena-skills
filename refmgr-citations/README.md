# refmgr-citations — 参考文献与引用管理 Skill

参赛提交：写作04｜参考文献与引用管理（product-arena-03-429cc14d）。

**安装**：把本目录整体放到 `/skills/weekly-skill/`（Harbor 约定）。入口 `SKILL.md`，脚本 `scripts/run_case.py`，纯 Python ≥ 3.8 标准库，无第三方依赖，无网络依赖（`--online` 可选）。

**一条命令**：
```bash
python scripts/run_case.py --input /input --out /app/output --task "renumber+dedup+convert:gbt7714+verify+consistency"
```

**四件事**：挂得对（引用落在需要支撑的论断句）· 编得顺（编号按首次出现推导，正文/文末/图注同步）· 收得净（规则表 + 证据账本去重，复核带不自动合并）· 对得上（元数据核验、编造条目标记、逐句论断—引用判定）。

**目录**：
```
SKILL.md                      工作流、硬规则、契约、失败处理、自查
scripts/refmgr.py             规范模型：稿件/标记/文献库解析，GB/T 7714、APA、BibTeX、RIS 渲染
scripts/engines.py            dedupe / renumber / consistency / convert / verify / claim pairs
scripts/run_case.py           CLI：/input → /app/output（含插入占位、模型判断合并）
references/rules.md           引用位置与形式规则、去重判据、论断判定标准
references/format-map.md      BibTeX/RIS/JSON/CNKI ↔ Entry 字段映射，GB/T & APA 渲染规则
references/failure-modes.md   基础 Agent 常见失败模式 → 本 Skill 处置 → 残余风险
references/surnames_zh_en.json 拼音↔汉字姓氏提示表（去重桥接，仅作提示）
examples/                     最小示例：输入 / 模型判断示意 / 示意输出
```

**限制**：脚注制只定位不排版；PDF 需先转文本；在线核验依赖 Crossref；"论断是否被支持"最终由模型判断，脚本强制写 `basis`。

**本地测试**：`_work/tests/`（在提交目录之外）含合成 fixture 的 e2e、单元、插入路径、幂等性测试。
