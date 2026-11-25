# Reproducibility checklist

Generated as `reproducibility_checklist.md` by `emit_outputs.py`. A box is ticked only
when the **section** states the item — not when the materials contain it, and not when it
would be reasonable to assume.

| item | what the section has to contain | why it matters |
|---|---|---|
| code version | a commit hash, tag, release id, or an explicit statement that none can be pinned | without it the numbers belong to no particular code |
| environment | framework and runtime versions, or an image / lock file reference | a version change silently changes results in every ML framework |
| run command | the exact command, including config path and overrides | the command is where overrides live that the config file does not show |
| random seed | every seed used, and at what point in the run it was set | seeds set after model init do not control initialisation |
| data access | a location, DOI, or access procedure | an unreachable dataset makes the paper unreproducible regardless of everything else |
| hardware | device model and count | determines the effective batch, the runtime, and what can be compared |
| repeat count | how many runs were aggregated | a single run has no dispersion, so no comparison is meaningful |
| preprocessing | what was filtered, normalised or dropped, and where that is recorded | the most common silent divergence between two "identical" runs |

## Reading the result

- **All ticked** is not a claim of correctness. It is a claim that a reader can act.
- **Unticked items are not all equal.** `code version` and `data access` are blocking; a
  missing `hardware` line is usually recoverable from the log.
- A ticked box next to a `TO-CONFIRM` block means the section *names* the item and says it
  is unconfirmed. That is consistent: the reader learns the limit, which is the point.

## The three that are almost always missing

In practice, on real materials, these three are absent far more often than the rest:

1. **the seed's position in the run** — "seed 42" without saying it was set before model
   construction proves nothing;
2. **the data split's provenance** — ratios are given, the splitting procedure is not, and
   a random split and a scaffold split give different numbers on the same data;
3. **the baseline's budget** — "we compare against X" without stating that X got the same
   compute turns a measurement into an assertion.

Ask about these three specifically rather than as a generic "more details please".
