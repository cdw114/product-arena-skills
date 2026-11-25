#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
texlib — deterministic LaTeX project/build/diagnosis core (Python 3.8+, stdlib only).

Design rule for this whole skill: every fact this module reports must be traceable to
(a) bytes on disk, (b) a compiler log line, or (c) a computed measurement. No guessing.
Where the module cannot decide, it says `confidence: low` and names the candidates.

Modules inside:
  text      — encoding-tolerant IO, hashing
  project   — main-file discovery, include graph, engine/bib-backend detection
  log       — pdflatex/latexmk/bibtex/biber log parsing with file-stack attribution
  structure — brace / environment / math-delimiter balance with line attribution
  patch     — typed, minimal, reversible source patches + unified diff
  bib       — .aux / .bbl / .bib parsing and cross-reference closure
  env       — engine probing, environment/resources.yaml, reproducible-build record
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys

# --------------------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------------------

ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".ipynb_checkpoints",
             ".pytest_cache", ".mypy_cache", ".DS_Store"}
TEXT_EXTS = {".tex", ".cls", ".sty", ".clo", ".def", ".cfg", ".ldf", ".fd", ".bbx", ".cbx",
             ".bib", ".bst", ".aux", ".bbl", ".toc", ".out", ".ltx", ".dtx", ".ins", ".tikz"}
BINARY_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg", ".gif", ".zip", ".gz"}


def read_text(path):
    """Read a text file tolerating the encodings that show up in real submissions."""
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace"), "latin-1(replace)"


def write_text(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8"))


def norm_rel(path, root):
    """Relative POSIX path from root, or the absolute path if it escapes root."""
    try:
        return os.path.relpath(os.path.abspath(path), os.path.abspath(root)).replace("\\", "/")
    except ValueError:
        return os.path.abspath(path).replace("\\", "/")


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


# --------------------------------------------------------------------------------------
# LaTeX source scanning helpers
# --------------------------------------------------------------------------------------

COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.M)


def strip_comments(text):
    """Remove % comments (respecting \\%). Line structure is preserved so line numbers stay valid."""
    out_lines = []
    for line in text.split("\n"):
        idx = None
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "%":
                idx = i
                break
            i += 1
        out_lines.append(line if idx is None else line[:idx])
    return "\n".join(out_lines)


def mask_verbatim(text):
    """Blank out verbatim-like environments so brace/&/$ counting does not fire inside them."""
    pattern = re.compile(
        r"\\begin\{(verbatim\*?|Verbatim\*?|lstlisting|minted|comment|alltt)\}.*?\\end\{\1\}",
        re.S)
    blanks = []

    def repl(m):
        blanks.append(m.group(0))
        return "\n" * m.group(0).count("\n") + " " * 0 + "\\begin{VERBATIM-MASKED}"

    return pattern.sub(repl, text)


def iter_args(text, start):
    """Yield (open_idx, close_idx) of balanced {...} groups starting at `start`."""
    i = start
    n = len(text)
    while i < n:
        if text[i] == "{":
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
            if depth == 0:
                yield i, j - 1
                return
            return
        i += 1


def find_arg(text, cmd, start=0):
    """Return the content of the first {...} argument of `cmd` at/after start, or None."""
    m = re.compile(re.escape(cmd) + r"(?![A-Za-z@])").search(text, start)
    if not m:
        return None
    for o, c in iter_args(text, m.end()):
        return text[o + 1:c]
    return None


def line_of_offset(text, offset):
    return text.count("\n", 0, offset) + 1


# --------------------------------------------------------------------------------------
# biblatex-aware load-order knowledge (packages whose placement matters)
# --------------------------------------------------------------------------------------

# Macros that a missing `\usepackage` explains. Keyed by control sequence.
# This table is the reason an "Undefined control sequence" can be turned into a patch
# instead of a guess: every entry names the package that defines the macro.
MACRO_PACKAGES = {
    # amsmath family
    "text": "amsmath", "dfrac": "amsmath", "tfrac": "amsmath", "boxed": "amsmath",
    "align": "amsmath", "gather": "amsmath", "operatorname": "amsmath",
    "DeclareMathOperator": "amsmath", "substack": "amsmath", "overset": "amsmath",
    "underset": "amsmath", "xrightarrow": "amsmath", "tag": "amsmath",
    "mathbb": "amssymb", "mathfrak": "amssymb", "leqslant": "amssymb",
    "geqslant": "amssymb", "nleq": "amssymb", "lvert": "amsmath", "rvert": "amsmath",
    "lVert": "amsmath", "rVert": "amsmath", "bm": "bm", "boldsymbol": "amsmath",
    "textbook": "amssymb",
    # equation helpers / symbols
    "SI": "siunitx", "si": "siunitx", "num": "siunitx", "unit": "siunitx",
    "qty": "siunitx", "SIrange": "siunitx", "sisetup": "siunitx",
    "ce": "mhchem", "pu": "mhchem",
    "mathcal": None,  # core
    "mathscr": "mathrsfs", "mathfrak": "amssymb", "cancel": "cancel",
    "nicefrac": "nicefrac", "binom": "amsmath", "genfrac": "amsmath",
    # tables
    "toprule": "booktabs", "midrule": "booktabs", "bottomrule": "booktabs",
    "cmidrule": "booktabs", "addlinespace": "booktabs", "specialrule": "booktabs",
    "multirow": "multirow", "multirowcell": "makecell",
    "makecell": "makecell", "thead": "makecell",
    "multicolumn": None, "arraybackslash": "array", "newcolumntype": "array",
    "tabularx": None, "endhead": None,
    "threeparttable": None, "makecell": "makecell",
    "rowcolor": "colortbl", "cellcolor": "colortbl", "columncolor": "colortbl",
    "dimexpr": None, "dimexprline": None,
    "setlength": None, "renewcommand": None,
    "resizebox": "graphicx", "scalebox": "graphicx", "includegraphics": "graphicx",
    "rotatebox": "graphicx", "graphicspath": "graphicx",
    "FloatBarrier": "placeins", "clearpage": None,
    "floatname": None, "restylefloat": "float",
    # refs / links
    "cref": "cleveref", "Cref": "cleveref", "crefrange": "cleveref",
    "autoref": "hyperref", "nameref": "hyperref", "href": "hyperref",
    "url": "hyperref", "hypersetup": "hyperref", "textcolor": "xcolor",
    "color": "xcolor", "definecolor": "xcolor",
    "geometry": None,
    # text / structure
    "textbf": None, "textit": None, "emph": None,
    "RaggedRight": "ragged2e", "justifying": "ragged2e",
    "setstretch": "setspace", "onehalfspacing": "setspace", "doublespacing": "setspace",
    "singlespacing": "setspace",
    "caption": "caption", "captionof": "caption", "captionsetup": "caption",
    "subfloat": "subfig", "subfigure": "subfigure",
    "SIlist": "siunitx",
    "foreignlanguage": "babel", "selectlanguage": "babel",
    "textzh": "xeCJK", "setCJKmainfont": "xeCJK", "setmainfont": "fontspec",
    "setsansfont": "fontspec", "setmonofont": "fontspec", "newfontfamily": "fontspec",
    "bingde": None,
    # lists / algorithms
    "begin": None,
    "algrenewcommand": "algorithm2e", "KwIn": "algorithm2e", "KwOut": "algorithm2e",
    "SetKwInOut": "algorithm2e", "DontPrintSemicolon": "algorithm2e",
    "STATE": "algorithmicx", "EndWhile": "algorithmicx", "Require": "algorithmicx",
    "Ensure": "algorithmicx",
    # misc
    "lstset": "listings", "lstinputlisting": "listings", "lstinline": "listings",
    "tikz": None, "draw": None, "node": None,
    "gls": "glossaries", "Gls": "glossaries", "makeglossaries": "glossaries",
    "printglossaries": "glossaries", "acrshort": "glossaries-extra",
    "todo": "todonotes", "missingfigure": "todonotes",
    "soul": "soul", "hl": "soul", "st": "soul", "ul": "soul",
    "textcelsius": "textcomp", "textdegree": "textcomp", "textmu": "textcomp",
    "textquotesingle": "textcomp", "textasciitilde": None,
    "micro": "textcomp", "SI": "siunitx",
    "sisetup": "siunitx",
    "verbatiminput": "verbatim",
    "ifthenelse": "ifthenelse", "whiledo": "ifthenelse",
    "and": None,
    "linebreak": None,
    "nocite": None,
    "printbibliography": "biblatex", "addbibresource": "biblatex",
    "parencite": "biblatex", "textcite": "biblatex", "autocite": "biblatex",
    "footcite": "biblatex", "citeauthor": "natbib", "citep": "natbib", "citet": "natbib",
    "citealp": "natbib", "citealt": "natbib", "citenum": "natbib",
}

