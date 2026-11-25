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
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import np_validate  # noqa: E402

MARK_RE = re.compile(r"^=== page (\d+) ===$", re.M)
HERE = os.path.dirname(os.path.abspath(__file__))
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
def page_starts(text):
    return [(int(m.group(1)), m.start()) for m in MARK_RE.finditer(text)]


def page_para_sent(text, pos):
    """Return (page, paragraph, sentence) for char position pos."""
    starts = page_starts(text)
    page, pstart = 1, 0
    for p, s in starts:
        if s <= pos:
            page, pstart = p, s
        else:
            break
    seg = text[pstart:pos]
    # drop marker line
    seg = re.sub(r"^=== page \d+ ===\n?", "", seg)
    paras = re.split(r"\n\s*\n", seg)
    paragraph = len(paras)
    sent_in_para = paras[-1]
    # sentence split: . ! ? followed by space or end
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", sent_in_para)
    sentence = len(parts)
    return page, paragraph, sentence


def find_all(text, quote):
    return [m.start() for m in re.finditer(re.escape(quote), text)]


def locate(text, quote):
    hits = find_all(text, quote)
    if hits:
        return (hits[0], hits[0] + len(quote)), len(hits)
    # Fallback 1: whitespace-normalised match (PDF line breaks inside the quote).
    pat = re.escape(quote)
    pat = re.sub(r"\\(n| |\t)", r"\\s+", pat)
    pat = re.sub(r"\\\n", r"\\s+", pat)
    m = re.search(pat, text)
    if m:
        return (m.start(), m.end()), 1
    # Fallback 2: tolerate hyphen+line-break inside a word ("English-\nto-German")
    # and any whitespace run where the quote has a space.
    pat2 = re.escape(quote)
    pat2 = pat2.replace(r"\-", r"(?:-\s*\n\s*|-\s*)")
    pat2 = re.sub(r"(\\ |\\n|\\t)+", r"\\s+", pat2)
    m = re.search(pat2, text)
    if m:
        return (m.start(), m.end()), 1
    return None, 0


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


