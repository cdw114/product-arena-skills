# Worked example

**This is a toy case.** Every file under `examples/input/` was written for this example and
no experiment was run. The numbers are internally consistent on purpose, so the pipeline
can be exercised in both directions: a draft that sources everything passes, and one
fabricated number blocks.

Reproduce it yourself:

```bash
python3 scripts/selftest.py --keep ./selftest_out
```

---

## The input

Four material files, deliberately the shape a real paper's supplement takes — a config, a
log, the entry point, and a data note:

| file | what it provides |
|---|---|
| `examples/input/materials/config.yaml` | nested settings: seed, model, optimiser, schedule, data ratios |
| `examples/input/materials/train.log` | versions, hardware, a resolved-config line, split counts, per-epoch lines, an override warning |
| `examples/input/materials/train.py` | argparse defaults, seed calls, the run command in a trailing comment |
| `examples/input/materials/README.md` | dataset tag, split procedure, baseline identity, repeat count, evaluation protocol |

`examples/input/case.json` declares the contract:

```json
"output_contract": {
  "methods_section": "markdown text of the Methods and Experiments section, ...",
  "parameter_table": "table of parameter name, value, unit, target and source",
  "evidence_map": "per-fact source locator ...",
  "coverage_report": "status of the six required elements ...",
  "open_questions": "items only the author can confirm ..."
}
```

## Step 1 — scan

```bash
python3 scripts/scan_case.py --input examples/input --work work
```

```
materials: 6   evidence_rows: 53   param_rows: 43   conflicts: 1   gaps: 7
coverage: steps partial, setup partial, params complete, datasets partial,
          baselines partial, repro partial, limitations missing
```

What it produced, abridged:

| eid | kind | name | value | locator |
|---|---|---|---|---|
| E0006 | config_value | `experiment.seed` | `42` | `materials/config.yaml#/experiment/seed` |
| E0011 | config_value | `train.epochs` | `120` | `materials/config.yaml#/train/epochs` |
| E0017 | config_value | `data.version` | `v1.2` | `materials/config.yaml#/data/version` |
| E0029 | log_value | `torch_version` | `2.1.2` | `materials/train.log:1` |
| E0042 | log_value | `weight_decay` | `0.1` | `materials/train.log:11` |
| E0053 | code_fact | `run_command` | `python train.py --config materials/config.yaml ...` | `materials/train.py:34` |

Three things worth noticing:

1. **The version is whole.** The log line is `torch 2.1.2`; a naive `key: value` scan stops
   at `2.1`. The scanner keeps consuming dotted digits.
2. **`data.version` is a dataset version, not a framework version.** The parent path
   decides; reading only the leaf files it under `framework_version`.
3. **One conflict, and it is real.** `train.weight_decay` is `0.01` in the config (E0012)
   and `0.1` in the log (E0042), where the log also says it was overridden on the command
   line. The per-epoch lines (`Epoch 97/120`) do *not* generate a fake `epochs` conflict,
   because a bare `Epoch` key is excluded from the key/value scan.

## Step 2 — draft

`examples/reference/draft.md`. Its opening rule is the skill's opening rule:

> We train a graph neural network to regress a scalar property of polymer structures, using
> the GINEConv architecture **[E0023]**. The pipeline runs in five ordered steps. Each step
> names what it consumes, what it produces, and the condition under which it fails, because
> a step whose failure mode is unstated cannot be checked by a reader.

and the conflict gets its own paragraph rather than a resolution:

> **TO-CONFIRM — weight decay.** The configuration sets 0.01 **[E0012]**. The training log
> records 0.1 and states that the value was read from the command line and overrode the
> configuration **[E0042]**. Both values are reported as they were found and neither is
> chosen.

## Step 3 — audit

```bash
python3 scripts/audit_draft.py --draft work/draft.md --work work --strict
```

```
verdict: ready
unsourced_numbers: 0   value_without_local_citation: 0
table_mismatches: 0    elements_complete: 7/7
```

## The negative run

One fabricated sentence appended to the same draft:

```
We also trained for 9000 epochs on 7 nodes with 512 workers.
```

```
verdict: blocked
must_fix: replace or source 1 number/version(s) that appear nowhere in the ledger: 9000
```

`9000` is caught because it is in no row. `512` is caught the same way. `7` is reported as
`value_without_local_citation` — 7 exists in the ledger (as the split seed) but this
paragraph does not cite it, so the paragraph is making a claim it cannot back. That
distinction matters: a number that exists *somewhere* is not the same as a number that is
*sourced here*, and only the second one is a citation.

## Step 4 — emit

```bash
python3 scripts/emit_outputs.py --input examples/input --work work --out out
```

```
status: success      contract fields: 5/5      audit_verdict: ready
```

`out/result.json`, abridged:

```json
{
  "case_id": "EXAMPLE-0001",
  "status": "success",
  "status_detail": "every contract field was filled and the draft audit did not block",
  "outputs": {"methods_section": "...", "parameter_table": "...", "...": "..."},
  "fact_source_map": [{"eid": "E0006", "fact": "experiment.seed", "value": "42",
                       "locator": "materials/config.yaml#/experiment/seed",
                       "confidence": "high", "status": "ok"}],
  "uncertainty": [
    {"id": "conflict_weight_decay", "kind": "conflict",
     "statement": "Which source is authoritative for 'weight_decay'? ...",
     "resolve_by": "author names the authoritative source"},
    {"id": "gaps_closed_by_draft", "kind": "observation",
     "statement": "6 scan-time gap(s) are answered by the finished draft ..."},
    {"id": "preview_note_0", "kind": "assumption",
     "statement": "docx not produced: python-docx not importable ..."}
  ],
  "version_and_boundaries": {"gaps_open": 1, "audit_verdict": "ready", ...}
}
```

Two behaviours visible here that are easy to get wrong:

- **`gaps_closed_by_draft`.** The scan found six element gaps because the materials are
  incomplete; the finished draft answers all six by asking the right questions and marking
  the unconfirmed values. They are recorded as closed, not silently dropped, and not left
  in the open list where they would contradict the coverage report.
- **`preview_note_0`.** `python-docx` was absent in the environment that produced this
  output. The docx was not built and the reason is in `uncertainty`. A run that instead
  claimed a preview would be lying in a field a reviewer is meant to trust.

## What the example does not show

- A real PDF. `examples/input/` has no PDF; PDF text extraction is exercised only in the
  failure path (recorded gap, `--extra-text` retry).
- A Chinese case. The coverage patterns accept both languages, but this fixture is English.
- A partially-filled contract. `templates/output_plan.json` documents the override path for
  a contract whose field names do not match a deliverable by keyword.