# environment -> package that defines it
ENV_PACKAGES = {
    "align": "amsmath", "align*": "amsmath", "gather": "amsmath", "gather*": "amsmath",
    "split": "amsmath", "multline": "amsmath", "multline*": "amsmath",
    "equation*": "amsmath", "eqnarray": None, "alignat": "amsmath",
    "cases": "amsmath", "matrix": "amsmath", "pmatrix": "amsmath", "bmatrix": "amsmath",
    "vmatrix": "amsmath", "Bmatrix": "amsmath", "smallmatrix": "amsmath",
    "theorem": "amsthm", "lemma": "amsthm", "proof": "amsthm", "definition": "amsthm",
    "corollary": "amsthm", "remark": "amsthm", "proposition": "amsthm",
    "tikzpicture": "tikz", "axis": "pgfplots",
    "tabularx": "tabularx", "tabular*": None, "longtable": "longtable",
    "tabu": "tabu", "longtabu": "tabu", "supertabular": "supertabular",
    "threeparttable": "threeparttable", "sidewaystable": "rotating",
    "sidewaysfigure": "rotating", "landscape": "lscape",
    "algorithm": "algorithm", "algorithmic": "algorithmic", "algorithm2e": "algorithm2e",
    "lstlisting": "listings", "minted": "minted",
    "verbatim": None, "comment": "comment", "quotation": None, "quote": None,
    "figure*": None, "table*": None, "subfigure": "subfigure", "subtable": "subcaption",
    "wrapfigure": "wrapfig", "multicols": "multicol",
    "thebibliography": None, "appendix": None, "abstract": None,
    "center": None, "flushleft": None, "flushright": None, "minipage": None,
    "enumerate": None, "itemize": None, "description": None, "list": None,
    "displaymath": None, "math": None, "verbatim*": None,
    "glossary": "glossaries", "acronym": "acronym",
}

# packages that must be loaded after a given package
LOAD_AFTER = {
    "hyperref": None,           # last-ish
    "cleveref": "hyperref",     # after hyperref
    "biblatex": None,
}

ENGINE_HINTS_CLASS = {
    "ctexart": "xelatex", "ctexrep": "xelatex", "ctexbook": "xelatex", "ctexbeamer": "xelatex",
    "beamer": "pdflatex",
    "moderncv": "pdflatex",
    "fontspec": "xelatex",
}


# --------------------------------------------------------------------------------------
# project discovery
# --------------------------------------------------------------------------------------

