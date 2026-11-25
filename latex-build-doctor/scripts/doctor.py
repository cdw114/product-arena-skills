#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor — LaTeX build doctor: diagnose, repair, verify, and record a reproducible build.

Run it as the first thing you do on any LaTeX writing/compilation case:

    python3 scripts/doctor.py --input /input --out /app/output --work /app/work

It will (1) find the project and its main file, (2) audit the sources statically, (3) build
with the right engine and bibliography backend, (4) read the log past the first error to the
root causes, (5) apply one minimal patch at a time and keep it only if a rebuild proves the
diagnostic set got smaller, (6) write the repaired sources, the PDF, the diffs, the
reproducibility record, and result.json.

Nothing here paraphrases the author's text: patches are limited to declarations, delimiters
and escapes, and every patch that removes content is refused by the guard in texlib.
"""

import argparse
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import texlib as T
import checks as C

SKILL_NAME = "latex-build-doctor"
SKILL_VERSION = "1.0.0"
DEFAULT_BUDGET_S = 420.0


# --------------------------------------------------------------------------------------
# input discovery
# --------------------------------------------------------------------------------------

def load_case(input_dir):
    """Read case.json/task.md with tolerant key names. Missing files are reported, not fatal."""
    info = {"case_json": None, "case": {}, "task": None, "task_files": [], "notes": []}
    cj = os.path.join(input_dir, "case.json")
    if os.path.isfile(cj):
        try:
            raw, enc = T.read_text(cj)
            info["case"] = json.loads(raw)
            info["case_json"] = cj
            info["case_encoding"] = enc
        except Exception as exc:  # noqa: BLE001
            info["notes"].append("case.json unreadable: %s" % exc)
    else:
        for name in ("case.json", "case.yaml", "case.yml"):
            p = os.path.join(input_dir, name)
            if os.path.isfile(p):
                info["notes"].append("found %s; only JSON is parsed" % name)
    for name in ("task.md", "task.txt", "TASK.md", "instruction.md", "prompt.md"):
        p = os.path.join(input_dir, name)
        if os.path.isfile(p):
            info["task_files"].append(p)
    if info["task_files"]:
        info["task"] = T.read_text(info["task_files"][0])[0]
    if not info["task"]:
        for k in ("task", "instruction", "prompt", "question"):
            if isinstance(info["case"], dict) and info["case"].get(k):
                info["task"] = str(info["case"][k])
                info["notes"].append("task text taken from case.json:%s" % k)
                break
    return info


def find_project(input_dir, case):
    """Locate the LaTeX project: an explicit path in case.json, else the first tree with .tex."""
    candidates = []
    if isinstance(case, dict):
        for key in ("project", "project_dir", "source_dir", "tex_dir", "root", "path",
                    "manuscript", "manuscript_dir", "files"):
            val = case.get(key)
            if isinstance(val, str):
                p = val if os.path.isabs(val) else os.path.join(input_dir, val)
                candidates.append(p)
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str):
                        p = v if os.path.isabs(v) else os.path.join(input_dir, v)
                        candidates.append(p)
    candidates.append(input_dir)
    for p in candidates:
        if os.path.isfile(p) and p.lower().endswith((".tex", ".ltx")):
            return os.path.dirname(os.path.abspath(p)), "case.json points at a single .tex file"
        if os.path.isdir(p):
            proj = T.discover(p)
            if proj.tex_files():
                return proj.root, "directory contains .tex sources"
    # last resort: walk down one level
    for entry in sorted(os.listdir(input_dir)):
        p = os.path.join(input_dir, entry)
        if os.path.isdir(p):
            proj = T.discover(p)
            if proj.tex_files():
                return proj.root, "subdirectory %s contains .tex sources" % entry
    return None, "no .tex file found under %s" % input_dir


# --------------------------------------------------------------------------------------
# patch planning
# --------------------------------------------------------------------------------------

def preamble_insert_line(proj):
    """Line number after which a new \\usepackage belongs (after the last existing one)."""
    try:
        text = T.strip_comments(proj.text(proj.main))
    except OSError:
        return 2
    lines = text.split("\n")
    last_usepackage = None
    docclass = None
    begin_doc = None
    for idx, line in enumerate(lines, 1):
        if re.search(r"\\documentclass", line) and docclass is None:
            docclass = idx
        if re.search(r"\\usepackage|\\RequirePackage", line):
            last_usepackage = idx
        if re.search(r"\\begin\s*\{document\}", line) and begin_doc is None:
            begin_doc = idx
    if last_usepackage:
        return last_usepackage
    if docclass:
        return docclass
    return 1


def already_loaded(proj, package):
    for p in proj.packages:
        if p["name"] == package:
            return True
    return False


def plan_missing_package(proj, diag, package, engines):
    """Build a \\usepackage patch, but only after asking the TeX distribution whether it exists."""
    if not package:
        return None, "no package could be attributed to this error"
    if already_loaded(proj, package):
        return None, "%s is already loaded, so loading it again would not help" % package
    kq = {"checked": False, "found": None}
    if engines and engines.get("kpsewhich", {}).get("available"):
        kq = T.kpsewhich(package + ".sty")
    line = preamble_insert_line(proj)
    patch = T.Patch(
        rule="R-ADD-PACKAGE", file=proj.main, op="insert_after", line=line,
        old=None, new="\\usepackage{%s}" % package,
        reason="%s is required by %s and is not loaded" % (package, diag.rule),
        diag_id=diag.id, confidence="high" if kq.get("found") else "medium",
        risk="low")
    if kq.get("checked") and not kq.get("found"):
        return None, ("%s.sty is not installed in this TeX distribution (kpsewhich found nothing). "
                      "Adding \\usepackage would fail again; the environment needs "
                      "`tlmgr install %s`." % (package, package))
    return patch, "ok"


def plan_brace_repair(proj, diag, tree_dir):
    """Turn 'File ended while scanning' into the brace that is actually missing."""
    rel = diag.file or proj.main
    path = os.path.join(tree_dir, rel.replace("/", os.sep))
    if not os.path.isfile(path):
        return None, "cannot locate %s in the working tree" % rel
    text, _ = T.read_text(path)
    depth, unclosed = T.brace_balance(text)
    if depth > 0 and unclosed:
        line, _off, snippet = unclosed[0]
        lines = text.split("\n")
        target = lines[line - 1] if line - 1 < len(lines) else ""
        new = target.rstrip() + "}"
        return T.Patch(
            rule="R-CLOSE-BRACE", file=rel, op="replace_line", line=line,
            old=target, new=new,
            reason="the first brace that is never closed in this file opens on line %d; TeX only "
                   "reports the symptom at end of file" % line,
            diag_id=diag.id, confidence="high", risk="medium"), "ok"
    if depth < 0:
        extra = brace_extra_closes(text)
        if extra:
            line = extra[0]
            lines = text.split("\n")
            target = lines[line - 1]
            idx = _last_unescaped_close(target)
            if idx >= 0:
                new = target[:idx] + target[idx + 1:]
                return T.Patch(
                    rule="R-REMOVE-EXTRA-BRACE", file=rel, op="replace_line", line=line,
                    old=target, new=new,
                    reason="this '}' closes a group that was never opened",
                    diag_id=diag.id, confidence="medium", risk="medium"), "ok"
    return None, "no unbalanced brace found in %s, so the cause is elsewhere" % rel


def brace_extra_closes(text):
    """Lines on which a '}' had no opening brace."""
    src = T.strip_comments(T.mask_verbatim(text))
    stack = 0
    line = 1
    out = []
    i = 0
    while i < len(src):
        ch = src[i]
        if ch == "\n":
            line += 1
        elif ch == "\\":
            i += 2
            continue
        elif ch == "{":
            stack += 1
        elif ch == "}":
            if stack:
                stack -= 1
            else:
                out.append(line)
        i += 1
    return out


def _last_unescaped_close(line):
    idx = -1
    i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == "}":
            idx = i
        i += 1
    return idx


MATHISH_RE = re.compile(
    r"(?:[A-Za-z0-9\}\]]\s*[_^]\s*(?:\{[^{}]*\}|[A-Za-z0-9]))|"
    r"(?:\\[A-Za-z]+\s*)")


def plan_math_shift(proj, diag, tree_dir):
    """Wrap the math-looking run on the reported line in $...$ (only if the line has no $)."""
    rel = diag.file or proj.main
    path = os.path.join(tree_dir, rel.replace("/", os.sep))
    if not os.path.isfile(path) or not diag.line:
        return None, "no line to repair"
    text, _ = T.read_text(path)
    lines = text.split("\n")
    if diag.line - 1 >= len(lines):
        return None, "line out of range"
    target = lines[diag.line - 1]
    if "$" in T.strip_comments(target):
        return None, "the line already has math delimiters; the imbalance is elsewhere"
    stripped = T.strip_comments(target)
    m = MATHISH_RE.search(stripped)
    if not m:
        return None, "no math-only token found on the reported line"
    start, end = m.start(), m.end()
    while start > 0 and stripped[start - 1] not in " \t({\n":
        start -= 1
    new = target[:start] + "$" + target[start:end] + "$" + target[end:]
    if new == target:
        return None, "no change"
    return T.Patch(rule="R-WRAP-MATH", file=rel, op="replace_line", line=diag.line,
                   old=target, new=new,
                   reason="math-only material on this line is outside math mode",
                   diag_id=diag.id, confidence="low", risk="medium"), "ok"


def plan_alignment_tab(proj, diag, tree_dir):
    """Escape a stray '&' when the reported line is not inside a tabular."""
    rel = diag.file or proj.main
    path = os.path.join(tree_dir, rel.replace("/", os.sep))
    if not os.path.isfile(path) or not diag.line:
        return None, "no line to repair"
    text, _ = T.read_text(path)
    lines = text.split("\n")
    if diag.line - 1 >= len(lines):
        return None, "line out of range"
    target = lines[diag.line - 1]
    if "tabular" in target or "align" in target:
        return None, "the '&' may be a legitimate alignment tab; hand this to a human"
    m = re.search(r"(?<!\\)&", target)
    if not m:
        return None, "no unescaped '&' on the reported line"
    new = target[:m.start()] + "\\&" + target[m.start() + 1:]
    return T.Patch(rule="R-ESCAPE-AMP", file=rel, op="replace_line", line=diag.line,
                   old=target, new=new,
                   reason="'&' outside a table is an alignment tab to TeX; the literal character "
                          "needs \\&",
                   diag_id=diag.id, confidence="medium", risk="low"), "ok"


def plan_label_after_caption(proj, finding, tree_dir):
    """Move a \\label that sits before its \\caption to after it."""
    rel = finding.get("file")
    path = os.path.join(tree_dir, (rel or "").replace("/", os.sep))
    if not rel or not os.path.isfile(path):
        return None, "file not found"
    text, _ = T.read_text(path)
    m = re.search(r"\\begin\s*\{(figure|table)\*?\}", text)
    while m:
        end = text.find("\\end{%s" % m.group(1), m.end())
        body = text[m.end():end if end != -1 else len(text)]
        cap = C.CAPTION_RE.search(body)
        lab = C.LABEL_RE.search(body)
        if cap and lab and lab.start() < cap.start():
            # find the caption's closing brace
            j = cap.end()
            depth = 1
            while j < len(body) and depth:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                j += 1
            lab_text = lab.group(0)
            new_body = body[:lab.start()] + body[lab.end():]
            shift = len(lab_text)
            insert_at = j - shift
            new_body = new_body[:insert_at] + "\n  " + lab_text + new_body[insert_at:]
            new_text = text[:m.end()] + new_body + text[(end if end != -1 else len(text)):]
            lines_before = text.split("\n")
            lines_after = new_text.split("\n")
            return T.Patch(
                rule="R-LABEL-AFTER-CAPTION", file=rel, op="rewrite_file",
                old=text, new=new_text,
                reason="a \\label before \\caption captures the section counter, so every "
                       "\\ref to the float prints the wrong number",
                diag_id=None, confidence="high", risk="low"), "ok"
        m = re.search(r"\\begin\s*\{(figure|table)\*?\}", text, m.end())
    return None, "no float with label-before-caption was located"


def plan_repairs(proj, diags, findings, tree_dir, engines, allow_class_fallback=False):
    """Ordered (patch, note) candidates for the current diagnostic set."""
    plans = []
    live = [d for d in diags if d.cascade_parent is None]
    live.sort(key=lambda d: (d.fix_order if d.fix_order is not None else 99))
    for d in live:
        if d.rule in ("E-MISSING-PKG", "E-UNDEFINED-CS", "E-ENV-UNDEFINED"):
            rc = d.root_cause or {}
            pkg = rc.get("package")
            patch, why = plan_missing_package(proj, d, pkg, engines)
            if patch:
                plans.append((patch, "add \\usepackage{%s} for %s" % (pkg, d.id)))
            else:
                plans.append((None, "UNRESOLVED %s: %s" % (d.id, why)))
        elif d.rule in ("E-FILE-ENDED-SCANNING", "E-EXTRA-CLOSE-BRACE",
                        "E-RUNAWAY-ARGUMENT"):
            patch, why = plan_brace_repair(proj, d, tree_dir)
            if patch:
                plans.append((patch, "%s: %s" % (patch.rule, d.id)))
            else:
                plans.append((None, "UNRESOLVED %s: %s" % (d.id, why)))
        elif d.rule == "E-MATH-MODE":
            patch, why = plan_math_shift(proj, d, tree_dir)
            if patch:
                plans.append((patch, "wrap math on line %s" % patch.line))
            else:
                plans.append((None, "UNRESOLVED %s: %s" % (d.id, why)))
        elif d.rule == "E-ALIGNMENT-TAB":
            patch, why = plan_alignment_tab(proj, d, tree_dir)
            if patch:
                plans.append((patch, "escape & on line %s" % patch.line))
            else:
                plans.append((None, "UNRESOLVED %s: %s" % (d.id, why)))
        elif d.rule == "E-BIB-MISSING":
            plans.append((None, "BUILD-PLAN %s: the bibliography backend has to run before the "
                                "next engine pass" % d.id))
        elif d.rule == "E-FONT-NOT-FOUND":
            plans.append((None, "UNRESOLVED %s: font is not installed in this image; this is an "
                                "environment gap, not a source defect" % d.id))
        elif d.rule == "E-MISSING-CLASS":
            plans.append((None, "UNRESOLVED %s: the class file is missing from the image and from "
                                "the project; substituting a standard class would change the "
                                "template, so this needs a human decision" % d.id))
        elif d.rule == "E-CAPACITY":
            plans.append((None, "UNRESOLVED %s: resource exhaustion usually means macro recursion; "
                                "the reported line is not the cause" % d.id))
    for f in findings:
        if f.get("auto_fixable") and f.get("rule") == "X-LABEL-BEFORE-CAPTION":
            patch, why = plan_label_after_caption(proj, f, tree_dir)
            if patch:
                plans.append((patch, "move \\label after \\caption in %s" % f.get("file")))
    return plans


# --------------------------------------------------------------------------------------
# build driver
# --------------------------------------------------------------------------------------

def diag_fingerprint(diags, stats):
    """A comparable score for 'is this state better than that one'."""
    live = [d for d in diags if d.cascade_parent is None]
    fatal = len([d for d in live if d.severity in ("error", "fatal", "capacity",
                                                   "missing-file", "font", "bib")])
    warnings = len([d for d in live if d.severity in ("warning", "overfull")])
    return (-fatal, -warnings, -len([d for d in live if d.severity == "error"]),
            1 if stats.get("pages") else 0)


class Builder(object):
    """Runs the compiler, with the pass plan, the time budget and full logging."""

    def __init__(self, proj, tree_dir, engine, backend, engines, log_dir, budget_s):
        self.proj = proj
        self.tree = tree_dir
        self.engine = engine
        self.backend = backend
        self.engines = engines
        self.log_dir = log_dir
        self.budget = budget_s
        self.spent = 0.0
        self.runs = []
        os.makedirs(log_dir, exist_ok=True)

    def available(self):
        if self.engine == "latexmk":
            return self.engines.get("latexmk", {}).get("available", False)
        return self.engines.get(self.engine, {}).get("available", False)

    def _run(self, cmd):
        res = T.run_command(cmd, self.tree, timeout=max(60, int(self.budget - self.spent)))
        self.spent += res.get("elapsed_s") or 0
        self.runs.append(res)
        return res

    def clean_aux(self):
        job = os.path.splitext(os.path.basename(self.proj.main))[0]
        for ext in (".aux", ".bbl", ".blg", ".out", ".toc", ".lof", ".lot", ".log",
                    ".fls", ".fdb_latexmk", ".nav", ".snm", ".bcf", ".run.xml"):
            p = os.path.join(self.tree, job + ext)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def compile_once(self, label):
        """One engine pass. Returns parsed transcript text."""
        if self.engine == "latexmk":
            cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-file-line-error",
                   "-halt-on-error", "-g", self.proj.main]
            if self.backend == "biber":
                cmd.insert(1, "-use-biber")
        else:
            flags = T.ENGINE_FLAGS.get(self.engine, ["-interaction=nonstopmode"])
            cmd = [self.engine] + list(flags) + [self.proj.main]
        res = self._run(cmd)
        transcript = res.get("output") or ""
        # the .log file carries the full picture; the console output is truncated
        job = os.path.splitext(os.path.basename(self.proj.main))[0]
        log_path = os.path.join(self.tree, job + ".log")
        if os.path.isfile(log_path):
            try:
                transcript = T.read_text(log_path)[0] + "\n" + transcript
            except OSError:
                pass
        fn = os.path.join(self.log_dir, "pass-%s.log" % label)
        T.write_text(fn, transcript)
        return {"transcript": transcript, "returncode": res.get("returncode"),
                "timed_out": res.get("timed_out"), "elapsed_s": res.get("elapsed_s"),
                "missing": res.get("missing"), "cmd": res.get("cmd")}

    def run_bib(self):
        job = os.path.splitext(os.path.basename(self.proj.main))[0]
        if self.backend == "biber":
            cmd = ["biber", job]
        elif self.backend == "bibtex":
            cmd = ["bibtex", job]
        else:
            return {"skipped": True, "reason": "no bibliography backend selected"}
        if cmd[0] not in self.engines or not self.engines.get(cmd[0], {}).get("available"):
            return {"skipped": True, "reason": "%s is not installed" % cmd[0]}
        res = self._run(cmd)
        out = res.get("output") or ""
        T.write_text(os.path.join(self.log_dir, "bib.log"), out)
        diags = T.parse_log(out, self.tree, source="bib") if cmd[0] == "bibtex" else []
        if cmd[0] == "biber":
            diags = _parse_biber_log(out)
        return {"cmd": " ".join(cmd), "returncode": res.get("returncode"),
                "output": out[:8000], "diags": diags, "elapsed_s": res.get("elapsed_s")}

    def build(self, plan, label_prefix="b"):
        """Execute the pass plan; stop early when the auxiliary state is stable."""
        report = {"passes": [], "bib": None, "stats": {}, "timed_out": False,
                  "engine_missing": False}
        if not self.available():
            report["engine_missing"] = True
            return report, "", []
        plan_steps = plan["steps"]
        last_transcript = ""
        all_diags = []
        for idx, step in enumerate(plan_steps):
            if self.spent > self.budget:
                report["timed_out"] = True
                break
            if step["tool"] in ("bibtex", "biber"):
                bres = self.run_bib()
                report["bib"] = bres
                all_diags.extend(bres.get("diags") or [])
                continue
            res = self.compile_once("%s%s" % (label_prefix, idx + 1))
            report["passes"].append({k: res[k] for k in ("returncode", "elapsed_s",
                                                         "timed_out", "cmd")})
            last_transcript = res["transcript"]
            diags = T.parse_log(res["transcript"], self.tree)
            stats = T.parse_log_stats(res["transcript"])
            report["stats"] = stats
            all_diags = diags + [d for d in all_diags if d.source == "bib"]
            # a fatal error means later passes cannot help
            if any(d.severity in ("fatal", "missing-file") for d in diags
                   if d.cascade_parent is None):
                break
        return report, last_transcript, all_diags


def _parse_biber_log(text):
    """Biber prefixes every line with a counter and the emitting module, e.g.
    `[44] Biber.pm:4609> WARN - ...`; the level and message are the only stable parts."""
    diags = []
    for line in text.split("\n"):
        s = line.strip()
        m = re.match(r"^(?:\[\d+\]\s+\S+>\s*)?(WARN|ERROR)\s+-\s+(.*)$", s)
        if not m:
            continue
        kind = "error" if m.group(1) == "ERROR" else "warning"
        d = T.Diag(kind, m.group(2), None, None, [s], source="biber")
        d.rule = "E-BIB-BIBER" if kind == "error" else "W-BIB-BIBER"
        diags.append(d)
    return diags


# --------------------------------------------------------------------------------------
# preview rendering
# --------------------------------------------------------------------------------------

PREVIEW_TOOLS = [
    ("pdftoppm", lambda src, dst: ["pdftoppm", "-png", "-r", "110", "-f", "1", "-l", "3",
                                   src, dst]),
    ("mutool", lambda src, dst: ["mutool", "draw", "-o", dst + "-%d.png", "-r", "110", src]),
    ("magick", lambda src, dst: ["magick", "-density", "110", src + "[0-2]", dst + "-%d.png"]),
    ("gs", lambda src, dst: ["gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r110",
                             "-sOutputFile=" + dst + "-%d.png", src]),
]


def render_previews(pdf_path, out_dir):
    """Render page images so a reviewer can look at the PDF without opening it."""
    if not os.path.isfile(pdf_path):
        return {"rendered": False, "reason": "no PDF produced"}
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, "page")
    for tool, make in PREVIEW_TOOLS:
        if not T._which(tool):
            continue
        res = T.run_command(make(pdf_path, stem), os.path.dirname(pdf_path) or ".", timeout=120)
        if res.get("returncode") == 0:
            files = sorted(f for f in os.listdir(out_dir) if f.lower().endswith(".png"))
            if files:
                return {"rendered": True, "tool": tool,
                        "files": [os.path.join(out_dir, f) for f in files]}
    return {"rendered": False,
            "reason": "no PDF rasteriser found (pdftoppm/mutool/magick/gs all absent)"}


# --------------------------------------------------------------------------------------
# result.json assembly
# --------------------------------------------------------------------------------------

CONTRACT_SYNONYMS = {
    "case_id": "case_id",
    "status": "status",
    "diagnostics": "diagnostics",
    "errors": "diagnostics",
    "compile": "build",
    "build": "build",
    "compilation": "build",
    "project": "project",
    "sources": "sources",
    "source_map": "sources",
    "evidence": "sources",
    "fixes": "fixes",
    "changes": "fixes",
    "change_log": "change_log",
    "patches": "fixes",
    "uncertainties": "uncertainties",
    "human_review": "human_review",
    "human_confirmation": "human_review",
    "reproducibility": "reproducibility",
    "repro": "reproducibility",
    "environment": "environment",
    "deliverables": "deliverables",
    "artifacts": "deliverables",
    "outputs": "deliverables",
    "checks": "static_checks",
    "static_checks": "static_checks",
    "lints": "static_checks",
    "tex": "project",
    "document": "project",
    "math": "static_checks",
    "tables": "static_checks",
    "citations": "static_checks",
    "references": "static_checks",
    "template": "static_checks",
    "integrity": "integrity",
    "contract": "contract",
}


def satisfy_contract(result, contract):
    """Make sure every declared output_contract field exists in result.json."""
    if not contract:
        return {"declared": [], "satisfied": {}, "missing": [], "note": "no output_contract declared"}
    if isinstance(contract, dict):
        fields = list(contract.keys())
    elif isinstance(contract, list):
        fields = [str(f) for f in contract]
    else:
        fields = [str(contract)]
    satisfied, missing = {}, []
    for field in fields:
        key = field.strip()
        if key in result:
            satisfied[key] = "native"
            continue
        target = CONTRACT_SYNONYMS.get(key.lower())
        if target and target in result:
            result[key] = result[target]
            satisfied[key] = "mapped_to:%s" % target
            continue
        # last resort: a stub that says exactly what is not covered
        result[key] = {"_contract_field": key,
                       "_status": "not_produced_by_this_skill",
                       "_note": "the declared output_contract field %r has no counterpart in this "
                                "LaTeX build case; the closest evidence is under "
                                "'diagnostics', 'build' and 'fixes'" % key}
        satisfied[key] = "stub_declared"
        missing.append(key)
    return {"declared": fields, "satisfied": satisfied, "missing": missing}


def findings_to_diags(findings, structural):
    """Express static/structural findings as diagnostics so result.json is never empty.

    Each one keeps its rule id and file:line, and is marked `source: static` so a reader can
    tell apart "a compiler said this" from "the source structure says this".
    """
    diags = []
    for f in structural:
        d = T.Diag("error", f.get("explanation") or f.get("rule"), f.get("file"),
                   (f.get("unclosed") or [{}])[0].get("line") if f.get("unclosed") else None,
                   [json.dumps(f, ensure_ascii=False)[:300]], source="static")
        d.rule = f.get("rule")
        d.root_cause = {"category": f.get("kind", "structure"),
                        "explanation": f.get("explanation", ""),
                        "confidence": "high", "evidence": [f.get("rule")]}
        diags.append(d)
    for f in findings:
        if f.get("severity") not in ("error", "warning"):
            continue
        d = T.Diag(f.get("severity"), f.get("explanation", f.get("rule")), f.get("file"),
                   f.get("line"), [json.dumps(f, ensure_ascii=False)[:300]], source="static")
        d.rule = f.get("rule")
        d.root_cause = {"category": f.get("kind", "static"),
                        "explanation": f.get("explanation", ""),
                        "confidence": "high" if f.get("severity") == "error" else "medium",
                        "evidence": [f.get("rule")]}
        if f.get("suggestion"):
            d.suggestion = f["suggestion"]
        diags.append(d)
    return T.annotate(diags)


def build_sources(proj, diags, findings, patches, build_report):
    """Every number and claim in result.json points at the file:line or log line behind it."""
    sources = []
    for d in diags:
        if d.cascade_parent is not None:
            continue
        sources.append({
            "claim": "%s at %s" % (d.rule, d.message[:110]),
            "evidence": "compiler log",
            "file": d.file, "line": d.line, "rule": d.rule, "severity": d.severity,
            "raw": (d.raw or [""])[0][:160],
        })
    for f in findings[:80]:
        sources.append({
            "claim": f.get("explanation", f.get("rule", ""))[:160],
            "evidence": "static check",
            "file": f.get("file"), "line": f.get("line"), "rule": f.get("rule"),
            "severity": f.get("severity"),
        })
    for p in patches:
        sources.append({
            "claim": "patched %s line %s: %s" % (p["file"], p["line"], p["reason"][:100]),
            "evidence": "source diff",
            "file": p["file"], "line": p["line"], "rule": p["rule"],
            "before": (p.get("old") or "")[:160], "after": (p.get("new") or "")[:160],
            "verified": p.get("verified"),
        })
    if build_report.get("passes"):
        sources.append({
            "claim": "%d engine pass(es) executed" % len(build_report["passes"]),
            "evidence": "build transcripts under build/",
            "file": None, "line": None, "rule": "BUILD", "severity": "info",
        })
    return sources


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="LaTeX build doctor")
    ap.add_argument("--input", default="/input", help="Harbor input directory")
    ap.add_argument("--out", default="/app/output", help="output directory")
    ap.add_argument("--work", default="/app/work", help="scratch directory")
    ap.add_argument("--project", default=None, help="override the LaTeX project root")
    ap.add_argument("--engine", default="auto",
                    help="auto|pdflatex|xelatex|lualatex|latexmk")
    ap.add_argument("--max-iter", type=int, default=4, help="repair iterations (default 4)")
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET_S,
                    help="wall-clock budget for all compiler passes, seconds")
    ap.add_argument("--no-build", action="store_true", help="static analysis only")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    log = [] if not args.quiet else []

    def say(msg):
        log.append(msg)
        if not args.quiet:
            sys.stderr.write(msg + "\n")

    # ---- resolve the fallback paths used outside Harbor ------------------------------
    if not os.path.isdir(args.input):
        for alt in ("input", os.path.join(os.path.dirname(args.out), "input")):
            if os.path.isdir(alt):
                args.input = alt
                break
    if args.out.startswith("/app/") and not os.path.isdir("/app"):
        args.out = os.path.abspath("output")
    if args.work.startswith("/app/") and not os.path.isdir("/app"):
        args.work = os.path.abspath("work")

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)

    inputs = load_case(args.input)
    case = inputs["case"] if isinstance(inputs["case"], dict) else {}
    case_id = T.guess_case_id(args.input, case)
    contract = case.get("output_contract")
    say("case_id=%s  output_contract=%s" % (case_id, contract))

    # ---- project discovery -----------------------------------------------------------
    root, why = (args.project, "explicit --project") if args.project else find_project(
        args.input, case)
    if not root:
        result = {
            "case_id": case_id, "status": "failed", "generated_at": T.now_iso(),
            "status_reason": "No LaTeX source was found under %s, so there was nothing to "
                             "diagnose or build." % args.input,
            "skill": {"name": SKILL_NAME, "version": SKILL_VERSION},
            "inputs": {"input_dir": args.input, "notes": inputs["notes"],
                       "files": sorted(os.listdir(args.input))
                       if os.path.isdir(args.input) else []},
        }
        result["contract"] = satisfy_contract(result, contract)
        T.write_json(os.path.join(args.out, "result.json"), result)
        say("FAILED: no LaTeX sources")
        return 2

    proj = T.discover(root)
    say("project root=%s main=%s files=%d" % (root, proj.main, len(proj.files)))
    if not proj.main:
        result = {
            "case_id": case_id, "status": "failed", "generated_at": T.now_iso(),
            "status_reason": "Found .tex files under %s but none that can be an entry point." % root,
            "skill": {"name": SKILL_NAME, "version": SKILL_VERSION},
            "project": proj.to_dict(),
        }
        result["contract"] = satisfy_contract(result, contract)
        T.write_json(os.path.join(args.out, "result.json"), result)
        return 2

    # ---- snapshot the input, so every later claim can be checked against it ----------
    snap = os.path.join(args.work, "snapshots")
    T.copy_tree(root, snap)
    say("snapshot -> %s" % snap)

    tree = os.path.join(args.work, "tree")
    T.copy_tree(root, tree)

    # ---- environment ----------------------------------------------------------------
    engines = T.probe_engines()
    resources = T.read_resources_yaml(args.input)
    say("engines: %s" % ", ".join(c for c in T.ENGINE_COMMANDS if engines.get(c, {}).get("available"))
        or "engines: none installed")

    engine_pick = T.detect_engine(proj)
    if args.engine != "auto":
        engine_pick = {"engine": args.engine, "reason": "forced by --engine",
                       "evidence": [], "confidence": "high"}
    if engine_pick["engine"] in ("latexmk",) and not engines.get("latexmk", {}).get("available"):
        engine_pick["fallback"] = "latexmk missing, falling back to pdflatex"
        engine_pick["engine"] = "pdflatex"
    backend = T.detect_bib_backend(proj)
    say("engine=%s (%s)  bib=%s" % (engine_pick["engine"], engine_pick["reason"],
                                    backend["backend"]))

    # ---- static checks on the pristine input ----------------------------------------
    bibs = [T.parse_bib(proj.abs(b)) for b in proj.bib_files]
    static = C.run_static_checks(proj, bibs=bibs, engines=engines)
    structural = T.structural_audit(proj)
    say("static: %d findings (%d errors), %d structural"
        % (static["summary"]["total"], static["summary"]["errors"], len(structural)))

    # ---- build + repair loop ---------------------------------------------------------
    builder = Builder(proj, tree, engine_pick["engine"], backend["backend"], engines,
                      os.path.join(args.work, "build"), args.budget)
    plan = T.build_plan(proj, engine_pick["engine"], backend["backend"])
    iterations = []
    applied, rejected, unresolved = [], [], []
    final_diags, final_stats, final_report = [], {}, {}
    build_attempted = False

    if args.no_build or not engines.get("any_engine"):
        unresolved.append({
            "rule": "ENV-NO-ENGINE", "severity": "error",
            "detail": "No TeX engine is installed in this environment, so the compile loop "
                      "could not run. Everything below is static analysis on the sources; the "
                      "diagnostics are what a compiler would report, derived from the source "
                      "structure, not from a run.",
        })
        say("no engine: static-only mode")
        proj_after = T.discover(tree)
        structural_after = T.structural_audit(proj_after)
        # no transcript exists, so the diagnostics block is filled from the source structure
        final_diags = findings_to_diags(static["findings"], structural)
    else:
        build_attempted = True
        builder.clean_aux()
        best_key = None
        tried = set()
        for it in range(args.max_iter + 1):
            report, transcript, diags = builder.build(plan, label_prefix="i%d-" % it)
            final_report = report
            final_stats = report.get("stats") or {}
            diags = T.annotate(diags, proj)
            key = diag_fingerprint(diags, final_stats)
            iterations.append({
                "iteration": it,
                "passes": len(report.get("passes") or []),
                "stats": final_stats,
                "diag_summary": T.summarize(diags),
                "fingerprint": list(key),
                "bib": {k: report["bib"].get(k) for k in ("cmd", "returncode")}
                if report.get("bib") else None,
            })
            say("iteration %d: %s pages=%s errors=%d" % (
                it, key, final_stats.get("pages"), T.summarize(diags)["fatal_errors"]))
            final_diags = diags
            live = [d for d in diags if d.cascade_parent is None]
            fatal = [d for d in live if d.severity in ("error", "fatal", "capacity",
                                                       "missing-file", "font", "bib")]
            if not fatal:
                if best_key is None or key >= best_key:
                    best_key = key
                break
            if it >= args.max_iter or builder.spent > args.budget:
                break
            proj_work = T.discover(tree)
            plans = plan_repairs(proj_work, diags, static["findings"], tree, engines)
            # a patch that was already tried and rolled back must not be tried again
            usable = [p for p, note in plans
                      if p is None or (p.rule, p.file, p.line) not in tried]
            plans = [p for p in plans if p[0] is None or (p[0].rule, p[0].file, p[0].line)
                     not in tried]
            if not usable:
                unresolved.append({
                    "rule": "REPAIR-EXHAUSTED", "severity": "error",
                    "detail": "Every patch candidate for the remaining errors was already tried "
                              "and rolled back, so guessing further would only churn the source.",
                })
                break
            did_something = False
            for patch, note in plans:
                if patch is None:
                    unresolved.append({"rule": "NO-PATCH", "severity": "info", "detail": note})
                    continue
                tried.add((patch.rule, patch.file, patch.line))
                patch.id = "P%03d" % (len(applied) + len(rejected) + 1)
                if patch.op == "rewrite_file":
                    path = os.path.join(tree, patch.file.replace("/", os.sep))
                    T.write_text(path, patch.new)
                    ok, msg, before, after = True, "rewrote file", patch.old, patch.new
                else:
                    ok, msg, before, after = T.apply_patch_to_tree(tree, patch)
                if not ok:
                    rejected.append({"patch": patch.to_dict(), "why": msg})
                    say("  reject %s: %s" % (patch.id, msg))
                    continue
                did_something = True
                rep2, tr2, d2 = builder.build(plan, label_prefix="i%d-%s-" % (it, patch.id))
                d2 = T.annotate(d2, proj)
                key2 = diag_fingerprint(d2, rep2.get("stats") or {})
                improved = key2 > key
                entry = patch.to_dict()
                entry["verified"] = bool(improved)
                entry["fingerprint_after"] = list(key2)
                if improved:
                    applied.append(entry)
                    final_diags, final_stats, final_report = d2, rep2.get("stats") or {}, rep2
                    say("  keep %s (%s): %s -> %s" % (patch.id, patch.rule, key, key2))
                    break
                # rollback: a patch that does not reduce the diagnostic set is not a fix
                if patch.op == "rewrite_file":
                    path = os.path.join(tree, patch.file.replace("/", os.sep))
                    T.write_text(path, before)
                else:
                    rollback = T.Patch(patch.rule, patch.file, "replace_line", patch.line,
                                       after, before)
                    try:
                        T.apply_patch_to_tree(tree, rollback)
                    except Exception:  # noqa: BLE001
                        pass
                entry["verified"] = False
                rejected.append({"patch": entry, "why": "no improvement in the diagnostic set"})
                say("  rollback %s: %s (no improvement)" % (patch.id, patch.rule))
                break
            if not did_something:
                unresolved.append({
                    "rule": "REPAIR-STALLED", "severity": "error",
                    "detail": "No remaining patch could be planned for the live errors, so the "
                              "loop stopped honestly instead of guessing.",
                })
                break
        # ---- post-loop fidelity pass on the repaired tree ---------------------------
        proj_after = T.discover(tree)
        structural_after = T.structural_audit(proj_after)

    # ---- final static checks on whatever we are delivering ---------------------------
    after_bibs = [T.parse_bib(proj_after.abs(b)) for b in proj_after.bib_files]
    static_after = C.run_static_checks(proj_after, bibs=after_bibs, engines=engines)
    integrity = C.anti_cheat(proj, proj_after)

    # ---- assemble deliverables -------------------------------------------------------
    fixed_dir = os.path.join(args.out, "fixed")
    T.copy_tree(tree, fixed_dir)
    build_dir = os.path.join(args.out, "build")
    if os.path.isdir(os.path.join(args.work, "build")):
        T.copy_tree(os.path.join(args.work, "build"), build_dir)

    pdf_rel = None
    job = os.path.splitext(os.path.basename(proj.main))[0]
    for cand in (os.path.join(fixed_dir, job + ".pdf"),
                 os.path.join(tree, job + ".pdf"),
                 os.path.join(root, job + ".pdf")):
        if os.path.isfile(cand):
            dst = os.path.join(args.out, job + ".pdf")
            if os.path.abspath(cand) != os.path.abspath(dst):
                try:
                    shutil.copy2(cand, dst)
                except OSError:
                    continue
            pdf_rel = T.safe_rel(dst, args.out)
            break

    previews = render_previews(os.path.join(args.out, job + ".pdf"),
                               os.path.join(args.out, "preview")) if pdf_rel else \
        {"rendered": False, "reason": "no PDF"}
    say("preview: %s" % previews.get("rendered"))

    # ---- diffs and patches -----------------------------------------------------------
    added, modified, removed = [], [], []
    for rel in sorted(set(proj_after.files)):
        a = os.path.join(snap, rel.replace("/", os.sep))
        b = os.path.join(tree, rel.replace("/", os.sep))
        if not os.path.isfile(b):
            continue
        if not os.path.isfile(a):
            added.append(rel)
        elif T.sha256_file(a) != T.sha256_file(b):
            modified.append(rel)
    for rel in sorted(set(proj.files)):
        if not os.path.isfile(os.path.join(tree, rel.replace("/", os.sep))):
            removed.append(rel)

    diff_chunks = []
    for rel in modified:
        try:
            old = T.read_text(os.path.join(snap, rel.replace("/", os.sep)))[0]
            new = T.read_text(os.path.join(tree, rel.replace("/", os.sep)))[0]
        except OSError:
            continue
        d = T.unified_diff(old, new, "a/" + rel, "b/" + rel)
        if d:
            diff_chunks.append(d)
    fix_dir = os.path.join(args.out, "fixes")
    os.makedirs(fix_dir, exist_ok=True)
    T.write_text(os.path.join(fix_dir, "changes.diff"),
                 "\n".join(diff_chunks) if diff_chunks else
                 "# no source change was required\n")
    T.write_json(os.path.join(fix_dir, "patches.json"), {
        "applied": applied, "rejected": rejected, "unresolved": unresolved,
        "files_added": added, "files_modified": modified, "files_removed": removed,
    })

    # ---- reproducibility record ------------------------------------------------------
    versions = {
        "generated_by": "%s %s" % (SKILL_NAME, SKILL_VERSION),
        "generated_at": T.now_iso(),
        "engine_chosen": engine_pick,
        "bib_backend": backend,
        "tool_versions": {k: v for k, v in engines.items()
                          if isinstance(v, dict) and v.get("available")},
        "python": sys.version.split()[0],
    }
    if final_report.get("passes"):
        versions["pass_commands"] = [p.get("cmd") for p in final_report["passes"]]
        versions["pass_seconds"] = [p.get("elapsed_s") for p in final_report["passes"]]
    job = os.path.splitext(os.path.basename(proj.main))[0]
    vers_txt_path = os.path.join(args.work, "build", job + ".log")
    if os.path.isfile(vers_txt_path):
        try:
            lst = T.parse_listfiles(T.read_text(vers_txt_path)[0])
            if lst:
                versions["packages"] = lst
        except OSError:
            pass
    T.write_build_repro(os.path.join(args.out, "repro"), proj_after,
                        engine_pick["engine"], backend["backend"], versions)
    input_hashes = T.tree_hashes(root, exts=T.TEXT_EXTS | {".bib", ".bst", ".png", ".pdf",
                                                           ".jpg", ".eps"})
    pdf_hash = T.sha256_file(os.path.join(args.out, job + ".pdf")) \
        if pdf_rel else None

    # ---- static report artefacts -----------------------------------------------------
    T.write_json(os.path.join(args.out, "diagnostics.json"), {
        "case_id": case_id,
        "engine": engine_pick,
        "bib_backend": backend,
        "iterations": iterations,
        "final_stats": final_stats,
        "items": [d.to_dict() for d in final_diags],
        "summary": T.summarize(final_diags),
        "structural_before": structural,
        "structural_after": structural_after,
    })
    T.write_json(os.path.join(args.out, "static-checks.json"), {
        "before": static["summary"], "after": static_after["summary"],
        "closure_before": static["closure"], "closure_after": static_after["closure"],
        "findings_after": static_after["findings"],
        "overfull": C.analyse_overfull(final_diags),
    })

    # ---- status ----------------------------------------------------------------------
    live_final = [d for d in final_diags if d.cascade_parent is None]
    remaining_errors = [d for d in live_final
                        if d.severity in ("error", "fatal", "capacity", "missing-file",
                                          "font", "bib")]
    compiled = bool(final_stats.get("pages"))
    status = "success"
    reasons = []
    if not build_attempted:
        status = "partial"
        reasons.append("没有可用的 TeX 引擎，本次只做了静态诊断与结构审计，未实际编译。")
    elif not compiled:
        status = "partial"
        reasons.append("编译闭环未收敛到可用的 PDF（剩余 %d 条阻断性错误）。" % len(remaining_errors))
    if remaining_errors and compiled:
        status = "partial"
        reasons.append("仍有 %d 条错误级诊断未解决。" % len(remaining_errors))
    integrity_errors = [f for f in integrity if f.get("severity") == "error"]
    if integrity_errors:
        status = "partial"
        reasons.append("完整性检查发现 %d 处内容被删除/抑制，需人工确认。" % len(integrity_errors))
    if static_after["summary"]["errors"]:
        if status == "success":
            status = "partial"
        reasons.append("静态检查仍有 %d 条 error 级问题（多为无法自动修的引用/表格/字体问题）。"
                       % static_after["summary"]["errors"])
    if not reasons:
        reasons.append("编译通过，静态检查无 error 级问题，留档完整。")

    result = {
        "case_id": case_id,
        "status": status,
        "status_reason": " ".join(reasons),
        "generated_at": T.now_iso(),
        "skill": {"name": SKILL_NAME, "version": SKILL_VERSION,
                  "scope": "LaTeX 源码诊断—修复—编译验证—可复现构建留档"},
        "inputs": {
            "input_dir": args.input,
            "case_json": inputs["case_json"],
            "task_files": inputs["task_files"],
            "task_excerpt": (inputs["task"] or "")[:1500],
            "notes": inputs["notes"],
        },
        "project": proj.to_dict(),
        "environment": {
            "engines": {k: v for k, v in engines.items() if isinstance(v, dict)},
            "resources_yaml": {"present": resources["present"], "path": resources.get("path")},
            "python": sys.version.split()[0],
        },
        "build": {
            "attempted": build_attempted,
            "engine": engine_pick,
            "bib_backend": backend,
            "plan_steps": ["%s %s" % (s["tool"], " ".join(s["args"])) for s in plan["steps"]],
            "iterations": iterations,
            "final_stats": final_stats,
            "success": compiled,
            "pages": final_stats.get("pages"),
            "pdf": pdf_rel,
            "pdf_sha256": pdf_hash,
            "timed_out": final_report.get("timed_out"),
            "budget_seconds": args.budget,
            "spent_seconds": round(builder.spent, 1),
        },
        "diagnostics": {
            "summary": T.summarize(final_diags),
            "items": [d.to_dict() for d in final_diags],
            "structural": {"before": structural, "after": structural_after},
        },
        "static_checks": {
            "before": static["summary"], "after": static_after["summary"],
            "findings": static_after["findings"][:200],
            "closure_after": static_after["closure"],
        },
        "fixes": {
            "applied": applied,
            "rejected": rejected,
            "unresolved": unresolved,
            "files_modified": modified,
            "files_added": added,
            "files_removed": removed,
            "diff": T.safe_rel(os.path.join(fix_dir, "changes.diff"), args.out),
        },
        "integrity": {"findings": integrity,
                      "clean": not integrity_errors},
        "reproducibility": {
            "engine": engine_pick["engine"],
            "bib_backend": backend["backend"],
            "pass_commands": versions.get("pass_commands", []),
            "input_hashes": input_hashes,
            "pdf_sha256": pdf_hash,
            "repro_dir": T.safe_rel(os.path.join(args.out, "repro"), args.out),
            "note": "同版本引擎与宏包 + 同输入哈希 → 版面可复现；PDF 字节级哈希不保证相同"
                    "（时间戳与字体子集顺序会变）。",
        },
        "deliverables": {
            "fixed_sources": T.safe_rel(fixed_dir, args.out),
            "main_tex": T.safe_rel(os.path.join(fixed_dir, proj.main), args.out),
            "pdf": pdf_rel,
            "preview_png": [T.safe_rel(p, args.out) for p in previews.get("files", [])],
            "build_logs": T.safe_rel(build_dir, args.out),
            "diagnostics": "diagnostics.json",
            "static_checks": "static-checks.json",
            "patches": "fixes/patches.json",
            "diff": "fixes/changes.diff",
            "report": "report.md",
            "repro": T.safe_rel(os.path.join(args.out, "repro"), args.out),
        },
        "human_review": [
            {"item": f.get("rule"), "file": f.get("file"), "line": f.get("line"),
             "why": f.get("explanation")}
            for f in static_after["findings"] if f.get("severity") == "error"
        ][:40],
        "uncertainties": [], "change_log": [], "log": log[-80:],
    }
    result["sources"] = build_sources(proj_after, final_diags, static_after["findings"],
                                      applied, final_report)
    ts = T.summarize(final_diags)
    if ts["suppressed"]:
        result["uncertainties"].append(
            "日志里还有 %d 条级联错误被归并到根因，未单独修复：修掉第一条后它们通常会消失，"
            "若未消失会在下一轮迭代中出现。" % ts["suppressed"])
    if not engines.get("any_engine"):
        result["uncertainties"].append(
            "本机没有 TeX 引擎，编译结论未经实际运行验证；静态诊断基于源码结构与 TeX 日志语法。")
    if static_after["closure"]["citations_without_entry"]:
        result["uncertainties"].append(
            "有 %d 个 \\cite 键在任何 .bib 里都找不到：%s。这需要作者或文献库补齐，"
            "Skill 不会凭空生成条目。"
            % (len(static_after["closure"]["citations_without_entry"]),
               ", ".join(static_after["closure"]["citations_without_entry"][:6])))
    for u in unresolved[:20]:
        result["uncertainties"].append("%s: %s" % (u["rule"], u["detail"][:200]))
    result["change_log"] = [
        {"step": "snapshot", "what": "输入工程快照到 work/snapshots，用于逐条回溯"},
        {"step": "discover", "what": "识别主文件 %s（依据：%s）" % (proj.main, why)},
        {"step": "engine", "what": "选定引擎 %s：%s" % (engine_pick["engine"],
                                                       engine_pick["reason"])},
        {"step": "static", "what": "静态检查 %d 条，结构审计 %d 条"
                                   % (static["summary"]["total"], len(structural))},
        {"step": "build", "what": "编译 %d 轮，实际执行 %d 个 pass"
                                  % (len(iterations), sum(i["passes"] for i in iterations))},
        {"step": "repair", "what": "应用补丁 %d 条，回滚 %d 条，未解决 %d 条"
                                   % (len(applied), len(rejected), len(unresolved))},
        {"step": "integrity", "what": "完整性检查 %d 条（%s）"
                                     % (len(integrity),
                                        "通过" if not integrity_errors else "有阻断")},
        {"step": "output", "what": "写出 fixed/、fixes/、build/、repro/、diagnostics.json、"
                                   "static-checks.json、result.json"},
    ]
    result["contract"] = satisfy_contract(result, contract)
    T.write_json(os.path.join(args.out, "result.json"), result)
    write_report(os.path.join(args.out, "report.md"), result)

    say("status=%s  pages=%s  applied=%d rejected=%d"
        % (status, final_stats.get("pages"), len(applied), len(rejected)))
    return 0


def write_report(path, result):
    """A human reviewer should be able to judge the run from this file alone."""
    b = result["build"]
    d = result["diagnostics"]
    s = result["static_checks"]
    L = []
    L.append("# LaTeX 编译诊断与修复报告")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| case_id | `%s` |" % result["case_id"])
    L.append("| 状态 | **%s** |" % result["status"])
    L.append("| 主文件 | `%s` |" % (result["project"]["main"] or "-"))
    L.append("| 引擎 | `%s`（%s） |" % (b["engine"]["engine"], b["engine"]["reason"]))
    L.append("| 参考文献后端 | `%s` |" % b["bib_backend"]["backend"])
    L.append("| 是否编译成功 | %s |" % ("是" if b["success"] else "否"))
    L.append("| 页数 | %s |" % (b["pages"] if b["pages"] else "-"))
    L.append("| 编译轮次 | %d |" % len(b["iterations"]))
    L.append("| 补丁：应用 / 回滚 / 未解决 | %d / %d / %d |"
             % (len(result["fixes"]["applied"]), len(result["fixes"]["rejected"]),
                len(result["fixes"]["unresolved"])))
    L.append("")
    L.append("## 状态说明")
    L.append("")
    L.append(result["status_reason"])
    L.append("")
    L.append("## 诊断：修前 vs 修后")
    L.append("")
    after = d["summary"]
    L.append("| 指标 | 修前 | 修后 |")
    L.append("|---|---|---|")
    L.append("| 结构性问题（大括号/环境/数学定界） | %d | %d |"
             % (len(d["structural"]["before"]), len(d["structural"]["after"])))
    L.append("| 日志诊断条目 | - | %d |" % after["total"])
    L.append("| 其中级联（归并到根因） | - | %d |" % after["suppressed"])
    L.append("| 静态检查 error / warning | %d / %d | %d / %d |"
             % (s["before"]["errors"], s["before"]["warnings"],
                s["after"]["errors"], s["after"]["warnings"]))
    L.append("")
    L.append("### 结构性问题（不需要编译器就能看到）")
    L.append("")
    if not d["structural"]["before"]:
        L.append("无。")
    for f in d["structural"]["before"]:
        loc = "`%s`" % f.get("file", "-")
        if f.get("unclosed"):
            first = f["unclosed"][0]
            loc += " 第 %s 行起" % first.get("line", "?")
        L.append("- **%s** %s — %s" % (f["rule"], loc, f.get("explanation", "")))
        for u in (f.get("unclosed") or [])[:3]:
            L.append("  - 未闭合：第 %s 行 `%s`" % (u.get("line"), (u.get("snippet") or "")[:80]))
    L.append("")
    L.append("### 日志诊断（按修复顺序）")
    L.append("")
    live = [x for x in d["items"] if x.get("cascade_parent") is None]
    if not b["attempted"]:
        L.append("本次未编译（环境无 TeX 引擎），诊断由源码结构推导，见下表与「静态检查明细」。")
    elif not live:
        L.append("编译无诊断。")
    for x in live[:20] if b["attempted"] else []:
        rc = x.get("root_cause") or {}
        L.append("- **%s** `%s:%s` — %s" % (x.get("rule"), x.get("file") or "-",
                                            x.get("line") or "-", x.get("message", "")[:160]))
        if rc.get("explanation"):
            L.append("  - 根因（%s）：%s" % (rc.get("confidence"), rc["explanation"]))
    L.append("")
    L.append("## 补丁（每条都经重新编译验证）")
    L.append("")
    if not result["fixes"]["applied"]:
        L.append("无。")
    for p in result["fixes"]["applied"]:
        L.append("- `%s` **%s** `%s:%s` — %s" % (p.get("id"), p.get("rule"), p.get("file"),
                                                 p.get("line"), p.get("reason")))
        if p.get("new"):
            L.append("  - 改为：`%s`" % p["new"][:160].replace("\n", "\\n"))
    if result["fixes"]["rejected"]:
        L.append("")
        L.append("被回滚的补丁（试过但没让诊断集变好，已还原）：")
        for r in result["fixes"]["rejected"]:
            p = r.get("patch", {})
            L.append("- `%s` %s — %s" % (p.get("rule"), r.get("why"), p.get("file")))
    L.append("")
    L.append("## 完整性（防止“用删除换编译通过”）")
    L.append("")
    if result["integrity"]["clean"]:
        L.append("通过：没有 \\cite/\\ref/\\label/公式/图表被删除，也没有引入 \\sloppy、"
                 "\\iffalse 这类掩盖手段。")
    for f in result["integrity"]["findings"]:
        L.append("- **%s** %s" % (f.get("rule"), f.get("explanation")))
    L.append("")
    L.append("## 静态检查明细（不依赖编译器）")
    L.append("")
    detail = [f for f in result["static_checks"]["findings"]
              if f.get("severity") in ("error", "warning")]
    if not detail:
        L.append("无 error / warning 级问题。")
    else:
        L.append("| 规则 | 级别 | 位置 | 说明 |")
        L.append("|---|---|---|---|")
        for f in detail[:24]:
            loc = "`%s:%s`" % (f.get("file") or "-", f.get("line") or "-")
            desc = (f.get("explanation") or "").replace("|", "/")[:150]
            L.append("| `%s` | %s | %s | %s |" % (f.get("rule"), f.get("severity"), loc, desc))
        if len(detail) > 24:
            L.append("| … | | | 另有 %d 条见 `static-checks.json` |" % (len(detail) - 24))
    L.append("")
    over = result["static_checks"].get("overfull") or []
    if over:
        L.append("### 溢出盒子（Overfull \\hbox，按严重度排序）")
        L.append("")
        for o in over[:10]:
            L.append("- `%s:%s` %.1fpt (%s) — %s" % (o.get("file"), o.get("line"),
                                                     o.get("amount_pt"), o.get("kind"),
                                                     o.get("suggestion")))
        L.append("")
    L.append("## 还需要人确认的（Skill 不猜）")
    L.append("")
    if not result["human_review"]:
        L.append("无。")
    for h in result["human_review"][:20]:
        L.append("- **%s** `%s:%s` — %s" % (h.get("item"), h.get("file") or "-",
                                            h.get("line") or "-", h.get("why")))
    L.append("")
    L.append("## 不确定与限制")
    L.append("")
    if not result["uncertainties"]:
        L.append("无。")
    for u in result["uncertainties"]:
        L.append("- %s" % u)
    L.append("")
    L.append("## 怎么复现这份产物")
    L.append("")
    L.append("```bash")
    L.append("cd %s" % result["deliverables"]["fixed_sources"])
    L.append("bash ../%s/build.sh" % result["deliverables"]["repro"])
    L.append("```")
    L.append("")
    L.append("引擎、宏包版本与每个输入文件的 sha256 记在 `%s/versions.txt`。"
             % result["deliverables"]["repro"])
    T.write_text(path, "\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
