# The six elements, and what "complete" means for each

The audit scores seven slots (limitations is counted separately from reproducibility).
"Complete" means every piece is present in the prose, not that the topic is mentioned.
Below: the pieces, the failure that each piece prevents, and the wording that usually
means the piece is missing.

---

## 1. Procedure — `steps`

**Pieces:** numbered or stepped structure · input stated · output stated · decision or
failure condition.

**Prevents:** an unreproducible "we then train the model". Without the input and output of
each step, a reader cannot tell where one stage ends and the next begins, so they cannot
place their own data into the pipeline.

**Tell that it is missing:** the section is a single paragraph of prose with no numbering,
or numbered items that each begin with a verb and name no artefact.

**Good:** "Build the splits. Input: `PolymerSplit` v1.2 [E0016]. Operation: scaffold split
with seed 7 [E0018] using 0.8/0.1/0.1 [E0019]. Output: three disjoint index sets. Failure
condition: a scaffold spanning two splits leaks the test set, so the splitter runs before
any model is instantiated."

**Bad:** "We split the data and trained the model."

## 2. Experimental setup — `setup`

**Pieces:** hardware · software versions · random seed.

**Prevents:** the single most common irreproducibility cause. Two runs of the same code on
a different GPU model, framework version or default RNG differ, and the paper gives no way
to tell whether it did.

**Tell that it is missing:** "we trained on a GPU"; "using PyTorch"; a seed mentioned
without saying what it seeds or when.

**Note:** state *when* the seed was set. A seed set after model construction does not
control initialisation, and the sentence "seed 42" is then true and misleading.

## 3. Parameters — `params`

**Pieces:** a table · learning rate · batch · epochs or steps · unit or target.

**Prevents:** a methods section whose numbers are in the config file but not the paper, or
in the paper but wrong.

**Tell that it is missing:** hyperparameters scattered in prose with no table; a value
whose unit is ambiguous (`batch 64` — per device? per step? accumulated?).

**Complete also requires agreement:** the audit checks each table row against the value it
cites. A table that agrees with itself but not with the ledger is worse than no table,
because it looks checked.

## 4. Datasets and splits — `datasets`

**Pieces:** dataset named · version stated · split ratios · size stated.

**Prevents:** the version drift failure. `Dataset v1.1` and `v1.2` are different datasets;
without the tag, the numbers cannot be attributed to either.

**Tell that it is missing:** a dataset name with no release tag; ratios with no statement
of how the split was drawn; "we held out 20%" with no seed.

**The subtle piece:** random split versus scaffold / group / temporal split gives different
numbers on the same data. Which one was used is part of the method, not a detail.

## 5. Baselines and comparison — `baselines`

**Pieces:** baseline named · baseline version · equal-budget statement · metric and
statistics.

**Prevents:** a comparison that is an assertion. "Our model outperforms X" without X's
version and budget is not a measurement — X may have been a different release, or trained
for a tenth of the compute.

**Tell that it is missing:** "compared with existing methods"; "outperforms the baseline";
a metric with no dispersion and no repeat count.

**Complete also requires:** saying how many runs the mean is over, and what counts as a
meaningful difference. A 0.002 gap on 3 runs is not a result.

## 6. Reproducibility — `repro`

**Pieces:** run command · code version · data access · environment.

**Prevents:** a paper that cannot be re-run even by its own authors a year later.

**Tell that it is missing:** "the code is available upon request"; a command without the
config path; versions listed without a lock file or image reference.

**Note:** an explicit "no revision identifier exists; the section cannot pin it" is a
complete piece. Silence is not.

## 7. Limitations — `limitations`

**Pieces:** a limitation named · a concrete condition · the scope of use.

**Prevents:** the boilerplate paragraph that says nothing. "Future work may address these
limitations" is not a limitation; it is a deferral.

**Tell that it is missing:** "may not generalise to other datasets"; "has some
limitations"; anything that could be pasted into another paper unchanged — which is the
test: if the sentence survives being moved to a different paper, it carries no information
about this one.

**Good:** "The protocol fails when the evaluation set is drawn from a scaffold distribution
disjoint from training at a granularity finer than the splitter's own: the validation split
then stops predicting test performance and model selection optimises the wrong objective
while still looking healthy."

**Bad:** "There are some limitations to our approach."

---

## How the audit scores it

Each element is `complete` when every piece matched, `partial` when some did, `missing`
when none did. The score is a floor, produced by keyword matching in both Chinese and
English — it cannot tell whether the sentence under a matched keyword is any good. Read the
draft. The checklist tells you where to look; it does not tell you it is fine.
