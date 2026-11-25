# Sentence rules that keep prose evidence-bound

These are the rules the audit can enforce and the ones it cannot. The second group matters
more: the audit only sees numbers, so the ways a methods section goes wrong without a
number are the ones that reach the reviewer unchecked.

## Enforceable by the audit

**1. Every number sits next to its citation.**
`... at 0.0003 [E0009] ...`, not `... at 0.0003 ... [E0009]` two sentences later. The
audit checks the paragraph, but a reader checks the clause.

**2. A number in a new clause gets a new citation.**
A citation covers the numbers in its own clause. Two clauses, two citations — even when
both come from the same eid.

**3. Tables and prose share one ledger.**
If the table says `0.01` and the paragraph says `0.1`, one of them is wrong and the audit
blocks until you say which. Never fix this by editing the table to match the prose.

**4. Derived values are marked.**
The effective batch is `64 × 2 = 128`. If you write `128`, say it is derived:
`an effective batch of 128 samples (64 [E0010] × 2 [E0014])`. A derived number with no
derivation is indistinguishable from a fabricated one.

**5. Units are stated or the number is dimensionless.**
`batch 64` is ambiguous: per device, per step, or accumulated? Write `64 samples per device
per step`.

## Not enforceable, and more important

**6. Do not let a sentence flow better than its evidence.**
The characteristic failure: the materials give `epochs: 120` and a log line mentioning
`best_epoch=97`, and the draft says "we trained for 120 epochs and selected the best
checkpoint at epoch 97" — which is fine — or "we trained for 97 epochs", which is not,
because it converted a selection result into a setting. If a sentence needs a value the
ledger does not have to stay grammatical, rewrite the sentence, not the value.

**7. Assertions about comparison need their budget.**
"Outperforms the baseline" is only a measurement if the baseline got the same compute. If
the materials do not say so, the sentence becomes "we compare against X v0.9 as reported in
the original paper" — a weaker claim that is also true.

**8. Do not call something a result when it is a setting.**
Learning rate, batch size and epochs are settings. MAE, F1 and wall-clock are results. A
methods section that reports results looks complete and is mis-filed; a results section
that reports settings cannot be checked against anything.

**9. Silent success is a failure mode of writing, not of code.**
If a PDF had no text layer, if a config parser fell back to line scanning, if a renderer
was missing — say so in the section's own limits or in `open_questions.md`. A methods
section that does not mention the gap reads as though there were none.

**10. Write the failure condition into the step, not into a caveat at the end.**
"we split the data by scaffold" and "a leak would bias the error" are one sentence, not
two paragraphs apart. The condition belongs where the reader is when they would do the
step themselves.

**11. Numbers a reader cannot use are noise.**
`1,000,000 training steps` when the unit is really `1 epoch = 1000 steps` and training
stopped at 120 epochs: the useful fact is the epoch count and the batch arithmetic. State
the setting the code actually takes.

**12. Precision claims precision.**
`0.0003` claims four decimal places; `3e-4` claims one significant figure. Write the value
at the precision the source gives, not more. A table that reports `0.00030000` when the
config said `3e-4` has invented precision.

## A test to apply to any paragraph you have written

Read it as though you were the reviewer with the code open in another window. For each
sentence, ask: **could I now get the same number?** If the answer depends on something not
in the sentence — a seed set earlier, a version recorded elsewhere, a split drawn some
other way — that something is missing from the methods section, however well the sentence
reads.

## Language note

Cases arrive in Chinese and English. Write the section in the language of `task.md`. The
audit's coverage patterns accept both, so switching language mid-run is safe; mixing both
in one section is not, except for terms that genuinely have no translation (`bf16`,
`AdamW`, a dataset name).
