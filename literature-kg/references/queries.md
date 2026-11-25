# Query catalogue (copy-paste)

All commands: `python scripts/query_kg.py --graph /app/work/graph.aligned.json --query <NAME> [...] --out /app/work/queries/<NAME>.json --question "<the task's question>"`.

Every output contains `result.nodes/edges`, a copied `evidence` array, `unresolvable[]` and `status`. Add extra unresolvable notes with `--unresolvable "text;text"`.

| name | args | use when the task asks | example |
|---|---|---|---|
| `neighbors` | `--node ID [--edge-type T] [--hops 1\|2]` | "what is X related to" | `--node N:model:roberta --hops 1` |
| `path` | `--src ID --dst ID` | "how are A and B connected" | |
| `by_source` | `--source SID` | "what does paper S contribute" | |
| `cross_paper` | — | "which concepts appear in both papers" | |
| `compare` | `--a ID --b ID` | "compare A and B across papers" (per-source evidence table) | |
| `conflicts` | — | "where do the papers disagree" | |
| `used_by` | `--node METHOD_ID` | "who uses method M" (reverse traversal over uses/evaluated_on/proposed_by) | |
| `reports` | `--node ID` | "what values are reported for X" (per-source values + conditions) | |
| `type` | `--type T` | "list all materials / methods / metrics" | |

Pick ≥3 queries that the task text actually asks for. If the task gives no explicit questions, default set: one `cross_paper`, one `compare` on a merged/kept-separate pair, one `used_by` or `reports`.

`unresolvable` must list, in plain words, what the graph cannot answer (e.g. "whether both used the same random seed: not stated in either paper"; "Figure 4 values: not in text").

Query templates for a typical task.md:

```
--query cross_paper --question "两篇论文共同出现的概念有哪些？"
--query compare --a N:dataset:sst-2@P --b N:dataset:sst-2@S --question "两篇的 SST-2 是否同一对象？"
--query reports --node N:model:roberta --question "两篇对 RoBERTa 报告的准确率分别是多少？"
```
