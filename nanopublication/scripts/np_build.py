#!/usr/bin/env python3
"""np_build.py - locate quotes, finalise the result bundle, export TriG.

Subcommands:
    locate    --text T --quote Q            print {page, paragraph, sentence, char_offset}
    finalise  --assertions A.yaml --text T --out DIR --case case.json [--relations R.json]
                                            fill locators, validate, write result.json,
                                            assertions.json, assertions.md, report.md
    trig      --assertions assertions.json --doc doc.json --out nanopubs.trig
                                             W3C-Nanopub-shaped TriG

assertions.yaml is a "relaxed YAML" file: a JSON list also parses.
"""
import argparse
import datetime
import hashlib
from urllib.parse import quote as uri_quote, urlsplit
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import np_validate  # noqa: E402
from np_validate import page_para_sent  # noqa: E402

MARK_RE = re.compile(r"^=== page (\d+) ===$", re.M)
SCHEMA_VER = "nanopub-skill/1.0"


# ----------------------------------------------------------------- parsing
def load_yaml_or_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        import yaml  # type: ignore
        return yaml.safe_load(raw)
    except Exception:
        pass
    return _mini_yaml(raw)


def _mini_yaml(raw):
    """Tiny YAML subset parser: a list of mappings.
    Supports flat keys, inline {..}/[..}, and one level of nested block lists:
        - id: A1
          inference_chain:
            - from: [A6]
              to: this
    Also accepts a top-level JSON array (handled by the caller)."""
    items, cur, sub_list, sub_item, indent = [], None, None, None, None
    for raw_line in raw.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        ind = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if line.startswith("- ") and ind == 0:
            cur, sub_list, sub_item = {}, None, None
            items.append(cur)
            line = line[2:].strip()
            m = re.match(r"^([A-Za-z_]\w*)\s*:\s*(.*)$", line)
            if m:
                cur[m.group(1)] = _val(m.group(2))
            continue
        if sub_list is not None and line.startswith("- ") and ind > (indent or 0):
            sub_item = {}
            sub_list.append(sub_item)
            m = re.match(r"^([A-Za-z_]\w*)\s*:\s*(.*)$", line[2:].strip())
            if m:
                sub_item[m.group(1)] = _val(m.group(2))
            continue
        m = re.match(r"^([A-Za-z_]\w*)\s*:\s*(.*)$", line)
        if not m or cur is None:
            continue
        k, v = m.group(1), m.group(2).strip()
        if ind > (indent or 0) and sub_item is not None:
            sub_item[k] = _val(v)
            continue
        if v == "":
            sub_list, indent = [], ind
            cur[k] = sub_list
            sub_item = None
        else:
            sub_list, sub_item, indent = None, None, ind
            cur[k] = _val(v)
    return items


def normalise_assertion(x):
    """Accept flat shorthand (quote / relation / locator at top level) and fold it into evidence."""
    ev = x.get("evidence")
    if not isinstance(ev, dict):
        ev = {}
    for k in ("quote", "relation", "quote_verbatim", "locator", "normalization_note"):
        if k in x and x[k] not in (None, "", {}):
            ev.setdefault(k, x.pop(k))
        elif k in x:
            x.pop(k)
    x["evidence"] = ev
    ev.setdefault("relation", "direct")
    ev.setdefault("quote_verbatim", ev.get("quote") is not None)
    ev.setdefault("locator", {})
    if x.get("qualifiers") in ({}, []):
        x["qualifiers"] = None
    x.setdefault("qualifiers", None)
    for k in ("hedge", "claimed_by"):
        x.setdefault(k, None)
    # Optional fields: present only when they carry a value (schema: no null for these).
    for k in ("controlling_quote", "controlling_quote_scope", "confidence_reason",
              "narrative_role", "inference_chain"):
        if k in x and x[k] in (None, "", []):
            del x[k]
    if x.get("supporting_evidence"):
        x["supporting_evidence"] = [s for s in x["supporting_evidence"] if s]
    else:
        x.pop("supporting_evidence", None)
    return x


def _split_top(s, sep=","):
    """Split s on sep at bracket depth 0, respecting quotes. Returns list of parts."""
    parts, depth, cur, q = [], 0, [], None
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p for p in (p.strip() for p in parts) if p]


