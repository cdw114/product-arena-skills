# Writing a question the author can answer

Every gap ends up in `open_questions.md`. A useless question costs the author a round
trip; a useful one costs them ten seconds. The difference is always the same: does it
name the file and the thing to say?

## Bad → good

| bad | why it fails | good |
|---|---|---|
| "Please provide more details about the experiment." | no file, no decision, unanswerable | "`materials/config.yaml` sets `train.weight_decay: 0.01` and `materials/train.log:11` records `0.1` as a command-line override. Which value did the run you want reported use?" |
| "What dataset did you use?" | the dataset is named; the version is the gap | "`materials/README.md` names the dataset but not a release tag. Which tag did the reported run load, and is it still downloadable?" |
| "Please confirm the limitations." | limitations are the author's knowledge, not a form field | "Under which condition does this method fail — input size, a distribution shift, missing metadata? The section needs one concrete condition, not a general caveat." |
| "Is the setup correct?" | invites a yes with no information | "The materials show one A100-40GB and `world_size=1`. Was every reported run single-GPU, or were some run multi-GPU with a different effective batch?" |
| "Add the code version." | the author may not have it | "No commit, tag or release appears in any material file. Do you have a revision identifier for the code state that produced the reported numbers, or should the section say it cannot be pinned?" |

## The pattern

```
<file>:<locator> says <value>.
<file>:<locator> says <other value> | says nothing.
Which is authoritative for <the specific decision>, or should the section say it is unconfirmed?
```

Four parts: the evidence on both sides, the specific conflict, the decision the answer
resolves, and the fallback if the author cannot answer.

## Grouping

- One question per parameter or per missing element. A compound question gets a partial
  answer.
- Order by severity: `blocking` first (a value needed to re-run), then `important`
  (needed for a fair comparison), then `nice` (polish).
- Never merge two unrelated parameters into one item because they came from the same file.

## What not to ask

- Anything the materials already answer. Re-read `scan_report.md` first: half the
  "missing" items are present and were missed by a pattern, not by the author.
- Anything only you can decide, such as how to word the section.
- Anything whose real answer is "add the file" when the file is in front of you.

## Marking the section

A question in `open_questions.md` must have a matching `**TO-CONFIRM — <topic>.**` block
in the prose. If the question is not in the prose, the reader of the paper never learns
the value is unconfirmed — which is exactly the failure this skill exists to prevent.
