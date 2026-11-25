<!-- part:background -->
## 1 Background

In recent years, molecular property prediction has attracted widespread attention, and
with the rapid development of deep learning it has become an important research topic.
Prior work has shown that pretraining on more molecules always helps. Molecular graph
encoders inherit a localized propagation rule from graph convolutional networks [1, 2],
and physically motivated continuous filters reach competitive accuracy on
quantum-chemical targets [8]. Contrastive pretraining scans the whole unlabelled pool
every epoch, so the number of forward passes grows with pool size [4].

The corpus is therefore the binding cost of the whole recipe.
<!-- /part:background -->

<!-- part:related_work -->
## 2 Related Work

Sener and Savarese select a subset of images by solving a k-centre problem on the
learned representation. The subset bounds the training error relative to the full set
[7]. The method is demonstrated on image classification.

Kipf and Welling propagate features along graph edges with a localized spectral filter.
The propagation rule scales linearly in the number of edges [1].

Gilmer and colleagues unify molecular models into a message-passing framework and set
a fixed neighbourhood radius per step [2].

Pretraining objectives for graphs have been studied systematically [3], extended to
contrastive positives built from chemical substructures [4], formulated as mutual
information between graph and substructure embeddings [5], and scaled to a graph
transformer over eleven million molecules [6]; a recent survey reports the same trend
\cite{baddoi2026}, and a follow-up applies the recipe to polymers
\cite{zhang2024phantom}. Encoder-side priors are reviewed elsewhere [8].
<!-- /part:related_work -->

<!-- part:contributions -->
## 4 Contributions

- **A selection-before-pretraining pipeline.** Molecules are ranked by a greedy
  coverage score in a spectral embedding and only the coreset is pretrained
  (Section 3, Fig. 1).
- **The first to make molecular pretraining affordable at 100 labels.** It improves
  accuracy by 27.4% over the strongest baseline (Table 9).
- **An attribution of the gain.** The benefit comes from which molecules are used
  rather than from the objective.
- **A budget sweep.** The advantage persists as the coreset budget grows (Fig. 9).

We claim this for molecular property prediction with large unlabelled pools and small
label budgets.
<!-- /part:contributions -->
