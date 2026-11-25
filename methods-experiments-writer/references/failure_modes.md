# Failure modes

Twelve ways this goes wrong, drawn from running the pipeline. Each one appears in a
real draft; each one is caught by something specific or not caught at all — and the ones
not caught are labelled as such.

---

### 1. The smooth sentence with an unsourced value
**Symptom.** "We use a learning rate of 1e-4" and no `1e-4` appears in any file.
**Cause.** The number came from the author's memory of a typical value, or from a
different project. It reads best precisely because it is unconstrained.
**Caught by.** `audit_draft.py` — `unsourced_number`, blocking.
**Fix.** Cite it or delete it. Add a `TO-CONFIRM` block if the parameter matters.

### 2. The config default mistaken for the run
**Symptom.** The config says `weight_decay: 0.01`; the log says `weight_decay=0.1` with
"command line override"; the draft says `0.01`.
**Cause.** The config file is the most convenient source, so it wins by default.
**Caught by.** `scan_case.py` conflict detection — two rows, both `status: conflict`.
**Fix.** Report both, mark `TO-CONFIRM`, ask. Do not pick.

### 3. The truncated version
**Symptom.** "torch 2.1" for a run that used `torch 2.1.2`.
**Cause.** A regex stops at the third digit, or a human abbreviates.
**Caught by.** The scanner's version extension — it keeps consuming `.digits` past the
first stop, so `2.1.2` stays `2.1.2`. The audit checks version strings against the ledger
as strings, so `2.1` will not match a row holding `2.1.2`.
**Fix.** Cite the full version.

### 4. The epoch counter read as a setting
**Symptom.** The log line `Epoch 97/120` becomes "we trained for 97 epochs".
**Cause.** A generic `key=value` scanner over a log sees `Epoch = 97`.
**Caught by.** `LOG_KEY_EXCLUDE` skips bare `epoch`/`step`/`iter` keys; totals come from a
dedicated pattern instead.
**Fix.** If you write the epoch count, take it from the `epochs` setting or from the
`N/M` of the last epoch line, and say which.

### 5. The number that labels structure
**Symptom.** The audit reports `unsourced: 2` for the "2" in "## 2. Experimental setup".
**Cause.** Structural digits are digits.
**Caught by.** Masking of section numbers, ordered-list markers, figure/table references,
citation brackets, versions and timestamps before the numeric scan.
**Fix.** Nothing — this is the audit's job to absorb.

### 6. The parameter table that agrees with itself
**Symptom.** The table says `0.01` for weight decay; the ledger's cited row says `0.1`.
**Cause.** The table was written from memory while the prose was written from the ledger.
**Caught by.** Each table row must corroborate a value it cites. A row citing an eid but
carrying a different number is blocking.
**Fix.** Regenerate the table from the ledger, or fix the citation and say which is right.

### 7. The boilerplate limitations paragraph
**Symptom.** "Our method has some limitations and future work may address them."
**Cause.** Limitations are written last and nobody knows what to say.
**Caught by.** The limitations element requires a limitation, a concrete condition and a
scope; the audit also flags boilerplate phrases.
**Fix.** Name the condition under which the method fails. If you cannot, ask the author —
this is a question only they can answer.

### 8. The silent parse failure
**Symptom.** The scan reports 4 evidence rows for a case with a 40-page PDF and three
configs.
**Cause.** The PDF had no text layer; the configs were XML.
**Caught by.** A gap (`pdf_text_not_extracted`, `unreadable_<file>`) rather than a silent
zero.
**Fix.** Extract the text with whatever the image has, `--extra-text`, re-run. Do not write
the section from the file names.

### 9. The token budget spent re-scanning
**Symptom.** The run ends with a half-written section after 60 model requests.
**Cause.** Re-running `scan_case.py` after every paragraph.
**Caught by.** Nothing but discipline.
**Fix.** Scan once, draft the whole section, audit once, revise, emit. Three tool calls,
not thirty.

### 10. The empty-result success
**Symptom.** `status: success` with an empty `uncertainty` list on real materials.
**Cause.** The draft was written only from well-covered parts and the gaps were quietly
dropped.
**Caught by.** The self-check in `SKILL.md` — non-empty uncertainty is expected on real
materials.
**Fix.** Reconcile `gaps.json` with `open_questions.md`. If the scan found gaps and the
question list is empty, either the draft answered them (say so, the emit does that
automatically) or they were lost.

### 11. The unsatisfiable contract field
**Symptom.** `result.json` has a contract field containing a paragraph of plausible text
that no deliverable produced.
**Cause.** The instinct to look finished.
**Caught by.** `emit_outputs.py` writes `null` and names the field in `uncertainty`.
**Fix.** Do not override it with prose. If the field genuinely needs a deliverable, add one.

### 12. The claimed preview
**Symptom.** "A PDF preview is included" when LibreOffice was not installed.
**Cause.** The docx was produced, so the preview was assumed.
**Caught by.** `previews` is populated by what actually returned a file; the absence is
written into `previews.notes` and into `uncertainty`.
**Fix.** Report the limit. An unrendered deliverable is acceptable; a claimed one that
does not exist is not.

---

## The pattern behind most of these

Every failure above is a case of **a fluent output standing in for a checked one**. The
pipeline is built so that the checked path is also the easy path: the ledger makes citation
cheaper than recall, the audit makes the unsourced number visible before a reviewer sees
it, and the null-field rule makes an unfinished field cheaper than a fabricated one.

None of it works if the writer treats the audit as an obstacle. It is cheap because it
runs; it is only useful if you run it before you believe your own draft.
