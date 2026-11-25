#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_rules — deterministic checks for an introduction / related-work draft.

Every rule here answers one of the four questions the task is graded on, and
every rule is decidable from the files alone: no model call, no judgement about
"good writing". A rule may only flag something it can point at.

  R01..R04, R13, R17  对得上  (matches up: citations, metadata, numbers, style)
  R05, R06, R10, R18  说得实 / 立得住 (coverage, recency, gap provenance)
  R07..R09            分得清  (grouping and comparison)
  R12, R15            对得上  (contribution -> evidence)
  R14, R16            立得住 / structure

The rule set is intentionally conservative: a rule fires only on a pattern that
is cheap to verify, so a reviewer reading the report never has to argue with it.
False positives are treated as a bug, not as a safe default.
"""

from __future__ import annotations

import re

import introlib as L

SEV_ERROR = "error"
SEV_WARN = "warn"
SEV_INFO = "info"

QUESTION = {
    "R01": "对得上", "R02": "说得实", "R03": "说得实", "R04": "对得上",
    "R05": "说得实", "R06": "立得住", "R07": "分得清", "R08": "分得清",
    "R09": "分得清", "R10": "说得实", "R11": "说得实", "R12": "对得上",
    "R13": "对得上", "R14": "立得住", "R15": "对得上", "R16": "立得住",
    "R17": "对得上", "R18": "对得上",
}

RULE_TITLE = {
    "R01": "citation_integrity",
    "R02": "uncited_claim",
    "R03": "citation_anchor_drift",
    "R04": "reference_metadata",
    "R05": "coverage_of_required_works",
    "R06": "recent_progress_covered",
    "R07": "group_completeness",
    "R08": "serial_summary_pattern",
    "R09": "grouping_consistency",
    "R10": "gap_provenance",
    "R11": "gap_filled_by_own_work",
    "R12": "contribution_evidence",
    "R13": "number_provenance",
    "R14": "four_part_structure",
    "R15": "novelty_claim_bounded",
    "R16": "vacuous_background",
    "R17": "citation_style_consistency",
    "R18": "abstract_metric_covered",
}

# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #

JUDGMENT_MARKERS = [
    "本文认为", "本文强调", "作者认为", "我们认为", "我们推断", "我们推测", "我们判断",
    "据作者判断", "据我们判断", "（作者判断）", "(作者判断)", "【作者判断】", "[作者判断]",
    "尚无一致结论", "尚未见报道", "尚不清楚",
    "we argue", "we believe", "we conjecture", "we hypothesise", "we hypothesize",
    "in our view", "we contend", "we posit", "author judgment", "author's judgment",
    "to our knowledge", "as far as we know", "we are not aware of",
]
JUDGMENT_RE = re.compile("|".join(re.escape(x) for x in JUDGMENT_MARKERS), re.I)

LIT_RE = re.compile(
    r"(?:研究表明|研究显示|已有研究|已有工作|已有文献|先前(?:的)?工作|相关工作|现有方法|现有研究|"
    r"学者(?:们)?(?:指出|认为|发现)|等人|"
    r"et\s+al\.?|prior\s+work|previous\s+(?:work|studies|research|approaches|methods)|"
    r"existing\s+(?:work|studies|methods|approaches)|has\s+been\s+(?:shown|reported|demonstrated|observed)|"
    r"have\s+been\s+(?:shown|reported|demonstrated|observed)|it\s+has\s+been\s+(?:shown|reported)|"
    r"studies\s+have\s+(?:shown|reported|found)|reported\s+by)", re.I)

COMPARATIVE_RE = re.compile(
    r"(?:优于|劣于|高于|低于|超过|不如|相当于|相比|相较|相比之下|而不是|而非|互补|"
    r"outperform\w*|superior|inferior|better\s+than|worse\s+than|higher\s+than|lower\s+than|"
    r"compared\s+(?:with|to)|in\s+contrast|by\s+contrast|whereas|however|unlike|instead|"
    r"rather\s+than|taken\s+together|read\s+together|in\s+sum|complementary|"
    r"trade-?off|取舍|代价|局限)", re.I)

SUPERLATIVE_RE = re.compile(
    r"(?:首个|首次|第一次|最优|最佳|最高|state-of-the-art|sota|first\s+(?:to|ever)|"
    r"unprecedented|to\s+the\s+best\s+of\s+our\s+knowledge|best\s+(?:known|reported))", re.I)

VACUOUS = [
    (r"近年来[^。；]{0,24}(?:受到|得到|引起)[^。；]{0,12}(?:广泛|极大|普遍|高度)?[^。；]{0,8}(?:关注|重视|研究)", "近年来受到广泛关注"),
    (r"随着[^。；]{0,24}(?:的)?(?:快速|迅速|高速|蓬勃)发展", "随着……的快速发展"),
    (r"has\s+attracted\s+(?:considerable|increasing|growing|widespread|much|a\s+lot\s+of)\s+attention", "has attracted ... attention"),
    (r"has\s+(?:drawn|received)\s+(?:considerable|increasing|growing|widespread|much)\s+(?:attention|interest)", "has drawn ... interest"),
    (r"with\s+the\s+(?:rapid|fast|continuous|steady)\s+(?:development|growth|advance(?:ment)?)\s+of", "with the rapid development of"),
    (r"plays?\s+an?\s+(?:increasingly\s+)?(?:important|crucial|vital|significant|key)\s+role", "plays an important role"),
    (r"在[^。；]{0,16}(?:中|领域)[^。；]{0,10}(?:发挥着?|扮演着?)[^。；]{0,6}(?:重要|关键|核心)的?(?:作用|角色)", "发挥着重要作用"),
    (r"(?:十分重要|至关重要|意义重大|不可或缺)(?:的)?(?:意义|作用|地位)?", "十分重要/至关重要"),
]
VACUOUS_RE = [(re.compile(p, re.I), lab) for p, lab in VACUOUS]

OUR_WORK_RE = re.compile(
    r"(?:本文|本研究|本工作|我们(?:提出|设计|构建|实现|开展|认为|把|将)|"
    r"\bwe\s+(?:propose|present|introduce|develop|design|build|show|demonstrate|report|"
    r"take|treat|address|target|aim|focus|handle|study|examine|adopt|use|argue|contend|posit)\b|"
    r"\bour\s+(?:work|method|approach|study|framework|pipeline|contribution)|"
    r"\bthis\s+(?:paper|work|study)\b)", re.I)

GROUP_FIELDS = ["method_route", "data_setting", "evaluation", "conclusion", "limitation"]


# --------------------------------------------------------------------------- #
# reporting helper
# --------------------------------------------------------------------------- #

def _finding(code, severity, message, **kw):
    rec = {"code": code, "severity": severity, "message": message}
    rec.update({k: v for k, v in kw.items() if v is not None})
    return rec


class Rule:
    """A rule collects findings; status is error > warn > pass."""

    def __init__(self, rid, title=None):
        self.id = rid
        self.title = title or RULE_TITLE.get(rid, rid)
        self.question = QUESTION.get(rid, "")
        self.findings = []
        self.checked = 0
        self.note = ""

    def add(self, code, severity, message, **kw):
        self.findings.append(_finding(code, severity, message, rule=self.id, **kw))

    def error(self, code, message, **kw):
        self.add(code, SEV_ERROR, message, **kw)

    def warn(self, code, message, **kw):
        self.add(code, SEV_WARN, message, **kw)

    def info(self, code, message, **kw):
        self.add(code, SEV_INFO, message, **kw)

    def result(self):
        errs = [f for f in self.findings if f["severity"] == SEV_ERROR]
        warns = [f for f in self.findings if f["severity"] == SEV_WARN]
        status = "error" if errs else ("warn" if warns else "pass")
        return {
            "id": self.id, "title": self.title, "question": self.question,
            "status": status, "checked": self.checked, "note": self.note,
            "n_error": len(errs), "n_warn": len(warns),
            "findings": self.findings,
        }


# --------------------------------------------------------------------------- #
# context helpers
# --------------------------------------------------------------------------- #

def _cited_ids(draft_paragraphs, part=None):
    ids = []
    for p in draft_paragraphs:
        if part and p["part"] != part:
            continue
        for c in p["sentences"]:
            for cid in c.get("ref_ids") or []:
                ids.append(cid)
    return ids


def _sentence_ids(sent, resolutions):
    return resolutions.get(id(sent), [])


def resolve_draft(ctx):
    """Attach resolved ref_ids to every sentence, once.

    Also records, per sentence, the citation number the draft uses for each
    reference (`ref_numbers`), so the bibliography can be rendered in the draft's
    own numbering instead of discovery order.
    """
    res = {}
    unanswered = {"n": 0, "unresolved": [], "ambiguous": []}
    for p in ctx["draft"]["paragraphs"]:
        for s in p["sentences"]:
            ids, unresolved, ambiguous, numbers = [], [], [], {}
            for c in s["citations"]:
                r = L.resolve_citation(c, ctx["lib_index"], ctx["reflist"])
                ids.extend(r["ref_ids"])
                unresolved.extend(r["unresolved"])
                ambiguous.extend(r["ambiguous"])
                nums = c.get("nums") or []
                if c["kind"] == L.CITE_KIND_NUMERIC and len(r["ref_ids"]) == len(nums):
                    for rid, n in zip(r["ref_ids"], nums):
                        numbers[rid] = n
            s["ref_ids"] = list(dict.fromkeys(ids))
            s["ref_numbers"] = numbers
            s["unresolved"] = list(dict.fromkeys(unresolved))
            s["ambiguous"] = list(dict.fromkeys(ambiguous))
            res[id(s)] = s["ref_ids"]
            unanswered["n"] += len(unresolved) + len(ambiguous)
            unanswered["unresolved"].extend(unresolved)
            unanswered["ambiguous"].extend(ambiguous)
    unanswered["unresolved"] = list(dict.fromkeys(unanswered["unresolved"]))
    unanswered["ambiguous"] = list(dict.fromkeys(unanswered["ambiguous"]))
    return res, unanswered


def all_sentences(ctx, part=None):
    for p in ctx["draft"]["paragraphs"]:
        if part and p["part"] != part:
            continue
        for s in p["sentences"]:
            yield p, s


def entry_by_id(ctx):
    return {e["ref_id"]: e for e in ctx["library"].get("entries") or []}


def _is_claim(sentence):
    """Classify a sentence's assertion surface. Returns list of matched kinds.

    Only the three high-precision signals are used. Comparative connectives
    ("however", "whereas", "相比之下") are deliberately not a trigger on their own:
    they appear in most well-written prose and would flood the report.
    """
    kinds = []
    if L.extract_numbers(sentence):
        kinds.append("numeric")
    if LIT_RE.search(sentence):
        kinds.append("literature")
    if SUPERLATIVE_RE.search(sentence):
        kinds.append("superlative")
    return kinds


def _has_judgment(sentence):
    return bool(JUDGMENT_RE.search(sentence))


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #

def r01_citation_integrity(ctx):
    r = Rule("R01")
    entries = entry_by_id(ctx)
    by_key = {}
    for e in entries.values():
        if e.get("key"):
            by_key[L.norm_ws(e["key"]).lower()] = e
    seen_bad = set()
    for p, s in all_sentences(ctx):
        r.checked += 1
        for raw in s.get("unresolved") or []:
            if raw in seen_bad:
                continue
            seen_bad.add(raw)
            r.error("invented_citation",
                    "引用标记 %s 在文献库与文末参考文献表中都找不到对应条目，无法核对。" % raw,
                    marker=raw, sentence=s["text"][:180], part=p["part"])
        for raw in s.get("ambiguous") or []:
            r.warn("ambiguous_citation",
                   "引用标记 %s 可以匹配到多条文献，无法唯一确定。" % raw,
                   marker=raw, sentence=s["text"][:180], part=p["part"])
    # a key form marker whose key is not in the library at all
    for p, s in all_sentences(ctx):
        for c in s.get("citations") or []:
            if c["kind"] != L.CITE_KIND_KEY:
                continue
            for k in c["keys"]:
                if k.lower() not in by_key:
                    if ("key:" + k) in seen_bad:
                        continue
                    seen_bad.add("key:" + k)
                    r.error("invented_citation",
                            "\\cite{%s} 的键不在文献库中（共 %d 条），疑似编造引用。" % (k, len(entries)),
                            marker=k, part=p["part"])
    if ctx["draft"]["citations"] and not entries:
        r.note = "文献库为空，无法核验引用；所有引用标记记为未解析。"
    return r


def r02_uncited_claim(ctx):
    r = Rule("R02")
    judged = 0
    for p, s in all_sentences(ctx):
        r.checked += 1
        if s.get("ref_ids"):
            continue
        if _has_judgment(s["text"]):
            judged += 1
            continue
        if p["part"] == "contributions":
            # own-work claims are checked against the manuscript by R12/R15, not by a citation
            continue
        kinds = _is_claim(s["text"])
        if not kinds:
            continue
        r.warn("uncited_claim",
               "该句含 %s 类论断但没有任何引用，也没有标注为作者判断。" % "/".join(kinds),
               kinds=kinds, sentence=s["text"][:200], part=p["part"], para=p["index"])
    if judged:
        r.info("author_judgment_marked", "%d 句显式标注为作者判断，未要求引用。" % judged)
    return r


def r03_citation_anchor(ctx):
    r = Rule("R03")
    for p in ctx["draft"]["paragraphs"]:
        r.checked += 1
        sents = p["sentences"]
        if len(sents) < 2:
            continue
        last_cited = max([i for i, s in enumerate(sents) if s.get("ref_ids")] or [-1])
        if last_cited <= 0:
            continue
        early = [s for i, s in enumerate(sents[:last_cited])
                 if not s.get("ref_ids") and _is_claim(s["text"])
                 and not _has_judgment(s["text"])]
        if early and last_cited == len(sents) - 1:
            r.warn("citation_anchor_drift",
                   "段落前 %d 句有论断但无引用，引用集中在段末；引用应落在它所支撑的那一句上。"
                   % len(early),
                   part=p["part"], para=p["index"],
                   uncited_claim_1=early[0]["text"][:160],
                   citation_at_end=sents[last_cited]["text"][:160])
    return r


MIN_YEAR = 1900


def _valid_doi(d):
    return bool(re.match(r"^10\.\d{4,9}/\S+$", d or ""))


def r04_metadata(ctx):
    r = Rule("R04")
    entries = entry_by_id(ctx)
    cited = set()
    for _, s in all_sentences(ctx):
        cited.update(s.get("ref_ids") or [])
    now_year = ctx.get("now_year") or 2100
    for rid in sorted(cited):
        e = entries.get(rid)
        if not e:
            continue
        r.checked += 1
        missing = [f for f in ("title", "authors", "year") if not e.get(f)]
        if not e.get("venue") and e.get("type") in ("journal", "conference", "chapter", ""):
            missing.append("venue")
        if missing:
            r.warn("metadata_incomplete",
                   "%s 缺少字段 %s，无法按任何引用格式完整排录。" % (rid, ",".join(missing)),
                   ref_id=rid, fields=missing, title=e.get("title", "")[:120])
        y = e.get("year")
        if y and (not isinstance(y, int) or y < MIN_YEAR or y > now_year + 1):
            r.warn("metadata_year_range", "%s 的年份 %s 越界或不可信。" % (rid, y), ref_id=rid, year=y)
        if e.get("doi") and not _valid_doi(e["doi"]):
            r.warn("metadata_bad_doi", "%s 的 DOI 形式不合法：%s" % (rid, e["doi"]),
                   ref_id=rid, doi=e["doi"])
        if e.get("pages"):
            pg = re.sub(r"[–—~−]", "-", str(e["pages"]))
            pg = re.sub(r"-{2,}", "-", pg).strip().strip(".,")
            ok = (re.match(r"^\d{1,6}(-\d{1,6})?$", pg)
                  or re.match(r"^[A-Za-z]{0,8}\d{1,8}$", pg)          # article number, e.g. bbae051
                  or re.match(r"^[A-Za-z]{1,8}\d{1,8}(-[A-Za-z]{0,8}\d{1,8})?$", pg))
            if not ok:
                r.warn("metadata_bad_pages", "%s 的页码形式可疑：%s" % (rid, e["pages"]),
                       ref_id=rid, pages=e["pages"])
        if e.get("merged_from"):
            r.info("deduplicated_entry",
                   "%s 由 %d 条重复记录合并（%s）。" % (rid, len(e["merged_from"]), e.get("key") or ""),
                   ref_id=rid)
    for e in entries.values():
        if e.get("doi"):
            for other in entries.values():
                if other is not e and other.get("doi") == e["doi"] and other["ref_id"] < e["ref_id"]:
                    r.warn("metadata_duplicate_doi",
                           "%s 与 %s 的 DOI 相同，可能是同一条文献的重复记录。"
                           % (other["ref_id"], e["ref_id"]), ref_id=e["ref_id"])
    return r


def r05_coverage(ctx):
    r = Rule("R05")
    entries = entry_by_id(ctx)
    cited = set()
    for _, s in all_sentences(ctx):
        cited.update(s.get("ref_ids") or [])
    roles = ctx["ledgers"]["refs"].get("entries") or []
    role_map = {}
    for row in roles:
        if isinstance(row, dict) and row.get("ref_id"):
            role_map[row["ref_id"]] = row
    must = [e["ref_id"] for e in entries.values() if e.get("must_cite")]
    for row in roles:
        if isinstance(row, dict) and row.get("must_cite") and row.get("ref_id"):
            must.append(row["ref_id"])
    must = list(dict.fromkeys(must))
    for rid in must:
        r.checked += 1
        if rid not in cited:
            title = (entries.get(rid) or {}).get("title", rid)[:110]
            r.error("must_cite_missing",
                    "%s（%s）被标为必须引用，但成稿中没有引用它。" % (rid, title), ref_id=rid)
    for rid, row in role_map.items():
        if not isinstance(row, dict):
            continue
        role = (row.get("role") or "").strip()
        if role in ("seminal", "representative", "recent", "baseline") and rid not in cited:
            r.warn("role_work_uncited",
                   "%s 被标为 %s，但成稿未引用。" % (rid, role), ref_id=rid, role=role)
    uncited = [e["ref_id"] for e in entries.values() if e["ref_id"] not in cited]
    if uncited:
        r.info("library_entries_uncited",
               "文献库 %d 条中有 %d 条未被引用：%s" % (len(entries), len(uncited), ",".join(uncited[:24])),
               ref_ids=uncited)
    return r


def r06_recency(ctx):
    r = Rule("R06")
    entries = entry_by_id(ctx)
    years = [e["year"] for e in entries.values() if isinstance(e.get("year"), int)]
    if len(years) < 3:
        r.note = "文献库年份不足 3 条，跳过近期进展检查。"
        return r
    newest = max(years)
    window = newest - 2
    recent = {e["ref_id"] for e in entries.values()
              if isinstance(e.get("year"), int) and e["year"] >= window}
    cited = set()
    for _, s in all_sentences(ctx):
        cited.update(s.get("ref_ids") or [])
    r.checked = len(recent)
    if len(recent) >= 2 and not (recent & cited):
        r.warn("recent_progress_missing",
               "文献库有 %d 条 %d 年之后的条目（最新 %d），成稿一条都没引；相关工作需要覆盖近期进展。"
               % (len(recent), window, newest),
               recent_refs=sorted(recent)[:12], newest_year=newest)
    for rid in sorted(recent & cited):
        r.info("recent_work_cited", "%s 属于近三年工作，已引用。" % rid, ref_id=rid)
    return r


def r07_group_completeness(ctx):
    r = Rule("R07")
    groups = ctx["ledgers"]["groups"].get("groups") or []
    if not groups:
        r.note = "未提供 ledger_groups.json；分组结构无法核对。"
        r.warn("no_group_ledger",
               "没有分组账本，相关工作只能按逐篇排列检查（见 R08），分组维度无法核对。")
        return r
    for g in groups:
        if not isinstance(g, dict):
            continue
        gid = g.get("group_id") or g.get("label") or "?"
        works = g.get("works") or []
        r.checked += 1
        if len(works) < 2:
            if not (g.get("single_work_reason") or g.get("comparison", {}).get("single_work_reason")):
                r.warn("group_too_small",
                       "分组 %s 只有 %d 篇文献，没有比较对象，也不是有意为之（未给出 single_work_reason）。"
                       % (gid, len(works)), group=gid)
        if not (g.get("dimension") or (g.get("comparison") or {}).get("dimension")):
            r.error("group_no_dimension",
                    "分组 %s 没有声明比较维度（dimension），无法判断它是按问题、方法路线还是评价方式分组。" % gid,
                    group=gid)
        cmp_ = g.get("comparison") or {}
        if not (cmp_.get("tradeoff") or cmp_.get("takeaway")):
            r.error("group_no_tradeoff",
                    "分组 %s 没有写取舍结论（comparison.tradeoff），组内只是并列，没有比较。" % gid,
                    group=gid)
        for w in works:
            if not isinstance(w, dict):
                continue
            missing = [f for f in GROUP_FIELDS if not L.norm_ws(str(w.get(f) or ""))]
            if missing:
                r.warn("group_work_field_missing",
                       "分组 %s 中的 %s 缺字段 %s，无法在同一维度上比较。"
                       % (gid, w.get("ref_id") or w.get("title") or "?", ",".join(missing)),
                       group=gid, ref_id=w.get("ref_id"), fields=missing)
    ctx["_group_ids"] = {g.get("group_id") for g in groups if isinstance(g, dict) and g.get("group_id")}
    return r


def r08_serial_summary(ctx):
    r = Rule("R08")
    paras = [p for p in ctx["draft"]["paragraphs"] if p["part"] == "related_work"]
    if not paras:
        r.note = "成稿没有相关工作部分，跳过。"
        return r
    dist = []
    for p in paras:
        ids = []
        for s in p["sentences"]:
            ids.extend(s.get("ref_ids") or [])
        dist.append(list(dict.fromkeys(ids)))
    r.checked = len(paras)
    run = 0
    worst = []
    for i, ids in enumerate(dist):
        single = len(ids) == 1 and not COMPARATIVE_RE.search(paras[i]["text"])
        run = run + 1 if single else 0
        if run >= 3:
            worst.append(i)
    if worst:
        seg = dist[worst[0] - 2:worst[0] + 1]
        r.warn("serial_summary_pattern",
               "相关工作中连续 %d 段各自只讲一篇文献且没有比较词，属于逐篇摘要拼接，不是按维度比较。"
               % (run if not worst else 3),
               paragraphs=[i + 1 for i in worst[:8]],
               works=[[x for x in s] for s in seg])
    multi = sum(1 for ids in dist if len(ids) >= 2)
    if dist and multi == 0 and len(dist) >= 3:
        r.warn("no_cross_work_comparison",
               "相关工作 %d 段中没有任何一段同时讨论两篇及以上文献，缺少横向比较。"
               % len(dist))
    # sentence-level: three consecutive sentences each citing one work, in a paragraph
    # that never compares anything. Gated on the paragraph having no comparative
    # vocabulary at all, so an ordinary "one citation per sentence" paragraph in a
    # properly comparative section is not flagged.
    for p in paras:
        if COMPARATIVE_RE.search(p["text"]):
            continue
        sents = p["sentences"]
        streak = 0
        for s in sents:
            one = len(s.get("ref_ids") or []) == 1
            streak = streak + 1 if one else 0
            if streak >= 3:
                r.warn("sentence_serial_summary",
                       "同一段内连续 3 句各引一篇且整段没有任何比较词，读起来像文献罗列。",
                       part="related_work", para=p["index"], sentence=s["text"][:160])
                break
    return r


def r09_grouping_consistency(ctx):
    r = Rule("R09")
    groups = ctx["ledgers"]["groups"].get("groups") or []
    if not groups:
        r.note = "没有分组账本，跳过双向一致性检查。"
        return r
    grouped = {}
    for g in groups:
        if not isinstance(g, dict):
            continue
        gid = g.get("group_id") or "?"
        for w in g.get("works") or []:
            if isinstance(w, dict) and w.get("ref_id"):
                grouped.setdefault(w["ref_id"], []).append(gid)
    rw_cited = set()
    for p, s in all_sentences(ctx, "related_work"):
        rw_cited.update(s.get("ref_ids") or [])
    entries = entry_by_id(ctx)
    r.checked = len(rw_cited) + len(grouped)
    for rid in sorted(rw_cited):
        if rid not in grouped:
            r.error("cited_but_ungrouped",
                    "%s（%s）在相关工作中被引用，但没有进入任何分组，比较维度上无法定位它。"
                    % (rid, (entries.get(rid) or {}).get("title", "")[:90]),
                    ref_id=rid)
    for rid in sorted(grouped):
        if rid not in rw_cited:
            r.warn("grouped_but_uncited",
                   "%s 出现在分组账本中，但相关工作正文没有引用它。" % rid, ref_id=rid)
    return r


def r10_gap_provenance(ctx):
    r = Rule("R10")
    gaps = ctx["ledgers"]["gaps"].get("gaps") or []
    gap_part = ctx["draft"]["parts"].get("gap") or {}
    gap_text = gap_part.get("text") or ""
    gap_cites = set()
    for p, s in all_sentences(ctx, "gap"):
        gap_cites.update(s.get("ref_ids") or [])
    if not gaps:
        r.note = "未提供 ledger_gaps.json；空白推导无法核对。"
        if gap_text:
            r.warn("no_gap_ledger",
                   "有研究空白段落但没有空白账本，无法核对空白是否由已引文献的缺口推出。")
        return r
    entries = entry_by_id(ctx)
    rw_cited = set()
    for _, s in all_sentences(ctx, "related_work"):
        rw_cited.update(s.get("ref_ids") or [])
    kinds = set(L.LEDGER_SPEC["gaps"]["limitation_kinds"])
    r.checked = len(gaps)
    for g in gaps:
        if not isinstance(g, dict):
            continue
        gid = g.get("gap_id") or "?"
        srcs = g.get("derived_from") or []
        if not srcs:
            r.error("gap_without_source",
                    "空白 %s 没有 derived_from，属于无出处的断言。" % gid, gap=gid)
            continue
        for src in srcs:
            if not isinstance(src, dict):
                continue
            rid = src.get("ref_id")
            if not rid:
                continue
            if rid not in entries:
                r.error("gap_source_not_in_library",
                        "空白 %s 引用的 %s 不在文献库中。" % (gid, rid), gap=gid, ref_id=rid)
                continue
            if rid not in rw_cited:
                r.error("gap_from_uncited_work",
                        "空白 %s 声称由 %s 的局限推出，但相关工作正文没有引用 %s。"
                        % (gid, rid, rid), gap=gid, ref_id=rid)
            kind = src.get("limitation_kind") or ""
            if kind and kind not in kinds:
                r.warn("gap_limitation_kind_unknown",
                       "空白 %s 对 %s 的缺口类型 %r 不在词表内。" % (gid, rid, kind),
                       gap=gid, ref_id=rid)
            ev = src.get("evidence") or {}
            if isinstance(ev, str):
                ev = {"kind": "quote", "text": ev}
            ekind = (ev.get("kind") or "").lower()
            quote = ev.get("text") or ev.get("quote") or ""
            if ekind == "quote" and quote:
                hay = L.norm_cmp(" ".join([entries[rid].get("abstract", ""),
                                           entries[rid].get("notes", ""),
                                           entries[rid].get("note", "")]))
                needle = L.norm_cmp(quote)
                if not hay:
                    r.warn("quote_unchecked",
                           "空白 %s 以 %s 的原文为据，但该条目没有摘要/笔记文本，引文无法自动核对。"
                           % (gid, rid), gap=gid, ref_id=rid)
                elif needle and needle not in hay:
                    r.error("unverifiable_quote",
                            "空白 %s 引用的 %s 原文片段在该条目文本中找不到：%r"
                            % (gid, rid, quote[:90]), gap=gid, ref_id=rid, quote=quote[:200])
            elif ekind == "author_judgment":
                r.info("gap_author_judgment",
                       "空白 %s 对 %s 的判断标为作者判断。" % (gid, rid), gap=gid, ref_id=rid)
            elif not ekind:
                r.warn("gap_evidence_unspecified",
                       "空白 %s 对 %s 的证据没有说明 kind（quote / paraphrase / author_judgment）。"
                       % (gid, rid), gap=gid, ref_id=rid)
        hf = g.get("how_filled") or {}
        ids = hf.get("contribution_ids") or []
        if not ids:
            r.error("gap_not_mapped", "空白 %s 没有指明由哪条贡献填补（how_filled.contribution_ids）。" % gid,
                    gap=gid)
    if not gap_cites and gap_text.strip():
        r.warn("gap_paragraph_no_citation",
               "研究空白段落没有任何引用；空白应当从已引工作的缺口推出，而不是另起一段断言。")
    return r


def r11_gap_filled(ctx):
    r = Rule("R11")
    gaps = ctx["ledgers"]["gaps"].get("gaps") or []
    contribs = ctx["ledgers"]["contributions"].get("contributions") or []
    if not gaps:
        r.note = "没有空白账本，跳过。"
        return r
    cids = {c.get("contribution_id") for c in contribs if isinstance(c, dict)}
    gap_text = (ctx["draft"]["parts"].get("gap") or {}).get("text") or ""
    for g in gaps:
        if not isinstance(g, dict):
            continue
        r.checked += 1
        gid = g.get("gap_id") or "?"
        ids = ((g.get("how_filled") or {}).get("contribution_ids") or [])
        for cid in ids:
            if cid not in cids:
                r.error("gap_maps_unknown_contribution",
                        "空白 %s 指向的贡献 %s 不存在于贡献账本。" % (gid, cid), gap=gid, contribution=cid)
        if ids and not gap_text.strip():
            r.error("gap_part_empty", "有空白账本但成稿没有研究空白段落。", gap=gid)
    if gaps and gap_text and not OUR_WORK_RE.search(gap_text):
        r.warn("gap_not_linked_to_own_work",
               "研究空白段落没有出现“本文/本研究/we/our work”之类的衔接，读者看不出本文如何填补它。")
    return r


_LOCTYPE_RE = {"figure": L.FIG_RE, "table": L.TAB_RE}


def _locator_numbers(loc_type, locator):
    rx = _LOCTYPE_RE.get(loc_type)
    if not rx or not locator:
        return []
    return [int(m.group(1)) for m in rx.finditer(str(locator))]


def r12_contribution_evidence(ctx):
    r = Rule("R12")
    contribs = ctx["ledgers"]["contributions"].get("contributions") or []
    ms = ctx["manuscript"]
    figs = {f["number"] for f in ms.get("figures") or []}
    tabs = {t["number"] for t in ms.get("tables") or []}
    eqs = {e.get("label") for e in ms.get("equations") or []}
    sec_nums = {s.get("number") for s in ms.get("sections") or [] if s.get("number")}
    sec_titles = [L.norm_cmp(s.get("title")) for s in ms.get("sections") or []]
    ms_numbers = set(ms.get("numbers") or [])
    ms_text = ms.get("text") or ""
    if not contribs:
        r.note = "未提供 ledger_contributions.json；贡献与证据的对应无法核对。"
        r.warn("no_contribution_ledger",
               "没有贡献账本，无法核对每条贡献是否与本文字方法、图表、实验结果一一对应。")
        return r
    allowed = set(L.LEDGER_SPEC["contributions"]["locator_types"])
    for c in contribs:
        if not isinstance(c, dict):
            continue
        r.checked += 1
        cid = c.get("contribution_id") or "?"
        ev = c.get("evidence") or []
        if not ev:
            r.error("contribution_without_evidence",
                    "贡献 %s 没有任何证据定位，属于无法核对的断言：%s"
                    % (cid, L.norm_ws(str(c.get("text") or ""))[:120]), contribution=cid)
            continue
        ok = 0
        for item in ev:
            if not isinstance(item, dict):
                continue
            lt = (item.get("locator_type") or "").lower()
            loc = item.get("locator") or ""
            if lt not in allowed:
                r.warn("evidence_locator_type_unknown",
                       "贡献 %s 的证据类型 %r 不在词表内（%s）。" % (cid, lt, "/".join(sorted(allowed))),
                       contribution=cid)
                continue
            if lt == "figure":
                nums = _locator_numbers("figure", loc)
                if not nums:
                    r.error("evidence_locator_unparsable",
                            "贡献 %s 的图证据 %r 里没有图号。" % (cid, loc), contribution=cid)
                elif not (set(nums) & figs):
                    r.error("evidence_figure_missing",
                            "贡献 %s 指向 %s，但正文索引里没有该图（已识别图：%s）。"
                            % (cid, loc, sorted(figs) or "无"), contribution=cid, locator=loc)
                else:
                    ok += 1
            elif lt == "table":
                nums = _locator_numbers("table", loc)
                if not nums:
                    r.error("evidence_locator_unparsable",
                            "贡献 %s 的表证据 %r 里没有表号。" % (cid, loc), contribution=cid)
                elif not (set(nums) & tabs):
                    r.error("evidence_table_missing",
                            "贡献 %s 指向 %s，但正文索引里没有该表（已识别表：%s）。"
                            % (cid, loc, sorted(tabs) or "无"), contribution=cid, locator=loc)
                else:
                    ok += 1
            elif lt == "equation":
                lab = re.sub(r"[()（）]", "", str(loc)).strip()
                if lab in eqs:
                    ok += 1
                else:
                    r.warn("evidence_equation_missing",
                           "贡献 %s 指向公式 %s，正文索引里没有该编号。" % (cid, loc),
                           contribution=cid, locator=loc)
            elif lt == "section":
                s = L.norm_cmp(str(loc))
                hit = (str(loc).strip() in sec_nums) or any(s and (s in t or t in s) for t in sec_titles if t)
                if hit:
                    ok += 1
                else:
                    r.error("evidence_section_missing",
                            "贡献 %s 指向章节 %r，正文里找不到该章节。" % (cid, loc),
                            contribution=cid, locator=loc)
            elif lt == "result":
                claim = L.norm_ws(str(item.get("claim_in_source") or ""))
                if not claim:
                    r.error("evidence_result_without_quote",
                            "贡献 %s 的 result 证据没有 claim_in_source，无法核对结果数值。" % cid,
                            contribution=cid)
                    continue
                if claim and L.norm_cmp(claim) and L.norm_cmp(claim) in L.norm_cmp(ms_text):
                    ok += 1
                    continue
                nums = L.number_keys_of(claim)
                if nums and nums <= ms_numbers:
                    ok += 1
                elif nums:
                    missing = sorted(nums - ms_numbers)
                    r.error("evidence_result_not_in_source",
                            "贡献 %s 的结果数值 %s 在正文中找不到，疑似为写作补出的数字。"
                            % (cid, missing), contribution=cid, missing=missing)
                else:
                    r.warn("evidence_result_unverifiable",
                           "贡献 %s 的 result 证据既无原文匹配也无数字可比，未能核对。" % cid,
                           contribution=cid)
        if ok == 0 and ev:
            r.error("contribution_evidence_unresolved",
                    "贡献 %s 的 %d 条证据全部无法定位到本文字方法/图表/结果。" % (cid, len(ev)),
                    contribution=cid)
    return r


def r13_number_provenance(ctx):
    r = Rule("R13")
    ms = ctx["manuscript"]
    allowed = set(ms.get("numbers") or [])
    for e in (ctx["library"].get("entries") or []):
        allowed |= L.number_keys_of(" ".join([e.get("abstract", ""), e.get("title", ""), e.get("note", "")]))
    for p, s in all_sentences(ctx):
        r.checked += 1
        for d in L.extract_numbers(s["text"]):
            k = L.number_key(d["value"], d["unit"])
            if k in allowed:
                continue
            # a bare figure/table/section reference is not a result number
            r.error("invented_metric",
                    "成稿中的 %s%s 在本论文材料与文献库里都找不到出处。"
                    % (d["raw"], d["unit"]), value=d["raw"], unit=d["unit"],
                    sentence=s["text"][:180], part=p["part"])
    return r


def r14_structure(ctx):
    r = Rule("R14")
    d = ctx["draft"]
    r.checked = len(L.PART_ORDER)
    if d.get("method") == "none":
        r.note = "未识别到分部标记，整篇按一段处理。"
        r.error("structure_not_detected",
                "成稿没有 <!-- part:background --> 之类的分部标记，也没有可识别的四个小标题；"
                "无法确认背景/相关工作/空白/贡献四部分齐全。")
        return r
    order_seen = []
    for p in L.PART_ORDER:
        info = d["parts"][p]
        if not info["present"] or not info["paragraphs"]:
            r.error("part_missing",
                    "缺少 %s 部分（%s）。" % (p, L.PART_LABEL[p].get(d["lang"], p)), part=p)
        else:
            order_seen.append(p)
            if len(info["paragraphs"]) < 1:
                r.warn("part_too_short", "%s 部分只有标题没有正文。" % p, part=p)
        if p == "related_work" and info["present"] and len(info["paragraphs"]) < 2:
            r.warn("related_work_too_thin",
                   "相关工作只有 1 段；按维度分组比较通常需要多段或一张比较表。")
    if len(order_seen) == 4 and order_seen != L.PART_ORDER:
        r.warn("part_order", "四部分的顺序是 %s，建议 背景→相关工作→空白→贡献。" % "→".join(order_seen))
    gap_txt = (d["parts"]["gap"]["text"] or "")
    contrib_txt = (d["parts"]["contributions"]["text"] or "")
    if gap_txt and contrib_txt:
        g_ids = set()
        for g in ctx["ledgers"]["gaps"].get("gaps") or []:
            if isinstance(g, dict):
                g_ids.add(g.get("gap_id"))
        mentioned = {x for x in g_ids if x and (x in gap_txt or x in contrib_txt)}
        if g_ids and len(mentioned) < len(g_ids):
            r.info("gap_ids_not_carried",
                   "空白账本有 %d 条，正文只显式提到 %d 条编号（正文不必写编号，此项仅提示）。"
                   % (len(g_ids), len(mentioned)))
    return r


def r15_novelty_bounded(ctx):
    r = Rule("R15")
    contribs = ctx["ledgers"]["contributions"].get("contributions") or []
    scope_by_id = {c.get("contribution_id"): c.get("scope") or {}
                   for c in contribs if isinstance(c, dict)}
    for p, s in all_sentences(ctx):
        r.checked += 1
        if not SUPERLATIVE_RE.search(s["text"]):
            continue
        if p["part"] == "contributions" and contribs:
            # bounded if any contribution declares a scope limit
            bounded = any((sc.get("stated_limits") or sc.get("not_claimed")) for sc in scope_by_id.values())
            if not bounded:
                r.warn("unbounded_novelty_claim",
                       "贡献部分出现 %r 类拔高表述，但没有任何贡献声明适用范围/不主张的内容。"
                       % SUPERLATIVE_RE.search(s["text"]).group(0),
                       sentence=s["text"][:180], part=p["part"])
            continue
        if not (s.get("ref_ids") or _has_judgment(s["text"])):
            r.warn("unbounded_novelty_claim",
                   "该句出现 %r 类拔高表述，既没有引用也没有标注为作者判断。"
                   % SUPERLATIVE_RE.search(s["text"]).group(0),
                   sentence=s["text"][:180], part=p["part"])
    return r


def r16_vacuous(ctx):
    r = Rule("R16")
    for p in ctx["draft"]["paragraphs"]:
        r.checked += 1
        if p["part"] != "background":
            continue
        for rx, label in VACUOUS_RE:
            m = rx.search(p["text"])
            if m:
                r.warn("vacuous_background",
                       "背景中出现空转铺垫「%s」，没有指向具体问题或技术约束：%s"
                       % (label, L.norm_ws(m.group(0))[:110]),
                       part="background", para=p["index"], phrase=label)
                break
    for p in ctx["draft"]["paragraphs"]:
        if p["part"] != "background":
            continue
        cits = [s for s in p["sentences"] if s.get("ref_ids")]
        if cits:
            continue
        claims = [s for s in p["sentences"] if _is_claim(s["text"])]
        if len(claims) >= 2 and not _has_judgment(p["text"]):
            r.warn("background_paragraph_unsourced",
                   "背景中有 1 段含 %d 句论断且全段无引用，读者无法判断这些说法的来源。" % len(claims),
                   part="background", para=p["index"])
    return r


def r17_style_consistency(ctx):
    r = Rule("R17")
    styles = {}
    for p in ctx["draft"]["paragraphs"]:
        for s in p["sentences"]:
            for c in s.get("citations") or []:
                styles.setdefault(c["kind"], []).append(c["raw"])
    r.checked = len(styles)
    if len(styles) > 1:
        r.warn("mixed_citation_style",
               "成稿混用了多种引用标记：%s。目标格式下应统一。"
               % ", ".join("%s(%d)" % (k, len(v)) for k, v in styles.items()),
               styles={k: len(v) for k, v in styles.items()})
    want = ctx.get("target_citation_style")
    if want and want != "none" and styles:
        got = list(styles)
        if want in ("numeric",) and "numeric" not in got:
            r.warn("citation_style_mismatch", "任务要求数字制引用，成稿用的是 %s。" % ",".join(got))
        elif want in ("key", "latex", "pandoc") and "key" not in got:
            r.warn("citation_style_mismatch", "任务要求 \\cite/@key 形式引用，成稿用的是 %s。" % ",".join(got))
        elif want in ("author-year", "author_year") and "author-year" not in got:
            r.warn("citation_style_mismatch", "任务要求著者-年份制引用，成稿用的是 %s。" % ",".join(got))
    return r


def r18_abstract_metrics(ctx):
    r = Rule("R18")
    abs_ = ctx["manuscript"].get("abstract") or ""
    contribs = ctx["ledgers"]["contributions"].get("contributions") or []
    if not abs_:
        r.note = "稿件没有摘要，跳过。"
        return r
    keys = L.extract_numbers(abs_)
    if not keys:
        r.note = "摘要里没有带单位的数值。"
        return r
    claimable = set()
    for c in contribs:
        if not isinstance(c, dict):
            continue
        blob = " ".join([str(c.get("text") or "")] +
                        [str(e.get("claim_in_source") or "") for e in (c.get("evidence") or [])
                         if isinstance(e, dict)])
        claimable |= {L.number_key(d["value"], d["unit"]) for d in L.extract_numbers(blob)}
    draft_nums = set()
    for _, s in all_sentences(ctx):
        draft_nums |= {L.number_key(d["value"], d["unit"]) for d in L.extract_numbers(s["text"])}
    r.checked = len(keys)
    pooled = claimable | draft_nums
    for d in keys:
        k = L.number_key(d["value"], d["unit"])
        if k not in pooled:
            r.warn("abstract_metric_unclaimed",
                   "摘要里的关键数值 %s%s 没有进入任何贡献条目，也没有在引言/相关工作中出现；"
                   "读者无法从贡献列表看到这个结果。" % (d["raw"], d["unit"]),
                   value=d["raw"], unit=d["unit"])
    return r


RULES = [r01_citation_integrity, r02_uncited_claim, r03_citation_anchor, r04_metadata,
         r05_coverage, r06_recency, r07_group_completeness, r08_serial_summary,
         r09_grouping_consistency, r10_gap_provenance, r11_gap_filled,
         r12_contribution_evidence, r13_number_provenance, r14_structure,
         r15_novelty_bounded, r16_vacuous, r17_style_consistency, r18_abstract_metrics]


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #

def run_audit(ctx):
    """Run every rule and fold the results into one report.

    ctx keys: draft, library, lib_index, reflist, manuscript, ledgers, case_id,
              lang, target_citation_style, now_year
    """
    resolve_draft(ctx)
    results, by_q = [], {}
    for fn in RULES:
        try:
            rule = fn(ctx)
            res = rule.result()
        except Exception as exc:  # a broken rule must not take the report down
            rid = fn.__name__.split("_")[0].upper()
            res = {"id": rid, "title": RULE_TITLE.get(rid, fn.__name__), "question": QUESTION.get(rid, ""),
                   "status": "error", "checked": 0, "note": "rule crashed",
                   "n_error": 1, "n_warn": 0,
                   "findings": [_finding("rule_crashed", SEV_ERROR,
                                         "规则执行异常：%s: %s" % (type(exc).__name__, exc), rule=rid)]}
        results.append(res)
        q = res.get("question") or "其他"
        agg = by_q.setdefault(q, {"error": 0, "warn": 0, "pass": 0, "checks": []})
        agg["error"] += res["n_error"]
        agg["warn"] += res["n_warn"]
        if res["status"] == "pass":
            agg["pass"] += 1
        agg["checks"].append({"id": res["id"], "title": res["title"], "status": res["status"]})

    n_err = sum(x["n_error"] for x in results)
    n_warn = sum(x["n_warn"] for x in results)
    n_info = sum(1 for x in results for f in x["findings"] if f["severity"] == SEV_INFO)
    gate = "pass" if n_err == 0 else "fail"
    must_fix = []
    for x in results:
        for f in x["findings"]:
            if f["severity"] == SEV_ERROR:
                must_fix.append({"rule": x["id"], "question": x["question"], "code": f["code"],
                                 "message": f["message"]})
    return {
        "case_id": ctx.get("case_id"),
        "gate": gate,
        "summary": {
            "checks_run": len(results),
            "errors": n_err,
            "warnings": n_warn,
            "infos": n_info,
            "rules_failed": [x["id"] for x in results if x["status"] == "error"],
            "rules_warned": [x["id"] for x in results if x["status"] == "warn"],
        },
        "must_fix": must_fix[:40],
        "by_question": by_q,
        "checks": results,
    }