def _val(v):
    v = v.strip()
    if v == "":
        return None
    if v.startswith("{") and v.endswith("}"):
        out = {}
        for part in _split_top(v[1:-1]):
            m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", part, re.S)
            if m:
                out[m.group(1)] = _val(m.group(2))
        return out
    if v.startswith("[") and v.endswith("]"):
        return [_val(p) for p in _split_top(v[1:-1])]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.lower() in ("null", "~"):
        return None
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except Exception:
        pass
    try:
        return float(v)
    except Exception:
        pass
    return v


# ----------------------------------------------------------------- locating
def locate(text, quote, hints=None):
    """Return every candidate and the candidates consistent with all supplied hints."""
    if not isinstance(quote, str) or not quote.strip():
        return [], []
    hints = hints or {}
    quote = quote.strip()
    pattern = r"\s+".join(re.escape(word).replace(r"\-", r"-(?:[^\S\n]*\n[^\S\n]*)?")
                          for word in quote.split())
    # Keep complete Latin words and identifiers while allowing Chinese substrings.
    if re.match(r"[A-Za-z0-9_]", quote):
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if re.search(r"[A-Za-z0-9_]$", quote):
        pattern += r"(?![A-Za-z0-9_])"
    offsets = np_validate.page_offsets(text)
    candidates, matches = [], []
    for match in re.finditer(rf"(?=({pattern}))", text):
        start, end = match.span(1)
        if MARK_RE.search(text, start, end):
            continue
        page, paragraph, sentence = page_para_sent(text, start, offsets)
        candidate = {"page": page, "paragraph": paragraph, "sentence": sentence,
                     "char_offset": [start, end]}
        candidates.append(candidate)
        if any(hints.get(key) not in (None, value) for key, value in candidate.items()):
            continue
        prefix = " ".join(str(hints.get("prefix") or "").split())
        suffix = " ".join(str(hints.get("suffix") or "").split())
        if prefix and not " ".join(text[:start].split()).endswith(prefix):
            continue
        if suffix and not " ".join(text[end:].split()).startswith(suffix):
            continue
        matches.append(candidate)
    return candidates, matches


