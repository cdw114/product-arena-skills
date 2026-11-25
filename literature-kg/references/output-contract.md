# Output contract — `result.json`

Path: `/app/output/result.json`. Produced by `scripts/assemble_result.py`, verified by `scripts/validate_result.py`.

If `/input/case.json` declares an `output_contract` (list of keys or object schema), **every key must be present**. `assemble_result.py` copies the keys from `contract.json` and fills any missing one with `null` plus an `uncertainties` entry — so you must still *populate* the ones that matter. Standard keys below are always present.

```json
{
  "case_id": "copied from case.json; 'unknown' if absent",
  "status": "success | partial | not_determinable | refused",
  "status_reason": "what is incomplete / why refused / where a human should take over",
  "scope": {"focus": ["..."], "out_of_scope": ["..."], "assumptions": ["..."]},
  "sources": [
    {
      "source_id": "10.xxxx/yyy",
      "doi": "10.xxxx/yyy",
      "title": "from corpus-manifest.json",
      "authors": "from corpus-manifest.json",
      "role": "primary | secondary",
      "license": "from corpus-manifest.json",
      "source_hash": "from corpus-manifest.json",
      "files": ["primary-material.json", "material.json"],
      "duplicate_formats": [],
      "paragraph_count": 0,
      "status": "ok | missing | unreadable"
    }
  ],
  "nodes": [ ...schema.md node... ],
  "edges": [ ...schema.md edge... ],
  "cross_paper_alignment": {
    "pairs": [{"a": "N:..", "b": "N:..", "decision": "merge|keep_separate|uncertain", "merge_basis": [...], "conflict": "...", "reason": "...", "relation": "..."}],
    "merged": ["N:.."],
    "kept_separate": ["N:.."],
    "uncertain": ["N:.."]
  },
  "queries": [
    {
      "id": "Q1",
      "question": "natural language question the task asked",
      "query": {"name": "neighbors", "args": {"node": "N:..", "hops": 1}},
      "result": {"nodes": [...], "edges": [...], "node_details": [...], "edge_details": [...]},
      "evidence": [{"source_id": "...", "paragraph_id": "...", "quote": "...", "attribution": "...", "evidence_strength": "...", "attached_to": "N:.."}],
      "unresolvable": ["what the graph could not answer and why"],
      "status": "ok | partial | unresolvable"
    }
  ],
  "incremental_update": {
    "base_source": "primary source_id",
    "new_source": "secondary source_id",
    "added_nodes": ["N:.."], "added_edges": ["E:.."],
    "merged_nodes": [{"a": "N:..", "b": "N:..", "basis": [...]}],
    "new_conflicts": ["..."],
    "kept_ids_stable": true,
    "export": ["/app/output/graph.graphml", "/app/output/graph.mmd"],
    "handling": "one paragraph: how new / merged / conflicting items were treated"
  },
  "merge_conflicts": [
    {"a": "N:..", "b": "N:..", "kind": "different_sample | different_conditions | different_object | value_conflict | ambiguous_alias | same_generic_term",
     "description": "...", "evidence_a": {...}, "evidence_b": {...}, "resolution": "kept_separate | merged_with_conditions_recorded | unresolved"}
  ],
  "uncertainties": [
    {"item": "N:.. or E:.. or topic", "reason": "not_reported | linearized_math | missing_file | low_confidence_extraction | third_party_report | indirect_evidence | source_conflict | input_warning",
     "location": {"source_id": "...", "paragraph_id": "..."},
     "statement": "..."}
  ],
  "unreported": ["things the task asked about that the corpus does not state (figures, supplements, raw data)"],
  "change_log": [{"step": "...", "what_changed": "...", "timestamp": "ISO-8601"}],
  "environment": {"python": "...", "scripts": [...], "graph_format": "json", "work_dir": "/app/work"},
  "stats": {"nodes": 0, "edges": 0, "cross_paper_nodes": 0, "cross_paper_edges": 0, "queries": 0, "merged": 0, "kept_separate": 0, "uncertain_pairs": 0, "nodes_by_type": {}, "edges_by_type": {}},
  "_meta": {"output_contract_keys": [...], "contract_keys_added_null": [...], "assembled_at": "..."}
}
```

## Minimal vs complete

| level | what is present | status |
|---|---|---|
| skeleton (saved early, step 3) | all top-level keys, `nodes: []`, `queries: []`, one `uncertainties` entry | `partial` |
| minimal | ≥1 source, nodes with verified evidence, ≥3 executed queries (may be `unresolvable`), `merge_conflicts` possibly `[]` | `partial` or `success` |
| complete | task-required types covered, alignment recorded, export files written, `incremental_update` if asked | `success` |

## Optional side files (write to `/app/output` when relevant)

- `graph.graphml` / `graph.mmd` / `graph.cypher` — export from `scripts/export_graph.py`
- `queries/Q1.json` … — raw query outputs (copies of work files)
- `README.md` — 5 lines: what was built, how to re-run (`python scripts/assemble_result.py ...`), limits

## Validation gate

`python scripts/validate_result.py --result /app/output/result.json --paragraphs /app/work/paragraphs --case /input/case.json --manifest /input/corpus-manifest.json` must exit 0. Every warning must be explained in `uncertainties`.