INCLUDE_RE = re.compile(r"\\(input|include|subfile|Import|subimport)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
DOCUMENTCLASS_RE = re.compile(r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}")
PACKAGE_RE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}")
BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{([^}]*)\}")
ADDBIB_RE = re.compile(r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
BIBSTYLE_RE = re.compile(r"\\bibliographystyle\s*\{([^}]*)\}")
MAGIC_RE = re.compile(r"^[ \t]*%\s*!\s*TEX\s+(?:program|encoding)\s*=\s*([A-Za-z0-9_\-+]+)", re.I | re.M)


class TexProject(object):
    """A discovered LaTeX project: files, main file, include graph, engine/backend hints."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.files = []          # rel posix paths of text-eligible files
        self.binary = []         # rel paths of binaries (figures etc.)
        self.main = None         # rel posix path
        self.main_candidates = []  # [(rel, score, why)]
        self.includes = {}       # rel -> [rel...]
        self.missing_includes = []  # [(from_rel, requested)]
        self.preamble_end = None
        self.classes = []
        self.packages = []       # [{'name','opts','line','file'}]
        self.bib_files = []
        self.bib_style = None
        self.documentclass = None
        self.documentclass_opts = None
        self.magic_engine = None
        self.encodings = {}
        self.notes = []

    # -- convenience -----------------------------------------------------------------
    def tex_files(self):
        return [f for f in self.files if f.endswith(".tex")]

    def abs(self, rel):
        return os.path.join(self.root, rel.replace("/", os.sep))

    def text(self, rel):
        return read_text(self.abs(rel))[0]

    def exists(self, rel):
        return os.path.isfile(self.abs(rel))

    def resolve_include(self, requested, from_rel):
        """Resolve a \\input argument to an existing project file, or None."""
        req = requested.strip()
        if not req:
            return None
        base = os.path.dirname(from_rel)
        cands = []
        raw = req.replace("\\", "/")
        for c in (raw, raw + ".tex", raw + ".ltx"):
            cands.append(norm_rel(os.path.join(self.root, c), self.root))
            if base:
                cands.append(norm_rel(os.path.join(self.root, base, c), self.root))
        for c in cands:
            if os.path.isfile(self.abs(c)):
                return c
        return None

    def to_dict(self):
        return {
            "root": self.root,
            "main": self.main,
            "main_candidates": [{"file": r, "score": s, "why": w} for r, s, w in self.main_candidates],
            "n_files": len(self.files),
            "tex_files": self.tex_files(),
            "includes": self.includes,
            "missing_includes": [{"from": a, "requested": b} for a, b in self.missing_includes],
            "documentclass": self.documentclass,
            "documentclass_options": self.documentclass_opts,
            "classes": self.classes,
            "packages": self.packages,
            "bib_files": self.bib_files,
            "bib_style": self.bib_style,
            "magic_engine": self.magic_engine,
            "encodings": self.encodings,
            "binary_assets": self.binary,
            "notes": self.notes,
        }


def _score_main(rel, text, total_tex):
    score = 0
    why = []
    if re.search(r"^[^%\n]*\\documentclass", text, re.M):
        score += 100
        why.append("has \\documentclass")
    if re.search(r"\\begin\s*\{document\}", text):
        score += 80
        why.append("has document environment")
    base = os.path.basename(rel).lower()
    for name in ("main.tex", "paper.tex", "manuscript.tex", "thesis.tex", "article.tex",
                 "ms.tex", "root.tex", "report.tex", "book.tex", "submission.tex"):
        if base == name:
            score += 40
            why.append("conventional name %s" % name)
            break
    if "/" in rel:
        score -= 15
        why.append("in a subdirectory")
    if re.search(r"\\(input|include)\s*\{", text):
        score += 10
        why.append("drives includes")
    score += min(len(text) // 2000, 10)
    return score, why


def discover(root, max_scan=4000):
    """Walk `root`, find LaTeX sources, pick the main file, build the include graph."""
    proj = TexProject(root)
    if not os.path.isdir(root):
        proj.notes.append("project root does not exist: %s" % root)
        return proj

    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith("._")]
        for fn in filenames:
            seen += 1
            if seen > max_scan:
                proj.notes.append("scan truncated at %d entries" % max_scan)
                break
            ext = os.path.splitext(fn)[1].lower()
            rel = norm_rel(os.path.join(dirpath, fn), root)
            if ext in TEXT_EXTS or ext in ("", ".latex"):
                proj.files.append(rel)
            elif ext in BINARY_EXTS:
                proj.binary.append(rel)
        if seen > max_scan:
            break

    proj.files.sort()
    proj.binary.sort()

    # --- main file scoring -----------------------------------------------------------
    for rel in proj.tex_files():
        try:
            text, enc = read_text(proj.abs(rel))
        except OSError:
            continue
        proj.encodings[rel] = enc
        s, why = _score_main(rel, strip_comments(text), len(proj.tex_files()))
        if s > 0:
            proj.main_candidates.append((rel, s, "; ".join(why)))
    proj.main_candidates.sort(key=lambda t: (-t[1], t[0]))
    if proj.main_candidates:
        proj.main = proj.main_candidates[0][0]
    elif proj.tex_files():
        proj.main = proj.tex_files()[0]
        proj.notes.append("no file has \\documentclass; falling back to %s" % proj.main)

    if not proj.main:
        return proj

    # --- preamble facts --------------------------------------------------------------
    main_text = strip_comments(proj.text(proj.main))
    m = re.search(r"\\begin\s*\{document\}", main_text)
    if m:
        proj.preamble_end = m.start()
    dc = DOCUMENTCLASS_RE.search(main_text)
    if dc:
        proj.documentclass_opts = dc.group(1)
        proj.documentclass = dc.group(2).strip()
        proj.classes.append(proj.documentclass)
    magic = MAGIC_RE.search(read_text(proj.abs(proj.main))[0])
    if magic:
        val = magic.group(1).lower()
        if val in ("pdflatex", "xelatex", "lualatex", "latex", "platex", "uplatex"):
            proj.magic_engine = val
    for rel in proj.tex_files():
        try:
            txt = strip_comments(proj.text(rel))
        except OSError:
            continue
        if re.search(r"\\documentclass", txt):
            name = (DOCUMENTCLASS_RE.search(txt).group(2) or "").strip()
            if name and name not in proj.classes:
                proj.classes.append(name)
        for pm in PACKAGE_RE.finditer(txt):
            opts = pm.group(1) or ""
            for name in (pm.group(2) or "").split(","):
                name = name.strip()
                if name:
                    proj.packages.append({
                        "name": name, "opts": opts.strip(),
                        "line": line_of_offset(txt, pm.start()), "file": rel,
                    })
        for bm in BIBLIOGRAPHY_RE.finditer(txt):
            for b in (bm.group(1) or "").split(","):
                b = b.strip()
                if b and b not in proj.bib_files:
                    proj.bib_files.append(b if b.endswith(".bib") else b + ".bib")
        for bm in ADDBIB_RE.finditer(txt):
            b = (bm.group(1) or "").strip()
            if b and b not in proj.bib_files:
                proj.bib_files.append(b)
        bst = BIBSTYLE_RE.search(txt)
        if bst and not proj.bib_style:
            proj.bib_style = bst.group(1).strip()

    # --- include graph ---------------------------------------------------------------
    queue = [proj.main]
    visited = set()
    while queue:
        rel = queue.pop(0)
        if rel in visited or not proj.exists(rel):
            continue
        visited.add(rel)
        try:
            txt = strip_comments(proj.text(rel))
        except OSError:
            continue
        kids = []
        for im in INCLUDE_RE.finditer(txt):
            requested = im.group(2).strip()
            resolved = proj.resolve_include(requested, rel)
            if resolved:
                kids.append(resolved)
                if resolved not in visited:
                    queue.append(resolved)
            else:
                proj.missing_includes.append((rel, requested))
        proj.includes[rel] = kids

    # mark class files that ship with the project
    for c in list(proj.classes):
        for cand in (c + ".cls", c + ".sty"):
            p = proj.abs(cand)
            if os.path.isfile(p):
                proj.notes.append("project ships class file %s" % cand)
    return proj


def detect_engine(proj, log_text=None):
    """Choose the engine, with the evidence that justifies the choice."""
    evidence = []
    if proj.magic_engine:
        return {"engine": proj.magic_engine, "reason": "magic comment in %s" % proj.main,
                "evidence": ["%% !TEX program = %s" % proj.magic_engine], "confidence": "high"}
    pkg_names = {p["name"] for p in proj.packages}
    cls = (proj.documentclass or "").lower()
    if cls in ENGINE_HINTS_CLASS:
        eng = ENGINE_HINTS_CLASS[cls]
        return {"engine": eng, "reason": "class %s requires %s" % (cls, eng),
                "evidence": ["\\documentclass{%s}" % cls], "confidence": "high"}
    if "fontspec" in pkg_names:
        return {"engine": "xelatex", "reason": "fontspec loaded (requires XeTeX/LuaTeX)",
                "evidence": ["\\usepackage{fontspec}"], "confidence": "high"}
    if "xeCJK" in pkg_names or "ctex" in pkg_names:
        return {"engine": "xelatex", "reason": "xeCJK/ctex requires a Unicode engine",
                "evidence": ["\\usepackage{xeCJK|ctex}"], "confidence": "high"}
    if "microtype" in pkg_names and "babel" in pkg_names:
        evidence.append("microtype+babel: pdflatex-friendly")
    # CJK characters in the source with a pdfTeX-only setup usually means a broken build
    has_cjk = False
    for rel in proj.tex_files()[:40]:
        try:
            if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", proj.text(rel)):
                has_cjk = True
                break
        except OSError:
            continue
    if has_cjk and not (pkg_names & {"xeCJK", "ctex", "CJKutf8", "CJK"}):
        return {"engine": "xelatex",
                "reason": "CJK text present but no CJK package: pdfTeX cannot typeset it",
                "evidence": ["CJK codepoints found in sources"], "confidence": "medium"}
    if log_text and "pdfTeX" in log_text[:400]:
        return {"engine": "pdflatex", "reason": "previous log ran pdfTeX successfully",
                "evidence": ["log header says pdfTeX"], "confidence": "medium"}
    return {"engine": "pdflatex", "reason": "default for Latin-script documents",
            "evidence": evidence or ["no engine-specific marker found"], "confidence": "medium"}


def detect_bib_backend(proj):
    names = {p["name"] for p in proj.packages}
    if "biblatex" in names:
        opts = " ".join(p.get("opts", "") for p in proj.packages if p["name"] == "biblatex")
        if "backend=bibtex" in opts.replace(" ", ""):
            return {"backend": "bibtex", "reason": "biblatex with backend=bibtex"}
        return {"backend": "biber", "reason": "biblatex default backend is biber"}
    if "natbib" in names:
        return {"backend": "bibtex", "reason": "natbib uses bibtex"}
    if proj.bib_files:
        return {"backend": "bibtex", "reason": "\\bibliography present"}
    return {"backend": "none", "reason": "no bibliography package/resource found"}


# --------------------------------------------------------------------------------------
# log parsing
# --------------------------------------------------------------------------------------

FILE_TOKEN_RE = re.compile(r"^[^\s()]*[./\\][^\s()]*$|^[^\s()]+\.[A-Za-z0-9]{1,6}$")
ERROR_LINE_RE = re.compile(r"^!\s?(.*)$")
LINE_REF_RE = re.compile(r"^l\.(\d+)(?:\s(.*))?$")
CONTEXT_REF_RE = re.compile(r"^<([A-Za-z0-9_.\-]+)>$")
OVERFULL_RE = re.compile(
    r"^(Overfull|Underfull) \\([hv]box|vbox)\s*\(([\d.]+)pt too (?:wide|high)\)\s*(.*)$")
MISSING_CHAR_RE = re.compile(r"^Missing character: There is no (.+?) in font (.+?)!$")
FONT_WARN_RE = re.compile(r"^LaTeX Font Warning: (.*)$")
LATEX_WARN_RE = re.compile(r"^LaTeX Warning: (.*)$")
PKG_WARN_RE = re.compile(r"^(?:Package|Class) (\S+) Warning: (.*)$")
OUTPUT_RE = re.compile(r"^Output written on .*?\((\d+) pages?, (\d+) bytes\)")
NO_OUTPUT_RE = re.compile(r"Fatal error occurred, no output PDF file produced")
UNDEF_REF_RE = re.compile(r"Reference [`']([^']+)' on page (\d+) undefined")
UNDEF_CITE_RE = re.compile(r"Citation [`']([^']+)' (?:on page \d+ )?undefined")
FILE_NOT_FOUND_RE = re.compile(r"File [`']([^']+)' not found")
MULTI_DEF_RE = re.compile(r"(?:Command|control sequence) \\([A-Za-z@]+) already defined")
# With -file-line-error (which this skill always passes) pdflatex prints
#   ./main.tex:12: Undefined control sequence.
# instead of the bare "! ..." form, so both spellings must be understood.
FILE_LINE_ERROR_RE = re.compile(
    r"^(\.{0,2}/?[^\s:]+?\.(?:tex|ltx|sty|cls|clo|def|bbl|aux|bib|tikz)):(\d+):\s?(.*)$")

SEVERITY_BY_KIND = {
    "fatal": "fatal", "error": "error", "missing-file": "error", "capacity": "fatal",
    "font": "error", "bib": "error", "warning": "warning", "overfull": "warning",
    "font-warning": "warning", "info": "info",
}


class Diag(object):
    """One parsed diagnostic. Mutable so root-cause and cascade passes can annotate it."""

    __slots__ = ("id", "kind", "severity", "message", "file", "line", "raw", "rule",
                 "root_cause", "cascade_parent", "fix_order", "confidence", "source",
                 "suggestion", "context")

    def __init__(self, kind, message, file=None, line=None, raw=None, source="log"):
        self.id = None
        self.kind = kind
        self.severity = SEVERITY_BY_KIND.get(kind, "warning")
        self.message = message.strip()
        self.file = file
        self.line = line
        self.raw = raw or []
        self.rule = None
        self.root_cause = None
        self.cascade_parent = None
        self.fix_order = None
        self.confidence = "medium"
        self.source = source
        self.suggestion = None
        self.context = None

    def signature(self):
        """Stable identity used to decide whether a repair actually helped."""
        msg = re.sub(r"\d+", "N", self.message)
        msg = re.sub(r"\s+", " ", msg)[:120]
        return "%s|%s|%s|%s" % (self.severity, self.file or "-", msg, "" if self.line is None else "L")

    def to_dict(self):
        d = {
            "id": self.id, "kind": self.kind, "severity": self.severity,
            "message": self.message, "file": self.file, "line": self.line,
            "rule": self.rule, "confidence": self.confidence, "source": self.source,
            "cascade_parent": self.cascade_parent, "fix_order": self.fix_order,
            "suggestion": self.suggestion, "context": self.context,
            "raw": self.raw[:6],
        }
        if self.root_cause:
            d["root_cause"] = self.root_cause
        return d


def _iter_log_lines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _track_files(lines):
    """Return per-line 'current file' using the TeX log's parenthesis nesting.

    Parentheses that do not open a file ("(preloaded format=pdflatex)") still have to be
    matched, otherwise their ')' closes a real file and every later error is attributed to
    the wrong source. Both kinds are therefore pushed; only file entries name a file.
    """
    stack = []          # list of filename-or-None
    current = [None] * len(lines)

    def top():
        for entry in reversed(stack):
            if entry is not None:
                return entry
        return None

    for idx, line in enumerate(lines):
        current[idx] = top()
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            if ch == "(":
                j = i + 1
                if j < n and line[j] == '"':
                    j += 1
                    k = j
                    while k < n and line[k] not in '"\n':
                        k += 1
                    tok = line[j:k].strip()
                    if tok and FILE_TOKEN_RE.match(tok):
                        stack.append(tok)
                        i = min(k + 1, n)
                        continue
                    stack.append(None)
                    i = min(k + 1, n)
                    continue
                k = j
                while k < n and line[k] not in " \t()":
                    k += 1
                tok = line[j:k]
                if tok and FILE_TOKEN_RE.match(tok) and not tok.startswith("="):
                    # trailing punctuation is not part of a path
                    tok = tok.rstrip(",;:")
                    stack.append(tok)
                    i = k
                    continue
                stack.append(None)   # non-file parenthesis: keep nesting balanced
                i = j
                continue
            if ch == ")":
                if stack:
                    stack.pop()
            i += 1
    return current


def _map_log_path(log_path, proj_root):
    """Map a path as printed in the log to a project-relative path when possible."""
    if not log_path:
        return None
    p = log_path.strip().strip('"').replace("\\", "/")
    p = re.sub(r"^\./", "", p)
    if proj_root:
        root = proj_root.replace("\\", "/").rstrip("/")
        if p.startswith(root + "/"):
            return p[len(root) + 1:]
    # a bare filename: keep it, the caller decides whether it exists
    if "/" not in p:
        return p
    if proj_root:
        for suffix_len in (3, 2, 1):
            parts = p.split("/")
            if len(parts) > suffix_len:
                candidate = "/".join(parts[-suffix_len:])
                if os.path.isfile(os.path.join(proj_root, candidate.replace("/", os.sep))):
                    return candidate
    return p


def _kind_from_message(msg):
    low = msg.lower()
    if "emergency stop" in low or "fatal error" in low or "==> fatal" in low:
        return "fatal"
    if "capacity exceeded" in low:
        return "capacity"
    if FILE_NOT_FOUND_RE.search(msg):
        return "missing-file"
    if "font" in low and ("not loadable" in low or "tfm" in low or "cannot be found" in low):
        return "font"
    if (".bbl" in low or "bbl" in low) and ("can't find" in low or "not found" in low):
        return "bib"
    return "error"


def parse_log(text, proj_root=None, source="log"):
    """Parse a pdflatex/xelatex/lualatex/latexmk console+log transcript."""
    diags = []
    lines = _iter_log_lines(text)
    current_file = _track_files(lines)
    i = 0
    n = len(lines)
    pending_runaway = None

    def cur_file(idx):
        return _map_log_path(current_file[idx] if idx < len(current_file) else None, proj_root)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # ---- runaway argument preamble ------------------------------------------
        if stripped.startswith("Runaway argument?"):
            buf = []
            j = i + 1
            while j < n and j < i + 12 and not lines[j].startswith("!"):
                buf.append(lines[j])
                j += 1
            pending_runaway = buf
            i = j
            continue

        # ---- hard error, -file-line-error spelling -------------------------------
        mfl = FILE_LINE_ERROR_RE.match(line)
        if mfl and "! " not in line[:2]:
            fpath = _map_log_path(mfl.group(1), proj_root)
            lineno = int(mfl.group(2))
            msg = mfl.group(3).strip()
            raw = [line]
            j = i + 1
            source_line = None
            if j < n:
                lm = LINE_REF_RE.match(lines[j])
                if lm:
                    source_line = (lm.group(2) or "").strip()
                    raw.append(lines[j])
                    j += 1
            d = Diag(_kind_from_message(msg), msg, fpath, lineno, raw, source=source)
            d.context = {"format": "file-line-error", "source_line": source_line}
            d.root_cause = None
            diags.append(d)
            i = j
            continue

        # ---- hard error, classic "!" spelling ------------------------------------
        m = ERROR_LINE_RE.match(line)
        if m and not line.startswith("!!"):
            msg = m.group(1).strip()
            raw = [line]
            j = i + 1
            ctx_lines = []
            # gather continuation lines until l.N / blank / next error
            while j < n:
                nxt = lines[j]
                if nxt.startswith("!") or nxt.startswith("l.") or nxt.strip() == "":
                    break
                if nxt.startswith("<") and nxt.endswith(">"):
                    break
                ctx_lines.append(nxt)
                raw.append(nxt)
                j += 1
            lineno = None
            src_line = None
            if j < n:
                lm = LINE_REF_RE.match(lines[j])
                if lm:
                    lineno = int(lm.group(1))
                    src_line = (lm.group(2) or "").strip()
                    raw.append(lines[j])
                    j += 1
                    # the following line is often the "rest of the line" continuation
                    if j < n and lines[j].startswith(" ") and not lines[j].startswith("   "):
                        raw.append(lines[j])
                        j += 1
            kind = _kind_from_message(msg)
            d = Diag(kind, msg, cur_file(i), lineno, raw, source=source)
            d.context = {
                "source_line": src_line,
                "continuation": ctx_lines[:4],
                "runaway": pending_runaway,
            }
            pending_runaway = None
            diags.append(d)
            i = j
            continue

        # ---- warnings ------------------------------------------------------------
        mw = UNDEF_REF_RE.search(line)
        if mw:
            d = Diag("warning", "undefined reference %s" % mw.group(1), cur_file(i), _line_from_warn(line))
            d.message = "Reference `%s' undefined" % mw.group(1)
            d.rule = "W-UNDEF-REF"
            d.context = {"key": mw.group(1)}
            diags.append(d)
            i += 1
            continue
        mc = UNDEF_CITE_RE.search(line)
        if mc:
            d = Diag("warning", "undefined citation %s" % mc.group(1), cur_file(i), _line_from_warn(line))
            d.message = "Citation `%s' undefined" % mc.group(1)
            d.rule = "W-UNDEF-CITE"
            d.context = {"key": mc.group(1)}
            diags.append(d)
            i += 1
            continue
        mo = OVERFULL_RE.match(line)
        if mo:
            d = Diag("overfull", "%s \\%s %spt" % (mo.group(1), mo.group(2), mo.group(3)),
                     cur_file(i), _line_from_warn(line))
            d.context = {"type": mo.group(1), "box": mo.group(2), "amount_pt": float(mo.group(3)),
                         "where": mo.group(4).strip()}
            d.rule = "W-OVERFULL"
            diags.append(d)
            i += 1
            continue
        mm = MISSING_CHAR_RE.match(stripped)
        if mm:
            d = Diag("font-warning", "missing character %s in font %s" % (mm.group(1), mm.group(2)),
                     cur_file(i), None)
            d.rule = "W-MISSING-CHAR"
            d.context = {"char": mm.group(1), "font": mm.group(2)}
            diags.append(d)
            i += 1
            continue
        mf = FONT_WARN_RE.match(stripped)
        if mf:
            d = Diag("font-warning", mf.group(1), cur_file(i), _line_from_warn(line))
            d.rule = "W-FONT"
            diags.append(d)
            i += 1
            continue
        mp = PKG_WARN_RE.match(stripped)
        if mp and "Warning" in line:
            d = Diag("warning", "%s: %s" % (mp.group(1), mp.group(2)), cur_file(i), _line_from_warn(line))
            d.rule = "W-PACKAGE"
            d.context = {"package": mp.group(1)}
            diags.append(d)
            i += 1
            continue
        i += 1

    return diags


def _line_from_warn(line):
    m = re.search(r"on input line (\d+)", line)
    return int(m.group(1)) if m else None


def parse_log_stats(text):
    """Facts about the run that do not depend on success: pages, output, engine banner."""
    stats = {"pages": None, "output_bytes": None, "output_file": None,
             "engine_banner": None, "fatal_no_output": bool(NO_OUTPUT_RE.search(text)),
             "warnings_count": 0, "errors_count": 0}
    m = re.search(r"Output written on (.+?) \((\d+) pages?, (\d+) bytes\)", text)
    if m:
        stats["output_file"] = m.group(1).strip()
        stats["pages"] = int(m.group(2))
        stats["output_bytes"] = int(m.group(3))
    head = text[:600]
    for banner in ("pdfTeX", "XeTeX", "LuaTeX", "LuaHBTeX"):
        if banner in head:
            stats["engine_banner"] = banner
            break
    mv = re.search(r"(pdfTeX, Version [^\n]+|XeTeX [^\n]+|LuaTeX[^\n]+|LuaHBTeX[^\n]+)", head)
    if mv:
        stats["engine_version"] = mv.group(1).strip()
    return stats


def parse_listfiles(text):
    """Parse a \\listfiles block: '*package.sty' followed by 'Package: name date version'."""
    pkgs = []
    lines = text.split("\n")
    pending = None
    for line in lines:
        s = line.strip()
        if s.startswith("*"):
            pending = os.path.basename(s[1:].strip())
            continue
        m = re.match(r"^(?:Package|Class|File):\s+(\S+)\s+(\d{4}/\d{2}/\d{2})?\s*(.*)$", s)
        if m:
            pkgs.append({"file": pending or (m.group(1) + ".sty"),
                         "name": m.group(1), "date": m.group(2) or "",
                         "version": (m.group(3) or "").strip()[:60]})
            pending = None
    return pkgs


# --------------------------------------------------------------------------------------
# root-cause classification
# --------------------------------------------------------------------------------------

def classify(diag, project_files=None):
    """Assign a rule id and a root_cause record to a diagnostic."""
    msg = diag.message
    low = msg.lower()
    ctx = diag.context or {}

    if diag.kind == "missing-file":
        m = FILE_NOT_FOUND_RE.search(msg)
        fname = m.group(1) if m else None
        ext = os.path.splitext(fname or "")[1].lower()
        pkg_name = fname[:-len(ext)] if fname and ext else fname
        if ext == ".cls":
            diag.rule = "E-MISSING-CLASS"
            diag.root_cause = {
                "category": "template-class-missing", "confidence": "high",
                "explanation": "The document class %s is not installed in this TeX distribution "
                               "and is not shipped with the project, so nothing in the preamble "
                               "can be processed." % fname,
                "evidence": [msg], "class": pkg_name,
            }
        else:
            diag.rule = "E-MISSING-PKG"
            diag.root_cause = {
                "category": "package-not-installed", "confidence": "high",
                "explanation": "%s is requested but not resolvable by this TeX distribution." % fname,
                "evidence": [msg], "package": pkg_name, "requested_file": fname,
            }
        return diag

    if "file ended while scanning" in low:
        used = re.search(r"scanning use of \\\\?([A-Za-z@]+)", msg)
        diag.rule = "E-FILE-ENDED-SCANNING"
        diag.root_cause = {
            "category": "unbalanced-brace-or-environment", "confidence": "high",
            "explanation": "TeX reached end of file while still reading an argument of \\%s. "
                           "The reported position is end-of-file, so the real defect is an unclosed "
                           "'{', '[' or \\begin{...} somewhere earlier in the same file."
                           % (used.group(1) if used else "?"),
            "evidence": [msg], "scan_backwards": True,
        }
        return diag

    if "runaway argument" in low or (ctx.get("runaway") and "paragraph ended before" in low):
        diag.rule = "E-RUNAWAY-ARGUMENT"
        diag.root_cause = {
            "category": "argument-swallowed-too-much", "confidence": "high",
            "explanation": "A command's argument consumed more text than intended, which almost "
                           "always means a missing closing brace or a stray opening one before it.",
            "evidence": [msg], "scan_backwards": True,
        }
        return diag

    if "undefined control sequence" in low:
        name = None
        cont = " ".join(ctx.get("continuation") or [])
        m = re.search(r"\\([A-Za-z@]+)", cont) or re.search(r"\\([A-Za-z@]+)",
                                                             ctx.get("source_line") or "")
        if m:
            name = m.group(1)
        if not name:
            m2 = re.search(r"\\([A-Za-z@]+)", msg)
            name = m2.group(1) if m2 else None
        pkg = MACRO_PACKAGES.get(name) if name else None
        diag.rule = "E-UNDEFINED-CS"
        diag.root_cause = {
            "category": "macro-undefined",
            "confidence": "high" if pkg else "medium",
            "explanation": ("\\%s is not defined. In standard LaTeX it comes from package '%s'."
                            % (name, pkg)) if pkg else
                           ("\\%s is not defined by any loaded package; it may be a typo, a missing "
                            "\\newcommand, or a missing package that this skill could not name with "
                            "confidence." % (name or "?")),
            "evidence": [msg] + ([ctx.get("source_line")] if ctx.get("source_line") else []),
            "macro": name, "package": pkg,
        }
        return diag

    if "missing $ inserted" in low or "extra }, or forgotten $" in low:
        diag.rule = "E-MATH-MODE"
        diag.root_cause = {
            "category": "math-shift", "confidence": "high",
            "explanation": "Math-only material (subscript '_', '^', a Greek letter, or a math "
                           "operator) appeared outside math mode, or a $ / \\[ was never closed.",
            "evidence": [msg], "scan_math": True,
        }
        return diag

    if "misplaced alignment tab" in low:
        diag.rule = "E-ALIGNMENT-TAB"
        diag.root_cause = {
            "category": "ampersand-outside-table", "confidence": "high",
            "explanation": "'&' was used outside a tabular/align context, so TeX read it as an "
                           "alignment tab. Either the cell separator belongs inside a table "
                           "environment, or the character should be the literal \\&.",
            "evidence": [msg],
        }
        return diag

    if "already defined" in low:
        diag.rule = "E-MACRO-REDEFINED"
        diag.root_cause = {"category": "symbol-clash", "confidence": "high",
                           "explanation": "Two loaded packages define the same macro. Load order or "
                                          "an option decides which one wins; the fix is to load them "
                                          "in the documented order or drop the duplicate.",
                           "evidence": [msg]}
        return diag

    if "capacity exceeded" in low:
        diag.rule = "E-CAPACITY"
        diag.root_cause = {"category": "tex-resource-exhausted", "confidence": "medium",
                           "explanation": "TeX ran out of a resource. Recursive macro expansion or "
                                          "an enormous table are the usual causes; the reported "
                                          "line is where the limit tripped, not where the loop began.",
                           "evidence": [msg]}
        return diag

    if "environment" in low and "undefined" in low:
        m = re.search(r"Environment (\S+) undefined", msg)
        env = m.group(1) if m else None
        pkg = ENV_PACKAGES.get(env) if env else None
        diag.rule = "E-ENV-UNDEFINED"
        diag.root_cause = {
            "category": "environment-undefined",
            "confidence": "high" if pkg else "low",
            "explanation": ("Environment '%s' is provided by package '%s', which is not loaded."
                            % (env, pkg)) if pkg else
                           ("Environment '%s' is not defined." % (env or "?")),
            "evidence": [msg], "environment": env, "package": pkg,
        }
        return diag

    if "too many }" in low or "extra }" in low:
        diag.rule = "E-EXTRA-CLOSE-BRACE"
        diag.root_cause = {"category": "unbalanced-brace", "confidence": "high",
                           "explanation": "A closing brace has no matching opening brace; TeX "
                                          "reports the first brace that closes an already-closed "
                                          "group, which may be well before the visible symptom.",
                           "evidence": [msg], "scan_backwards": True}
        return diag

    if "font" in low and ("not loadable" in low or "not found" in low):
        diag.rule = "E-FONT-NOT-FOUND"
        diag.root_cause = {"category": "font-not-available", "confidence": "high",
                           "explanation": "The font metrics or the font file itself are not installed. "
                                          "This is an environment problem, not a source problem.",
                           "evidence": [msg]}
        return diag

    if diag.kind == "bib":
        diag.rule = "E-BIB-MISSING"
        diag.root_cause = {"category": "bibliography-not-built", "confidence": "high",
                           "explanation": "The .bbl file is missing, which means the bibliography "
                                          "backend never ran. The build plan, not the source, is "
                                          "what has to change.",
                           "evidence": [msg]}
        return diag

    if diag.kind == "fatal":
        diag.rule = "E-FATAL"
        diag.root_cause = {"category": "run-aborted", "confidence": "low",
                           "explanation": "The run stopped. If this follows another error, that "
                                          "earlier error is the cause and this one is noise.",
                           "evidence": [msg]}
        return diag

    if diag.rule is None:
        diag.rule = "E-OTHER"
        diag.root_cause = {"category": "unclassified", "confidence": "low",
                           "explanation": "No specific rule matched this message yet.",
                           "evidence": [msg]}
    return diag


FATAL_FOLLOWERS = (
    "emergency stop", "fatal error occurred", "no output pdf file produced",
    "pdftex error", "==> fatal error",
)


def annotate(diags, project=None):
    """Assign ids, drop pure cascade noise, order by fix priority."""
    for idx, d in enumerate(diags, 1):
        d.id = "D%03d" % idx
        if d.rule is None:
            classify(d)

    # cascade suppression: a fatal error after a real error is noise
    seen_blocker = None
    for d in diags:
        low = d.message.lower()
        is_follower = any(f in low for f in FATAL_FOLLOWERS)
        if seen_blocker is not None and (is_follower or d.rule == "E-FATAL"):
            d.cascade_parent = seen_blocker.id
        if d.severity in ("error", "fatal", "capacity", "font", "missing-file", "bib") \
                and not is_follower:
            if seen_blocker is None:
                seen_blocker = d
    # "File ended while scanning" makes every later error meaningless
    scanning = [d for d in diags if d.rule == "E-FILE-ENDED-SCANNING"]
    if scanning:
        first = scanning[0]
        for d in diags:
            if d is not first and not d.cascade_parent and d.severity in ("error", "fatal", "capacity"):
                d.cascade_parent = first.id

    live = [d for d in diags if d.cascade_parent is None]
    # priority: missing class > missing package > brace/scan > run-away > math > macro > rest
    prio = {
        "E-MISSING-CLASS": 0, "E-FILE-ENDED-SCANNING": 1, "E-EXTRA-CLOSE-BRACE": 1,
        "E-RUNAWAY-ARGUMENT": 2, "E-MISSING-PKG": 3, "E-BIB-MISSING": 4,
        "E-MATH-MODE": 5, "E-UNDEFINED-CS": 6, "E-ENV-UNDEFINED": 6,
        "E-ALIGNMENT-TAB": 7, "E-FONT-NOT-FOUND": 8, "E-MACRO-REDEFINED": 9,
        "E-CAPACITY": 10, "E-FATAL": 99, "E-OTHER": 50,
    }
    live.sort(key=lambda d: (prio.get(d.rule, 40), d.file or "", d.line or 0))
    for order, d in enumerate(live, 1):
        d.fix_order = order
    return diags


def summarize(diags):
    live = [d for d in diags if d.cascade_parent is None]
    counts = {}
    for d in diags:
        counts[d.severity] = counts.get(d.severity, 0) + 1
    return {
        "total": len(diags),
        "live": len(live),
        "suppressed": len(diags) - len(live),
        "by_severity": counts,
        "fatal_errors": len([d for d in live if d.severity in ("error", "fatal", "capacity",
                                                               "missing-file", "font", "bib")]),
        "warnings": len([d for d in live if d.severity == "warning"]),
    }


# --------------------------------------------------------------------------------------
# structure: braces, environments, math delimiters
# --------------------------------------------------------------------------------------

def brace_balance(text):
    """Return (final_depth, unclosed_opens) where unclosed_opens is [(line, col, snippet)].

    A negative depth means there is a '}' with no opening brace, which is a different defect
    and needs a different patch, so it is reported rather than folded into the depth.
    """
    src = strip_comments(mask_verbatim(text))
    stack = []
    line = 1
    i = 0
    n = len(src)
    extra_closes = []
    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            stack.append((line, i))
        elif ch == "}":
            if stack:
                stack.pop()
            else:
                extra_closes.append(line)
        i += 1
    unclosed = []
    for (ln, off) in stack:
        start = src.rfind("\n", 0, off) + 1
        end = src.find("\n", off)
        snippet = src[start:end if end != -1 else n].strip()
        unclosed.append((ln, off, snippet[:120]))
    if extra_closes and not stack:
        return -len(extra_closes), unclosed
    return len(stack), unclosed


ENV_BEGIN_RE = re.compile(r"\\begin\s*\{([^}]+)\}")


def env_balance(text):
    """Return (unclosed_envs, stray_ends) with line numbers."""
    src = strip_comments(mask_verbatim(text))
    stack = []
    unclosed, stray = [], []
    for m in re.finditer(r"\\(begin|end)\s*\{([^}]+)\}", src):
        kind, name = m.group(1), m.group(2).strip()
        ln = line_of_offset(src, m.start())
        if kind == "begin":
            stack.append((name, ln))
        else:
            if stack and stack[-1][0] == name:
                stack.pop()
            elif stack:
                # tolerate a mismatch by searching down the stack
                found = None
                for k in range(len(stack) - 1, -1, -1):
                    if stack[k][0] == name:
                        found = k
                        break
                if found is None:
                    stray.append({"environment": name, "line": ln})
                else:
                    unclosed.extend({"environment": e, "line": l} for e, l in stack[found + 1:])
                    del stack[found:]
            else:
                stray.append({"environment": name, "line": ln})
    unclosed.extend({"environment": e, "line": l} for e, l in stack)
    return unclosed, stray


MATH_INLINE_RE = re.compile(r"(?<!\\)\$(?!\$)")
MATH_DISPLAY_RE = re.compile(r"(?<!\\)\\\[|(?<!\\)\\\]")


def math_balance(text):
    """Detect unbalanced $ pairs and \\[ \\] pairs (line numbers of the openers)."""
    src = strip_comments(mask_verbatim(text))
    dollars = [line_of_offset(src, m.start()) for m in MATH_INLINE_RE.finditer(src)]
    opens = [line_of_offset(src, m.start()) for m in re.finditer(r"(?<!\\)\\\[", src)]
    closes = [line_of_offset(src, m.start()) for m in re.finditer(r"(?<!\\)\\\]", src)]
    return {
        "inline_dollar_lines": dollars,
        "inline_balanced": len(dollars) % 2 == 0,
        "display_open_lines": opens,
        "display_close_lines": closes,
        "display_balanced": len(opens) == len(closes),
    }


def structural_audit(proj, rels=None):
    """Static structural findings; works with or without a TeX installation."""
    findings = []
    for rel in (rels or proj.tex_files()):
        if not proj.exists(rel):
            continue
        try:
            txt = proj.text(rel)
        except OSError:
            continue
        depth, unclosed = brace_balance(txt)
        if depth < 0:
            findings.append({"kind": "brace", "file": rel, "rule": "S-BRACE-EXTRA",
                             "severity": "error", "final_depth": depth,
                             "explanation": "%d '}' has no matching '{'. TeX stops at the first one."
                                            % (-depth)})
        elif depth > 0:
            findings.append({
                "kind": "brace", "file": rel, "rule": "S-BRACE-UNCLOSED",
                "severity": "error", "final_depth": depth,
                "unclosed": [{"line": l, "snippet": s} for l, _o, s in unclosed[:8]],
                "explanation": "%d '{' never closed. TeX reports this at end of file, not here." % depth,
            })
        unclosed_env, stray = env_balance(txt)
        if unclosed_env:
            findings.append({"kind": "environment", "file": rel, "rule": "S-ENV-UNCLOSED",
                             "severity": "error", "unclosed": unclosed_env[:8],
                             "explanation": "\\begin{...} without \\end{...}"})
        if stray:
            findings.append({"kind": "environment", "file": rel, "rule": "S-ENV-STRAY-END",
                             "severity": "error", "stray": stray[:8],
                             "explanation": "\\end{...} with no matching \\begin{...}"})
        mb = math_balance(txt)
        if not mb["inline_balanced"]:
            findings.append({"kind": "math", "file": rel, "rule": "S-MATH-UNBALANCED",
                             "severity": "error",
                             "dollar_lines": mb["inline_dollar_lines"][:12],
                             "explanation": "odd number of unescaped $ — one pair is never closed"})
        if not mb["display_balanced"]:
            findings.append({"kind": "math", "file": rel, "rule": "S-DISPLAY-UNBALANCED",
                             "severity": "error",
                             "open_lines": mb["display_open_lines"][:12],
                             "close_lines": mb["display_close_lines"][:12],
                             "explanation": "\\[ and \\] counts differ"})
    return findings


# --------------------------------------------------------------------------------------
# patch engine
# --------------------------------------------------------------------------------------

class Patch(object):
    """One minimal source edit, typed and justified."""

    __slots__ = ("id", "rule", "diag_id", "file", "op", "line", "old", "new",
                 "reason", "confidence", "risk")

    def __init__(self, rule, file, op, line=None, old=None, new=None, reason="",
                 diag_id=None, confidence="medium", risk="low"):
        self.id = None
        self.rule = rule
        self.diag_id = diag_id
        self.file = file
        self.op = op           # insert_after | replace_line | insert_before
        self.line = line        # 1-based
        self.old = old
        self.new = new
        self.reason = reason
        self.confidence = confidence
        self.risk = risk

    def to_dict(self):
        return {"id": self.id, "rule": self.rule, "diag_id": self.diag_id, "file": self.file,
                "op": self.op, "line": self.line, "old": self.old, "new": self.new,
                "reason": self.reason, "confidence": self.confidence, "risk": self.risk}


FORBIDDEN_DELETIONS = ("\\cite", "\\citep", "\\citet", "\\ref", "\\eqref", "\\autoref",
                       "\\label", "\\begin{equation", "\\begin{align", "\\includegraphics",
                       "\\section", "\\subsection", "\\caption")


def guard_patch(patch, before_text, after_text):
    """Refuse edits that 'repair' a build by deleting the content the build is about."""
    if patch.op == "replace_line" and (patch.new or "").strip() == "":
        for token in FORBIDDEN_DELETIONS:
            if token in (patch.old or ""):
                return False, "would delete a line containing %s" % token
    if patch.op == "insert_after" and "\\usepackage" in (patch.new or ""):
        if re.search(r"\\usepackage\s*\{[^}]*\\", patch.new or ""):
            return False, "malformed \\usepackage"
    # no-op edits
    if patch.op == "replace_line" and patch.old == patch.new:
        return False, "no change"
    return True, "ok"


def apply_patch_text(text, patch):
    lines = text.split("\n")
    ln = patch.line
    if ln is None or ln < 1:
        ln = 1
    if patch.op == "insert_after":
        idx = min(ln, len(lines))
        lines.insert(idx, patch.new)
        return "\n".join(lines)
    if patch.op == "insert_before":
        idx = max(0, min(ln - 1, len(lines)))
        lines.insert(idx, patch.new)
        return "\n".join(lines)
    if patch.op == "replace_line":
        idx = ln - 1
        if idx < 0 or idx >= len(lines):
            raise IndexError("line %d out of range" % ln)
        if patch.old is not None and lines[idx].strip() != (patch.old or "").strip():
            raise ValueError("line %d does not match expected content" % ln)
        lines[idx] = patch.new
        return "\n".join(lines)
    raise ValueError("unknown op %r" % patch.op)


def apply_patch_to_tree(tree_dir, patch):
    """Apply a patch on disk inside tree_dir; return (ok, message, before, after)."""
    path = os.path.join(tree_dir, patch.file.replace("/", os.sep))
    if not os.path.isfile(path):
        return False, "file not found: %s" % patch.file, None, None
    text, _enc = read_text(path)
    ok, why = guard_patch(patch, text, text)
    if not ok:
        return False, why, text, text
    try:
        new_text = apply_patch_text(text, patch)
    except (IndexError, ValueError) as exc:
        return False, str(exc), text, text
    write_text(path, new_text)
    return True, "applied", text, new_text


def unified_diff(old, new, fromfile, tofile, context=3):
    """Minimal dependency-free unified diff (LCS via difflib)."""
    import difflib
    old_lines = old.split("\n")
    new_lines = new.split("\n")
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile,
                                n=context, lineterm="")
    out = list(diff)
    if not out:
        return None
    return "\n".join(out) + "\n"


def copy_tree(src, dst, skip_dirs=None):
    skip = set(skip_dirs or SKIP_DIRS)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in skip]
        rel = os.path.relpath(dirpath, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        if not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
        for fn in filenames:
            s = os.path.join(dirpath, fn)
            if os.path.islink(s):
                continue
            try:
                shutil.copy2(s, os.path.join(target, fn))
            except (OSError, IOError):
                pass
    return dst


def tree_hashes(root, exts=None):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            if os.path.islink(p):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if exts and ext not in exts:
                continue
            try:
                out[norm_rel(p, root)] = sha256_file(p)
            except OSError:
                continue
    return out


# --------------------------------------------------------------------------------------
# bib / aux / bbl
# --------------------------------------------------------------------------------------

def parse_aux(path):
    """Read the facts a .aux carries: which citations/labels exist, which bib files ran."""
    info = {"citations": [], "bibcites": [], "bibstyle": None, "bibdata": [],
            "labels": [], "newlabel": {}, "files_exist": os.path.isfile(path)}
    if not info["files_exist"]:
        return info
    text, _ = read_text(path)
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("\\citation{"):
            for k in s[len("\\citation{"):-1].split(","):
                k = k.strip()
                if k and k not in info["citations"]:
                    info["citations"].append(k)
        elif s.startswith("\\bibcite{"):
            m = re.match(r"\\bibcite\{([^}]*)\}\{([^}]*)\}", s)
            if m:
                info["bibcites"].append({"key": m.group(1), "label": m.group(2)})
        elif s.startswith("\\bibstyle{"):
            info["bibstyle"] = s[len("\\bibstyle{"):-1]
        elif s.startswith("\\bibdata{"):
            info["bibdata"] = [b.strip() for b in s[len("\\bibdata{"):-1].split(",") if b.strip()]
        elif s.startswith("\\newlabel{"):
            m = re.match(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}\{(\d+)\}", s)
            if m:
                info["labels"].append(m.group(1))
                info["newlabel"][m.group(1)] = {"text": m.group(2), "page": int(m.group(3))}
    return info


def parse_bbl(path):
    out = {"exists": os.path.isfile(path), "entries": 0, "keys": [], "problems": []}
    if not out["exists"]:
        return out
    text, _ = read_text(path)
    keys = re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]*)\}", text)
    out["keys"] = keys
    out["entries"] = len(keys)
    if "\\bibitem" not in text and "\\entry" not in text and len(text) > 200:
        out["problems"].append("no \\bibitem found in .bbl")
    return out


BIB_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s}]+)\s*,", re.I)


def parse_bib(path):
    """Tolerant BibTeX reader: entry types, keys, field names (not a full parser)."""
    out = {"path": path, "exists": os.path.isfile(path), "entries": [], "keys": [],
           "types": {}, "problems": []}
    if not out["exists"]:
        return out
    text, _ = read_text(path)
    for m in BIB_ENTRY_RE.finditer(text):
        etype = m.group(1).lower()
        if etype in ("comment", "string", "preamble"):
            continue
        key = m.group(2).strip()
        # brace-match the entry body to collect field names
        j = m.end()
        depth = 1
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[m.end():j - 1] if depth == 0 else text[m.end():]
        fields = [f.lower() for f in re.findall(r"(?m)^\s*([A-Za-z]+)\s*=", body)]
        out["entries"].append({"type": etype, "key": key, "fields": fields,
                               "size": len(body)})
        out["keys"].append(key)
        out["types"][etype] = out["types"].get(etype, 0) + 1
    if depth and depth > 0:
        out["problems"].append("unbalanced braces at end of .bib")
    return out


CITE_CMD_RE = re.compile(
    r"\\(?:no)?cite[A-Za-z]*\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}")
REF_CMD_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref|nameref)\*?\s*\{([^}]*)\}")
LABEL_CMD_RE = re.compile(r"\\label\s*\{([^}]*)\}")


def scan_citations_and_refs(proj, rels=None):
    """Collect every cite key, ref key and label definition with file:line."""
    cites, refs, labels = [], [], []
    for rel in (rels or proj.tex_files()):
        if not proj.exists(rel):
            continue
        try:
            txt = strip_comments(proj.text(rel))
        except OSError:
            continue
        for m in CITE_CMD_RE.finditer(txt):
            for k in m.group(1).split(","):
                k = k.strip()
                if k:
                    cites.append({"key": k, "file": rel, "line": line_of_offset(txt, m.start())})
        for m in REF_CMD_RE.finditer(txt):
            for k in m.group(1).split(","):
                k = k.strip()
                if k:
                    refs.append({"key": k, "file": rel, "line": line_of_offset(txt, m.start())})
        for m in LABEL_CMD_RE.finditer(txt):
            labels.append({"key": m.group(1).strip(), "file": rel,
                           "line": line_of_offset(txt, m.start())})
    return {"citations": cites, "references": refs, "labels": labels}


def compute_bib_closure(proj, scan=None, bib_entries=None):
    """Which cite keys resolve, which do not, which library entries are unused."""
    scan = scan or scan_citations_and_refs(proj)
    bib_keys = set()
    for e in (bib_entries or []):
        bib_keys.update(e["keys"])
    label_keys = {l["key"] for l in scan["labels"]}
    cite_keys = {c["key"] for c in scan["citations"]}
    ref_keys = {r["key"] for r in scan["references"]}
    missing = sorted(cite_keys - bib_keys)
    undefined_refs = sorted(ref_keys - label_keys)
    unused = sorted(bib_keys - cite_keys)
    return {
        "cite_keys": len(cite_keys),
        "bib_keys": len(bib_keys),
        "label_keys": len(label_keys),
        "ref_keys": len(ref_keys),
        "citations_without_entry": missing,
        "references_without_label": undefined_refs,
        "unused_bib_entries": unused,
        "closed": not missing and not undefined_refs,
    }


# --------------------------------------------------------------------------------------
# environment probing
# --------------------------------------------------------------------------------------

ENGINE_COMMANDS = ("latexmk", "pdflatex", "xelatex", "lualatex", "tectonic", "latex",
                   "platex", "uplatex")
BIB_COMMANDS = ("bibtex", "biber")


def _which(cmd):
    from shutil import which
    return which(cmd)


#: public alias used by the orchestrator to test for external tools
which = _which


def probe_engines(timeout=20):
    """Report which engines actually exist and their versions. Never assumes."""
    found = {}
    for cmd in ENGINE_COMMANDS + BIB_COMMANDS + ("kpsewhich",):
        path = _which(cmd)
        if not path:
            found[cmd] = {"available": False}
            continue
        ver = None
        try:
            proc = subprocess.run([cmd, "--version"], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=timeout)
            ver = (proc.stdout or b"").decode("utf-8", "replace").split("\n")[0].strip()[:200]
        except Exception as exc:  # noqa: BLE001 - probing must never raise
            ver = "version probe failed: %s" % type(exc).__name__
        found[cmd] = {"available": True, "path": path, "version": ver}
    found["any_engine"] = any(found[c]["available"] for c in ENGINE_COMMANDS)
    found["any_bib"] = any(found[c]["available"] for c in BIB_COMMANDS)
    return found


def kpsewhich(name, timeout=20):
    """Ask the TeX distribution whether a file is installed."""
    if not _which("kpsewhich"):
        return {"checked": False, "found": None,
                "reason": "kpsewhich not on PATH; cannot verify installation"}
    try:
        proc = subprocess.run(["kpsewhich", name], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=timeout)
        out = (proc.stdout or b"").decode("utf-8", "replace").strip()
        return {"checked": True, "found": out or None,
                "path": out or None, "available": bool(out)}
    except Exception as exc:  # noqa: BLE001
        return {"checked": False, "found": None, "reason": str(exc)}


def read_resources_yaml(root):
    """Read environment/resources.yaml if present (tiny YAML subset: nested maps + lists of maps)."""
    candidates = []
    for rel in ("environment/resources.yaml", "resources.yaml", "../environment/resources.yaml"):
        p = os.path.normpath(os.path.join(root, rel))
        if os.path.isfile(p):
            candidates.append(p)
    if not candidates:
        return {"present": False, "path": None, "tools": [], "runtimes": []}
    path = candidates[0]
    text, _ = read_text(path)
    tools, runtimes = [], []
    current = None
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if s.startswith("- "):
            item = s[2:].strip()
            entry = {}
            if ":" in item:
                k, v = item.split(":", 1)
                entry[k.strip()] = v.strip().strip('"\'')
            for target in (tools, runtimes):
                if current and current.get("_list") is target:
                    if entry:
                        target.append(entry)
                    break
            continue
        if ":" in s and not s.startswith("-"):
            k, v = s.split(":", 1)
            k, v = k.strip(), v.strip().strip('"\'')
            if indent == 0:
                current = {"key": k}
                if k in ("tools", "tooling", "binaries"):
                    current = {"_list": tools}
                elif k in ("runtimes", "runtime", "paths", "preinstalled"):
                    current = {"_list": runtimes}
                elif v:
                    tools.append({"name": k, "value": v})
            elif v:
                tools.append({"name": k, "value": v})
    return {"present": True, "path": path, "raw": text[:4000], "tools": tools,
            "runtimes": runtimes}


# --------------------------------------------------------------------------------------
# build execution
# --------------------------------------------------------------------------------------

def run_command(cmd, cwd, timeout=300, env=None):
    """Run a subprocess, capturing output; never raises."""
    started = None
    try:
        import time as _time
        started = _time.time()
        proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout, env=env)
        elapsed = _time.time() - started
        return {
            "cmd": cmd if isinstance(cmd, str) else " ".join(cmd),
            "returncode": proc.returncode,
            "output": (proc.stdout or b"").decode("utf-8", "replace"),
            "elapsed_s": round(elapsed, 2),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        out = exc.output or b""
        if isinstance(out, str):
            out = out.encode("utf-8", "replace")
        return {"cmd": " ".join(cmd) if not isinstance(cmd, str) else cmd,
                "returncode": None, "output": out.decode("utf-8", "replace"),
                "elapsed_s": timeout, "timed_out": True}
    except FileNotFoundError:
        return {"cmd": " ".join(cmd) if not isinstance(cmd, str) else cmd,
                "returncode": 127, "output": "", "elapsed_s": 0,
                "timed_out": False, "missing": True}
    except Exception as exc:  # noqa: BLE001
        return {"cmd": " ".join(cmd) if not isinstance(cmd, str) else cmd,
                "returncode": -1, "output": "%s: %s" % (type(exc).__name__, exc),
                "elapsed_s": 0, "timed_out": False, "error": True}


ENGINE_FLAGS = {
    "pdflatex": ["-interaction=nonstopmode", "-file-line-error", "-halt-on-error",
                 "-synctex=1"],
    "xelatex": ["-interaction=nonstopmode", "-file-line-error", "-halt-on-error",
                "-synctex=1"],
    "lualatex": ["-interaction=nonstopmode", "-file-line-error", "-halt-on-error",
                 "-synctex=1"],
    "latex": ["-interaction=nonstopmode", "-file-line-error", "-halt-on-error"],
    "platex": ["-interaction=nonstopmode", "-file-line-error", "-halt-on-error"],
    "uplatex": ["-interaction=nonstopmode", "-file-line-error", "-halt-on-error"],
}


def build_plan(proj, engine, backend, max_passes=4):
    """A convergent pass sequence derived from the project, not a fixed 'run three times'."""
    job = os.path.splitext(os.path.basename(proj.main))[0]
    steps = []
    steps.append({"tool": engine, "args": ENGINE_FLAGS.get(engine, []) + [proj.main],
                  "why": "first pass: generates .aux, resolves \\label/\\ref skeleton"})
    if backend in ("bibtex", "biber") and (proj.bib_files or backend == "biber"):
        steps.append({"tool": backend, "args": [job],
                      "why": "bibliography: turns .aux \\citation into .bbl"})
        steps.append({"tool": engine, "args": ENGINE_FLAGS.get(engine, []) + [proj.main],
                      "why": "second pass: pulls \\bibitem numbers from .bbl"})
    steps.append({"tool": engine, "args": ENGINE_FLAGS.get(engine, []) + [proj.main],
                  "why": "final pass: settles page numbers and cross-references"})
    return {"job": job, "steps": steps, "max_passes": max_passes}


def write_build_repro(out_dir, proj, engine, backend, versions):
    """Write build.sh / latexmkrc / versions.txt so someone else can reproduce the artefact."""
    os.makedirs(out_dir, exist_ok=True)
    job = os.path.splitext(os.path.basename(proj.main))[0]
    lines = ["#!/usr/bin/env bash",
             "# Generated by latex-build-doctor — reproducible rebuild of %s" % job,
             "set -euo pipefail",
             "cd \"$(dirname \"$0\")/..\"",
             "ENGINE=\"${ENGINE:-%s}\"" % engine,
             "\"$ENGINE\" -interaction=nonstopmode -file-line-error %s.tex" % job]
    if backend in ("bibtex", "biber") and (proj.bib_files or backend == "biber"):
        lines += ["%s %s" % (backend, job),
                  "\"$ENGINE\" -interaction=nonstopmode -file-line-error %s.tex" % job]
    lines += ["\"$ENGINE\" -interaction=nonstopmode -file-line-error %s.tex" % job,
              "", "echo \"built: %s.pdf\"" % job]
    write_text(os.path.join(out_dir, "build.sh"), "\n".join(lines) + "\n")
    lm = ["# latexmkrc generated by latex-build-doctor",
          "$pdf_mode = %s;" % (5 if engine == "xelatex" else 1),
          ]
    if engine == "xelatex":
        lm.insert(1, "$pdflatex = 'xelatex -interaction=nonstopmode -file-line-error %O %S';")
    if backend == "biber":
        lm.append("$bibtex_use = 2;")
        lm.append("$biber = 'biber %O %S';")
    write_text(os.path.join(out_dir, "latexmkrc"), "\n".join(lm) + "\n")
    write_text(os.path.join(out_dir, "versions.txt"),
               json.dumps(versions, ensure_ascii=False, indent=2) + "\n")
    write_text(os.path.join(out_dir, "README.md"), _repro_readme(job, engine, backend, versions))
    return out_dir


def _repro_readme(job, engine, backend, versions):
    return """# Reproducible build record

Everything here was written by the run that produced the PDF next to it.

| Item | Value |
|---|---|
| main file | `{job}.tex` |
| engine | `{engine}` |
| bibliography backend | `{backend}` |
| pass sequence | engine → (bib) → engine → engine |

## Rebuild

```bash
bash repro/build.sh          # or: latexmk -r repro/latexmkrc {job}.tex
```

## What "same artefact" means

Byte-identical PDFs are not promised by TeX: timestamps and font subset ordering move the
bytes around. The checkable invariants are the ones recorded in `versions.txt`:
engine version, package list and versions, and the sha256 of every input file. With the same
versions and the same inputs, page count and layout reproduce even when the PDF hash does not.
""".format(job=job, engine=engine, backend=backend)


# --------------------------------------------------------------------------------------
# small utilities used by the orchestrator
# --------------------------------------------------------------------------------------

def safe_rel(path, root):
    p = norm_rel(path, root)
    return p if not p.startswith("..") else os.path.basename(path)


def now_iso():
    import datetime
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def guess_case_id(input_dir, case=None):
    if case and isinstance(case, dict) and case.get("case_id"):
        return str(case["case_id"])
    if case and isinstance(case, dict) and case.get("id"):
        return str(case["id"])
    base = os.path.basename(os.path.abspath(input_dir).rstrip("/\\"))
    return base or "unknown"
