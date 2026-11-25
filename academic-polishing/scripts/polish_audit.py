#!/usr/bin/env python3
"""polish_audit.py — deterministic, language-aware audit for academic polishing.

It NEVER rewrites text. It extracts *protected spans* (hedges, quantifiers,
numbers + units, citations, terminology) from a source text and compares them
with a revised text, reporting every span that was dropped, added or altered.

Usage:
  python polish_audit.py extract  --text FILE [--lang zh|en|auto] [--json OUT]
  python polish_audit.py compare  --source FILE --revised FILE [--lang auto]
                                    [--glossary glossary.json] [--json OUT]
                                    [--source-format md|tex|docx|txt]

Exit code (compare): 0 = no blocking findings, 2 = at least one finding.
The JSON is the contract consumed by the edit ledger and by result.json.

Design notes
------------
* Everything is regex + rule based; no model calls, no network, stdlib only.
* "Protected" means the polishing Skill must not change these spans unless the
  task explicitly asks for it, and any change must be listed in the ledger.
* A finding is a *prompt for the editor*, not a verdict: a dropped hedge may be
  exactly what a "strengthen the claim" task requested. The ledger records it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# --------------------------------------------------------------------------
# Language detection (coarse, good enough to choose rule tables)
# --------------------------------------------------------------------------

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def detect_lang(text: str) -> str:
    cjk = len(CJK_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk == 0 and latin == 0:
        return "unknown"
    if cjk > latin * 0.2:
        return "zh"
    return "en"


# --------------------------------------------------------------------------
# Strip markup so LaTeX / Markdown syntax is not mistaken for content
# --------------------------------------------------------------------------

TEX_CMD_ARG_RE = re.compile(r"\\(?:cite\w*|ref|eqref|label|pageref)(?:\[[^\]]*\])?\{([^}]*)\}")
TEX_CMD_RE = re.compile(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?")
TEX_MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]*\$", re.S)
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MD_EMPH_RE = re.compile(r"(\*\*|__|\*|_)(.*?)\1")
MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.M)
HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_markup(text: str, fmt: str) -> tuple[str, list[dict]]:
    """Return (plain_text, citations) where citations keep their raw keys."""
    citations: list[dict] = []
    plain = text.replace("\r\n", "\n").replace("\r", "\n")
    if fmt == "tex":
        for m in TEX_CMD_ARG_RE.finditer(plain):
            kind = "citation" if m.group(0).startswith("\\cite") else "ref"
            for key in m.group(1).split(","):
                key = key.strip()
                if key:
                    citations.append({"kind": kind, "key": key, "raw": m.group(0)})
            plain = plain.replace(m.group(0), " ")
        plain = TEX_MATH_RE.sub(" ", plain)
        plain = TEX_CMD_RE.sub(" ", plain)
        plain = plain.replace("{", " ").replace("}", " ")
    elif fmt == "md":
        def _link(m):
            return m.group(1)
        plain = MD_LINK_RE.sub(_link, plain)
        plain = MD_HEADING_RE.sub("", plain)
        plain = MD_EMPH_RE.sub(r"\2", plain)
        # Markdown academic citations: [@key], [@key1; @key2], (Author 2020)
        for m in re.finditer(r"\[@([^\]]+)\]", plain):
            for key in re.split(r"[;,]", m.group(1)):
                key = key.strip().lstrip("@")
                if key:
                    citations.append({"kind": "citation", "key": key, "raw": m.group(0)})
        plain = re.sub(r"\[@[^\]]+\]", " ", plain)
    plain = HTML_TAG_RE.sub(" ", plain)
    plain = unicodedata.normalize("NFC", plain)
    return plain, citations


# --------------------------------------------------------------------------
# Rule tables
# --------------------------------------------------------------------------

ZH_HEDGES = [
    "可能", "或许", "也许", "大概", "大约", "似乎", "似乎", "倾向于", "有望", "在一定程度上",
    "一定程度上", "部分地", "初步", "初步表明", "提示", "暗示", "提示着", "值得进一步", "有待",
    "尚需", "尚不明确", "尚不清楚", "需要进一步", "进一步研究", "推测", "猜测", "我们认为",
    "我们推测", "推测可能", "或可", "大致", "左右", "上下", " approximately", "近似", "近似于",
    "通常", "一般", "往往", "有时", "偶尔", "在某些情况下", "多数情况下", "多数", "少数",
    "主要", "部分", "显著", "明显", "略微", "稍微", "稍", "较", "更为", "更加", "相对",
    "基本", "几乎", "接近", "约", "约为", "近", "超过", "以上", "以下", "不到", "不足",
    "提示", "表明", "说明", "显示", "证实", "证明", "验证", "确认", "揭示", "支持",
]
ZH_ABSOLUTES = [
    "必然", "一定", "完全", "始终", "所有", "任何", "从不", "永不", "绝对", "毫无",
    "证明", "证实", "确证", "毋庸置疑", "必然", "总是", "一律", "统统", "全部", "毫无例外",
    "彻底", "根本", "永远",
]
ZH_CONNECTIVES = [
    "因此", "所以", "由于", "因为", "然而", "但是", "不过", "而", "并且", "而且", "同时",
    "此外", "另外", "另一方面", "相比之下", "与之相比", "进一步", "进而", "从而", "即", "也就是说",
    "例如", "比如", "包括", "总之", "综上所述", "总而言之", "首先", "其次", "最后", "然后",
]
ZH_FILLERS = [
    "值得注意的是", "需要指出的是", "众所周知", "毫无疑问", "具有重要意义", "具有重要的理论意义",
    "引起了广泛关注", "备受关注", "日益受到关注", "成为研究热点", "热点问题", "得到了广泛的应用",
    "广泛应用于", "极大地", "大大地", "有效地", "显著地", "深刻", "深入", "全面", "系统",
    "综上所述", "不言而喻", "显而易见", "在一定程度上",
]

EN_HEDGES = [
    "may", "might", "could", "can", "would", "should", "possibly", "probably", "likely", "unlikely",
    "perhaps", "arguably", "appears", "appear", "seems", "seem", "suggests", "suggest", "proposes",
    "proposed", "indicates", "indicate", "implies", "imply", "tends", "tend", "generally", "typically",
    "usually", "often", "sometimes", "occasionally", "rarely", "seldom", "partly", "partially",
    "mostly", "mainly", "largely", "to some extent", "to a certain extent", "in some cases",
    "in most cases", "approximately", "roughly", "about", "around", "nearly", "almost", "up to",
    "at least", "at most", "more than", "less than", "few", "some", "many", "several", "most",
    "preliminary", "preliminarily", "tentatively", "tentative", "we hypothesize", "we speculate",
    "it is possible", "it is likely", "remains unclear", "remains to be", "further studies",
    "further investigation", "warrants further", "merits further", "not fully understood",
    "not well understood", "poorly understood", "remains controversial", "remains debated",
]
EN_ABSOLUTES = [
    "always", "never", "all", "every", "each", "none", "no", "impossible", "certainly", "definitely",
    "undoubtedly", "without doubt", "unquestionably", "inevitably", "proves", "prove", "proven",
    "confirms", "definitively", "completely", "entirely", "totally", "wholly",
]
EN_CONNECTIVES = [
    "however", "therefore", "thus", "hence", "consequently", "moreover", "furthermore", "in addition",
    "in contrast", "by contrast", "in comparison", "compared with", "compared to", "although",
    "though", "whereas", "while", "since", "because", "so", "such that", "thereby", "wherein",
    "nevertheless", "nonetheless", "instead", "for example", "for instance", "specifically",
    "in particular", "notably", "importantly", "in summary", "in conclusion", "overall", "first",
    "second", "third", "finally", "firstly", "secondly", "lastly",
]
EN_FILLERS = [
    "it is worth noting that", "it should be noted that", "it is important to note that",
    "notably", "importantly", "interestingly", "intriguingly", "it is well known that",
    "as is well known", "plays a crucial role", "plays an important role", "has attracted",
    "has garnered", "has received considerable attention", "has become a hot topic",
    "in recent years", "in the past decade", "over the past decade", "increasingly",
    "significantly", "dramatically", "greatly", "effectively", "efficiently", "robustly",
    "comprehensive", "systematic", "in-depth", "state-of-the-art", "novel", "paradigm",
    "delve into", "elucidate", "leverage", "utilize", "in order to", "due to the fact that",
    "a total of", "in terms of", "with respect to", "regarding",
]

# Numbers with optional unit / percent / range. Units are deliberately loose;
# the point is to catch 3.2 mg -> 3.2 g and 15% -> 15.
_NUM = r"[+-]?\d+(?:[.,]\d+)*(?:\s*[×xX]\s*10\^?[-+]?\d+|\s*[eE][-+]?\d+)?"
_UNIT_ALTS = [
    # mass / volume / concentration
    r"mg", r"kg", r"μg|µg|ug", r"ng", r"pg", r"mL|ml", r"μL|µl|ul", r"mM", r"nmol|pmol",
    # length / time / frequency / energy / power / electric / temperature / pressure
    r"nm", r"mm", r"cm", r"km", r"μm|µm|um", r"pm", r"ns", r"ms", r"μs|µs|us", r"min", r"hrs?",
    r"kHz", r"MHz", r"GHz", r"Hz", r"kJ", r"kcal", r"keV", r"MeV", r"eV", r"cal", r"J",
    r"mW", r"kW", r"kWh", r"W", r"mV", r"kV", r"V", r"mA", r"kPa", r"MPa", r"GPa", r"Pa", r"atm", r"bar",
    # statistics / experiment
    r"molecules", r"participants", r"replicates", r"patients", r"subjects", r"samples", r"trials", r"atoms", r"ions", r"cells",
    r"[xX]-?fold", r"fold", r"r\.?p\.?m|rpm", r"fps", r"dpi", r"ppm", r"ppb",
    r"wt\.?%|vol\.?%|at\.?%|mol\.?%",
    r"million", r"billion", r"thousand",
    # CJK counters
    r"倍|年|月|日|天|小时|分钟|秒|次|个|例|只|株|粒|份|项|组|种|类|张|台|元|万元|亿|万|千|百万",
    # single letters last so they don't shadow longer ones
    r"g", r"L|l", r"m", r"s", r"h", r"A", r"K", r"J", r"V", r"W", r"mol", r"bp", r"kb", r"Mb", r"Gb", r"aa", r"kDa", r"Da", r"°C|℃",
]
UNIT_RE = r"(?:%|‰|°|" + "|".join(_UNIT_ALTS) + r")"
NUM_UNIT_RE = re.compile(
    r"(?<![\w.])(" + _NUM + r")(\s*" + UNIT_RE + r"(?![A-Za-z]))?",
    re.I,
)
PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*[%‰]")
RANGE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:[-–—~～至到])\s*\d+(?:[.,]\d+)?")
P_VALUE_RE = re.compile(r"[pP]\s*[<>=≤≥]\s*(?:\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|\d+\s*[×x]\s*10\^?[-+]?\d+)", re.I)
STAT_RE = re.compile(r"\b(?:r|rr|r²|R²|r2|OR|HR|RR|CI|SD|SE|SEM|AUC|n|N)\s*[=<>]?\s*[+-]?\d+(?:\.\d+)?", re.I)

# Citation-ish patterns for plain text (author-year), so they survive markup stripping
AUTHOR_YEAR_RE = re.compile(
    r"([A-Z][A-Za-z\-]+(?:\s+(?:et\s+al\.?|and|&)\s*[A-Z]?[A-Za-z\-]*)?,?\s*\(?(?:19|20)\d{2}[a-z]?(?:[,;]\s*(?:19|20)\d{2}[a-z]?)*\)?)"
)
ZH_AUTHOR_YEAR_RE = re.compile(r"([\u4e00-\u9fff]{2,4}(?:等|等人|和[\u4e00-\u9fff]{2,4})?,?\s*\(?(?:19|20)\d{2}[a-z]?\)?)")
# Foreign names inside Chinese prose: "Smith 等 (2019)" / "Smith 和 Lee 2020"
ZH_LATIN_AUTHOR_YEAR_RE = re.compile(
    r"([A-Z][A-Za-z\-]+(?:\s*(?:等|等人|和|与)\s*[A-Z]?[A-Za-z\-\u4e00-\u9fff]*)?,?\s*\(?(?:19|20)\d{2}[a-z]?\)?)"
)
BRACKET_NUM_RE = re.compile(r"\[\d+(?:[,，\-–]\s*\d+)*\]")

# Function words that carry scope / polarity; dropping them changes meaning
ZH_NEGATION = ["不", "未", "无", "非", "没有", "无法", "不能", "并非", "不是", "尚未", "并不", "从未"]
EN_NEGATION = ["not", "no", "never", "neither", "nor", "without", "cannot", "n't", "unable", "fails to"]

# Translationese markers (zh text that reads like English) — reported as style hints only
ZH_TRANSLATIONESE = [
    (r"对于[^，。；]{1,12}来说", "对于…来说：英文 'for X' 直译，可删或改'就X而言'"),
    (r"基于[^，。；]{1,12}的基础上", "'基于…的基础上'：两个介词叠用"),
    (r"进行了[^，。；]{0,8}(研究|分析|探讨|观察|调查)", "'进行了…研究'：名词化冗余，改'研究了/分析了'"),
    (r"使得[^，。；]{1,20}得以", "'使得…得以'：英文 enable 直译"),
    (r"起着[^，。；]{0,6}作用", "'起着…作用'：play a role 直译，可具体化"),
    (r"扮演着?[^，。；]{0,8}角色", "'扮演…角色'：play a role 直译"),
    (r"由于[^，。；]{1,20}的原因", "'由于…的原因'：冗余"),
    (r"[^，。；]{1,10}的一个重要的[^，。；]{1,6}", "'一个重要的…'：填充形容词"),
    (r"被动的?[^，。；]{0,6}", "被动式：中文学术写作少用'被'，改主动"),
    (r"作为[^，。；]{1,10}的[^，。；]{1,6}，", "句首'作为…的…'：英文分词直译"),
    (r"在[^，。；]{1,10}方面", "'在…方面'：可省，直接说"),
    (r"通过[^，。；]{1,16}的方式", "'通过…的方式'：冗余"),
    (r"具有[^，。；]{0,6}(重要)?意义", "'具有…意义'：空泛，具体化"),
    (r"对[^，。；]{1,12}进行了[^，。；]{1,6}", "'对…进行了…'：名词化，改动词直述"),
    (r"得到了?[^，。；]{0,6}(广泛|普遍|极大|大幅|深入)(的)?(应用|关注|提升|改善|发展|研究)", "'得到广泛的…'：空泛评价，改具体结果"),
    (r"综上所述|总而言之|由此可见", "套路化总结连接词：仅在确有总结时保留一次"),
    (r"随着[^，。；]{1,16}的发展", "'随着…的发展'：套话开头，可直接陈述背景"),
]
EN_TRANSLATIONESE_ZHSRC = [
    (r"\bthe\b\s+\w+\s+\bof\b\s+\w+\s+\bis\b", "中式'the X of Y is'：可改 'Y's X is' 或动词句"),
    (r"\bhas\s+a\s+(?:very\s+)?(?:important|significant|great)\s+", "'has a very important…'：中文'具有重要'直译"),
    (r"\bmore\s+and\s+more\b", "'more and more'：中文'越来越多'直译，改 increasingly"),
    (r"\bthe\b\s+\w+\s+\bproblem\b", "句尾'problem'：中文'问题'直译，常可删"),
    (r"\bplay\s+an?\s+(?:important|key|crucial|significant)\s+role\b", "'play a role'：中文'起作用'直译"),
    (r"\bin\s+order\s+to\b", "'in order to'：冗余，改 to"),
    (r"\bput\s+forward\b", "'put forward'：中文'提出'直译，改 proposed"),
    (r"\bresearch\s+on\b", "'research on'：改 'study of' 或动词"),
]

# Typographic rules (zh academic): ASCII punctuation inside CJK runs is a defect
ZH_ASCII_PUNCT = re.compile(r"[\u4e00-\u9fff][,;:!?](?=[\u4e00-\u9fff\s])")
ZH_MIXED_PUNCT = re.compile(r"[\u4e00-\u9fff]\.(?=\s|$|[\u4e00-\u9fff])")
EN_DOUBLE_SPACE = re.compile(r"[ \t]{2,}")
EN_SPACE_BEFORE_PUNCT = re.compile(r"\s+[,.;:!?](?=\s|$)")
SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z\u4e00-\u9fff])")


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def _word_hits(text: str, words: list[str], lang: str) -> list[dict]:
    hits = []
    for w in words:
        if lang == "en":
            pat = re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", re.I)
        else:
            pat = re.compile(re.escape(w))
        for m in pat.finditer(text):
            hits.append({"kind": "hedge", "text": m.group(0), "start": m.start(), "end": m.end()})
    # drop overlapping hits of the same category (e.g. 一定程度上 inside 在一定程度上)
    hits.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    kept = []
    for h in hits:
        if kept and h["start"] < kept[-1]["end"]:
            continue
        kept.append(h)
    return kept


def extract_spans(text: str, lang: str) -> dict:
    """Extract all protected spans from plain (markup-stripped) text."""
    hedging_words = ZH_HEDGES if lang == "zh" else EN_HEDGES
    absolute_words = ZH_ABSOLUTES if lang == "zh" else EN_ABSOLUTES
    neg_words = ZH_NEGATION if lang == "zh" else EN_NEGATION

    hedges = []
    for h in _word_hits(text, hedging_words, lang):
        h["strength"] = "hedge"
        hedges.append(h)
    for h in _word_hits(text, absolute_words, lang):
        h["strength"] = "absolute"
        hedges.append(h)
    for h in _word_hits(text, neg_words, lang):
        h["strength"] = "negation"
        hedges.append(h)
    hedges.sort(key=lambda h: h["start"])

    numbers = []
    seen = set()
    for m in list(P_VALUE_RE.finditer(text)) + list(STAT_RE.finditer(text)) + list(NUM_UNIT_RE.finditer(text)):
        s = m.group(0).strip()
        key = (m.start(), s)
        if key in seen:
            continue
        seen.add(key)
        numbers.append({"kind": "number", "text": s, "start": m.start(), "end": m.end()})
    # keep non-overlapping, longest-first
    numbers.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    kept = []
    for n in numbers:
        if kept and n["start"] < kept[-1]["end"]:
            continue
        kept.append(n)
    numbers = kept

    sentences = [s.strip() for s in SENT_SPLIT_RE.split(text) if s and s.strip()]
    return {
        "lang": lang,
        "hedges": [{"text": h["text"], "strength": h["strength"]} for h in hedges],
        "numbers": [n["text"] for n in numbers],
        "sentences": sentences,
    }


def extract_terms(text: str, lang: str, top: int = 60) -> list[dict]:
    """Candidate terms: capitalised phrases (en), 2–6 char CJK n-grams that repeat (zh)."""
    if lang == "zh":
        cjk = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
        grams = Counter()
        for run in cjk:
            for n in (2, 3, 4, 5, 6):
                for i in range(len(run) - n + 1):
                    grams[run[i:i + n]] += 1
        # keep grams that are not strict substrings of a more frequent longer gram with same count
        cands = {g: c for g, c in grams.items() if c >= 2}
        keep = {}
        for g, c in sorted(cands.items(), key=lambda kv: -len(kv[0])):
            if any(g != k and g in k and cands[k] >= c for k in keep):
                continue
            keep[g] = c
        terms = [{"term": g, "count": c} for g, c in sorted(keep.items(), key=lambda kv: -kv[1])[:top]]
        return terms
    words = re.findall(r"[A-Z][a-z]+(?:[-\s][A-Z]?[a-z]+)*", text)
    stop = {"The", "This", "These", "We", "Our", "In", "On", "However", "Therefore", "Figure", "Table", "Section",
            "Here", "To", "For", "And", "But", "Moreover", "Furthermore", "While", "Although", "Since", "After",
            "Before", "Then", "Thus", "Hence", "Results", "Methods", "Discussion", "Introduction", "Conclusion",
            "Abstract", "References", "Acknowledgements"}
    cnt = Counter(w for w in words if w not in stop and len(w) > 2)
    # merge acronyms (all caps) too
    acr = Counter(re.findall(r"\b[A-Z]{2,6}\b", text))
    terms = [{"term": t, "count": c, "type": "acronym"} for t, c in acr.most_common(top)]
    terms += [{"term": t, "count": c, "type": "name"} for t, c in cnt.most_common(top)]
    return terms[:top]


def citation_set(citations: list[dict]) -> dict[str, list[str]]:
    by_kind = defaultdict(list)
    for c in citations:
        by_kind[c["kind"]].append(c["key"])
    return {k: sorted(set(v)) for k, v in by_kind.items()}


def author_year_set(text: str, lang: str) -> set[str]:
    pat = AUTHOR_YEAR_RE if lang == "en" else ZH_AUTHOR_YEAR_RE
    found = {re.sub(r"\s+", " ", m.group(1)) for m in pat.finditer(text)}
    if lang == "zh":
        # Chinese papers cite foreign authors in Latin script too: Smith et al. (2019), Smith 等 (2019)
        found |= {re.sub(r"\s+", " ", m.group(1)) for m in AUTHOR_YEAR_RE.finditer(text)}
        found |= {re.sub(r"\s+", " ", m.group(1)) for m in ZH_LATIN_AUTHOR_YEAR_RE.finditer(text)}
    return found


def bracket_num_set(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(0)) for m in BRACKET_NUM_RE.finditer(text)}


# --------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip().lower()


def compare_sets(src: list[str] | set[str], rev: list[str] | set[str], label: str) -> dict:
    s = {_norm(x) for x in src}
    r = {_norm(x) for x in rev}
    dropped = sorted(s - r)
    added = sorted(r - s)
    return {"label": label, "source_count": len(s), "revised_count": len(r),
            "dropped": dropped, "added": added}


def compare_strength(src: list[dict], rev: list[dict]) -> dict:
    cs = Counter(h["strength"] for h in src)
    cr = Counter(h["strength"] for h in rev)
    per_word_s = Counter(_norm(h["text"]) for h in src)
    per_word_r = Counter(_norm(h["text"]) for h in rev)
    return {
        "by_class": {k: {"source": cs.get(k, 0), "revised": cr.get(k, 0)} for k in ("hedge", "absolute", "negation")},
        "hedge_words_dropped": sorted(w for w in per_word_s if per_word_r[w] < per_word_s[w]),
        "hedge_words_added": sorted(w for w in per_word_r if per_word_r[w] > per_word_s[w]),
    }


def compare_counts(src: dict, rev: dict) -> dict:
    sl, rl = len(src["sentences"]), len(rev["sentences"])
    src_chars = sum(len(s) for s in src["sentences"])
    rev_chars = sum(len(s) for s in rev["sentences"])
    return {
        "sentences": {"source": sl, "revised": rl, "ratio": round(rl / sl, 3) if sl else None},
        "chars": {"source": src_chars, "revised": rev_chars, "ratio": round(rev_chars / src_chars, 3) if src_chars else None},
        "hedges_per_sentence": {"source": round(len(src["hedges"]) / sl, 3) if sl else None,
                                "revised": round(len(rev["hedges"]) / rl, 3) if rl else None},
    }


def style_hints(text: str, lang: str) -> list[dict]:
    hints = []
    if lang == "zh":
        for pat, msg in ZH_TRANSLATIONESE:
            for m in re.finditer(pat, text):
                hints.append({"type": "translationese", "match": m.group(0), "hint": msg})
        for m in ZH_ASCII_PUNCT.finditer(text):
            hints.append({"type": "punct", "match": m.group(0), "hint": "中文句内使用了半角标点"})
        for m in ZH_MIXED_PUNCT.finditer(text):
            hints.append({"type": "punct", "match": m.group(0), "hint": "中文句末使用了半角句点"})
    else:
        for pat, msg in EN_TRANSLATIONESE_ZHSRC:
            for m in re.finditer(pat, text, re.I):
                hints.append({"type": "translationese", "match": m.group(0), "hint": msg})
        for m in EN_SPACE_BEFORE_PUNCT.finditer(text):
            hints.append({"type": "punct", "match": m.group(0), "hint": "标点前多余空格"})
        for m in EN_DOUBLE_SPACE.finditer(text):
            hints.append({"type": "punct", "match": m.group(0), "hint": "连续空格"})
    # long sentence
    for s in SENT_SPLIT_RE.split(text):
        s = s.strip()
        if not s:
            continue
        if lang == "zh" and len(s) > 60:
            hints.append({"type": "long_sentence", "match": s[:40] + "…", "hint": f"长句 {len(s)} 字，考虑拆分"})
        if lang == "en" and len(re.findall(r"\b\w+\b", s)) > 45:
            hints.append({"type": "long_sentence", "match": s[:60] + "…", "hint": f"长句 {len(s.split())} 词，考虑拆分"})
    return hints


def glossary_check(text: str, glossary: dict, lang: str) -> list[dict]:
    """glossary: {"preferred": {"zh": "...", "en": "..."}, "variants": ["...", ...]} list."""
    out = []
    plain = text
    for entry in glossary.get("terms", []):
        pref = entry.get("preferred", {})
        pstr = pref.get(lang) or pref.get("zh") or pref.get("en")
        if not pstr:
            continue
        variants = entry.get("variants", []) or []
        for v in variants:
            if _norm(v) == _norm(pstr):
                continue
            pat = (re.escape(v) if lang == "zh" else r"(?<![A-Za-z])" + re.escape(v) + r"(?![A-Za-z])")
            n = len(re.findall(pat, plain, 0 if lang == "zh" else re.I))
            if n:
                out.append({"preferred": pstr, "variant_found": v, "count": n})
    return out


def load_text(path: str, fmt: str) -> tuple[str, str, list[dict]]:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    if fmt == "auto":
        fmt = "tex" if Path(path).suffix.lower() in (".tex", ".latex") else ("md" if Path(path).suffix.lower() in (".md", ".markdown") else "txt")
    plain, cites = strip_markup(raw, fmt)
    return raw, plain, cites


def cmd_extract(a: argparse.Namespace) -> int:
    _, plain, cites = load_text(a.text, a.source_format)
    lang = a.lang if a.lang != "auto" else detect_lang(plain)
    spans = extract_spans(plain, lang)
    result = {
        "tool": "polish_audit/extract", "lang": lang,
        "hedges": spans["hedges"], "numbers": spans["numbers"],
        "citations": citation_set(cites),
        "author_year": sorted(author_year_set(plain, lang)),
        "bracket_numbers": sorted(bracket_num_set(plain)),
        "candidate_terms": extract_terms(plain, lang),
        "style_hints": style_hints(plain, lang),
        "counts": {"sentences": len(spans["sentences"]), "chars": len(plain)},
    }
    _emit(result, a.json)
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    _, sp, sc = load_text(a.source, a.source_format)
    _, rp, rc = load_text(a.revised, a.source_format)
    lang = a.lang if a.lang != "auto" else detect_lang(sp)
    src, rev = extract_spans(sp, lang), extract_spans(rp, lang)
    glossary = {}
    if a.glossary and Path(a.glossary).exists():
        glossary = json.loads(Path(a.glossary).read_text(encoding="utf-8"))

    report = {
        "tool": "polish_audit/compare", "lang": lang,
        "hedge_strength": compare_strength(src["hedges"], rev["hedges"]),
        "numbers": compare_sets(src["numbers"], rev["numbers"], "numbers"),
        "citations": compare_sets([f"{c['kind']}:{c['key']}" for c in sc], [f"{c['kind']}:{c['key']}" for c in rc], "citation_keys"),
        "author_year": compare_sets(author_year_set(sp, lang), author_year_set(rp, lang), "author_year"),
        "bracket_numbers": compare_sets(bracket_num_set(sp), bracket_num_set(rp), "bracket_numbers"),
        "counts": compare_counts(src, rev),
        "glossary_violations_revised": glossary_check(rp, glossary, lang),
        "glossary_violations_source": glossary_check(sp, glossary, lang),
        "style_hints_source": style_hints(sp, lang),
        "style_hints_revised": style_hints(rp, lang),
    }
    # Blocking: anything that changes a number, citation, or a *dropped* hedge/negation/absolute.
    # Added negations/hedges are reported but not blocking: Chinese 不 also occurs in 不断/不仅,
    # and an added hedge merely weakens a claim (still listed for the editor to confirm).
    blocking = []
    for k in ("numbers", "citations", "author_year", "bracket_numbers"):
        if report[k]["dropped"] or report[k]["added"]:
            blocking.append({"check": k, "dropped": report[k]["dropped"], "added": report[k]["added"]})
    dropped_words = report["hedge_strength"]["hedge_words_dropped"]
    if dropped_words:
        blocking.append({"check": "hedge_words", "dropped": dropped_words, "added": []})
    if report["hedge_strength"]["hedge_words_added"]:
        report["notes"] = {"hedge_words_added": "added hedges are informational; confirm each was intended"}
    report["blocking"] = blocking
    report["verdict"] = "clean" if not blocking else "review"
    _emit(report, a.json)
    print(f"[polish_audit] lang={lang} verdict={report['verdict']} blocking={len(blocking)} "
          f"hedges {len(src['hedges'])}->{len(rev['hedges'])} numbers {len(src['numbers'])}->{len(rev['numbers'])}",
          file=sys.stderr)
    return 0 if not blocking else 2


def _emit(obj: dict, path: str | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if path and path != "-":
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


def _stderr_reconfigure() -> None:
    # Windows consoles default to a legacy code page; force UTF-8 so CJK spans are readable.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    _stderr_reconfigure()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="extract protected spans from one text")
    e.add_argument("--text", required=True)
    e.add_argument("--lang", default="auto", choices=["auto", "zh", "en"])
    e.add_argument("--source-format", default="auto", choices=["auto", "txt", "md", "tex"])
    e.add_argument("--json")
    e.set_defaults(fn=cmd_extract)
    c = sub.add_parser("compare", help="compare source vs revised")
    c.add_argument("--source", required=True)
    c.add_argument("--revised", required=True)
    c.add_argument("--lang", default="auto", choices=["auto", "zh", "en"])
    c.add_argument("--source-format", default="auto", choices=["auto", "txt", "md", "tex"])
    c.add_argument("--glossary")
    c.add_argument("--json")
    c.set_defaults(fn=cmd_compare)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
