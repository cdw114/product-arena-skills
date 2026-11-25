<!-- part:background -->
## 1 Background

Molecular property prediction decides which compounds reach an assay, and the binding
constraint on it is labelled data: a single high-quality measurement costs weeks of
bench work, so most tasks supply a few hundred labels rather than the tens of
thousands that supervised training assumes. The progress of the last decade has been
on the representation side. Message passing over a fixed neighbourhood radius [2] and
localized spectral propagation [1] supply the inductive bias that makes molecular
graphs learnable, and physically motivated continuous filters push single-task
accuracy on quantum-chemical targets towards experimental error [8].

That bias fixes what a model can represent, not how much data it needs. SchNet-class
models are trained from scratch for every task [8], so each new endpoint pays the full
training cost again, and this is why self-supervised pretraining has become the
default: masked atom and bond objectives, contrastive objectives over chemically
meaningful positives, and mutual-information objectives over graph substructures all
transfer to downstream endpoints with far fewer labels [3, 4, 5, 6]. The recipe is now
stable. What it assumes is not.

Every one of these objectives is defined over an unlabelled pool that is taken as
given, whole and free. Contrastive pretraining scans the entire pool each epoch, so
the number of forward passes grows with pool size [4], and graph-transformer
pretraining on eleven million molecules does the same [6]. The corpus therefore
enters the budget as a cost and never as a decision variable.
<!-- /part:background -->

<!-- part:related_work -->
## 2 Related Work

Three routes can be distinguished by what they treat as the thing to optimise. The
first optimises the pretraining objective. Node- and graph-level objectives can be
combined, and objective choice matters more than encoder capacity, to the point where
naive pretraining hurts [3]; contrastive positives built from atom masking, bond
deletion and subgraph removal outperform supervised training when labels are scarce
[4]; mutual-information objectives between graph and substructure embeddings are
competitive on graph-level benchmarks [5]; and node- and edge-level self-supervision
on a graph transformer transfers to molecular classification at scale [6]. These
works differ in sample efficiency per epoch but agree on the setting: the pool is
fixed and every molecule is visited. Their trade-off is therefore a trade-off in the
objective alone, whereas the compute cost per epoch is set by a quantity that none of
them varies.

The second route optimises which molecules are used. Greedy k-centre selection gives
a subset whose training error is bounded relative to the full set [7]; label-aware
selection instead ranks molecules by how informative they would be for the downstream
label budget and gains up to 8.6% over random pretraining [9]. The two differ in what
they trust: [7] trusts a fixed feature space enough to guarantee coverage inside it,
whereas [9] trusts an informativeness estimate and gives up any guarantee. Scaling
studies supply the missing quantity: downstream error falls as a power law in corpus
size and flattens past roughly one million molecules [10], which implies that a large
fraction of the pool is redundant, but the law is fitted on an uncurated corpus and so
cannot say how small a curated one could be. Taken together, the three works establish
that the corpus matters and that no existing selection rule optimises its cost.

The third route optimises the encoder and its geometric priors [1, 2, 8]. Localized
propagation scales linearly in edges and reaches global spectral information only by
stacking layers [1]; a single message-passing step cannot see beyond its radius [2];
continuous-filter convolution enforces rotation and translation invariance and reaches
state of the art on a single task without any pretraining [8]. This route is
complementary rather than competing: it fixes the representable space in which any
selection rule must operate, and its cost model of retraining per task is precisely
what pretraining is meant to remove.
<!-- /part:related_work -->

<!-- part:gap -->
## 3 Research Gap

The corpus question is not unanswered so much as unasked. Selection rules optimise
either coverage of a feature space that does not yet exist [7] or the label budget
[9], and both leave the cost of pretraining unmodelled, while label-aware selection
explicitly ignores the cost of the corpus itself [9]. Scaling evidence says most of
the pool is redundant [10], and the large-scale pretraining papers observe the cost
without testing whether a smaller corpus would suffice [6]. The gap is therefore a
mismatch of objective: the quantity that decides whether low-resource pretraining is
affordable is the pretraining cost, and no cited selection rule optimises it, because
none of them is stated over a representation that is still being learned [7].

We take that mismatch as the design target. This paper treats the unlabelled pool as a
decision variable rather than a cost, selects a coverage-maximising coreset in a fixed
spectral embedding before any pretraining happens, and pretrains only on that subset.
Because selection precedes learning, the coverage argument of [7] applies where it
previously could not, and because the budget is explicit, the plateau observed in [10]
becomes a quantity to be reached sooner rather than a law to be obeyed.
<!-- /part:gap -->

<!-- part:contributions -->
## 4 Contributions

- **A selection-before-pretraining pipeline.** Molecules are ranked by a greedy
  coverage score in a spectral embedding of the graph Laplacian and only the selected
  coreset is pretrained, so the corpus cost becomes a tunable budget rather than a
  fixed tax (Section 3, Fig. 1).
- **Accuracy at a fixed label budget.** At 100 labels per dataset the pipeline
  improves accuracy by 11.3% over the strongest self-supervised baseline and reduces
  pretraining cost by 62.4%, from 41 GPU-hours to 15.4 GPU-hours (Table 1, Table 3).
- **An attribution of the gain.** Removing the coverage score and selecting uniformly
  drops accuracy by 6.8%, while removing masked bond prediction costs only 1.4%, so
  the benefit comes from which molecules are used rather than from the objective
  (Table 2).
- **A budget sweep.** The advantage persists as the coreset budget grows and narrows
  to 3.1% at a 20% budget, which locates the regime in which selection stops paying
  (Fig. 2).

We claim this for molecular property prediction with large unlabelled pools and small
label budgets. We do not claim a theoretical guarantee for the coverage score, and we
do not claim transfer to protein families outside the kinase panel used here.
<!-- /part:contributions -->