# ----------------------------------------------------------------- finalise
def load_case(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def bind_evidence(evidence, text, label, item, unresolved):
    quote = evidence.get("quote")
    hints = evidence.get("locator") or {}
    candidates, matches = locate(text, quote, hints)
    if len(matches) != 1:
        if not candidates:
            reason, detail = "quote_not_found", "quote was not found in source"
        elif not matches:
            reason, detail = "ambiguous", "no occurrence matches the locator hints"
        else:
            reason, detail = "ambiguous", "more than one occurrence matches the locator hints"
        issue = {"item": item, "reason": reason, "review_required": True, "evidence_id": label,
                 "detail": f"{label}: {detail}", "quote": quote}
        if hints:
            issue["locator_hint"] = hints
        if candidates:
            issue["candidates"] = matches or candidates
        unresolved.append(issue)
        return False
    locator = matches[0]
    start, end = locator["char_offset"]
    evidence["quote"] = text[start:end]
    evidence["locator"] = {**hints, **locator}
    return True


def fill_assertion(assertion, text, unresolved):
    ev = assertion["evidence"]
    aid, item = assertion["id"], assertion.get("text") or assertion["id"]
    if ev["relation"] == "not_reported":
        ev.update(quote="", quote_verbatim=False, locator={"char_offset": None})
        unresolved.append({"assertion_id": aid, "item": item, "reason": "not_reported"})
        return True
    quote = ev.get("quote")
    if not bind_evidence(ev, text, aid, item, unresolved):
        return False
    ev["quote_verbatim"] = True
    if ev["quote"] != quote:
        ev["normalization_note"] = "quote stored as the exact source slice after matching PDF wrapping"
    supporting = [e for index, e in enumerate(assertion.get("supporting_evidence") or [], 1)
                  if bind_evidence(e, text, f"{aid} supporting evidence {index}", item, unresolved)]
    if supporting:
        assertion["supporting_evidence"] = supporting
    else:
        assertion.pop("supporting_evidence", None)
    if assertion.get("controlling_quote"):
        locator = dict(assertion.get("controlling_quote_locator") or {})
        if assertion.get("controlling_quote_offset") is not None:
            locator.setdefault("char_offset", assertion["controlling_quote_offset"])
        locator.setdefault("page", ev["locator"]["page"])
        evidence = {"quote": assertion["controlling_quote"], "locator": locator}
        if not bind_evidence(evidence, text, f"{aid} controlling quote", item, unresolved):
            return False
        assertion["controlling_quote"] = evidence["quote"]
        assertion["controlling_quote_locator"] = evidence["locator"]
        assertion["controlling_quote_offset"] = evidence["locator"]["char_offset"]
    return True


def coverage(text, assertions):
    """Count non-empty paragraphs per physical page, including short results and tables."""
    paras = set()
    # Match content between page markers and blank lines, preserving original offsets.
    start = 0
    offsets = np_validate.page_offsets(text)
    for boundary in re.finditer(r"^=== page \d+ ===$|\n[ \t]*\n|\Z", text, re.M):
        content = re.search(r"\S", text[start:boundary.start()])
        if content:
            paras.add(page_para_sent(text, start + content.start(), offsets)[:2])
        start = boundary.end()
    quoted_paras = set()
    for a in assertions:
        co = ((a.get("evidence") or {}).get("locator") or {}).get("char_offset")
        if co:
            quoted_paras.add(page_para_sent(text, co[0], offsets)[:2])
    covered = len(quoted_paras & paras)
    return {"paragraphs_total": len(paras), "paragraphs_with_assertion": covered,
            "ratio": round(covered / len(paras), 3) if paras else None}


def to_markdown(np_):
    lines = [f"# Assertions ({len(np_['assertions'])})", ""]
    for a in np_["assertions"]:
        ev = a.get("evidence") or {}
        loc = ev.get("locator") or {}
        lines.append(f"## {a.get('id')} [{a.get('claim_type')}; {ev.get('relation')}; {a.get('confidence')}]")
        lines.append(f"- text: {a.get('text')}")
        lines.append(f"- S-P-O: {a.get('subject')} | {a.get('predicate')} | {a.get('object')}")
        if a.get("qualifiers"):
            lines.append(f"- qualifiers: {json.dumps(a.get('qualifiers'), ensure_ascii=False)}")
        if a.get("hedge"):
            lines.append(f"- hedge: {a.get('hedge')}")
        if a.get("claimed_by"):
            lines.append(f"- claimed_by: {a.get('claimed_by')}")
        lines.append(f"- quote: \"{ev.get('quote')}\"")
        lines.append(f"- locator: page {loc.get('page')}, paragraph {loc.get('paragraph')}, sentence {loc.get('sentence')}, chars {loc.get('char_offset')}")
        if a.get("controlling_quote"):
            lines.append(f"- controlling quote: \"{a.get('controlling_quote')}\" ({a.get('controlling_quote_scope')})")
        if a.get("inference_chain"):
            lines.append(f"- inference: {json.dumps(a.get('inference_chain'), ensure_ascii=False)}")
        for se in a.get("supporting_evidence") or []:
            lines.append(f"- supporting: \"{se.get('quote')}\"")
        lines.append("")
    if np_.get("relations"):
        lines += [f"# Relations ({len(np_['relations'])})", ""]
        for r in np_["relations"]:
            lines.append(f"- {r.get('subject')} **{r.get('predicate')}** {r.get('object')} ({r.get('confidence')})")
            lines.append(f"  - quote: \"{(r.get('evidence') or {}).get('quote')}\"")
    if np_.get("unresolved"):
        lines += ["", f"# Unresolved ({len(np_['unresolved'])})", ""]
        for u in np_["unresolved"]:
            lines.append(f"- {u.get('item')} ({u.get('reason')})")
    return "\n".join(lines) + "\n"


def to_report(np_, case, checks, stats, text_meta, status):
    lines = ["# Reading report", ""]
    lines.append(f"- case_id: {case.get('case_id')}")
    lines.append(f"- status: {status}")
    lines.append(f"- schema: {np_.get('schema_version')}")
    if text_meta:
        lines.append(f"- source: {text_meta.get('path')} (backend {text_meta.get('backend')}, pages {text_meta.get('pages')})")
    doc = np_.get("document") or {}
    lines.append(f"- document: {doc.get('title')}  ({doc.get('year')})  doi:{doc.get('doi')}")
    lines.append("")
    lines.append("## Coverage")
    lines.append(f"- paragraphs with claims: {np_['quality']['coverage']['paragraphs_with_assertion']} / {np_['quality']['coverage']['paragraphs_total']}")
    lines.append(f"- claims: {stats['n_assertions']} (direct {stats['n_direct']}, inferred {stats['n_inferred']}, not_reported {stats['n_not_reported']})")
    lines.append(f"- relations: {stats['n_relations']}")
    lines.append("")
    lines.append("## Quality checks")
    for c in checks:
        lines.append(f"- {'PASS' if c['passed'] else 'FAIL'} {c['id']}: {c['detail']}")
    lines.append("")
    if np_.get("unresolved"):
        lines.append("## Unresolved")
        for u in np_["unresolved"]:
            lines.append(f"- {u.get('item')} ({u.get('reason')})")
            if u.get("detail"):
                lines.append(f"  - {u['detail']}")
            if u.get("quote"):
                lines.append(f"  - Submitted quote: {u['quote']!r}")
            if u.get("locator_hint"):
                lines.append(f"  - Locator hint: {u['locator_hint']}")
            for candidate in u.get("candidates", []):
                lines.append(f"  - Candidate: page {candidate['page']}, paragraph {candidate['paragraph']},"
                             f" sentence {candidate['sentence']}, chars {candidate['char_offset']}")
        lines.append("")
    lines += ["## Claim and evidence review", "",
              "Check which subject each value describes, what was measured and under which conditions.",
              "", "| Claim | Text | Evidence |", "|---|---|---|"]
    for assertion in np_["assertions"]:
        quote = assertion["evidence"].get("quote")
        if quote:
            if assertion.get("controlling_quote"):
                quote += " [Scope] " + assertion["controlling_quote"]
            statement, quote = (" ".join(value.split()).replace("|", "\\|")
                                for value in (str(assertion.get("text") or ""), quote))
            lines.append(f"| {assertion['id']} | {statement} | {quote} |")
    lines.append("")
    lines.append("## Limitations")
    lines.append("- Only the material provided for this case was read; no external sources were used.")
    lines.append("- Inferred claims use only source facts plus arithmetic/logic; see each inference_chain.")
    lines.append("- Reading scope and any OCR pages are listed in result.json sources.")
    return "\n".join(lines) + "\n"


def cmd_finalise(a):
    with open(a.text, encoding="utf-8") as f:
        text = f.read()
    raw = load_yaml_or_json(a.assertions) or []
    if isinstance(raw, dict):
        raw = raw.get("assertions", [])
    rels = (load_yaml_or_json(a.relations) or []) if a.relations else []
    doc = (load_yaml_or_json(a.doc) or {}) if a.doc else {}
    case = load_case(a.case)
    meta = load_case(a.text_meta)
    unresolved = (load_yaml_or_json(a.unresolved) or []) if a.unresolved else []
    for label, records in (("assertions", raw), ("relations", rels), ("unresolved", unresolved)):
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError(f"{label} must contain a list of objects")
    extraction_failed = meta.get("status") == "failed"
    missing_pages = meta.get("pages_without_text", [])
    if extraction_failed or missing_pages:
        details = [meta.get("reason"), meta.get("note"),
                   f"no text on in-scope pages {missing_pages}" if missing_pages else None]
        unresolved.append({"item": "Source text could not be read in full", "reason": "source_unavailable",
                           "detail": " | ".join(filter(None, details))})
    assertions = []
    for i, x in enumerate(raw, 1):
        normalise_assertion(x)
        if not x.get("id"):
            x["id"] = f"A{i}"
        if fill_assertion(x, text, unresolved):
            assertions.append(x)
    invalid = np_validate.unsupported_inferences(assertions, text)
    for assertion in assertions:
        aid = assertion["id"]
        if aid in invalid:
            unresolved.append({"item": assertion["text"], "evidence_id": aid, "reason": "unsupported_inference",
                               "detail": f"{aid}: inference needs an acyclic chain to verified direct evidence"})
    assertions = [assertion for assertion in assertions if assertion["id"] not in invalid]
    ids = {assertion["id"] for assertion in assertions}
    relations = []
    for i, r in enumerate(rels, 1):
        if not r.get("id"):
            r["id"] = f"R{i}"
        item = f"{r.get('subject')} {r.get('predicate')} {r.get('object')}"
        if r.get("subject") not in ids or r.get("object") not in ids:
            unresolved.append({"item": item, "evidence_id": r["id"], "reason": "ambiguous",
                               "review_required": True, "detail": f"{r['id']}: relation refers to an unavailable claim"})
        elif bind_evidence(r.setdefault("evidence", {}), text, r["id"], item, unresolved):
            relations.append(r)
    np_ = {"schema_version": SCHEMA_VER,
           "document": {"title": doc.get("title"), "authors": doc.get("authors") or [], "year": doc.get("year"),
                        "doi": doc.get("doi"), "venue": doc.get("venue"), "version": doc.get("version"),
                        "identifier_type": "doi" if doc.get("doi") else None,
                        "identifier_value": doc.get("doi")},
           "assertions": assertions, "relations": relations, "unresolved": unresolved}
    checks, stats = np_validate.validate({**np_, "ocr_pages": meta.get("ocr_pages", [])}, text)
    np_["quality"] = {**stats, "coverage": coverage(text, assertions), "checks": checks}
    cited_pages = {page for record in assertions + relations for page in np_validate.evidence_pages(record)}
    reviewed = meta.get("pages_read", [])
    if not isinstance(reviewed, list) or any(type(page) is not int or page < 1 for page in reviewed):
        raise ValueError("pages_read must list reviewed physical page numbers")
    page_keys = ("pages_requested", "pages_without_text", "pages_with_native_text", "ocr_pages")
    sources = [{"path": meta.get("path") or a.text, "kind": meta.get("backend") or "text",
                "pages_read": sorted(set(reviewed) | cited_pages),
                "pages_with_text": meta.get("pages_with_text") or [], "sha256": meta.get("sha256"), "out": a.text,
                **{key: meta[key] for key in page_keys if key in meta}}]
    result = dict.fromkeys(np_validate.contract_fields(case))
    if a.fields:
        with open(a.fields, encoding="utf-8-sig") as f:
            fields = json.load(f)
        if not isinstance(fields, dict):
            raise ValueError("--fields must be a JSON object")
        result.update(fields)
    result["case_id"] = case.get("case_id")
    result["status"] = "failed" if extraction_failed else a.status
    result["sources"] = sources
    result["nanopub"] = np_
    checks.append(np_validate.schema_check(result))
    checks.append(np_validate.contract_check(result, case))
    checks.sort(key=lambda entry: (int(re.match(r"Q(\d+)", entry["id"])[1]), entry["id"]))
    passed = all(c["passed"] for c in checks)
    status = "partial" if result["status"] == "success" and not passed else result["status"]
    result["status"] = status
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "assertions.json"), "w", encoding="utf-8") as f:
        json.dump({"assertions": assertions, "relations": relations, "unresolved": unresolved}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "assertions.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(np_))
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(to_report(np_, case, checks, stats, meta, status))
    print(json.dumps({"status": status, "checks": [(c["id"], c["passed"]) for c in checks],
                      "issues": [c["detail"] for c in checks if not c["passed"]], "out": a.out}, indent=2))
    return 0 if passed and status != "failed" else 1


# ----------------------------------------------------------------- trig
def rdf_literal(value):
    return json.dumps(str(value), ensure_ascii=False)


def cmd_trig(a):
    data = load_yaml_or_json(a.assertions)
    graph = data.get("nanopub", data) if isinstance(data, dict) else {"assertions": data}
    assertions = graph.get("assertions", [])
    doc = load_case(a.doc) if a.doc else graph.get("document") or {}
    digest = hashlib.sha256(json.dumps([doc, graph], sort_keys=True).encode()).hexdigest()
    base = a.base or f"urn:nanopub:{digest}:"
    for iri in (base, a.orcid):
        if iri and (not urlsplit(iri).scheme or re.search(r'[\s<>"{}|^\x60\\]', iri)):
            raise ValueError("RDF identifiers require an absolute IRI without unsafe delimiters")
    def resource(kind, value):
        return "<" + base + kind + uri_quote(str(value), safe="") + ">"
    lines = ["@prefix np: <http://www.nanopub.org/nschema#> .",
             "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
             "@prefix dc: <http://purl.org/dc/terms/> .",
             "@prefix prov: <http://www.w3.org/ns/prov#> .",
             "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> ."]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    published = {x["id"] for x in assertions if x["evidence"]["relation"] != "not_reported"}
    for x in assertions:
        aid = x["id"]
        if aid not in published:
            continue
        pub, head, ag, pg, info, statement = (resource(kind, aid) for kind in
            ("publication-", "head-", "assertion-", "provenance-", "pubinfo-", "statement-"))
        ev = x["evidence"]
        lines.extend([f"{head} {{ {pub} a np:Nanopublication ; np:hasAssertion {ag} ;",
                      f"  np:hasProvenance {pg} ; np:hasPublicationInfo {info} . }}",
                      f"{ag} {{ {statement} a rdf:Statement ;",
                      f"  rdf:subject {resource('entity/', x['subject'])} ;",
                      f"  rdf:predicate {resource('predicate/', x['predicate'])} ;",
                      f"  rdf:object {rdf_literal(x['object'])} ; dc:description {rdf_literal(x['text'])} ."])
        for key in ("qualifiers", "hedge", "claimed_by", "confidence", "inference_chain"):
            if x.get(key):
                value = json.dumps(x[key], ensure_ascii=False) if isinstance(x[key], (dict, list)) else x[key]
                lines.append(f"  {statement} {resource('field/', key)} {rdf_literal(value)} .")
        lines.extend(["}", f"{pg} {{ {ag} dc:description {rdf_literal(ev['quote'])} ;",
                      f"  {resource('field/', 'locator')} {rdf_literal(json.dumps(ev['locator']))} ;",
                      f"  {resource('field/', 'evidenceRelation')} {rdf_literal(ev['relation'])} ."])
        if doc.get("doi"):
            doi = re.sub(r"^https://doi\.org/", "", str(doc["doi"]))
            lines.append(f"  {ag} prov:wasDerivedFrom <https://doi.org/{uri_quote(doi, safe='/')}> .")
        if doc.get("title"):
            lines.append(f"  {ag} dc:source {rdf_literal(doc['title'])} .")
        lines.extend(["}", f"{info} {{ {pub} dc:created {rdf_literal(now)}^^xsd:dateTime ."])
        if a.orcid:
            lines.append(f"  {pub} dc:creator <{a.orcid}> .")
        lines.append("}")
    for edge in graph.get("relations", []):
        if edge["subject"] in published and edge["object"] in published:
            lines.append(f"{resource('assertion-', edge['subject'])} {resource('relation/', edge['predicate'])} "
                         f"{resource('assertion-', edge['object'])} .")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps({"status": "ok", "n": len(published), "out": str(a.out)}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("locate")
    p.add_argument("--text", required=True)
    p.add_argument("--quote", required=True)
    p.add_argument("--page", type=int)
    p.add_argument("--paragraph", type=int)
    p.add_argument("--sentence", type=int)
    p.add_argument("--prefix")
    p.add_argument("--suffix")
    p = sub.add_parser("finalise")
    p.add_argument("--assertions", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--case")
    p.add_argument("--doc")
    p.add_argument("--relations")
    p.add_argument("--unresolved")
    p.add_argument("--text-meta")
    p.add_argument("--fields", help="JSON object with answers and other output_contract fields")
    p.add_argument("--status", choices=("partial", "success", "failed"), default="partial")
    p = sub.add_parser("trig")
    p.add_argument("--assertions", required=True)
    p.add_argument("--doc")
    p.add_argument("--out", required=True)
    p.add_argument("--base")
    p.add_argument("--orcid")
    a = ap.parse_args()
    if a.cmd == "locate":
        text = open(a.text, "r", encoding="utf-8").read()
        hints = {key: getattr(a, key) for key in ("page", "paragraph", "sentence", "prefix", "suffix")}
        candidates, matches = locate(text, a.quote, hints)
        if len(matches) != 1:
            print(json.dumps({"found": False, "occurrences": len(candidates),
                              "candidates": matches or candidates, "quote": a.quote}))
            return 1
        print(json.dumps({"found": True, "occurrences": len(candidates), **matches[0]}))
        return 0
    if a.cmd == "finalise":
        try:
            return cmd_finalise(a)
        except (OSError, ValueError) as exc:
            print(f"cannot finalise: {exc}", file=sys.stderr)
            return 2
    if a.cmd == "trig":
        return cmd_trig(a)
    return 1


if __name__ == "__main__":
    sys.exit(main())