# ----------------------------------------------------------------- finalise
def load_case(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fill_assertion(a, text, warn):
    a.setdefault("id", None)
    a.setdefault("evidence", {})
    ev = a["evidence"]
    q = ev.get("quote")
    rel = ev.get("relation", "direct")
    if rel == "not_reported" or not q:
        ev["relation"] = rel if rel else "not_reported"
        ev.setdefault("quote_verbatim", False)
        ev.setdefault("locator", {})
        return
    span, nhits = locate(text, q)
    if span is None:
        warn.append(f"{a['id']}: quote not found in text; marked inferred")
        ev["relation"] = "inferred"
        ev["quote_verbatim"] = False
        ev.setdefault("locator", {})
        a.setdefault("inference_chain", [{"from": [], "to": "this", "rationale": "quote reconstruction failed"}])
        a["confidence"] = "low"
        return
    if nhits > 1:
        warn.append(f"{a['id']}: quote occurs {nhits} times; first occurrence used")
    start, end = span
    exact = text[start:end] == q
    if not exact:
        # Whitespace-normalised match (PDF line breaks inside the quote). Store the exact
        # source slice so text[start:end] == quote holds; the words are unchanged.
        ev["quote"] = text[start:end]
        ev["quote_verbatim"] = True
        ev.setdefault("normalization_note", "quote stored as exact source slice; input differed only in whitespace")
        q = ev["quote"]
    else:
        ev["quote_verbatim"] = True
    page, paragraph, sentence = page_para_sent(text, start)
    loc = ev.get("locator") or {}
    loc.update({"page": loc.get("page") or page, "paragraph": loc.get("paragraph") or paragraph,
                "sentence": loc.get("sentence") or sentence, "char_offset": [start, end]})
    ev["locator"] = loc
    for se in a.get("supporting_evidence") or []:
        sq = se.get("quote")
        sspan, _ = locate(text, sq) if sq else (None, 0)
        if sspan:
            sp,appar,ss = page_para_sent(text, sspan[0])
            se["locator"] = {"page": sp, "paragraph": appar, "sentence": ss, "char_offset": list(sspan)}
    cq = a.get("controlling_quote")
    if cq:
        cspan, _ = locate(text, cq)
        if cspan:
            a["controlling_quote_offset"] = list(cspan)


def coverage(text, assertions):
    """Count source paragraphs (>=5 words) and how many carry at least one quote."""
    body = re.sub(r"^=== page \d+ ===$", "", text, flags=re.M)
    paras = [p for p in re.split(r"\n\s*\n", body) if word_count(p) >= 5]
    quoted_paras = set()
    for a in assertions:
        co = ((a.get("evidence") or {}).get("locator") or {}).get("char_offset")
        if co:
            quoted_paras.add(page_para_sent(text, co[0])[:2])
    return {"paragraphs_total": len(paras), "paragraphs_with_assertion": len(quoted_paras),
            "ratio": round(len(quoted_paras) / len(paras), 3) if paras else None}


def word_count(s):
    return len(re.findall(r"\w+", s))


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


def to_report(np_, case, warn, checks, stats, text_meta, status):
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
    if warn:
        lines.append("## Warnings from finalise")
        lines += [f"- {w}" for w in warn]
        lines.append("")
    if np_.get("unresolved"):
        lines.append("## Unresolved")
        for u in np_["unresolved"]:
            lines.append(f"- {u.get('item')} ({u.get('reason')})")
        lines.append("")
    lines.append("## Limitations")
    lines.append("- Only the material provided for this case was read; no external sources were used.")
    lines.append("- Inferred claims use only source facts plus arithmetic/logic; see each inference_chain.")
    lines.append("- Reading scope and any OCR pages are listed in result.json sources.")
    return "\n".join(lines) + "\n"


def cmd_finalise(a):
    text = open(a.text, "r", encoding="utf-8").read()
    raw = load_yaml_or_json(a.assertions)
    if isinstance(raw, dict):
        raw = raw.get("assertions", [])
    rels = []
    if a.relations and os.path.isfile(a.relations):
        rels = load_yaml_or_json(a.relations)
    doc = load_yaml_or_json(a.doc) if a.doc and os.path.isfile(a.doc) else {}
    case = load_case(a.case)
    warn = []
    for i, x in enumerate(raw, 1):
        if not isinstance(x, dict):
            continue
        normalise_assertion(x)
        if not x.get("id"):
            x["id"] = f"A{i}"
        fill_assertion(x, text, warn)
    raw = [x for x in raw if isinstance(x, dict)]
    for i, r in enumerate(rels, 1):
        if not r.get("id"):
            r["id"] = f"R{i}"
        if r.get("evidence") and r["evidence"].get("quote"):
            span, _ = locate(text, r["evidence"]["quote"])
            if span:
                p,appar,s = page_para_sent(text, span[0])
                r["evidence"] = {"quote": text[span[0]:span[1]],
                                 "locator": {"page": p, "paragraph": appar, "sentence": s, "char_offset": list(span)}}
            else:
                warn.append(f"{r['id']}: relation quote not found in text")
    unresolved = []
    for x in raw:
        ev = x.get("evidence") or {}
        if ev.get("relation") == "not_reported":
            unresolved.append({"assertion_id": x["id"], "item": x.get("text"), "reason": "not_reported"})
    if isinstance(a.unresolved, str) and os.path.isfile(a.unresolved):
        unresolved += load_yaml_or_json(a.unresolved)
    np_ = {"schema_version": SCHEMA_VER,
           "document": {"title": doc.get("title"), "authors": doc.get("authors") or [], "year": doc.get("year"),
                        "doi": doc.get("doi"), "venue": doc.get("venue"), "version": doc.get("version"),
                        "identifier_type": "doi" if doc.get("doi") else None,
                        "identifier_value": doc.get("doi")},
           "assertions": raw, "relations": rels, "unresolved": unresolved}
    checks, stats = np_validate.validate({"assertions": raw, "relations": rels, "unresolved": unresolved}, text)
    np_["quality"] = {**stats, "coverage": coverage(text, raw), "checks": checks}
    meta = json.load(open(a.text_meta, encoding="utf-8")) if a.text_meta and os.path.isfile(a.text_meta) else {}
    sources = [{"path": meta.get("path") or a.text, "kind": meta.get("backend") or "text",
                "pages_read": meta.get("pages_with_text") or [], "sha256": meta.get("sha256"), "out": a.text}]
    # result.json: start from the case output_contract so every field is present
    result = {}
    contract = case.get("output_contract") or case.get("outputContract") or {}
    if isinstance(contract, dict):
        fields = contract.get("fields", contract)
    else:
        fields = contract
    names = []
    if isinstance(fields, dict):
        names = list(fields.keys())
    elif isinstance(fields, list):
        names = [k if isinstance(k, str) else k.get("name") for k in fields]
    for k in names:
        result[k] = None
    result["case_id"] = case.get("case_id")
    result["status"] = a.status
    result["sources"] = sources
    result["nanopub"] = np_
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "assertions.json"), "w", encoding="utf-8") as f:
        json.dump({"assertions": raw, "relations": rels, "unresolved": unresolved}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "assertions.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(np_))
    status = "success" if all(c["passed"] for c in checks) else a.status
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(to_report(np_, case, warn, checks, stats, meta, status))
    print(json.dumps({"status": status, "checks": [(c["id"], c["passed"]) for c in checks],
                      "warnings": warn, "out": a.out}, ensure_ascii=False, indent=2))
    return 0 if all(c["passed"] for c in checks) else 1


# ----------------------------------------------------------------- trig
def _uri(s):
    s = re.sub(r"[^A-Za-z0-9-]+", "_", str(s)).strip("_")
    return s or "x"


def cmd_trig(a):
    data = load_yaml_or_json(a.assertions)
    if isinstance(data, dict):
        A = data.get("assertions", [])
        R = data.get("relations", [])
    else:
        A, R = data, []
    doc = load_yaml_or_json(a.doc) if a.doc and os.path.isfile(a.doc) else {}
    base = a.base or "http://example.org/nanopub/"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    orcid = a.orcid or "https://orcid.org/0000-0000-0000-0000"
    L = ["@prefix np: <http://www.nanopub.org/nschema#> .",
         "@prefix dc: <http://purl.org/dc/terms/> .",
         "@prefix pav: <http://purl.org/pav/> .",
         "@prefix prov: <http://www.w3.org/ns/prov#> .",
         "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
         ""]
    for x in A:
        aid = _uri(x.get("id"))
        ev = x.get("evidence") or {}
        s, p, o = x.get("subject"), x.get("predicate"), x.get("object")
        L.append(f"{base}assertion-{aid} {{")
        L.append(f"  a np:Assertion ;")
        L.append(f"  <{base}res/{_uri(s)}> <{base}pred/{_uri(p)}> <{base}res/{_uri(o)}> ;")
        L.append(f"  dc:title \"{_esc(x.get('text'))}\"@en ;")
        L.append("}")
        L.append(f"{base}provenance-{aid} {{")
        L.append(f"  a np:Provenance ;")
        L.append(f"  prov:wasAttributedTo <{orcid}> ;")
        L.append(f"  prov:wasGeneratedBy [ a prov:Activity ; prov:used <{base}source-{_uri(doc.get('doi') or doc.get('title'))}> ; prov:endedAtTime \"{now}\"^^xsd:dateTime ] ;")
        L.append(f"  pav:createdBy <{orcid}> ;")
        L.append(f"  dc:description \"evidence ({ev.get('relation')}): '{_esc(ev.get('quote'))}' at page {((ev.get('locator') or {}).get('page'))} chars {((ev.get('locator') or {}).get('char_offset'))}\"@en ;")
        L.append("}")
        L.append(f"{base}publication-{aid} {{")
        L.append(f"  a np:Nanopublication ;")
        L.append(f"  np:hasAssertion {base}assertion-{aid} ;")
        L.append(f"  np:hasProvenance {base}provenance-{aid} ;")
        L.append(f"  np:hasPublicationInfo {base}pubinfo-{aid} .")
        L.append("}")
        L.append(f"{base}pubinfo-{aid} {{")
        L.append("  a np:PublicationInfo ;")
        L.append(f"  dc:created \"{now}\"^^xsd:dateTime ;")
        L.append(f"  pav:createdBy <{orcid}> ;")
        L.append(f"  dc:title \"{_esc(doc.get('title'))}\"@en .")
        L.append("}")
    for r in R:
        L.append(f"{base}assertion-{_uri(r.get('subject'))} <{base}rel/{_uri(r.get('predicate'))}> <{base}assertion-{_uri(r.get('object'))}> .")
    if not A:
        L.append("# no assertions")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(json.dumps({"status": "ok", "n": len(A), "out": a.out}))
    return 0


def _esc(s):
    return (str(s) if s is not None else "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("locate")
    p.add_argument("--text", required=True)
    p.add_argument("--quote", required=True)
    p = sub.add_parser("finalise")
    p.add_argument("--assertions", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--case")
    p.add_argument("--doc")
    p.add_argument("--relations")
    p.add_argument("--unresolved")
    p.add_argument("--text-meta")
    p.add_argument("--status", default="partial")
    p = sub.add_parser("trig")
    p.add_argument("--assertions", required=True)
    p.add_argument("--doc")
    p.add_argument("--out", required=True)
    p.add_argument("--base")
    p.add_argument("--orcid")
    a = ap.parse_args()
    if a.cmd == "locate":
        text = open(a.text, "r", encoding="utf-8").read()
        span, n = locate(text, a.quote)
        if not span:
            print(json.dumps({"found": False, "quote": a.quote}))
            return 1
        page, paragraph, sentence = page_para_sent(text, span[0])
        print(json.dumps({"found": True, "occurrences": n, "page": page, "paragraph": paragraph,
                          "sentence": sentence, "char_offset": list(span)}))
        return 0
    if a.cmd == "finalise":
        return cmd_finalise(a)
    if a.cmd == "trig":
        return cmd_trig(a)
    return 1


if __name__ == "__main__":
    sys.exit(main())
