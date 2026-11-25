#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checks — static fidelity checks for a LaTeX project (no TeX installation required).

These checks exist because "it compiles" is not the same as "it is right". A document can
build cleanly while a \\ref points at nothing, a table's last row has one cell too many and
silently overflows the margin, an equation's units are typeset in italic math, or the
template's mandatory \\keywords block is missing.

Every finding carries: rule id, severity, file, line, the evidence it was derived from, and
whether the skill may fix it automatically (`auto_fixable`) or must hand it to a human.
"""

import os
import re

import texlib as T

# --------------------------------------------------------------------------------------
# tables and floats
# --------------------------------------------------------------------------------------

TABULAR_BEGIN_RE = re.compile(
    r"\\begin\s*\{(tabular\*?|tabularx|longtable|tabu|longtabu|array|supertabular)\}"
    r"\s*(?:\[[^\]]*\])?\s*")
RESIZE_WRAP_RE = re.compile(
    r"\\(resizebox|scalebox|adjustbox)\s*[{\[(]")
CAPTION_RE = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{")
LABEL_RE = re.compile(r"\\label\s*\{([^}]*)\}")
SECTION_RE = re.compile(r"\\(?:section|subsection|subsubsection|chapter|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{")


def read_brace_group(text, pos):
    """Read a balanced {...} starting at or after `pos`. Returns (content, end_pos)."""
    i = pos
    n = len(text)
    while i < n and text[i] in " \t\n":
        i += 1
    if i >= n or text[i] != "{":
        return None, pos
    depth = 1
    j = i + 1
    while j < n and depth:
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
        j += 1
    if depth:
        return None, pos
    return text[i + 1:j - 1], j


def parse_column_spec(spec):
    """Count the columns a tabular preamble declares. Handles p{..}, *{n}{..}, @{}, >{..}."""
    cols = 0
    i = 0
    n = len(spec)
    while i < n:
        ch = spec[i]
        if ch == "[":
            # an option list such as S[table-format=2.1]: its letters are not column types
            depth = 1
            i += 1
            while i < n and depth:
                if spec[i] == "[":
                    depth += 1
                elif spec[i] == "]":
                    depth -= 1
                i += 1
            continue
        if ch in "lcrXSYs":
            cols += 1
            i += 1
        elif ch in "pmb":
            i += 1
            if i < n and spec[i] == "{":
                depth, i = 1, i + 1
                while i < n and depth:
                    if spec[i] == "{":
                        depth += 1
                    elif spec[i] == "}":
                        depth -= 1
                    i += 1
            if ch in "pmb":
                cols += 1
        elif ch == "*":
            m = re.match(r"\*\{(\d+)\}\{", spec[i:])
            if m:
                times = int(m.group(1))
                j = i + m.end()
                depth = 1
                k = j
                while k < n and depth:
                    if spec[k] == "{":
                        depth += 1
                    elif spec[k] == "}":
                        depth -= 1
                    k += 1
                inner = spec[j:k - 1]
                cols += times * parse_column_spec(inner)
                i = k
            else:
                i += 1
        elif ch in "|[]":
            i += 1
        elif ch == "@":
            i += 1
            if i < n and spec[i] == "{":
                depth, i = 1, i + 1
                while i < n and depth:
                    if spec[i] == "{":
                        depth += 1
                    elif spec[i] == "}":
                        depth -= 1
                    i += 1
        elif ch in "!><":
            i += 1
            if i < n and spec[i] == "{":
                depth, i = 1, i + 1
                while i < n and depth:
                    if spec[i] == "{":
                        depth += 1
                    elif spec[i] == "}":
                        depth -= 1
                    i += 1
        else:
            i += 1
    return cols


def _split_rows(body):
    """Split a tabular body on unescaped \\\\ at brace depth 0."""
    rows, cur, depth, i = [], [], 0, 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "\\":
            if i + 1 < n and body[i + 1] == "\\" and depth == 0:
                rows.append("".join(cur))
                cur = []
                i += 2
                continue
            cur.append(body[i:i + 2])
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        cur.append(ch)
        i += 1
    if "".join(cur).strip():
        rows.append("".join(cur))
    return rows


def _count_cells(row, base_cols):
    """Cells in one row: '&' separators plus the extra columns each \\multicolumn claims."""
    depth = 0
    cells = 1
    i = 0
    n = len(row)
    while i < n:
        ch = row[i]
        if ch == "\\":
            if row.startswith("\\multicolumn", i):
                m = re.match(r"\\multicolumn\s*\{(\d+)\}", row[i:])
                if m:
                    cells += max(int(m.group(1)) - 1, 0)
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "&" and depth == 0:
            cells += 1
        i += 1
    return cells


def check_tables(proj):
    findings = []
    for rel in proj.tex_files():
        if not proj.exists(rel):
            continue
        try:
            txt = T.strip_comments(proj.text(rel))
        except OSError:
            continue
        for m in TABULAR_BEGIN_RE.finditer(txt):
            env = m.group(1)
            # column preamble: tabularx/tabu take a width first, everything else does not
            pos = m.end()
            spec_inner = ""
            if env in ("tabularx", "tabu", "longtabu"):
                _width, pos = read_brace_group(txt, pos)
                spec_inner, pos = read_brace_group(txt, pos)
            elif env == "tabular*":
                _width, pos = read_brace_group(txt, pos)
                spec_inner, pos = read_brace_group(txt, pos)
            else:
                spec_inner, pos = read_brace_group(txt, pos)
            if spec_inner is None:
                spec_inner = ""
            body_start = pos if pos else m.end()
            endtok = "\\end{%s}" % env
            end_idx = txt.find(endtok, body_start)
            body = txt[body_start:end_idx] if end_idx != -1 else txt[body_start:body_start + 20000]
            ncols = parse_column_spec(spec_inner)
            begin_line = T.line_of_offset(txt, m.start())
            if end_idx == -1:
                findings.append({
                    "kind": "table", "rule": "T-UNCLOSED", "severity": "error",
                    "file": rel, "line": begin_line,
                    "explanation": "%s is never closed with %s" % (env, endtok),
                    "auto_fixable": True,
                })
                continue
            if ncols == 0:
                findings.append({
                    "kind": "table", "rule": "T-NO-COLSPEC", "severity": "warning",
                    "file": rel, "line": begin_line, "spec": spec_inner[:80],
                    "explanation": "column preamble could not be read, so cell counts cannot be verified",
                    "auto_fixable": False,
                })
                continue
            # row-by-row cell count
            for ri, row in enumerate(_split_rows(body)):
                stripped = row.strip()
                if not stripped:
                    continue
                if re.match(r"^\\(toprule|midrule|bottomrule|hline|cline|cmidrule|"
                            r"endfirsthead|endhead|endfoot|endlastfoot|addlinespace|"
                            r"caption|caption\*|label|centering|small|footnotesize|"
                            r"scriptsize|tiny|normalsize|arraystretch|setlength|"
                            r"renewcommand)", stripped):
                    continue
                cells = _count_cells(stripped, ncols)
                if cells != ncols:
                    row_line = begin_line + body[:body.find(row) + 1].count("\n") if row in body else begin_line
                    findings.append({
                        "kind": "table", "rule": "T-CELL-MISMATCH", "severity": "error",
                        "file": rel, "line": row_line,
                        "declared_columns": ncols, "cells_in_row": cells,
                        "row_excerpt": stripped[:120],
                        "explanation": "row %d has %d cells but the preamble declares %d columns; "
                                       "the extra '&' shifts every later column and usually pushes "
                                       "the table past the margin" % (ri + 1, cells, ncols),
                        "auto_fixable": False,
                    })
            # width risk
            longest = max([len(r) for r in _split_rows(body)] or [0])
            if ncols >= 9 or (ncols >= 5 and longest > 260):
                findings.append({
                    "kind": "table", "rule": "T-WIDTH-RISK", "severity": "warning",
                    "file": rel, "line": begin_line, "declared_columns": ncols,
                    "longest_row_chars": longest,
                    "explanation": "%d columns with up to %d characters on one row is very likely "
                                   "to exceed \\textwidth" % (ncols, longest),
                    "suggestion": "tabularx with an X column, or \\begin{sidewaystable} for a "
                                  "table that is wider than it is tall",
                    "auto_fixable": False,
                })
            if env == "longtable" and "\\endfirsthead" not in body and "\\endhead" not in body:
                findings.append({
                    "kind": "table", "rule": "T-LONGTABLE-NO-HEAD", "severity": "warning",
                    "file": rel, "line": begin_line,
                    "explanation": "longtable without \\endfirsthead/\\endhead repeats no header "
                                   "on continuation pages",
                    "auto_fixable": False,
                })
    # scaling instead of fixing: the task statement explicitly forbids masking overflow
    for rel in proj.tex_files():
        if not proj.exists(rel):
            continue
        try:
            txt = T.strip_comments(proj.text(rel))
        except OSError:
            continue
        for m in RESIZE_WRAP_RE.finditer(txt):
            window = txt[m.start():m.start() + 400]
            if "tabular" in window or "table" in window:
                findings.append({
                    "kind": "table", "rule": "T-SCALED-TO-FIT", "severity": "warning",
                    "file": rel, "line": T.line_of_offset(txt, m.start()),
                    "explanation": "\\%s is scaling a table to fit. The width problem still exists; "
                                   "it has only been hidden, and the font size no longer matches "
                                   "the rest of the document." % m.group(1),
                    "suggestion": "re-flow the table (tabularx / p{} / sideways) instead of scaling",
                    "auto_fixable": False,
                })
    return findings


# --------------------------------------------------------------------------------------
# math
# --------------------------------------------------------------------------------------

UNIT_RE = re.compile(
    r"(?<![\w\\])-?\d+(?:\.\d+)?\s*(?:kg|g|mg|μg|ng|m|cm|mm|μm|nm|km|s|ms|μs|ns|min|h|K|°C|"
    r"mol|mmol|Pa|kPa|MPa|GPa|N|J|kJ|W|kW|V|mV|A|mA|Hz|kHz|MHz|GHz|eV|keV|MeV|GeV|T|mT|"
    r"bar|atm|L|mL|μL|rpm|dB|%)(?![A-Za-z])")
MATH_SPAN_RE = re.compile(r"(?<!\\)\$(.{1,400}?)(?<!\\)\$|\\\[(.{1,2000}?)\\\]", re.S)
MATH_ENVS_RE = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?|displaymath)\}(.*?)"
    r"\\end\{\1\}", re.S)


def check_math(proj):
    findings = []
    label_seen = {}
    for rel in proj.tex_files():
        if not proj.exists(rel):
            continue
        try:
            raw = proj.text(rel)
        except OSError:
            continue
        txt = T.strip_comments(raw)
        n_left = len(re.findall(r"\\left(?![A-Za-z])", txt))
        n_right = len(re.findall(r"\\right(?![A-Za-z])", txt))
        if n_left != n_right:
            findings.append({
                "kind": "math", "rule": "M-LEFT-RIGHT", "severity": "error", "file": rel,
                "line": None, "left": n_left, "right": n_right,
                "explanation": "\\left and \\right are unbalanced (%d vs %d); TeX reports this as "
                               "'Missing \\right' at the end of the group, not where the pair broke"
                               % (n_left, n_right),
                "auto_fixable": False,
            })
        # units typeset in math italic — unit errors hide in equations as often as in $..$
        math_spans = []
        for m in MATH_SPAN_RE.finditer(txt):
            math_spans.append((m.start(), m.group(1) or m.group(2) or ""))
        for m in MATH_ENVS_RE.finditer(txt):
            math_spans.append((m.start(), m.group(2) or ""))
        for start_off, span in math_spans:
            um = UNIT_RE.search(span)
            if not um:
                continue
            raw_unit = um.group(0).strip()
            num = re.match(r"^(-?\d+(?:\.\d+)?)\s*(.*)$", raw_unit)
            value, unit = (num.group(1), num.group(2)) if num else (raw_unit, "")
            findings.append({
                "kind": "math", "rule": "M-UNIT-ITALIC", "severity": "warning", "file": rel,
                "line": T.line_of_offset(txt, start_off),
                "excerpt": span[max(0, um.start() - 20):um.end() + 10].strip(),
                "explanation": "a number-with-unit appears inside math mode, so the unit is "
                               "typeset in italic math font and the spacing is wrong",
                "suggestion": "\\SI{%s}{%s} (siunitx) or %s\\,\\mathrm{%s}"
                              % (value, unit, value, unit),
                "auto_fixable": False,
            })
        # equations: alignment markers and duplicate labels
        for m in MATH_ENVS_RE.finditer(txt):
            env, body = m.group(1), m.group(2)
            if env.startswith(("align", "eqnarray")) and "&" not in body:
                findings.append({
                    "kind": "math", "rule": "M-ALIGN-NO-AMP", "severity": "warning", "file": rel,
                    "line": T.line_of_offset(txt, m.start()),
                    "explanation": "align without '&' produces one right-aligned column instead of "
                                   "aligned relations",
                    "auto_fixable": False,
                })
            for lm in LABEL_RE.finditer(body):
                key = lm.group(1).strip()
                if key in label_seen:
                    findings.append({
                        "kind": "math", "rule": "M-DUPLICATE-LABEL", "severity": "error",
                        "file": rel, "line": T.line_of_offset(txt, m.start()),
                        "key": key, "first_defined": label_seen[key],
                        "explanation": "the same \\label appears twice; \\ref resolves to whichever "
                                       "one the .aux saw last",
                        "auto_fixable": False,
                    })
                else:
                    label_seen[key] = "%s:%s" % (rel, T.line_of_offset(txt, lm.start()))
    return findings


# --------------------------------------------------------------------------------------
# cross references, citations, graphics, includes
# --------------------------------------------------------------------------------------

def check_references(proj, scan, aux=None):
    findings = []
    label_map = {}
    for l in scan["labels"]:
        label_map.setdefault(l["key"], []).append(l)
    for key, defs in label_map.items():
        if len(defs) > 1:
            findings.append({
                "kind": "reference", "rule": "X-DUPLICATE-LABEL", "severity": "error",
                "key": key, "definitions": defs[:5],
                "explanation": "duplicate \\label{%s}; \\ref cannot be trusted" % key,
                "auto_fixable": False,
            })
    for r in scan["references"]:
        if r["key"] not in label_map:
            findings.append({
                "kind": "reference", "rule": "X-REF-WITHOUT-LABEL", "severity": "error",
                "file": r["file"], "line": r["line"], "key": r["key"],
                "explanation": "\\ref{%s} has no \\label{%s} anywhere in the project, so the "
                               "compiled PDF prints '??'" % (r["key"], r["key"]),
                "auto_fixable": False,
            })
    for l in scan["labels"]:
        if not any(l["key"] == r["key"] for r in scan["references"]):
            findings.append({
                "kind": "reference", "rule": "X-LABEL-UNUSED", "severity": "info",
                "file": l["file"], "line": l["line"], "key": l["key"],
                "explanation": "label is defined but never referenced",
                "auto_fixable": False,
            })
    # a \label before its \caption takes the section number instead of the float number
    for rel in proj.tex_files():
        if not proj.exists(rel):
            continue
        try:
            txt = T.strip_comments(proj.text(rel))
        except OSError:
            continue
        for m in re.finditer(r"\\begin\s*\{(figure|table)\*?\}", txt):
            end = txt.find("\\end{%s" % m.group(1), m.end())
            body = txt[m.end():end if end != -1 else m.end() + 4000]
            cap = CAPTION_RE.search(body)
            lab = LABEL_RE.search(body)
            if cap and lab and lab.start() < cap.start():
                findings.append({
                    "kind": "reference", "rule": "X-LABEL-BEFORE-CAPTION", "severity": "error",
                    "file": rel,
                    "line": T.line_of_offset(txt, m.start()) + body[:lab.start()].count("\n"),
                    "explanation": "\\label comes before \\caption inside a float, so it captures "
                                   "the enclosing section counter and every \\ref to the figure "
                                   "prints the wrong number",
                    "auto_fixable": True,
                    "fix": "move \\label after \\caption",
                })
    return findings


def check_citations(proj, closure, bibs, scan=None):
    findings = []
    scan = scan or {"citations": [], "references": [], "labels": []}
    first_cite = {}
    for c in scan.get("citations", []):
        first_cite.setdefault(c["key"], c)
    for key in closure["citations_without_entry"]:
        where = first_cite.get(key) or {}
        findings.append({
            "kind": "citation", "rule": "C-CITE-NO-ENTRY", "severity": "error", "key": key,
            "file": where.get("file"), "line": where.get("line"),
            "explanation": "\\cite{%s} but no .bib entry has that key; BibTeX leaves it as [?]" % key,
            "auto_fixable": False,
        })
    for bib in bibs:
        if not bib["exists"]:
            findings.append({
                "kind": "citation", "rule": "C-BIB-MISSING", "severity": "error",
                "path": bib["path"],
                "explanation": "the .bib file named by \\bibliography does not exist",
                "auto_fixable": False,
            })
        for problem in bib.get("problems", []):
            findings.append({
                "kind": "citation", "rule": "C-BIB-MALFORMED", "severity": "error",
                "path": bib["path"], "detail": problem,
                "explanation": "a malformed .bib makes bibtex abort and leaves the bibliography empty",
                "auto_fixable": False,
            })
        for entry in bib.get("entries", []):
            required = {"article": ("author", "title", "journal", "year"),
                        "inproceedings": ("author", "title", "booktitle", "year"),
                        "book": ("author", "title", "publisher", "year"),
                        "phdthesis": ("author", "title", "school", "year"),
                        "misc": ("title",)}.get(entry["type"], ())
            missing = [f for f in required if f not in entry["fields"]]
            if missing:
                findings.append({
                    "kind": "citation", "rule": "C-BIB-FIELD-MISSING", "severity": "warning",
                    "path": bib["path"], "entry": entry["key"], "missing": missing,
                    "explanation": "entry lacks %s; the formatted reference will have holes"
                                   % ", ".join(missing),
                    "auto_fixable": False,
                })
    if closure["citations_without_entry"] and not proj.bib_files:
        pass  # covered by C-CITE-NO-ENTRY
    return findings


GRAPHICS_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
GRAPHIC_EXTS = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".PDF", ".PNG", ".JPG")


def check_graphics(proj):
    findings = []
    search_dirs = [""]
    for rel in proj.tex_files():
        if not proj.exists(rel):
            continue
        try:
            txt = T.strip_comments(proj.text(rel))
        except OSError:
            continue
        gp = re.search(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\})+)\s*\}", txt)
        if gp:
            for d in re.findall(r"\{([^{}]*)\}", gp.group(1)):
                if d.strip() and d.strip() not in search_dirs:
                    search_dirs.append(d.strip())
        for m in GRAPHICS_RE.finditer(txt):
            name = m.group(1).strip()
            if not name:
                continue
            base_dir = os.path.dirname(rel)
            candidates = []
            for ext in GRAPHIC_EXTS:
                candidates.append(os.path.join(base_dir, name + ext))
                for d in search_dirs:
                    if d:
                        candidates.append(os.path.join(base_dir, d.rstrip("/\\"), name + ext))
                        candidates.append(os.path.join(d.rstrip("/\\"), name + ext))
            if not any(os.path.isfile(proj.abs(c)) for c in candidates):
                findings.append({
                    "kind": "graphics", "rule": "G-GRAPHIC-MISSING", "severity": "error",
                    "file": rel, "line": T.line_of_offset(txt, m.start()), "target": name,
                    "searched": candidates[:6],
                    "explanation": "\\includegraphics{%s} resolves to no file; pdfTeX stops with "
                                   "'File not found'" % name,
                    "auto_fixable": False,
                })
    return findings


def check_includes(proj):
    findings = []
    for from_rel, requested in proj.missing_includes:
        findings.append({
            "kind": "include", "rule": "I-INCLUDE-MISSING", "severity": "error",
            "file": from_rel, "target": requested,
            "explanation": "\\input/\\include{%s} names a file that is neither in the project nor "
                           "on the TeX search path" % requested,
            "auto_fixable": False,
        })
    return findings


# --------------------------------------------------------------------------------------
# template compliance
# --------------------------------------------------------------------------------------

CORE_REQUIRED = [
    ("\\documentclass", r"\\documentclass"),
    ("document environment", r"\\begin\s*\{document\}"),
    ("\\end{document}", r"\\end\s*\{document\}"),
]


def _class_options_from_cls(cls_path):
    """Read \\DeclareOption{...} names out of a class file shipped with the project."""
    if not os.path.isfile(cls_path):
        return None
    text, _ = T.read_text(cls_path)
    text = T.strip_comments(text)
    names = set(re.findall(r"\\DeclareOption\*?\s*\{([^}]*)\}", text))
    names.update(re.findall(r"\\DeclareOption\s*\{([^}]*)\}", text))
    executes = re.findall(r"\\ExecuteOptions\s*\{([^}]*)\}", text)
    for e in executes:
        for n in e.split(","):
            if n.strip():
                names.add(n.strip())
    parents = re.findall(r"\\LoadClass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", text)
    return {"options": sorted(names), "loads": parents}


def check_template(proj, engines=None):
    findings = []
    if not proj.main:
        return [{
            "kind": "template", "rule": "P-NO-MAIN", "severity": "error",
            "explanation": "no LaTeX entry point found (no file with \\documentclass)",
            "auto_fixable": False,
        }]
    main_text = T.strip_comments(proj.text(proj.main))
    for label, pattern in CORE_REQUIRED:
        if not re.search(pattern, main_text):
            findings.append({
                "kind": "template", "rule": "P-CORE-MISSING", "severity": "error",
                "file": proj.main, "what": label,
                "explanation": "the main file has no %s" % label,
                "auto_fixable": label != "\\documentclass",
            })
    # title block
    has_maketitle = bool(re.search(r"\\maketitle", main_text))
    for cmd, rule, sev in (("\\title", "P-TITLE-MISSING", "error"),
                           ("\\author", "P-AUTHOR-MISSING", "error")):
        if has_maketitle and not re.search(re.escape(cmd) + r"\s*(?:\[[^\]]*\])?\s*\{", main_text):
            findings.append({
                "kind": "template", "rule": rule, "severity": sev, "file": proj.main,
                "explanation": "\\maketitle is used but %s is never set, so the title block is empty"
                               % cmd,
                "auto_fixable": False,
            })
    if not re.search(r"\\begin\s*\{abstract\}", main_text) and "abstract" in main_text.lower():
        findings.append({
            "kind": "template", "rule": "P-ABSTRACT-NOT-ENV", "severity": "warning",
            "file": proj.main,
            "explanation": "the word 'abstract' appears but there is no abstract environment",
            "auto_fixable": False,
        })
    # bibliography wiring
    has_bib_cmd = bool(re.search(r"\\(bibliography|printbibliography)\b", main_text))
    if re.search(r"\\(cite[A-Za-z]*)\s*[\[{]", main_text) and not has_bib_cmd:
        findings.append({
            "kind": "template", "rule": "P-BIB-NOT-WIRED", "severity": "error",
            "file": proj.main,
            "explanation": "\\cite is used but there is no \\bibliography or \\printbibliography, "
                           "so no bibliography is generated",
            "auto_fixable": False,
        })
    # class availability
    cls = proj.documentclass
    if cls:
        local = None
        for cand in (proj.abs(cls + ".cls"), proj.abs(os.path.join("tex", cls + ".cls"))):
            if os.path.isfile(cand):
                local = cand
                break
        if local:
            info = _class_options_from_cls(local)
            if info and proj.documentclass_opts:
                requested = [o.strip() for o in proj.documentclass_opts.split(",") if o.strip()]
                unknown = [o for o in requested if o.split("=")[0] not in info["options"]]
                if unknown:
                    findings.append({
                        "kind": "template", "rule": "P-CLASS-OPTION-UNKNOWN", "severity": "warning",
                        "file": proj.main, "class": cls, "unknown_options": unknown,
                        "declared_options": info["options"][:40],
                        "explanation": "the class file does not declare these options; LaTeX ignores "
                                       "them silently, so the layout silently differs from the "
                                       "template's intent",
                        "auto_fixable": False,
                    })
        else:
            kq = T.kpsewhich(cls + ".cls") if (engines is None or engines.get("kpsewhich", {}).get("available")) else {"checked": False}
            if kq.get("checked") and not kq.get("found"):
                findings.append({
                    "kind": "template", "rule": "P-CLASS-UNAVAILABLE", "severity": "error",
                    "file": proj.main, "class": cls,
                    "explanation": "the class file %s.cls is neither shipped with the project nor "
                                   "installed, which is the single most common reason a template "
                                   "submission cannot build anywhere else" % cls,
                    "auto_fixable": False,
                })
    # required sibling files named by the class
    return findings


# --------------------------------------------------------------------------------------
# anti-cheat: did the repair remove the thing that was being built?
# --------------------------------------------------------------------------------------

FORBIDDEN_INTRODUCTIONS = {
    r"\\sloppy": "\\sloppy hides an overfull line instead of fixing the paragraph",
    r"\\tolerance\s*=\s*[0-9]{4,}": "a huge \\tolerance suppresses badness warnings rather than fixing layout",
    r"\\hbadness\s*=\s*[0-9]{4,}": "\\hbadness is raised to silence under/overfull reports",
    r"\\vfuzz\s*=\s*[0-9]+pt": "\\vfuzz silences box warnings",
    r"\\iffalse": "\\iffalse comments out live content",
    r"\\tracingall": "\\tracingall is a debugging switch, not a fix",
    r"\\nonstopmode": "\\nonstopmode inside the source forces the build past errors",
    r"\\batchmode": "\\batchmode inside the source forces the build past errors",
    r"\\scrollmode": "\\scrollmode inside the source hides the interaction that reveals errors",
}
CONTENT_TOKENS = ("\\cite", "\\ref", "\\eqref", "\\autoref", "\\cref", "\\label",
                  "\\includegraphics", "\\begin{equation", "\\begin{align",
                  "\\section", "\\caption", "\\bibitem")


def _scan_tokens(proj, rel_list):
    out = {t: 0 for t in CONTENT_TOKENS}
    for rel in rel_list:
        if not proj.exists(rel):
            continue
        try:
            txt = T.strip_comments(proj.text(rel))
        except OSError:
            continue
        for t in CONTENT_TOKENS:
            if t in ("\\section",):
                out[t] += len(re.findall(r"\\section\b", txt))
            elif t in ("\\begin{equation", "\\begin{align"):
                out[t] += len(re.findall(re.escape(t), txt))
            else:
                out[t] += len(re.findall(re.escape(t) + r"\b", txt))
    return out


def anti_cheat(proj_before, proj_after, rel_list=None):
    """Compare the repaired tree against the input snapshot: no content may silently vanish."""
    rels = rel_list or [f for f in proj_after.tex_files() if proj_before.exists(f)]
    before = _scan_tokens(proj_before, rels)
    after = _scan_tokens(proj_after, rels)
    findings = []
    for token in CONTENT_TOKENS:
        b, a = before[token], after[token]
        if a < b:
            findings.append({
                "kind": "integrity", "rule": "A-CONTENT-REMOVED", "severity": "error",
                "token": token, "before": b, "after": a,
                "explanation": "%d occurrence(s) of %s disappeared during the repair. A build "
                               "that succeeds because the content was deleted is not a fix."
                               % (b - a, token),
                "auto_fixable": False,
            })
    for rel in rels:
        if not proj_after.exists(rel):
            continue
        try:
            txt = T.strip_comments(proj_after.text(rel))
            orig = T.strip_comments(proj_before.text(rel))
        except OSError:
            continue
        for pattern, why in FORBIDDEN_INTRODUCTIONS.items():
            if re.search(pattern, txt) and not re.search(pattern, orig):
                findings.append({
                    "kind": "integrity", "rule": "A-SUPPRESSION-INTRODUCED", "severity": "error",
                    "file": rel, "pattern": pattern, "explanation": why,
                    "auto_fixable": False,
                })
    # net content shrinkage per file (>3% of non-blank characters, excluding comments)
    for rel in rels:
        if not proj_after.exists(rel):
            continue
        try:
            a = T.strip_comments(proj_after.text(rel))
            b = T.strip_comments(proj_before.text(rel))
        except OSError:
            continue
        ca = len(re.sub(r"\s+", "", a))
        cb = len(re.sub(r"\s+", "", b))
        if cb > 200 and ca < cb * 0.97:
            findings.append({
                "kind": "integrity", "rule": "A-TEXT-SHRUNK", "severity": "warning",
                "file": rel, "chars_before": cb, "chars_after": ca,
                "delta_pct": round(100.0 * (ca - cb) / cb, 1),
                "explanation": "the file lost more than 3%% of its non-blank characters",
                "auto_fixable": False,
            })
    return findings


# --------------------------------------------------------------------------------------
# overfull boxes: reported by the compiler, interpreted here
# --------------------------------------------------------------------------------------

def analyse_overfull(diags, max_items=25):
    """Turn over/underfull warnings into an actionable list, worst first."""
    items = []
    for d in diags:
        if d.kind != "overfull":
            continue
        ctx = d.context or {}
        amount = ctx.get("amount_pt") or 0.0
        where = (ctx.get("where") or "").lower()
        kind = "table-or-alignment" if "alignment" in where or "longtable" in where else "paragraph"
        items.append({
            "severity": "error" if amount > 10 else "warning",
            "file": d.file, "line": d.line, "amount_pt": amount, "kind": kind,
            "box": ctx.get("box"), "type": ctx.get("type"),
            "explanation": ("%s \\%s by %.1fpt%s" % (ctx.get("type"), ctx.get("box"), amount,
                                                    " in " + where if where else "")),
            "suggestion": ("reduce column count, use tabularx/p{} or rotate the table"
                           if kind == "table-or-alignment" else
                           "rewrite the sentence or add a hyphenation point; do not scale the box"),
        })
    items.sort(key=lambda x: -x["amount_pt"])
    return items[:max_items]


# --------------------------------------------------------------------------------------
# aggregate
# --------------------------------------------------------------------------------------

def run_static_checks(proj, bibs=None, engines=None):
    """All checks in one call. Returns findings + the closure summary they were based on."""
    scan = T.scan_citations_and_refs(proj)
    bibs = bibs or []
    closure = T.compute_bib_closure(proj, scan=scan, bib_entries=bibs)
    findings = []
    findings += check_template(proj, engines=engines)
    findings += check_includes(proj)
    findings += check_graphics(proj)
    findings += check_references(proj, scan)
    findings += check_citations(proj, closure, bibs, scan=scan)
    findings += check_tables(proj)
    findings += check_math(proj)
    for f in findings:
        f.setdefault("auto_fixable", False)
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order.get(f.get("severity"), 3), f.get("rule", ""),
                                f.get("file") or "", f.get("line") or 0))
    summary = {"total": len(findings),
               "errors": len([f for f in findings if f.get("severity") == "error"]),
               "warnings": len([f for f in findings if f.get("severity") == "warning"]),
               "info": len([f for f in findings if f.get("severity") == "info"]),
               "by_rule": {}}
    for f in findings:
        summary["by_rule"][f["rule"]] = summary["by_rule"].get(f["rule"], 0) + 1
    return {"findings": findings, "summary": summary, "closure": closure, "scan": scan}
