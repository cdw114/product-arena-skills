<!--
WORKED EXAMPLE - NOT A REAL EXPERIMENT.

This is the output shape the skill aims at, written against the toy fixture in
examples/input/. Every [E####] tag resolves to a row in the ledger that
scripts/scan_case.py builds from examples/input/materials/*. scripts/selftest.py
reproduces the whole chain and fails if any number here loses its source.

Do not read any value below as scientific data.
-->

# Methods and Experiments

## Procedure

We train a graph neural network to regress a scalar property of polymer structures, using
the GINEConv architecture [E0023]. The pipeline runs in five ordered steps. Each step names
what it consumes, what it produces, and the condition under which it fails, because a step
whose failure mode is unstated cannot be checked by a reader.

1. **Load and validate the configuration.** Input: `materials/config.yaml`, read by the entry
   point `materials/train.py` [E0053]. Operation: parse the nested YAML and assert that every
   key the optimiser needs is present. Output: an in-memory configuration object. Failure
   condition: when a training key is absent the run aborts before a GPU is allocated, so an
   incomplete configuration never reaches the training loop.
2. **Fix randomness.** Input: the configuration object. Operation: seed Python, NumPy and
   PyTorch from `experiment.seed` = 42 [E0006], and set the CUDA seeds to the same value in
   the entry point [E0051]. Output: a deterministic random state. Failure condition: the CUDA
   seeding calls are skipped when no GPU is visible, so a CPU run cannot be treated as a
   replicate of a GPU run.
3. **Build the splits.** Input: `PolymerSplit` [E0016] at release tag `v1.2` [E0017].
   Operation: draw a scaffold split with a dedicated split seed of 7 [E0018] using the
   configured fractions 0.8 / 0.1 / 0.1 [E0019] [E0020] [E0021], which the log records as
   8000 / 1000 / 1000 rows [E0045] [E0046] [E0047]. Output: three disjoint index sets.
   Failure condition: when one scaffold appears in more than one split the test set leaks and
   the reported error is optimistic, so the splitter runs before any model is instantiated.
4. **Train.** Input: the training split and the configuration object. Operation: minimise MAE
   for 120 epochs [E0011] with AdamW [E0008] at a learning rate of 0.0003 [E0009], batch size
   64 [E0010], accumulating gradients over 2 steps [E0014], in bf16 precision [E0015], with
   500 warmup steps [E0013]. Output: a checkpoint whenever the validation MAE improves.
   Failure condition: training diverges when the learning rate is paired with an effective
   batch other than the one it was tuned at, so the accumulation factor is held fixed across
   every run reported here.
5. **Evaluate.** Input: the checkpoint chosen on the validation split. Operation: compute MAE
   on the test split over 3 repeats [E0002] and report mean and standard deviation. Output:
   the results table. Failure condition: with fewer than 3 repeats [E0002] the standard
   deviation is not estimable, so a single-run number must not be presented with an
   uncertainty.

## Experimental setup

Hardware: one NVIDIA A100-SXM4-40GB [E0033] with 40 GB of device memory [E0034]. Software:
Python 3.10.13 [E0030], torch 2.1.2 [E0029], CUDA 12.1 [E0031], cuDNN 8.9.2 [E0032].
Randomness: run seed 42 [E0006] and split seed 7 [E0018]; the two are independent on purpose,
so a reader can hold one fixed while varying the other. Repeats: every configuration was
trained 3 times [E0002] and the mean is reported with the standard deviation.

Training and evaluation are separate passes over separate data. The validation split drives
checkpoint selection only; the test split is read once per repeat and never used for
selection, thresholding or early stopping.

## Parameters

The full parameter table, with units, the object each value acts on and the file it came
from, is `parameter_table.md`. It is generated from the same ledger as this paragraph, so the
two cannot disagree. The values a reader needs in order to re-run the main experiment:

| parameter | value | unit | target | source |
|---|---|---|---|---|
| learning rate | 0.0003 | 1 | optimiser | `materials/config.yaml` [E0009] |
| batch size | 64 | samples | dataloader | `materials/config.yaml` [E0010] |
| gradient accumulation | 2 | steps | optimiser step | `materials/config.yaml` [E0014] |
| epochs | 120 | epochs | training loop | `materials/config.yaml` [E0011] |
| warmup | 500 | steps | learning-rate schedule | `materials/config.yaml` [E0013] |
| dropout | 0.1 | 1 | model | `materials/config.yaml` [E0007] |
| hidden dimension | 256 | 1 | model | `materials/config.yaml` [E0024] |
| layers | 4 | 1 | model | `materials/config.yaml` [E0025] |
| precision | bf16 | 1 | autocast context | `materials/config.yaml` [E0015] |

**TO-CONFIRM — weight decay.** The configuration sets 0.01 [E0012]. The training log records
0.1 and states that the value was read from the command line and overrode the configuration
[E0042]. Both values are reported as they were found and neither is chosen. Until the author
confirms which one the reported run used, the section must not state a single number here:
writing one of them would describe a run that may not have happened.

## Datasets and splits

`PolymerSplit` [E0016] at release tag `v1.2` [E0017] contains 10000 polymer structures with
one scalar target each [E0039]. The split is 0.8 / 0.1 / 0.1 train / validation / test
[E0019] [E0020] [E0021], which is 8000 / 1000 / 1000 rows as recorded in the run log
[E0045] [E0046] [E0047] and in the dataset note [E0001]. The split is drawn by scaffold
[E0003] with a split seed of 7 [E0018] that is independent of the run seed [E0006].

**TO-CONFIRM — dataset access.** The materials name the release tag but give no download
location, licence or access condition. The section therefore makes no statement about
redistribution or about where a reader obtains the data.

## Baselines and comparison

We compare against `GNN-baseline` v0.9 [E0004], the baseline of the original paper, re-trained
here rather than quoted [E0005]. The comparison holds the budget fixed: one A100-SXM4-40GB
[E0033], 120 epochs [E0011], the same splits [E0001]. Because neither model received more
compute than the other, a difference between them is a statement about the models and not
about the budget.

The metric is MAE on the test split, averaged over 3 repeats [E0002] and reported as mean and
standard deviation. A difference is called meaningful only when the two intervals do not
overlap; where they do overlap the section says the two are indistinguishable at this sample
size instead of ranking them.

## Reproducibility

- **Code and command.** `materials/train.py`, invoked as
  `python train.py --config materials/config.yaml` [E0053].
- **Environment.** Python 3.10.13 [E0030], torch 2.1.2 [E0029], CUDA 12.1 [E0031], cuDNN
  8.9.2 [E0032].
- **Hardware.** One NVIDIA A100-SXM4-40GB [E0033] with 40 GB [E0034].
- **Seeds.** 42 for the run [E0006], 7 for the split [E0018].
- **Repeats.** 3 per configuration [E0002], mean and standard deviation reported.
- **Run start recorded in the log.** 2026-03-02 [E0044].

**TO-CONFIRM — code state.** No version-control identifier appears in any material file. The
exact commit cannot be pinned from the evidence available, so the section cites the file and
the command and leaves the revision to the author.

## Limitations

The protocol fails when the evaluation set is drawn from a scaffold distribution disjoint from
training at a granularity finer than the splitter's own: under that condition the validation
split stops predicting test performance, and model selection optimises the wrong objective
while still looking healthy. It also fails when the effective batch is changed without
repeating the learning-rate sweep, because 0.0003 [E0009] was tuned at the accumulated batch
implied by 64 [E0010] times 2 [E0014]. The results therefore do not transfer to runs that
change the effective batch, the hidden dimension [E0024] or the number of layers [E0025];
each of those needs a fresh sweep. A single run carries no uncertainty estimate and is outside
the scope of the claims made here.

---

## Fact-to-source map

`evidence_map.md` carries the full ledger: every row, its locator and its confidence.
Conventions: a text or log locator is `path:line`; a JSON or YAML locator is
`path#/json-pointer`. A reviewer re-opens either form directly.

## Open questions for the author

`open_questions.md` is generated from the scan's gap list together with the one source
conflict found in the materials (weight decay). Each item names the file to open.
