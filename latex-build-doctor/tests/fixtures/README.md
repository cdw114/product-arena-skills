# Log fixtures — what they are and what they are not

These `.log` / `.blg` files drive `scripts/selftest.py`. They are **hand-written transcripts
that follow the published grammar of the TeX, BibTeX and Biber logs**, not files captured from
a compiler run, because the machine this skill was authored on has no TeX distribution
installed (`probe_engines()` reports `any_engine: false` there).

That distinction matters and is not hidden anywhere:

- What the fixtures **do** prove: the parser is driven by the documented line grammar —
  `! <message>` blocks, `<file>:<line>: <message>` blocks produced by `-file-line-error`,
  the parenthesis file stack, `Runaway argument?`, `l.<n>` position lines, `Overfull \hbox`
  records, `Missing character`, `Output written on ...`, `\citation`/`\bibcite` in `.aux`,
  and the `WARN -` / `ERROR -` prefixes in Biber output.
- What they **cannot** prove: that the messages appear in exactly this order for a specific
  real document. That is a property of the document, not of the parser.

The first time the skill runs inside an image with `pdflatex` present, the compile loop reads
real logs and `build/pass-*.log` keeps them, so any parser gap shows up as a diagnostic that
says `E-OTHER` instead of one of the specific rules. `references/error-catalog.md` lists every
rule with the log signature it is keyed on, so a gap is diagnosable from the output alone.
