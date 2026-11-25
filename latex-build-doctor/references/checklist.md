# 交付清单（打印用）

一次运行结束后，从上到下逐条打勾。任何一条打不上，`status` 就不该写 `success`。

## A. 契约

- [ ] `result.json` 在 `/app/output` 根目录
- [ ] 含 `case_id`，值与 `case.json` 一致
- [ ] 含 `output_contract` 里**全部**字段
- [ ] `contract.missing` 为空，或每个缺口都在 `status_reason` / `uncertainties` 里解释过
- [ ] `status` ∈ {`success`,`partial`,`failed`}，且与 `status_reason` 一致

## B. 编译

- [ ] `build.attempted` 真实：真跑了编译器才是 `true`
- [ ] `build.engine.reason` 与 `evidence` 能站得住（不是「默认」两字了事）
- [ ] `build.bib_backend.backend` 与工程里的宏包一致（biblatex→biber、natbib→bibtex）
- [ ] `build.pass_commands` 与实际执行过的一致
- [ ] `build.success=true` 时 `build.pages > 0`，且 `main.pdf` 存在
- [ ] `build.success=false` 时 `status != success`
- [ ] `build.spent_seconds <= build.budget_seconds`

## C. 诊断

- [ ] `diagnostics.items` 每条都有 `file`+`line`，或 `source: static` 且有 `rule`
- [ ] `summary.live + summary.suppressed == summary.total`
- [ ] `suppressed > 0` 时，报告里解释了「归并到哪个根因」
- [ ] `fix_order` 有序，第一条是最该先修的
- [ ] `root_cause.category` 不是 `unclassified`（是的话要说明为什么）

## D. 补丁

- [ ] `fixes.applied` 每条都有 `rule` / `file` / `line` / `reason` / `verified: true`
- [ ] `fixes.rejected` 每条都有 `why`（=「没让诊断集变好」或具体原因）
- [ ] `fixes.changes.diff` 与 `applied` 一致（能 `git apply` 复核）
- [ ] `fixed/` 的文件名与目录结构与输入一致（没有偷偷重命名/合并文件）
- [ ] 没有任何补丁改了正文句子（只有声明、定界符、转义、加载顺序）

## E. 完整性

- [ ] `integrity.clean == true`
- [ ] `\cite` / `\ref` / `\label` / `\includegraphics` / `\begin{equation}` / `\caption` 数量未减少
- [ ] 未引入 `\sloppy` / `\tolerance=9999` / `\hbadness` / `\iffalse` / `\nonstopmode`
- [ ] `integrity.clean == false` 时 `status == partial`，且报告「完整性」一节列了每一项

## F. 可复现

- [ ] `repro/build.sh` / `repro/latexmkrc` / `repro/versions.txt` / `repro/README.md` 齐备
- [ ] `versions.txt` 的版本号来自真实 `--version` 探测，不是猜的
- [ ] `input_hashes` 覆盖所有 `.tex/.cls/.sty/.bib/.bst`
- [ ] `reproducibility.note` 说明了「PDF 字节哈希不保证相同」

## G. 人工项

- [ ] 缺文献条目（`C-CITE-NO-ENTRY`）逐条列在 `human_review`
- [ ] 缺图片/缺 `\input`/缺 `.cls`/缺字体逐条列出
- [ ] `T-CELL-MISMATCH`、`M-LEFT-RIGHT` 这类要人决策的项逐条列出
- [ ] 每条 `human_review` 都有 `file`+`line`+`why`（不写「请人工检查」这种空话）

## H. 诚实性

- [ ] 没有编造版本号、页数、耗时、评分
- [ ] 没有把 `examples/` 的产物当正式结果
- [ ] 没有在无引擎时声称编译通过
- [ ] `uncertainties` 非空至少一条（除极端干净的 `success`）

## I. 自测

- [ ] `python3 scripts/selftest.py` → `145/145 assertions passed`
- [ ] 同输入跑两次，`diagnostics` 与 `fixes` 一致（幂等）
