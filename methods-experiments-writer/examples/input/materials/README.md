# PolymerSplit

Dataset: **PolymerSplit v1.2** (release tag `v1.2`, published 2026-02-11). 10000 polymer
structures with a scalar target.

Split: 8000 / 1000 / 1000 train / val / test, drawn by scaffold with `split_seed=7`.
The test split is never touched during model selection.

Baseline: **GNN-baseline v0.9** from the original paper, re-trained here with the same
compute budget (one A100-40GB, 120 epochs) so the comparison is like for like.

Run: `python train.py --config materials/config.yaml`

Evaluation: MAE on the test split, averaged over 3 repeats, reported as mean +- std.
