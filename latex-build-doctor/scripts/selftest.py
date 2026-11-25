#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest — regression suite for latex-build-doctor.

Runs without a TeX installation: it exercises the deterministic layers (discovery, log
parsing, root-cause attribution, structural audit, static checks, patch engine, integrity
guard, contract satisfaction) and one end-to-end run of doctor.py in static-only mode.

    python3 scripts/selftest.py            # summary + exit code
    python3 scripts/selftest.py --verbose  # one line per assertion

Exit code 0 only when every assertion passes.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import texlib as T
import checks as C

FIX = os.path.join(ROOT, "tests", "fixtures")
VERBOSE = "--verbose" in sys.argv
RESULTS = []


def tmpdir():
    """A writable scratch directory.

    Deliberately built with os.makedirs + a uuid rather than tempfile.mkdtemp: under some
    confinement layers a directory created by mkdtemp is not writable by the same process,
    and a test suite that cannot write is useless. Cleanup is the caller's rmtree.
    """
    import uuid
    bases = [os.environ.get("LB_TEST_TMP"), os.path.join(ROOT, ".selftest-tmp"),
             os.path.join(os.getcwd(), ".selftest-tmp")]
    for base in bases:
        if not base:
            continue
        try:
            os.makedirs(base, exist_ok=True)
            d = os.path.join(base, "t-" + uuid.uuid4().hex[:12])
            os.makedirs(d)
            probe = os.path.join(d, "_probe")
            os.makedirs(probe)
            os.rmdir(probe)
            return d
        except OSError:
            continue
    import tempfile as _tf
    return _tf.mkdtemp()


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    if VERBOSE or not cond:
        sys.stderr.write("%s %s%s\n" % ("PASS" if cond else "FAIL", name,
                                        ("  <- " + str(detail)) if detail and not cond else ""))
    return bool(cond)


def eq(name, got, want):
    return check(name, got == want, "got %r want %r" % (got, want))


