---
name: literature-kg
description: Build an evidence-backed literature knowledge graph from one or more paper corpora (JATS paragraph text, JSON/Markdown material) — extract entities (researchers/materials/methods/tasks/metrics/conclusions) and relations with paper-level source_id + paragraph_id + verbatim quote, align aliases across papers without over-merging, run graph queries, and emit a schema-valid result.json. Use when a task asks to construct a knowledge graph from papers, cross-paper concept alignment, or evidence-anchored literature QA. Trigger on "知识图谱", "knowledge graph", "实体抽取", "关系抽取", "跨论文对齐", "构建图谱", "literature graph".
---

# Literature Knowledge Graph Construction (evidence-first)

## 0. Hard rules (read before anything else)

1. **Input files are the only source of truth.** Read the actual files under `/input` (and `environment/resources.yaml` if present). Never infer content from the challenge title, a topic label, or domain priors. If a file listed in a manifest is missing → record `status: missing` for that source and continue with the rest.
2. **No prepared answers.** Every node, edge and query result must be produced by the workflow below from the actual input during this run.
3. **Evidence on every substantive node and edge.** Each node/edge carries its own `source_id` (which paper), `paragraph_id` (the organizer's JATS paragraph id), and a verbatim `quote` (short, 20–200 chars, must be a substring of the paragraph text). Do not pool evidence across papers. Do not attach a primary-paper DOI/title/author to a secondary-paper node.
4. **Positions are JATS paragraph IDs, not PDF pages.** If the corpus has no PDF page numbers, never write `page: 1` and call it "the PDF page". Use `{"source_id":..., "paragraph_id":...}`; if a page is genuinely available in the input (e.g. `<page>` element or `page` field), include it *as given* and label it `"page_source": "input"`.
5. **Inline math / sub-superscripts are linearized.** If the bundle includes a `secondary-publisher.xml` (or any JATS XML) use it to verify linearized formula text; otherwise keep the linearized text verbatim and set `normalization_note: "linearized inline math; source XML not provided"`.
6. **No images, supplementary attachments, raw data.** Do not infer numbers from figures, image pixels, supplementary files or underlying clinical/experimental data that are not in the text. If a claim depends on such data → `status: not_reported`.
7. **Keep unresolved and conflicting items explicit.** Unreported values, in-source conflicts and cross-paper conflicts must be listed in `uncertainties`/`merge_conflicts`, never silently dropped or resolved by guessing.
8. **Budget.** You have 64 model requests / 900 s / 16 384 tokens per response. Save a partial `result.json` **early** (after step 3) and improve incrementally. Prefer the scripts in `scripts/` over manual JSON writing — they are deterministic and cost zero model requests.

## 1. Identify inputs and question boundary (Phase A — always first)

Run `python scripts/inspect_inputs.py --input /input --out /app/work/input_inventory.json`. This produces an inventory: every file, its role (inferred from filename + top-level keys), record counts, and which paragraphs belong to which `source_id`. It also copies the `output_contract` keys from `case.json` (if present) so step 9 can prove every required field is present.

### 1.1 Expected input layout (the challenge's fixed bundle)

| File | Role | How to use |
|---|---|---|
| `/input/case.json` | case id + `output_contract` (required result fields) + maybe `task` | `case_id` and contract are **copied verbatim** into `result.json` |
| `/input/task.md` (or `task.md` next to case.json) | the task text | decides the scope (table below) |
| `corpus-manifest.json` | list of papers: `doi`, `title`, `authors`, `source_hash`, `license`, role | **authoritative** source registry → `result.json.sources[]` |
| `material.json` | aggregated paragraph index of *both* papers | per-paragraph `paragraph_id`, `source_id`, `section`, linearized `text` |
| `primary-material.json` | paragraphs of paper 1 (the original paper) | same paragraph schema; the root DOI/title/authors in `case.json` belong to **this** paper only |
| `secondary-material.json` | paragraphs of paper 2 (the newly added paper) | same paragraph schema |
| `secondary-publisher.xml` | publisher JATS XML of paper 2 | use only to verify linearized inline math / sub-superscripts; not a third source |
| `environment/resources.yaml` | tools available in the pinned image | read it to know whether OCR / PDF tools exist |

**Identity rule.** `material.json` is an *index* of the two papers, not a third paper. Map each paragraph to exactly one `source_id` (from the paragraph's own `source_id`/`doi` field; if absent, from the file it appears in when that file is single-paper, e.g. `primary-material.json`). The same paper in two files (index + per-paper file) is **one** source; this is not cross-paper evidence. The root DOI/title/authors of the case belong to the primary paper and must never be attached to a secondary node.

Then read `task.md` fully and decide the scope:

| task.md asks for | Deliverable focus |
|---|---|
| 构建/构建图谱 (build graph) | full graph + ≥3 queries |
| 对齐/别名/合并 (align / alias / merge) | `cross_paper_alignment` with per-pair `merge_decision` + rationale |
| 查询/问答 (query / QA) | `queries[]` with subgraph, evidence, and `unresolvable[]` |
| 增量更新 (incremental update) | `incremental_update` block (new nodes, merged, conflicts, export format) |
| translation / QA only | still produce the minimal graph the answer needs; keep evidence anchors |

Write the decided scope + boundary to `/app/work/scope.json` (`{"focus": [...], "out_of_scope": [...], "assumptions": [...]}`). Anything in the input you *could* use but the task did not ask for goes in `out_of_scope` — do not pad the graph.

**Recurring trap:** a bundle may present "two papers" as the same paper in two formats (JSON + Markdown of one paper). Per the challenge rules this is **not** cross-paper evidence. Detect it by comparing DOI / title / authors across files in `corpus-manifest.json` (or the material headers). If two files share a DOI/title/author set, they are one source; the graph gets **one** source_id for them and you note `duplicate_formats: [...]` in the source record.

## 2. Parse and segment (Phase B)

Work from the paragraph index (`material.json` or the per-paper files). Expected per-paragraph fields (tolerate absence):

```
paragraph_id  (string, organizer JATS id — use exactly as given)
source_id     (string; if absent derive from the file's DOI, e.g. "10.1234/abc" → use the DOI itself)
section_path  (list or "/"-joined string) — e.g. ["Introduction"], ["Results","2.1 Cohort"]
section_id / heading
text          (linearized text, inline math already flattened)
page          (optional; only when the input has it)
```

If the input is JATS XML rather than JSON, run `python scripts/jats_to_paragraphs.py --xml <file> --source-id <DOI> --out /app/work/paragraphs/<source_id>.jsonl`. If it is Markdown only, run `python scripts/md_to_paragraphs.py`. The output of this phase is one JSONL per source: `{"paragraph_id","source_id","section_path","text","page?","char_span":[s,e]}`.

Store the paragraph store at `/app/work/paragraphs/*.jsonl`. **Everything downstream quotes from this store**, so that `quote` strings can be verified to be substrings.

## 3. Minimal viable graph, saved early (Phase C0)

Before deep extraction, emit a skeleton `result.json` with: `case_id`, `status: "partial"`, `sources[]` (from the manifest), `nodes: []`, `edges: []`, `queries: []`, `uncertainties: ["extraction in progress"]`. This guarantees a schema-valid deliverable exists if the budget runs out.

## 4. Extract entities (Phase C1)

Target entity types (extend only if the task names others): `researcher`, `institution`, `material`, `method`, `task`, `model`, `metric`, `dataset`, `conclusion`, `condition`. For each paragraph, extract mentions and normalize to a node:

```json
{
  "id": "N:method:finetune-roberta",
  "type": "method",
  "canonical_name": "fine-tuning of RoBERTa",
  "aliases": ["RoBERTa fine-tuning", "fine-tuned RoBERTa"],
  "definition": "one sentence, paraphrased, no numbers that are not in the quotes",
  "evidence": [
    {"source_id": "10.1234/primary", "paragraph_id": "pa-12", "quote": "we fine-tune RoBERTa on ...", "attribution": "author", "evidence_strength": "direct"},
    {"source_id": "10.5678/secondary", "paragraph_id": "sb-07", "quote": "...", "attribution": "cited", "evidence_strength": "indirect"}
  ],
  "first_seen": "10.1234/primary",
  "provenance": {"extraction": "llm", "verified_by": "scripts/validate_result.py"}
}
```

Rules:
- **One node per distinct real-world object**, identified by DOI/title/authors of the paper it comes from. Same generic method term in two papers (e.g. both say "CNN") is a *candidate* for alignment, not automatically one node — see Phase C2.
- **Aliases are kept even when they are **not** merged. An alias that is ambiguous (could be two objects) goes into `merge_conflicts`, not into `aliases`.
- Numbers/conditions/samples stay attached to the paper that reports them (in the evidence quote), never in the shared `definition` of a cross-paper node.
- Quote verification: every quote must be an exact substring of `paragraphs[paragraph_id].text`. The validator enforces this — fix failing quotes by re-reading the paragraph, not by editing the quote from memory.
- **Author claim vs. third-party report.** Every evidence item carries `attribution`: `"author"` when the paper's own authors state the fact about their own work ("we fine-tune..."), `"cited"` when the paper reports someone else's result in a review/related-work sentence ("Smith et al. achieved 91%..."), `"background"` for generic domain statements. Nodes built only from `cited`/`background` evidence get `confidence: "low"` and a definition prefixed with the attribution, e.g. `"As reported by <source_id>: ..."`. Never present a third-party number as the paper's own result.
- **Extraction must be text-grounded.** Do not add an entity because a model "knows" it belongs to the topic. If a named object appears nowhere in the paragraph text, it is not a node.

**Extraction strategy under budget** (do not read the whole corpus repeatedly):
1. Read the Abstract, Introduction, Methods and Conclusion sections of each paper (by `section_path`) in full.
2. Read Results/Tables/Discussion paragraphs only where they contain numbers or named comparisons — scan with `grep`-like keyword hits via `scripts/find_paragraphs.py --pattern`.
3. Each extraction pass over a chunk writes directly into `/app/work/graph.draft.json` via `python scripts/graph_op.py add-node ...` (or by editing the JSON file and calling `graph_op.py check`).

## 5. Extract relations (Phase C2)

Relations are typed, **directed**, evidence-backed edges:

```json
{
  "id": "E:uses:pa-12:finetune-roberta->sst2",
  "type": "uses" | "evaluated_on" | "proposed_by" | "compared_with" | "outperforms" | "same_as" | "part_of" | "measures" | "reports_value" | "contradicts" | "extends" | "cites",
  "src": "N:method:finetune-roberta",
  "dst": "N:dataset:sst2",
  "evidence": [{"source_id": "...", "paragraph_id": "...", "quote": "..."}],
  "conditions": "optional free text copied from the quote context, e.g. 'lr=1e-5, 3 epochs' (keep paper-local!)",
  "confidence": "high|medium|low",
  "cross_paper": false
}
```

- A relation asserted only by one paper is **paper-local**: `cross_paper: false`, evidence from that paper only. If a second paper independently asserts the same relation between the *same two aligned nodes*, you may add a second evidence entry — but each evidence item keeps its own `source_id`.
- **Never merge conditions**: if paper A says "accuracy 91% on dataset X with 10k samples" and paper B says "accuracy 85% on dataset X with 1k samples", the node `dataset:X` can be shared (if the dataset identity is established — see 6.2) but the two `reports_value` edges are separate edges with their own conditions. Do **not** produce a combined "88%".
- `contradicts` edges are legitimate and valuable: use them when two papers report conflicting results for the same aligned pair, and also list them in `merge_conflicts`.
- **Evidence strength per edge** (`evidence_strength`): `direct` = the quote states the relation explicitly ("we use X", "X outperforms Y (p<0.05)"); `indirect` = the relation must be inferred from two separate sentences/paragraphs or from a review sentence; `cooccurrence_only` = X and Y merely appear in the same paragraph — **this is not a relation**. Never create an edge from co-occurrence alone. Likewise never create `outperforms`/`supports` from "related work discusses both", from a hypothesis ("may improve"), or from a future-work sentence. If the only support is a hypothesis, either skip the edge or use `type: "hypothesizes"` with `evidence_strength: "indirect"` and `confidence: "low"`.
- `direction` matters: `outperforms(A,B)` is not `outperforms(B,A)`. Re-read the quote and make sure `src` is the subject of the sentence.

## 6. Cross-paper alignment (Phase C3) — the core of this challenge

### 6.1 Candidate generation (deterministic)
Run `python scripts/align_candidates.py --graph /app/work/graph.draft.json --out /app/work/align_candidates.json`. It proposes candidates from:
- exact alias match (case/whitespace/punctuation-insensitive),
- alias containment (`"RoBERTa"` ⊂ `"RoBERTa-large"` → candidate, but **flagged as possible different object**),
- Jaccard on canonical names ≥ 0.6,
- same `type` + shared token in name (e.g. both `material` containing "PLA").

### 6.2 Decide each candidate (LLM, with evidence)
For each candidate pair, decide `merge` / `keep_separate` / `uncertain` by answering, **from quotes**, the four identity tests:

| Test | Question | Merge requires |
|---|---|---|
| T1 identity | Do both papers refer to the same real-world object (same model instance, same physical sample, same dataset release, same task definition)? | yes |
| T2 conditions | Are experimental conditions/sample/population equivalent? If they differ, the *objects* may still be the same but the *results* must not be combined. | yes for object identity; record conditions separately |
| T3 definition | Do the definitions/ descriptions agree? | yes or one is silent |
| T4 conflict | Is there a reported conflict in value/result? | allowed, but → `merge_conflicts` |

Decision rules:
- **Same generic method/material term ≠ same object.** "CNN", "transformer", "PLA", "human serum" are *classes*. Merge as a class node only if both papers use the term for the same class **and** you keep per-paper instance nodes separately (e.g. `N:model:cnn` class; `N:model:cnn@primary` and `N:model:cnn@secondary` instances with `instance_of` edges). This is the "class/instance" pattern — use it whenever two papers use a generic term with different configurations.
- **Same explicit name + same defining citation + compatible definition → merge** (e.g. both cite "SST-2 (Socher et al., 2013)" as the dataset). Record `merge_basis: ["same_explicit_name", "same_definition", "compatible_conditions"]`.
- **Same name but different sample/population/model instance → keep separate** with a `related_to` edge and a `merge_conflicts` entry (`reason: different_sample`).
- **Do not force every alias to merge.** An alias with no counterpart in the other paper stays a paper-local alias.
- Different papers' conditions, samples and numeric results must never be combined into one conclusion; if the task asks for a "consensus" conclusion, emit it only as `conclusion` node with *per-paper* `reports_value` edges and an explicit `consensus_status: "not_formed"` when values differ.

Write the decisions to `/app/work/alignment.json`:
```json
{"pairs": [{"a": "N:...", "b": "N:...", "decision": "merge|keep_separate|uncertain",
            "merge_basis": [...], "conflict": "...", "evidence_a": {...}, "evidence_b": {...}}]}
```
Then apply: `python scripts/apply_alignment.py --graph graph.draft.json --alignment alignment.json --out graph.aligned.json`. `apply_alignment.py` unions `aliases`, unions `evidence` (each item keeps its own `source_id`), sets `first_seen` to the earliest source, and writes `merged_from: [...]`. It **refuses** to merge two nodes that have conflicting numeric `reports_value` edges unless you pass `--allow-conflict` *and* the conflict is listed in `merge_conflicts`.

## 7. Graph queries (Phase C4) — at least 3, actually executed

Run queries with `python scripts/query_kg.py --graph graph.aligned.json --query <name> --out /app/work/queries/<name>.json`. Supported:

| query | args | returns |
|---|---|---|
| `neighbors` | `--node <id> [--type <edge_type>] [--hops 1..2]` | subgraph of neighbors with edges + evidence |
| `path` | `--src <id> --dst <id>` | shortest path(s) with evidence |
| `by_source` | `--source <source_id>` | all nodes/edges from one paper |
| `cross_paper` | (none) | every node with evidence from ≥2 source_ids + every `cross_paper` edge |
| `compare` | `--a <id> --b <id>` | side-by-side evidence per paper (for merge_conflicts / consensus) |
| `conflicts` | (none) | all `contradicts` edges and `merge_conflicts` |
| `used_by` | `--node <method_id>` | papers that use a method (reverse traversal) |

Each executed query becomes one entry in `result.json.queries[]`:
```json
{"id": "Q1", "question": "Which datasets are used by methods proposed in the secondary paper?",
 "cypher_or_dsl": "path(src=cross_paper method, dst=dataset) filtered by first_seen=secondary",
 "result": {"nodes": [...ids...], "edges": [...ids...]},
 "evidence": [{"source_id": "...", "paragraph_id": "...", "quote": "..."}],
 "unresolvable": ["metric 'perplexity' is not defined in either paper → no definition node"],
 "status": "ok|partial|unresolvable", "reason": "..."}
```
The `evidence` field of a query is the union of the evidence of the returned nodes/edges — **copy it from the graph file**, do not retype. Anything the graph cannot answer goes into `unresolvable` with the reason (e.g. "no paragraph in the corpus states X" or "figure data not provided").

## 8. Incremental update (Phase C5, only if the task asks)

When a new paper (e.g. `secondary-material.json`) is added to an existing graph built from the primary:
1. Keep existing node ids stable. New nodes from the new paper get ids `N:<type>:<slug>`; if a candidate aligns with an existing node → apply Phase 6; else new node with `first_seen = new source_id`.
2. Record in `result.json.incremental_update`: `added_nodes`, `added_edges`, `merged_nodes` (with basis), `new_conflicts`.
3. Export: `python scripts/export_graph.py --graph graph.aligned.json --format graphml|json|cypher --out /app/output/graph.<ext>`. GraphML is the default for tools; JSON-LD optional. The export must round-trip evidence anchors (store them as node/edge attributes).

## 9. Assemble `result.json` (Phase D)

Run `python scripts/assemble_result.py --work /app/work --case-id <case_id> --out /app/output/result.json`. It fills the output contract from the work files and auto-computes counts. Then **validate**: `python scripts/validate_result.py --result /app/output/result.json --paragraphs /app/work/paragraphs --manifest /input/corpus-manifest.json`. The validator enforces:

- all `output_contract` fields present + `case_id`
- every evidence quote is an exact substring of the referenced paragraph
- `paragraph_id` exists under the referenced `source_id`
- every node/edge has ≥1 evidence item (schema allows 0 only for `status: not_reported` placeholders)
- no DOI/title/author of source A attached to a node whose evidence is entirely from source B
- node/edge ids referenced in `queries[].result` exist
- every `merge` decision in `alignment.json` has a non-empty `merge_basis`
- ≥3 queries with `status` in `{ok, partial, unresolvable}` are present (warn if fewer)

Fix every `error`; `warning`s may be kept if explained in `uncertainties`.

## 10. Output contract (`/app/output/result.json`)

```json
{
  "case_id": "string — copied from /input/case.json",
  "status": "success | partial | not_determinable | refused",
  "status_reason": "string",
  "scope": {"focus": [...], "out_of_scope": [...], "assumptions": [...]},
  "sources": [
    {"source_id": "DOI or file-derived id", "doi": "...", "title": "...", "authors": "...",
     "role": "primary|secondary", "files": ["primary-material.json"], "paragraph_count": 0,
     "license": "...", "content_hash": "...", "duplicate_formats": [], "status": "ok|missing|unreadable"}
  ],
  "nodes": [...],
  "edges": [...],
  "cross_paper_alignment": {"pairs": [...alignment.json pairs...], "merged": [...ids...], "kept_separate": [...ids...]},
  "queries": [...],
  "incremental_update": {...} | null,
  "merge_conflicts": [
    {"a": "N:..", "b": "N:..", "kind": "different_sample | different_conditions | value_conflict | ambiguous_alias | same_generic_term",
     "description": "...", "evidence_a": {...}, "evidence_b": {...}, "resolution": "kept_separate | merged_with_conditions_recorded | unresolved"}
  ],
  "uncertainties": [
    {"item": "...", "reason": "not_reported | linearized_math | missing_file | low_confidence_extraction | source_conflict",
     "location": {"source_id": "...", "paragraph_id": "..."}, "statement": "..."}
  ],
  "unreported": ["...things the corpus does not state, which the task asked about..."],
  "change_log": [{"step": "...", "what_changed": "...", "timestamp": "ISO-8601"}],
  "environment": {"python": "...", "scripts": ["scripts/..."], "graph_format": "..."},
  "stats": {"nodes": 0, "edges": 0, "cross_paper_nodes": 0, "queries": 0, "merged": 0, "kept_separate": 0}
}
```

Full field reference: `references/output-contract.md`. Graph schema: `references/schema.md`. Alignment decision tree with worked examples: `references/evidence-rules.md`. Query catalogue and copy-paste commands: `references/queries.md`.

## 11. Failure handling

| Situation | Action | `status` |
|---|---|---|
| `/input/case.json` missing | still build from `task.md` + materials, set `case_id: "unknown"`, note in `uncertainties` | partial |
| A material file missing / unreadable / not valid JSON | inventory marks `missing`; build from the rest; list in `sources[].status` | partial |
| Encrypted / binary PDF only (no text layer) | use OCR tool if present in the environment (`environment/resources.yaml` lists tools); otherwise refuse that source, continue with others | partial or not_determinable |
| Paragraph text garbled (bad font/encoding) | keep raw, mark `reason: garbled_text`, do not "fix" by guessing | partial |
| Quote fails substring check | re-read paragraph; if the paragraph truly does not contain it, delete the evidence and downgrade node confidence | — |
| Two papers disagree on a value for aligned nodes | add `contradicts` edge + `merge_conflicts` entry; do not average | success/partial (not an error) |
| Budget nearly exhausted (≈50 requests or ≈12 min) | stop extraction; run assemble + validate; `status: partial` with what is done | partial |
| Task asks for data not in text (figures, supplements) | `unreported[]` entry, `unresolvable[]` in the query | partial |

## 12. Self-check before finishing

- [ ] `validate_result.py` exits 0 (errors) and every warning is explained
- [ ] ≥3 queries executed, each with evidence copied from the graph and an `unresolvable` list (possibly empty)
- [ ] every cross-paper merged node has `merge_basis` and per-source evidence; every kept-separate pair has a reason
- [ ] no page numbers invented; positions are `paragraph_id`s
- [ ] `status`, `uncertainties`, `unreported`, `change_log` filled honestly
- [ ] `/app/output/graph.graphml` (or `.json`) exported if the task mentions 图谱导出

## 13. Minimal example (illustrative only — not a case answer)

Input (`/input/task.md` excerpt): "围绕『跨论文方法复用』构建图谱并回答：两篇论文是否使用了同一预训练模型？"

```bash
python scripts/inspect_inputs.py --input /input --out /app/work/input_inventory.json
python scripts/graph_op.py init --out /app/work/graph.draft.json
python scripts/graph_op.py add-node --graph /app/work/graph.draft.json --type model --name "BERT-base" \
  --source 10.1/A --paragraph p3 --quote "we use BERT-base (Devlin et al., 2019) as the encoder"
python scripts/align_candidates.py --graph /app/work/graph.draft.json --out /app/work/align_candidates.json
# ... decide pairs (LLM) → /app/work/alignment.json
python scripts/apply_alignment.py --graph /app/work/graph.draft.json --alignment /app/work/alignment.json --out /app/work/graph.aligned.json
python scripts/query_kg.py --graph /app/work/graph.aligned.json --query compare --a N:model:bert-base@A --b N:model:bert-base@B --out /app/work/queries/q1.json
python scripts/assemble_result.py --work /app/work --case-id demo --out /app/output/result.json
python scripts/validate_result.py --result /app/output/result.json --paragraphs /app/work/paragraphs
```

Illustrative output (示例，非正式案例结果):

```json
{"case_id": "demo", "status": "partial",
 "queries": [{"id": "Q1", "question": "Do both papers use the same pretrained model?",
   "result": {"nodes": ["N:model:bert-base"], "edges": ["E:same_as:p3:p9"]},
   "evidence": [{"source_id": "10.1/A", "paragraph_id": "p3", "quote": "we use BERT-base (Devlin et al., 2019) as the encoder"},
                {"source_id": "10.1/B", "paragraph_id": "p9", "quote": "The encoder is BERT-base-uncased."}],
   "unresolvable": ["whether the fine-tuning hyperparameters are identical: not reported in 10.1/B"],
   "status": "partial", "reason": "model identity matches; training configuration in B not reported"}],
 "merge_conflicts": [], "uncertainties": [{"item": "hyperparameters", "reason": "not_reported", "statement": "B does not state learning rate or epochs"}]}
```
