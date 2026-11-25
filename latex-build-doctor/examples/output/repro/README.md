# Reproducible build record

Everything here was written by the run that produced the PDF next to it.

| Item | Value |
|---|---|
| main file | `main.tex` |
| engine | `pdflatex` |
| bibliography backend | `bibtex` |
| pass sequence | engine → (bib) → engine → engine |

## Rebuild

```bash
bash repro/build.sh          # or: latexmk -r repro/latexmkrc main.tex
```

## What "same artefact" means

Byte-identical PDFs are not promised by TeX: timestamps and font subset ordering move the
bytes around. The checkable invariants are the ones recorded in `versions.txt`:
engine version, package list and versions, and the sha256 of every input file. With the same
versions and the same inputs, page count and layout reproduce even when the PDF hash does not.
