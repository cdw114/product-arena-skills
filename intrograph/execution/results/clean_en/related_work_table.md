### Pretraining objectives on a whole unlabelled pool

Dimension: what is predicted during pretraining, and how much of the pool is touched

| Work | Method route | Data / setting | Evaluation | Conclusion | Limitation |
|---|---|---|---|---|---|
| Hu 2020 | node-level plus graph-level masked/contrastive objectives, combined in one schedule | one fixed unlabelled molecular corpus, used whole | downstream classification and regression with a linear or fine-tuned head | objective choice matters more than encoder capacity, and naive pretraining can hurt | corpus treated as a single pool; pretraining cost is not modelled |
| Wang 2022 | contrastive learning with atom masking, bond deletion and subgraph positives | full unlabelled pool, every molecule scanned each epoch | MoleculeNet property benchmarks against supervised baselines | contrastive positives built from chemical subgraphs beat supervised training in low label regimes | number of forward passes grows with pool size and dominates the compute budget |
| Sun 2020 | mutual-information maximisation between graph and substructure embeddings | any unlabelled graph set; choice of set does not enter the objective | eight graph classification benchmarks | unsupervised objectives are competitive with supervised pretraining on graph-level tasks | objective is agnostic to which graphs are used, so redundant graphs cost compute without changing the objective |
| Rong 2020 | graph transformer with node- and edge-level self-supervision | eleven million unlabelled molecules | molecular property classification | large-scale transformer pretraining transfers to molecular tasks | no experiment asks whether a smaller corpus would suffice |

**Trade-off**: All four routes spend their effort on the objective and none on which molecules are used: contrastive or generative objectives differ in sample efficiency per epoch, whereas GPU time per epoch is set by the pool size they all take as given. R0003 shows objective choice is decisive, which makes the corpus question invisible rather than answered.

**Best for**: tasks where the unlabelled pool is small enough that scanning it repeatedly is affordable

### Selecting a subset of the unlabelled pool

Dimension: what signal drives selection, and what it optimises

| Work | Method route | Data / setting | Evaluation | Conclusion | Limitation |
|---|---|---|---|---|---|
| Sener 2018 | k-centre greedy selection in a fixed embedding | image classification and segmentation datasets | error of a model trained on the subset, bounded relative to the full set | a bounded k-centre subset reproduces full-set error | the guarantee is stated for a fixed feature space and does not transfer to learned representations |
| Liu 2024 | per-molecule informativeness estimated for the downstream label budget | unlabelled molecular pool with a 100-label downstream task | downstream accuracy against random pretraining | label-aware selection gains up to 8.6% over random pretraining | selection is guided by label scarcity alone and ignores the cost of the pretraining corpus itself |
| Chen 2025 | empirical scaling law of downstream error against corpus size | a fixed, uncurated corpus across three model families and eighteen tasks | power-law fit of downstream error | returns flatten past roughly one million molecules | the law is fitted on an uncurated corpus, so it cannot say whether a curated subset reaches the same plateau |

**Trade-off**: R0007 optimises coverage of a feature space that does not yet exist, R0009 optimises for the label budget but treats the corpus as free, and R0010 shows the corpus size matters yet assumes it is uncurated. None of the three optimises the cost of pretraining itself, which is the quantity that decides whether low-resource pretraining is affordable.

**Best for**: settings where pretraining compute is abundant and only labels are scarce

### Encoders and geometric priors

Dimension: what inductive bias the encoder supplies, and whether it is pretrained at all

| Work | Method route | Data / setting | Evaluation | Conclusion | Limitation |
|---|---|---|---|---|---|
| Kipf 2017 | first-order approximation of a localized spectral filter | citation and knowledge graphs; node-level tasks | node classification accuracy | localized propagation scales linearly in edges | one hop per layer, so global spectral information needs many layers |
| Gilmer 2017 | message passing over a fixed neighbourhood radius, unified framework | QM9 quantum chemistry | regression error on quantum-chemical targets | message passing reaches state of the art on QM9 | a fixed radius means a single step cannot see beyond it |
| Sch\"utt 2017 | continuous-filter convolution giving rotation and translation invariance | QM9 molecules | mean absolute error on molecular targets | physically motivated filters reach state of the art without pretraining | trained from scratch per task, so every dataset pays the full training cost |

**Trade-off**: These encoders bake in the geometry and topology of molecules, and R0008 shows that is enough to reach state of the art on a single task; the price is that each new task retrains from scratch. The bias and the pretraining question are therefore separable: the encoder fixes what can be represented, and selection fixes what is learned from.

**Best for**: single-task settings with enough labelled data to train from scratch
