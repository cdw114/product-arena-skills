# Section outline

Fill every slot. A slot you cannot fill from the ledger becomes a `TO-CONFIRM` block —
it does not get deleted, because a missing slot is the thing the reader most needs to
know about.

Cite as you write: `... at a learning rate of 0.0003 [E0009] ...`.
One tag may cover several numbers in one clause; a number in a new clause needs its own.

---

## Procedure

<intro: what is trained or computed, from what input, to what end. One or two sentences.>

1. **<verb phrase>.** Input: <what it consumes, with the file>. Operation: <what it does,
   concretely>. Output: <what it produces, and where it lands>. Failure condition: <the
   condition under which this step silently produces the wrong thing, or aborts>.

2. **<verb phrase>.** Input: … Operation: … Output: … Failure condition: …

<repeat. Each step is one action at one level of detail: do not fold "build the splits"
and "train" into one numbered item, and do not split "load the config" into five.>

## Experimental setup

Hardware: <device model, count, memory> [E####].
Software: <framework, version> [E####], <CUDA / driver / runtime> [E####], <OS or image>.
Randomness: <run seed> [E####], <split seed if separate> [E####]; state which libraries
were seeded and when, relative to model construction.
Repeats: <n> [E####], and what is aggregated across them.

<one paragraph on what is separated from what: which split drives model selection, which
is read once, which is never touched.>

## Parameters

The full table, with units and sources, is `parameter_table.md`. The values a reader needs
to re-run the main experiment:

| parameter | value | unit | target | source |
|---|---|---|---|---|
| <name> | <value> [E####] | <unit> | <the object it acts on> | `<file>` [E####] |

<If any parameter is contested, a block per parameter:>

**TO-CONFIRM — <parameter>.** <File A> sets <value> [E####]. <File B> records <value> and
says <why they differ> [E####]. Both are reported and neither is chosen. The section must
not state a single value here until the author confirms which one the reported run used.

## Datasets and splits

<dataset name> [E####] at <version / release tag> [E####] contains <size and unit> [E####].
The split is <ratios> [E####] which is <absolute counts> [E####]. The split is drawn by
<method> with <seed> [E####], independent of the run seed [E####]. The validation split
drives <what>; the test split is used for <what> and nothing else.

Preprocessing: <what was removed, normalised, filtered, and where that is recorded>.

**TO-CONFIRM — dataset access.** <what is missing: location, licence, access condition.>

## Baselines and comparison

We compare against <baseline> <version> [E####], <what it is and where it comes from>
[E####]. The comparison holds the budget fixed: <hardware> [E####], <schedule> [E####],
<same splits or not> [E####]. Because <the budget statement>, a difference between them is
a statement about the methods and not about the compute either one received.

The metric is <metric> [E####] on <which split>, averaged over <n> repeats [E####] and
reported as <mean ± std | median and IQR | …>. <how a difference is called meaningful.>

## Reproducibility

- **Code and command.** `<path>`, invoked as `<command>` [E####].
- **Environment.** <versions> [E####].
- **Hardware.** <device> [E####].
- **Seeds.** <values> [E####].
- **Repeats.** <n> [E####].
- **Data access.** <how to obtain it> [E####].

**TO-CONFIRM — code state.** <the version-control identifier that is missing, and the
consequence: the exact revision cannot be pinned from the materials.>

## Limitations

<One paragraph per limitation. Each one names the condition under which the method fails,
and stops. Not "may not generalise" — "fails when <specific condition>, because <specific
mechanism>, which shows up as <specific symptom>.">

The results do not transfer to runs that change <the thing the tuning depended on>; each of
those needs a fresh <sweep / calibration>.

---

## Fact-to-source map

`evidence_map.md` carries the full ledger. Conventions: a text or log locator is
`path:line`; a JSON or YAML locator is `path#/json-pointer`.

## Open questions for the author

`open_questions.md`, generated from the scan's gap list and every conflict found.