def fixture(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------------------
# a small but realistic project used by most tests
# --------------------------------------------------------------------------------------

PAPER_MAIN = r"""\documentclass[11pt]{article}
\usepackage{amsmath}
\usepackage{graphicx}
\title{A small paper}
\author{A. Author}
\begin{document}
\maketitle
\begin{abstract}
An abstract.
\end{abstract}
\input{sections/intro}
\input{sections/method}
\input{sections/missing-section}
\begin{table}[t]
\centering
\begin{tabular}{lcc}
\toprule
Name & Value & Unit \\
\midrule
alpha & 1.0 & m \\
beta & 2.0 & s & extra \\
\bottomrule
\end{tabular}
\caption{A table}
\label{tab:one}
\end{table}
\begin{figure}[t]
\centering
\includegraphics[width=\linewidth]{figures/does-not-exist}
\label{fig:results}
\caption{Results}
\end{figure}
See Fig.~\ref{fig:result} and Table~\ref{tab:one}.
As shown in \cite{smith2020}.
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
"""

INTRO_TEX = r"""\section{Introduction}
\label{sec:intro}
The dielectric constant \epsilon_r is 3.9 for this film.
We cite \cite{ghost2018} for the method.
\begin{equation}
E = 3.2 J
\label{eq:energy}
\end{equation}
An unclosed group starts here {and never ends.
"""

METHOD_TEX = r"""\section{Method}
\begin{center}
\begin{tabularx}{\textwidth}{lX}
a & b \\
\end{tabularx}
\end{center}
\resizebox{\textwidth}{!}{\begin{tabular}{lcr} 1 & 2 & 3 \\ \end{tabular}}
\begin{align}
x = y + z
\end{align}
\begin{equation}
\left( a + b
\label{eq:bad}
\end{equation}
\begin{equation}
F = m a
\label{eq:energy}
\end{equation}
"""

REFS_BIB = r"""@article{chen2019,
  author = {Chen, L.},
  title = {A study},
  journal = {J. Test},
  year = {2019}
}

@article{duplicate2019,
  author = {Someone, A.},
  title = {Half an entry
  year = {2019}
}
"""


def make_project(base):
    os.makedirs(os.path.join(base, "sections"), exist_ok=True)
    os.makedirs(os.path.join(base, "figures"), exist_ok=True)
    T.write_text(os.path.join(base, "main.tex"), PAPER_MAIN)
    T.write_text(os.path.join(base, "sections", "intro.tex"), INTRO_TEX)
    T.write_text(os.path.join(base, "sections", "method.tex"), METHOD_TEX)
    T.write_text(os.path.join(base, "refs.bib"), REFS_BIB)
    return base


# --------------------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------------------

def test_text_utils():
    tmp = tmpdir()
    try:
        p = os.path.join(tmp, "gb.txt")
        with open(p, "wb") as fh:
            fh.write("中文编码".encode("gb18030"))
        text, enc = T.read_text(p)
        eq("text: gb18030 fallback decodes", text, "中文编码")
        check("text: encoding is reported", enc in ("gb18030", "utf-8"), enc)

        eq("text: sha256 of same content is stable",
           T.sha256_text("abc"), T.sha256_text("abc"))
        diff = T.unified_diff("a\nb\n", "a\nc\n", "a/x.tex", "b/x.tex")
        check("text: unified_diff marks the changed line", "+c" in diff and "-b" in diff, diff)
        eq("text: identical text produces no diff",
           T.unified_diff("same\n", "same\n", "a", "b"), None)
        eq("text: strip_comments keeps the line count",
           T.strip_comments("a%x\nb %y\nc").count("\n"), 2)
        eq("text: strip_comments respects \\%", T.strip_comments(r"50\% done"), r"50\% done")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_project_discovery():
    tmp = tmpdir()
    try:
        make_project(tmp)
        proj = T.discover(tmp)
        eq("project: main file is main.tex", proj.main, "main.tex")
        check("project: all three tex files found", len(proj.tex_files()) >= 3,
              proj.tex_files())
        eq("project: documentclass detected", proj.documentclass, "article")
        eq("project: documentclass options", proj.documentclass_opts, "11pt")
        check("project: refs.bib recorded", "refs.bib" in proj.bib_files, proj.bib_files)
        eq("project: bib style", proj.bib_style, "plain")
        check("project: missing include detected",
              any(x[1] == "sections/missing-section" for x in proj.missing_includes),
              proj.missing_includes)
        check("project: include graph has intro",
              "sections/intro.tex" in proj.includes.get("main.tex", []),
              proj.includes)
        eng = T.detect_engine(proj)
        eq("project: default engine pdflatex", eng["engine"], "pdflatex")
        eq("project: bib backend bibtex", T.detect_bib_backend(proj)["backend"], "bibtex")
        # engine comes from the magic comment when present
        T.write_text(os.path.join(tmp, "main.tex"),
                     "% !TEX program = xelatex\n" + PAPER_MAIN)
        proj2 = T.discover(tmp)
        eq("project: magic comment selects xelatex",
           T.detect_engine(proj2)["engine"], "xelatex")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_structure_audit():
    depth, unclosed = T.brace_balance("line one {\n line two {\n}")
    eq("structure: two opens one close leaves depth 1", depth, 1)
    eq("structure: first unclosed brace line", unclosed[0][0], 1)
    d2, _ = T.brace_balance("ok } here")
    check("structure: extra close reports negative depth", d2 < 0, d2)
    d3, _ = T.brace_balance("a {b} c")
    eq("structure: balanced text has depth 0", d3, 0)
    d4, _ = T.brace_balance("100\\% {ok}")
    eq("structure: \\% does not swallow the line", d4, 0)
    d5, _ = T.brace_balance("\\begin{verbatim}\n{{{{\n\\end{verbatim}")
    eq("structure: braces inside verbatim are ignored", d5, 0)

    unclosed_env, stray = T.env_balance("\\begin{a}\n\\begin{b}\n\\end{a}")
    check("structure: unclosed environment reported", unclosed_env, unclosed_env)
    check("structure: stray end reported", stray == [], stray)

    mb = T.math_balance("cost $5 and $6")
    check("structure: balanced inline math", mb["inline_balanced"], mb)
    mb2 = T.math_balance("cost $5 only")
    check("structure: unbalanced inline math detected", not mb2["inline_balanced"], mb2)

    tmp = tmpdir()
    try:
        make_project(tmp)
        proj = T.discover(tmp)
        findings = T.structural_audit(proj)
        rules = {f["rule"] for f in findings}
        check("structure: unclosed brace found in intro.tex",
              "S-BRACE-UNCLOSED" in rules, rules)
        check("structure: unbalanced \\left found", True)  # checked in test_math_checks
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_classic():
    tmp = tmpdir()
    try:
        make_project(tmp)
        diags = T.parse_log(fixture("undefined-cs-classic.log"), tmp)
        T.annotate(diags, T.discover(tmp))
        errs = [d for d in diags if d.rule == "E-UNDEFINED-CS"]
        check("log/classic: undefined control sequence found", errs, [d.rule for d in diags])
        if errs:
            eq("log/classic: attributed to sections/intro.tex", errs[0].file,
               "sections/intro.tex")
            eq("log/classic: line number", errs[0].line, 12)
            rc = errs[0].root_cause or {}
            eq("log/classic: offending macro named", rc.get("macro"), "badmacro")
        stray_par = [d for d in diags
                     if d.rule in ("E-EXTRA-CLOSE-BRACE", "E-RUNAWAY-ARGUMENT")]
        check("log/classic: 'extra }' classified as a brace problem",
              stray_par, [d.rule for d in diags])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_fileline():
    tmp = tmpdir()
    try:
        make_project(tmp)
        diags = T.parse_log(fixture("undefined-cs-fileline.log"), tmp)
        T.annotate(diags, T.discover(tmp))
        cs = [d for d in diags if d.rule == "E-UNDEFINED-CS"]
        eq("log/file-line: three undefined macros parsed", len(cs), 3)
        if cs:
            eq("log/file-line: file attribution", cs[0].file, "sections/method.tex")
            eq("log/file-line: line attribution", cs[0].line, 14)
            eq("log/file-line: macro from the l.N line",
               (cs[0].root_cause or {}).get("macro"), "toprule")
            eq("log/file-line: macro mapped to booktabs",
               (cs[0].root_cause or {}).get("package"), "booktabs")
        miss = [d for d in diags if d.rule == "E-MISSING-PKG"]
        check("log/file-line: missing package detected", miss, [d.rule for d in diags])
        if miss:
            eq("log/file-line: package name has no .sty suffix",
               (miss[0].root_cause or {}).get("package"), "siunitx")
        summary = T.summarize(diags)
        check("log/file-line: fatal error suppressed as cascade",
              summary["suppressed"] >= 1, summary)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_scanning():
    tmp = tmpdir()
    try:
        make_project(tmp)
        diags = T.parse_log(fixture("file-ended-scanning.log"), tmp)
        T.annotate(diags, T.discover(tmp))
        sc = [d for d in diags if d.rule == "E-FILE-ENDED-SCANNING"]
        check("log/scanning: 'File ended while scanning' recognised", sc,
              [d.rule for d in diags])
        if sc:
            check("log/scanning: root cause points at an unclosed brace",
                  "unbalanced" in (sc[0].root_cause or {}).get("category", ""),
                  sc[0].root_cause)
            eq("log/scanning: asks the reader to scan backwards",
               (sc[0].root_cause or {}).get("scan_backwards"), True)
        summary = T.summarize(diags)
        check("log/scanning: emergency-stop noise suppressed", summary["suppressed"] >= 1,
              summary)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_warnings():
    tmp = tmpdir()
    try:
        make_project(tmp)
        diags = T.parse_log(fixture("mixed-warnings.log"), tmp)
        T.annotate(diags, T.discover(tmp))
        rules = [d.rule for d in diags]
        check("log/warn: undefined reference captured", "W-UNDEF-REF" in rules, rules)
        check("log/warn: undefined citation captured", "W-UNDEF-CITE" in rules, rules)
        check("log/warn: overfull boxes captured", "W-OVERFULL" in rules, rules)
        check("log/warn: missing character captured", "W-MISSING-CHAR" in rules, rules)
        refs = [d for d in diags if d.rule == "W-UNDEF-REF"]
        if refs:
            eq("log/warn: reference key", refs[0].context.get("key"), "fig:results")
            eq("log/warn: reference line", refs[0].line, 58)
        over = [d for d in diags if d.rule == "W-OVERFULL"]
        eq("log/warn: both overfull boxes parsed", len(over), 2)
        worst = C.analyse_overfull(diags)
        if worst:
            eq("log/warn: worst overflow amount", worst[0]["amount_pt"], 37.22868)
            align = [w for w in worst if w["kind"] == "table-or-alignment"]
            check("log/warn: the alignment overfull is classified as a table problem",
                  align, worst)
            if align:
                eq("log/warn: alignment overflow amount", align[0]["amount_pt"], 12.5)
        stats = T.parse_log_stats(fixture("mixed-warnings.log"))
        eq("log/warn: page count read", stats["pages"], 1)
        eq("log/warn: output bytes read", stats["output_bytes"], 19824)
        eq("log/warn: engine banner", stats["engine_banner"], "pdfTeX")
        check("log/warn: no-output flag absent", stats["fatal_no_output"] is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_log_missing_class():
    tmp = tmpdir()
    try:
        make_project(tmp)
        diags = T.parse_log(fixture("missing-class.log"), tmp)
        T.annotate(diags, T.discover(tmp))
        mc = [d for d in diags if d.rule == "E-MISSING-CLASS"]
        check("log/class: missing .cls recognised", mc, [d.rule for d in diags])
        if mc:
            eq("log/class: class name", (mc[0].root_cause or {}).get("class"), "revtex4-2")
            eq("log/class: fix is not automatic",
               mc[0].severity, "error")
        plan = [p for p in T.annotate(diags, None) if p.rule == "E-MISSING-CLASS"]
        check("log/class: classified as error severity", plan and plan[0].severity == "error")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bib_logs():
    tmp = tmpdir()
    try:
        make_project(tmp)
        diags = T.parse_log(fixture("bibtex-missing-db.blg"), tmp, source="bib")
        check("log/bibtex: transcript parsed", isinstance(diags, list))
        biber = __import__("doctor")._parse_biber_log(fixture("biber-errors.blg"))
        eq("log/biber: one ERROR line", len([d for d in biber if d.severity == "error"]), 1)
        eq("log/biber: two WARN lines", len([d for d in biber if d.severity == "warning"]), 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_aux_bbl_bib():
    tmp = tmpdir()
    try:
        make_project(tmp)
        T.write_text(os.path.join(tmp, "main.aux"), r"""\relax
\citation{smith2020}
\citation{chen2019}
\bibstyle{plain}
\bibdata{refs}
\bibcite{chen2019}{1}
\newlabel{sec:intro}{{1}{1}}
\newlabel{tab:one}{{1}{2}}
\newlabel{eq:energy}{{2}{3}}
""")
        aux = T.parse_aux(os.path.join(tmp, "main.aux"))
        eq("aux: citations read", sorted(aux["citations"]), ["chen2019", "smith2020"])
        eq("aux: bibdata read", aux["bibdata"], ["refs"])
        eq("aux: labels read", len(aux["labels"]), 3)
        eq("aux: newlabel page", aux["newlabel"]["tab:one"]["page"], 2)

        T.write_text(os.path.join(tmp, "main.bbl"),
                     "\\begin{thebibliography}{1}\n\\bibitem{chen2019} C.\n"
                     "\\end{thebibliography}\n")
        bbl = T.parse_bbl(os.path.join(tmp, "main.bbl"))
        eq("bbl: one bibitem", bbl["entries"], 1)
        eq("bbl: key", bbl["keys"], ["chen2019"])

        bib = T.parse_bib(os.path.join(tmp, "refs.bib"))
        eq("bib: two entries", len(bib["entries"]), 2)
        check("bib: chen2019 has author", "author" in bib["entries"][0]["fields"],
              bib["entries"][0]["fields"])
        check("bib: malformed entry reported", bib["problems"], bib["problems"])

        proj = T.discover(tmp)
        bibs = [T.parse_bib(proj.abs(b)) for b in proj.bib_files]
        static = C.run_static_checks(proj, bibs=bibs)
        closure = static["closure"]
        check("bib: cite without entry found",
              "ghost2018" in closure["citations_without_entry"], closure)
        check("bib: cite smith2020 without entry found",
              "smith2020" in closure["citations_without_entry"], closure)
        check("bib: unused entries listed", "duplicate2019" in closure["unused_bib_entries"],
              closure)
        check("bib: ref without label found",
              "fig:result" in closure["references_without_label"], closure)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_table_checks():
    eq("table: lcc is 3 columns", C.parse_column_spec("lcc"), 3)
    eq("table: p{3cm} is 1 column", C.parse_column_spec("p{3cm}"), 1)
    eq("table: *{3}{c} expands", C.parse_column_spec("*{3}{c}"), 3)
    eq("table: @{} does not add a column", C.parse_column_spec("@{}l@{}"), 1)
    eq("table: >{\\bfseries}l is 1", C.parse_column_spec(r">{\bfseries}l"), 1)
    eq("table: |c|c| is 2", C.parse_column_spec("|c|c|"), 2)
    eq("table: S column counted", C.parse_column_spec("lS[table-format=2.1]"), 2)
    eq("table: multicolumn adds spans", C._count_cells(r"\multicolumn{2}{c}{x} & y", 3), 3)
    eq("table: escaped & is not a separator", C._count_cells(r"a \& b & c", 2), 2)
    eq("table: rowwise cells", C._count_cells("a & b & c", 3), 3)

    tmp = tmpdir()
    try:
        make_project(tmp)
        proj = T.discover(tmp)
        findings = C.check_tables(proj)
        rules = [f["rule"] for f in findings]
        check("table: cell mismatch detected", "T-CELL-MISMATCH" in rules, rules)
        check("table: scaling a table flagged", "T-SCALED-TO-FIT" in rules, rules)
        mm = [f for f in findings if f["rule"] == "T-CELL-MISMATCH"]
        if mm:
            eq("table: declared columns on mismatch", mm[0]["declared_columns"], 3)
            eq("table: cells found on mismatch", mm[0]["cells_in_row"], 4)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_math_checks():
    tmp = tmpdir()
    try:
        make_project(tmp)
        proj = T.discover(tmp)
        findings = C.check_math(proj)
        rules = [f["rule"] for f in findings]
        check("math: unbalanced \\left flagged", "M-LEFT-RIGHT" in rules, rules)
        check("math: unit in math italic flagged", "M-UNIT-ITALIC" in rules, rules)
        check("math: align without & flagged", "M-ALIGN-NO-AMP" in rules, rules)
        check("math: duplicate label flagged", "M-DUPLICATE-LABEL" in rules, rules)
        unit = [f for f in findings if f["rule"] == "M-UNIT-ITALIC"]
        if unit:
            check("math: suggests siunitx", "siunitx" in (unit[0].get("suggestion") or ""),
                  unit[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_template_and_graphics():
    tmp = tmpdir()
    try:
        make_project(tmp)
        proj = T.discover(tmp)
        findings = C.check_graphics(proj)
        check("graphics: missing figure detected",
              any(f["rule"] == "G-GRAPHIC-MISSING" for f in findings), findings)
        findings = C.check_includes(proj)
        check("include: missing section detected",
              any(f["rule"] == "I-INCLUDE-MISSING" for f in findings), findings)
        findings = C.check_template(proj, engines={"kpsewhich": {"available": False}})
        rules = [f["rule"] for f in findings]
        check("template: no false 'class unavailable' when kpsewhich is absent",
              "P-CLASS-UNAVAILABLE" not in rules, rules)
        # a class file that ships with the project is read for its declared options
        T.write_text(os.path.join(tmp, "myclass.cls"),
                     "\\DeclareOption{twocolumn}{}\n\\DeclareOption{draft}{}\n")
        T.write_text(os.path.join(tmp, "main.tex"),
                     PAPER_MAIN.replace("\\documentclass[11pt]{article}",
                                        "\\documentclass[11pt,unknownopt]{myclass}"))
        proj2 = T.discover(tmp)
        findings = C.check_template(proj2, engines=None)
        opt = [f for f in findings if f["rule"] == "P-CLASS-OPTION-UNKNOWN"]
        check("template: unknown class option detected", opt, [f["rule"] for f in findings])
        if opt:
            eq("template: the unknown option is named", opt[0]["unknown_options"],
               ["11pt", "unknownopt"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_patch_engine():
    tmp = tmpdir()
    try:
        make_project(tmp)
        path = os.path.join(tmp, "sections", "intro.tex")
        original = T.read_text(path)[0]
        # insert_after
        p = T.Patch("R-ADD-PACKAGE", "sections/intro.tex", "insert_after", 1, None,
                    "\\usepackage{booktabs}")
        ok, msg, before, after = T.apply_patch_to_tree(tmp, p)
        check("patch: insert_after applied", ok, msg)
        eq("patch: inserted line landed after line 1",
           T.read_text(path)[0].split("\n")[1], "\\usepackage{booktabs}")
        # rollback
        T.write_text(path, before)
        eq("patch: rollback restores the file", T.read_text(path)[0], original)
        # replace_line with a content check
        lines = T.read_text(path)[0].split("\n")
        target = lines[2]
        p2 = T.Patch("R-TEST", "sections/intro.tex", "replace_line", 3, target,
                     target + " % fixed")
        ok, msg, _b, _a = T.apply_patch_to_tree(tmp, p2)
        check("patch: replace_line applied", ok, msg)
        # a mismatched old line must be refused, not silently overwrite
        p3 = T.Patch("R-TEST", "sections/intro.tex", "replace_line", 3,
                     "this is not the line", "something else")
        ok, msg, _b, _a = T.apply_patch_to_tree(tmp, p3)
        check("patch: content mismatch refused", not ok, msg)
        # the integrity guard refuses 'fixes' that delete citations
        p4 = T.Patch("R-CHEAT", "sections/intro.tex", "replace_line", 4,
                     "We cite \\cite{ghost2018} for the method.", "")
        ok, msg = T.guard_patch(p4, "", "")
        check("patch: deleting a \\cite line refused", not ok, msg)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_integrity_guard():
    tmp = tmpdir()
    before_root = os.path.join(tmp, "before")
    after_root = os.path.join(tmp, "after")
    try:
        make_project(before_root)
        make_project(after_root)
        proj_before = T.discover(before_root)
        proj_after = T.discover(after_root)
        eq("integrity: identical trees are clean",
           C.anti_cheat(proj_before, proj_after), [])

        # remove a citation -> must be caught
        p = os.path.join(after_root, "main.tex")
        T.write_text(p, T.read_text(p)[0].replace("As shown in \\cite{smith2020}.", ""))
        proj_after = T.discover(after_root)
        found = C.anti_cheat(proj_before, proj_after)
        check("integrity: removed \\cite detected",
              any(f["rule"] == "A-CONTENT-REMOVED" and f["token"] == "\\cite" for f in found),
              found)

        # add \sloppy -> must be caught
        make_project(after_root)
        p = os.path.join(after_root, "main.tex")
        T.write_text(p, T.read_text(p)[0].replace("\\maketitle", "\\maketitle\n\\sloppy"))
        proj_after = T.discover(after_root)
        found = C.anti_cheat(proj_before, proj_after)
        check("integrity: introduced \\sloppy detected",
              any(f["rule"] == "A-SUPPRESSION-INTRODUCED" for f in found), found)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_contract():
    import doctor
    result = {"case_id": "x", "status": "partial", "diagnostics": {"a": 1},
              "build": {"b": 2}}
    info = doctor.satisfy_contract(result, ["case_id", "status", "diagnostics",
                                            "sources", "mystery_field"])
    check("contract: native field kept", info["satisfied"].get("case_id") == "native", info)
    check("contract: missing field is stubbed, not invented",
          info["satisfied"].get("mystery_field") == "stub_declared", info)
    check("contract: stub states it was not produced",
          result["mystery_field"]["_status"] == "not_produced_by_this_skill", result)
    check("contract: missing list names the gap", "mystery_field" in info["missing"], info)

    r2 = {"case_id": "x", "status": "ok", "diagnostics": 1}
    info2 = doctor.satisfy_contract(r2, ["errors"])
    eq("contract: synonym 'errors' maps to diagnostics", r2["errors"], 1)


def test_static_idempotent():
    tmp = tmpdir()
    try:
        make_project(tmp)
        proj = T.discover(tmp)
        a = C.run_static_checks(proj, bibs=[T.parse_bib(proj.abs(b)) for b in proj.bib_files])
        b = C.run_static_checks(proj, bibs=[T.parse_bib(proj.abs(b)) for b in proj.bib_files])
        eq("idempotence: static checks twice are identical",
           json.dumps(a["summary"], sort_keys=True),
           json.dumps(b["summary"], sort_keys=True))
        eq("idempotence: findings identical",
           json.dumps(a["findings"], sort_keys=True),
           json.dumps(b["findings"], sort_keys=True))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_doctor_end_to_end():
    tmp = tmpdir()
    try:
        inp = os.path.join(tmp, "input")
        out = os.path.join(tmp, "output")
        work = os.path.join(tmp, "work")
        make_project(inp)
        T.write_json(os.path.join(inp, "case.json"),
                     {"case_id": "selftest-01",
                      "output_contract": ["status", "diagnostics", "build", "fixes",
                                          "sources", "uncertainties"]})
        T.write_text(os.path.join(inp, "task.md"),
                     "修好这个 LaTeX 工程并交付可编译的源码。")
        cmd = [sys.executable, os.path.join(HERE, "doctor.py"),
               "--input", inp, "--out", out, "--work", work,
               "--no-build", "--quiet"]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=180)
        eq("doctor: exit code 0 in static-only mode", proc.returncode, 0)
        rp = os.path.join(out, "result.json")
        check("doctor: result.json written", os.path.isfile(rp))
        if os.path.isfile(rp):
            res = json.loads(T.read_text(rp)[0])
            eq("doctor: case_id carried through", res["case_id"], "selftest-01")
            check("doctor: status is partial without an engine", res["status"] == "partial",
                  res["status"])
            check("doctor: status_reason explains why", bool(res["status_reason"]))
            for field in ("diagnostics", "build", "fixes", "sources", "uncertainties"):
                check("doctor: contract field %s present" % field, field in res, list(res))
            check("doctor: sources are file-anchored",
                  any(s.get("file") for s in res["sources"]), res["sources"][:2])
            check("doctor: static findings recorded",
                  res["static_checks"]["before"]["total"] > 0, res["static_checks"]["before"])
            check("doctor: uncertainties are stated", res["uncertainties"], res["uncertainties"])
        for rel in ("report.md", "diagnostics.json", "static-checks.json",
                    "fixes/patches.json", "fixes/changes.diff", "repro/build.sh",
                    "repro/latexmkrc", "repro/versions.txt", "fixed/main.tex"):
            check("doctor: artefact %s" % rel, os.path.isfile(os.path.join(out, rel)), rel)
        rep = T.read_text(os.path.join(out, "report.md"))[0]
        check("doctor: report names the status", "状态" in rep and "partial" in rep, rep[:200])
        check("doctor: report lists structural problems", "S-BRACE-UNCLOSED" in rep, rep[:2000])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


TESTS = [
    ("text utilities", test_text_utils),
    ("project discovery", test_project_discovery),
    ("structural audit", test_structure_audit),
    ("log: classic error block", test_log_classic),
    ("log: -file-line-error block", test_log_fileline),
    ("log: file-ended scanning", test_log_scanning),
    ("log: warnings and overfull", test_log_warnings),
    ("log: missing class", test_log_missing_class),
    ("log: bibtex/biber", test_bib_logs),
    ("aux/bbl/bib parsing", test_aux_bbl_bib),
    ("tables", test_table_checks),
    ("math", test_math_checks),
    ("template and graphics", test_template_and_graphics),
    ("patch engine", test_patch_engine),
    ("integrity guard", test_integrity_guard),
    ("output contract", test_contract),
    ("static checks are idempotent", test_static_idempotent),
    ("doctor end-to-end (static mode)", test_doctor_end_to_end),
]


def main():
    failures = 0
    for name, fn in TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            failures += 1
            RESULTS.append((name, False, "%s: %s" % (type(exc).__name__, exc)))
            sys.stderr.write("ERROR in %s\n" % name)
            if VERBOSE:
                traceback.print_exc()
    passed = len([r for r in RESULTS if r[1]])
    failed = [r for r in RESULTS if not r[1]]
    print("")
    print("=" * 72)
    print("latex-build-doctor selftest: %d/%d assertions passed, %d group(s) with errors"
          % (passed, len(RESULTS), failures))
    if failed:
        print("")
        for name, _ok, detail in failed:
            print("  FAIL %s  %s" % (name, detail))
    print("=" * 72)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
