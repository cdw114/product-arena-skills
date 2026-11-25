#!/usr/bin/env python3
"""
papertrans.protect — Mask verbatim-critical spans with opaque placeholders.

Masked categories (each placeholder is opaque so the translator cannot "translate" it):
  NUM   numbers with units / percent / ranges / signed values          e.g. 3.5 mg, −20 °C, 15–20%, p < 0.05
  CITE  bracket citations and author-year                                 e.g. [12], [3–5], (Smith et al., 2020)
  REF   cross-references to figures/tables/equations/sections             e.g. Fig. 3, Table 2, Eq. (4), §2.1
  MATH  inline math / symbols / subscripts                                e.g. x_i, T_c, 10^-3, a ∝ b
  TERM  glossary-locked terms (exact match, case-sensitive, longest-first) e.g. "graph neural network"

Placeholder format: ⟦K#0001⟧  — the translator is told to copy these tokens verbatim.
`restore()` puts the original span back after translation and records every placeholder used.

Public API:
  protect_text(text, glossary) -> (masked_text, marks)
  restore(masked_translation, marks) -> (restored_text, report)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

PLACEHOLDER_RE = re.compile(r"⟦([A-Z]+)#(\d{4})⟧")
PLACEHOLDER_TMPL = "⟦{kind}#{idx:04d}⟧"

# ---------------------------------------------------------------------------------------------
# Patterns (ordered; first match wins for a given span)
# ---------------------------------------------------------------------------------------------
UNIT = (r"(?:mg|g|kg|μg|µg|ng|pg|mol|mmol|μmol|km|m|cm|mm|μm|µm|nm|pm|L|mL|μL|µL|"
        r"s|ms|μs|ns|min|h|hr|hrs|day|days|week|weeks|year|years|kDa|Da|eV|keV|MeV|GeV|J|kJ|MJ|"
        r"W|mW|kW|kWh|Wh|V|mV|kV|mA|A|Ω|Hz|kHz|MHz|GHz|THz|Pa|kPa|MPa|GPa|bar|atm|T|mT|K|°C|°F|N|"
        r"rad|ppm|ppb|M|mM|μM|%|‰|bit|kb|MB|GB|TB|px|dpi|fps)")
_ONE_UNIT = UNIT + r"(?:\s*[−\-]\s*\d+)?\b(?![A-Za-z])"
# unit (+ optional 2nd unit: mg L−1), compound units mg/kg, per-unit mL/h
_UNIT_TAIL = (
    r"(?:\s?(?:" + _ONE_UNIT + r"(?:\s+" + _ONE_UNIT + r")?"
    r"|(?:mg|g|mL|L|mmol)\s*/\s*(?:kg|L|mL|d|day|h)\b"
    r"|\d+\s*/\s*(?:mL|L|kg|g|h)\b)"
    r"|(?<=[0-9])(?:mg|kg|ng|μg|µg|mL|kDa|°C|min|hrs|ppm)\b)?"   # glued units: 5mg
)
_NUM_CORE = (
    r"(?:"
    r"\d+(?:\.\d+)?\s*[×x]\s*10\s*(?:[−\-]?\s*\{?\d+\}?|\^\{?[−\-]?\d+\}?)"  # 1.0 × 10−3 / 10^{−3}
    r"|[−\-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|[−\-+]?\d+(?:\.\d+)?(?:[eE][−\-+]?\d+)?"
    r")"
)
NUM_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9.\-−])" + _NUM_CORE +
    r"(?:\s*(?:[–\-~±]\s*[−\-+]?\d+(?:\.\d+)?))?" +     # ranges / ±
    _UNIT_TAIL +
    r"|(?:pH|pKa)\s*[=:]?\s*\d+(?:\.\d+)?",             # pH 7.4
    re.I)

PCT_RE = re.compile(r"(?<![A-Za-z0-9.])[−\-+]?\d+(?:\.\d+)?(?:\s*[–\-~]\s*[−\-+]?\d+(?:\.\d+)?)?\s*[%‰]")
STAT_RE = re.compile(r"(?<![A-Za-z0-9])(?:[prR]|df|t|F|χ²|χ2|z|OR|HR|RR|CI|SE|SD)\s*(?:=|<|>|≤|≥)\s*[−\-+]?\d*\.?\d+(?:[eE][−\-+]?\d+)?")
CITE_BRACKET_RE = re.compile(r"\[\d+(?:\s*[,;–\-]\s*\d+)*[a-z]?\](?:\s*[;,]\s*\[\d+(?:\s*[–\-]\s*\d+)*[a-z]?\])*")
CITE_AUTHOR_YEAR_RE = re.compile(
    r"\(\s*[A-Z][^()]{1,80}?\d{4}[a-z]?(?:\s*[;,]\s*[A-Z]?[^()]{0,80}?\d{4}[a-z]?)*\s*\)")
CITE_NUM_SUP_RE = re.compile(r"(?<![A-Za-z0-9\]])\^\s*\{\s*\d+(?:\s*[,–-]\s*\d+)*\s*\}")
XREF_RE = re.compile(
    r"\b(?:(?:Fig(?:ure)?s?|Tables?|Eqs?\.?|Equations?|Sections?|Sec\.|Supplementary|Scheme|Algorithms?|Alg\.|Appendix|App\.|Chapters?|Chap\.|Refs?\.|Eqns?\.|Extended\s+Data|SI\s+Fig|SI\s+Table|SI\s+Note|SI\s+Section|Dataset|Data\s+Availability)\s*\.?\s*"
    r"(?:S?\d+(?:\.\d+)*(?:\s*[–\-]\s*\d+)?[a-zA-Z]?(?:\s*[–\-–]\s*[A-Z])?(?:\s*,\s*[a-z](?![A-Za-z]))*"
    r"|\(\s*\d+(?:\.\d+)*\s*\)(?:\s*[–\-]\s*\(\s*\d+\s*\))?"
    r"|[IVX]+)"
    r"(?:\s*(?:[–\-–]|and|to|,)\s*(?:S?\d+(?:\.\d+)*[a-zA-Z]?|\(\s*\d+\s*\)))*"
    r"|(?:§|§§)\s*\d+(?:\.\d+)+(?:\s*(?:[–\-–]|and|to)\s*\d+(?:\.\d+)*)*)",
    re.I)
MATH_SYM = "∫≈≤≥≠±×÷∂∇∞√∝∈ℝℕℤ⇌∑∏→←↔⋅∘≅≡≪≫∼~αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ"
MATH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?:"
    r"[A-Za-z](?:_[A-Za-z0-9]+|_\{[A-Za-z0-9,]+\}|\^\{?[-−]?\d+\}?)+"        # x_i, T_c, 10^{-3}
    r"|[A-Za-z]\s*[=±<>≤≥≈∝∼]\s*[A-Za-z\d(]"                                   # x = 3
    r"|[∑∏∫√∂∇∞±]\s*[\w{(]*"
    r"|[≤≥≠∝≅≡≪≫∼→←↔⇌]"
    r")")
MATH_SYM_RE = re.compile("[" + re.escape(MATH_SYM) + "]")


@dataclass
class Mark:
    idx: int
    kind: str
    original: str
    start: int
    end: int
    surface: str = ""
    term_id: str = ""
    canonical: str = ""


@dataclass
class ProtectResult:
    masked: str
    marks: list[Mark] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------
def term_pattern(term: str) -> str:
    """Regex source (no flags) matching `term` case-insensitively, singular or plural, with -/space variants."""
    toks = re.split(r"[\s\-]+", term.strip())
    if not toks or not toks[0]:
        return re.escape(term)
    toks[-1] = re.sub(r"(?<=.{3})s$", "", toks[-1])
    parts = [re.escape(toks[0])] + [r"[\s\-]+" + re.escape(t) for t in toks[1:]]
    return "".join(parts) + ("s?" if toks[-1][-1].isalpha() else "")


def _find_spans(text: str, glossary_terms: list[tuple[str, str]]) -> list[Mark]:
    spans: list[tuple[int, int, str, str, str, str]] = []  # (s, e, kind, original, term_id, canonical)
    # TERM first (longest first), since terms must not be partially masked by NUM etc.
    for term, tid in sorted(glossary_terms, key=lambda x: -len(x[0])):
        if not term or len(term) < 2 or not re.search(r"[A-Za-z]", term):
            continue
        # case-insensitive; optional plural 's' on the last word; hyphen/space variants between words
        words = term_pattern(term)
        for m in re.finditer(r"(?<![A-Za-z])" + r"(?:" + words + r")" + r"(?![A-Za-z])", text, re.I):
            spans.append((m.start(), m.end(), "TERM", m.group(0), tid, term))
    for m in CITE_BRACKET_RE.finditer(text):
        spans.append((m.start(), m.end(), "CITE", m.group(0), "", ""))
    for m in CITE_AUTHOR_YEAR_RE.finditer(text):
        spans.append((m.start(), m.end(), "CITE", m.group(0), "", ""))
    for m in CITE_NUM_SUP_RE.finditer(text):
        spans.append((m.start(), m.end(), "CITE", m.group(0), "", ""))
    for m in XREF_RE.finditer(text):
        spans.append((m.start(), m.end(), "REF", m.group(0), "", ""))
    for m in STAT_RE.finditer(text):
        spans.append((m.start(), m.end(), "MATH", m.group(0), "", ""))
    for m in NUM_UNIT_RE.finditer(text):
        s = m.group(0)
        if not re.search(r"\d", s):
            continue
        # bare small integers (no unit / decimal / range / percent) are left in the text so that
        # translations like "two encoders" / "三组" stay natural; the verifier still checks digit multisets.
        if re.fullmatch(r"[−\-+]?\d{1,4}", s.strip()) and not re.match(r"^(?:19|20)\d{2}$", s.strip()):
            continue
        spans.append((m.start(), m.end(), "NUM", s, "", ""))
    for m in PCT_RE.finditer(text):
        spans.append((m.start(), m.end(), "NUM", m.group(0), "", ""))
    for m in MATH_TOKEN_RE.finditer(text):
        spans.append((m.start(), m.end(), "MATH", m.group(0), "", ""))
    # resolve overlaps: keep longest; tie → earlier kind priority TERM>CITE>REF>NUM>MATH
    prio = {"TERM": 0, "CITE": 1, "REF": 2, "NUM": 3, "MATH": 4}
    spans.sort(key=lambda s: (-(s[1] - s[0]), prio[s[2]], s[0]))
    chosen: list[tuple] = []
    occupied: list[tuple[int, int]] = []
    for s in spans:
        if any(s[0] < e and s[1] > b for b, e in occupied):
            continue
        occupied.append((s[0], s[1]))
        chosen.append(s)
    chosen.sort(key=lambda s: s[0])
    return [Mark(idx=i + 1, kind=k, original=o, start=s, end=e, term_id=t, canonical=c)
            for i, (s, e, k, o, t, c) in enumerate(chosen)]


def protect_text(text: str, glossary_terms: list[tuple[str, str]] | None = None, idx_offset: int = 0,
                 kinds: tuple[str, ...] = ("TERM", "CITE", "REF", "NUM", "MATH")) -> ProtectResult:
    """Mask spans. `glossary_terms` = [(surface_form, term_id), ...]. `idx_offset` lets caller keep
    placeholder IDs unique across a whole batch."""
    glossary_terms = glossary_terms or []
    marks = _find_spans(text, glossary_terms)
    kinds_set = set(kinds)
    out, last, counter = [], 0, idx_offset
    kept: list[Mark] = []
    for mk in marks:
        if mk.kind not in kinds_set:
            continue
        counter += 1
        mk.idx = counter
        mk.surface = PLACEHOLDER_TMPL.format(kind=mk.kind, idx=mk.idx)
        out.append(text[last:mk.start])
        out.append(mk.surface)
        last = mk.end
        kept.append(mk)
    out.append(text[last:])
    counts: dict[str, int] = {}
    for mk in kept:
        counts[mk.kind] = counts.get(mk.kind, 0) + 1
    return ProtectResult(masked="".join(out), marks=kept, counts=counts)


def restore(masked_translation: str, marks: list[Mark], keep_term_placeholders: bool = False) -> tuple[str, dict[str, Any]]:
    """Put original spans back into a translation. Report placeholders that were altered/dropped/duplicated."""
    by_surface = {mk.surface: mk for mk in marks}
    report: dict[str, Any] = {
        "expected": len(marks),
        "found": 0, "missing": [], "unexpected": [], "duplicated": [],
        "kind_check": {},  # kind -> [found, expected]
    }
    found_counts: dict[str, int] = {}
    for mk in marks:
        c = masked_translation.count(mk.surface)
        if c == 1:
            report["found"] += 1
            found_counts[mk.kind] = found_counts.get(mk.kind, 0) + 1
        elif c == 0:
            report["missing"].append({"ph": mk.surface, "kind": mk.kind, "original": mk.original})
        else:
            report["duplicated"].append({"ph": mk.surface, "count": c, "kind": mk.kind, "original": mk.original})
            report["found"] += 1
            found_counts[mk.kind] = found_counts.get(mk.kind, 0) + 1
    for m in PLACEHOLDER_RE.finditer(masked_translation):
        if m.group(0) not in by_surface:
            report["unexpected"].append(m.group(0))
    expected_by_kind: dict[str, int] = {}
    for mk in marks:
        expected_by_kind[mk.kind] = expected_by_kind.get(mk.kind, 0) + 1
    report["kind_check"] = {k: {"found": found_counts.get(k, 0), "expected": v} for k, v in expected_by_kind.items()}

    def sub(m: re.Match) -> str:
        mk = by_surface.get(m.group(0))
        if mk is None:
            return m.group(0)
        if mk.kind == "TERM" and keep_term_placeholders:
            return mk.surface
        return mk.original

    restored = PLACEHOLDER_RE.sub(sub, masked_translation)
    report["ok"] = not report["missing"] and not report["unexpected"] and not report["duplicated"]
    return restored, report


def marks_to_json(marks: list[Mark]) -> list[dict[str, Any]]:
    return [asdict(m) for m in marks]


def marks_from_json(items: list[dict[str, Any]]) -> list[Mark]:
    return [Mark(**{k: v for k, v in it.items() if k in Mark.__dataclass_fields__}) for it in items]
