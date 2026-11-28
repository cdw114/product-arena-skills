#!/usr/bin/env python3
"""np_validate.py - quality checks for a nanopub assertion file.

Usage:
    python3 np_validate.py assertions.json --text /app/work/text.txt [--json]
    python3 np_validate.py /app/output/result.json --text /app/work/text.txt   (reads .nanopub.assertions)

Exit code 0 = all checks pass, 1 = at least one check failed, 2 = input unreadable.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from np_fidelity import claim_differences, compact, table_context

CLAIM_TYPES = {"observation", "definition", "method", "result", "interpretation", "limitation",
               "hypothesis", "question", "other"}
RELATION_TYPES = {"supports", "contradicts", "refines", "qualifies", "depends_on", "same_as",
                 "derived_from", "extends", "part_of", "compared_to"}
EVIDENCE_RELATIONS = {"direct", "inferred", "not_reported"}
CONFIDENCE = {"high", "medium", "low"}
UNRESOLVED_REASONS = {"not_reported", "ambiguous", "out_of_scope", "conflicting_evidence",
                      "source_unavailable", "quote_not_found", "unsupported_inference"}
NARRATIVE_ROLES = {"background", "gap", "objective", "method", "result", "conclusion",
                   "limitation", "future_work", "other"}
MARK_RE = re.compile(r"^=== page (\d+) ===$", re.M)
# Two finite-verb coordination patterns used by Q2 (heuristic).
COORD_RE = re.compile(
    r"\b(\w+ed|\w+s|was|were|is|are|has|have|had|increased|decreased|reduced|showed|show|"
    r"induced|caused|inhibited|promoted)\b[^.;]{0,80}?\b(and|but|while|whereas|which)\b"
    r"[^.;]{0,80}?\b(was|were|is|are|has|have|had|increased|decreased|reduced|showed|show|"
    r"induced|caused|inhibited|promoted)\b", re.I)
SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "nanopub.schema.json"


def load(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"assertions": data, "relations": [], "unresolved": []}
    if "nanopub" in data:
        np_ = data["nanopub"]
        return {"assertions": np_.get("assertions", []), "relations": np_.get("relations", []),
                "unresolved": np_.get("unresolved", []), "quality": np_.get("quality"),
                "ocr_pages": [p for source in data.get("sources", []) for p in source.get("ocr_pages", [])]}
    return {"assertions": data.get("assertions", []), "relations": data.get("relations", []),
            "unresolved": data.get("unresolved", []), "quality": data.get("quality")}


def page_offsets(text):
    """Return [(page_no, char_start)], including a sentinel for the end."""
    offs = [(int(m.group(1)), m.start()) for m in MARK_RE.finditer(text)]
    offs.append((None, len(text)))
    return offs


def page_para_sent(text, pos, offsets=None):
    page, start_of_page = 1, 0
    if offsets is None:
        offsets = page_offsets(text)
    for p, start in offsets:
        if p is None or start > pos:
            break
        page, start_of_page = p, start
    segment = MARK_RE.sub("", text[start_of_page:pos], count=1).lstrip("\n")
    paragraphs = re.split(r"\n\s*\n", segment)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])|(?<=[。！？])\s*(?=\S)",
                         paragraphs[-1] + text[pos:pos + 1])
    return page, len(paragraphs), len(sentences)


def bound_quote(text, evidence, offsets=None):
    locator = evidence.get("locator") or {}
    span = locator.get("char_offset")
    if not (isinstance(span, list) and len(span) == 2 and all(type(n) is int for n in span)):
        return False
    start, end = span
    if not 0 <= start < end <= len(text) or text[start:end] != evidence.get("quote"):
        return False
    actual = page_para_sent(text, start, offsets)
    return all(locator.get(key) in (None, value)
               for key, value in zip(("page", "paragraph", "sentence"), actual))


def unsupported_inferences(assertions, text):
    """Resolve the dependency graph from verified direct evidence."""
    pending = {a.get("id"): a for a in assertions if (a.get("evidence") or {}).get("relation") == "inferred"}
    if not pending:
        return set()
    grounded = {a.get("id") for a in assertions
                if (a.get("evidence") or {}).get("relation") == "direct"
                and a["evidence"].get("quote_verbatim") is True
                and bound_quote(text, a["evidence"])
                and not claim_differences(a, text)}
    while pending:
        ready = []
        for aid, assertion in pending.items():
            chain = assertion.get("inference_chain") or []
            if chain and all(isinstance(step, dict) and isinstance(step.get("from"), list)
                             and step["from"] and all(isinstance(ref, str) and ref in grounded for ref in step["from"])
                             and isinstance(step.get("rationale"), str) and step["rationale"].strip()
                             for step in chain) and bound_quote(text, assertion["evidence"]):
                ready.append(aid)
        if not ready:
            break
        for aid in ready:
            grounded.add(aid)
            del pending[aid]
    return set(pending)


def evidence_pages(record):
    locators = [(record.get("evidence") or {}).get("locator") or {},
                record.get("controlling_quote_locator") or {}]
    locators.extend((item.get("locator") or {}) for item in record.get("supporting_evidence") or [])
    return {loc["page"] for loc in locators if loc.get("page") is not None}


def word_count(s):
    return len(re.findall(r"\w+", s))


def check(name, passed, detail):
    return {"id": name, "passed": bool(passed), "detail": detail}


def validate(data, text):
    A = data.get("assertions", [])
    R = data.get("relations", [])
    U = data.get("unresolved", [])
    offsets = page_offsets(text)
    ids = [a.get("id") for a in A]
    idset = set(ids)
    results = []

    # Q1 unique ids
    all_ids = ids + [r.get("id") for r in R]
    dup = sorted({i for i in all_ids if all_ids.count(i) > 1}, key=str)
    results.append(check("Q1_unique_ids", not dup and all(all_ids), f"{len(ids)} claims, {len(R)} relations" + (f", duplicates: {dup}" if dup else "")))
    results.append(check("Q19_extraction_outcome", bool(A or U),
                         "documented reading outcome" if A or U else "no claims or explanation for the empty extraction"))

    # Q2 atomic text
    bad = []
    for a in A:
        t = str(a.get("text") or "")
        if COORD_RE.search(t) or t.count("; ") >= 1:
            bad.append(a.get("id"))
    results.append(check("Q2_atomic", not bad, f"{len(bad)} compound texts" + (f": {bad[:10]}" if bad else "")))

    # Q3 quote found + Q4 offset matches + Q5 minimal + Q6 no ellipsis
    nf, off_bad, long_q, ell, blob_words = [], [], [], [], []
    for a in A:
        ev = a.get("evidence") or {}
        q = ev.get("quote")
        rel = ev.get("relation")
        if rel == "not_reported":
            continue
        if not q:
            nf.append(a.get("id"))
            continue
        if "..." in q or "[...]" in q or "…" in q:
            ell.append(a.get("id"))
        wc = word_count(q)
        blob_words.append(wc)
        if wc > 60 and q.count(".") > 1:
            long_q.append(a.get("id"))
        if q not in text:
            nf.append(a.get("id"))
        elif not bound_quote(text, ev, offsets) or ev.get("quote_verbatim") is not True:
            off_bad.append(a.get("id"))
        extras = list(a.get("supporting_evidence") or [])
        if a.get("controlling_quote"):
            locator = a.get("controlling_quote_locator") or {"char_offset": a.get("controlling_quote_offset")}
            extras.append({"quote": a["controlling_quote"], "locator": locator})
        if any(not bound_quote(text, extra, offsets) for extra in extras):
            off_bad.append(f"{a.get('id')} supplemental evidence")
    results.append(check("Q3_quote_found", not nf, f"{len(nf)} quotes not in source" + (f": {nf[:10]}" if nf else "")))
    # relation quotes must also exist in the source (Q3b)
    nf_r = []
    for r in R:
        ev = r.get("evidence") or {}
        q = ev.get("quote")
        if q and q not in text:
            nf_r.append(r.get("id"))
        elif q and not bound_quote(text, ev, offsets):
            off_bad.append(r.get("id"))
    results.append(check("Q3b_relation_quote_found", not nf_r, f"{len(nf_r)} relation quotes not in source" + (f": {nf_r}" if nf_r else "")))
    results.append(check("Q4_offset_matches", not off_bad, f"{len(off_bad)} offsets wrong/missing" + (f": {off_bad[:10]}" if off_bad else "")))
    results.append(check("Q5_minimal", not long_q, f"{len(long_q)} quotes > 60 words" + (f": {long_q[:10]}" if long_q else "")))
    results.append(check("Q6_no_ellipsis", not ell, f"{len(ell)} quotes contain ellipsis" + (f": {ell[:10]}" if ell else "")))

    # Q7 relation targets
    bad_r = [r.get("id") for r in R if r.get("subject") not in idset or r.get("object") not in idset]
    results.append(check("Q7_relation_target", not bad_r, f"{len(R)} relations" + (f", bad: {bad_r}" if bad_r else "")))

    # Q8 direct claims: subject/object words appear in quote
    bad8 = []
    for a in A:
        ev = a.get("evidence") or {}
        if ev.get("relation") != "direct":
            continue
        q = (table_context(ev.get("quote") or "", ev, text) or compact(ev.get("quote") or "")).lower()
        spo = [a.get("subject", ""), a.get("object", "")]
        missing = [w for w in spo if w and not _words_in(w, q)]
        if missing:
            bad8.append(a.get("id"))
    results.append(check("Q8_direct_has_spo", not bad8, f"{len(bad8)} direct claims lack S/O words in quote" + (f": {bad8[:10]}" if bad8 else "")))

    # Q9 inferred chain
    bad9 = sorted(unsupported_inferences(A, text), key=str)
    results.append(check("Q9_inferred_chain", not bad9, f"{len(bad9)} inferences lack a chain to verified direct evidence" + (f": {bad9[:10]}" if bad9 else "")))

    # Q10 not_reported listed
    nr = {a.get("id") for a in A if (a.get("evidence") or {}).get("relation") == "not_reported"}
    listed = {u.get("assertion_id") or u.get("item") for u in U}
    miss = sorted(nr - listed)
    results.append(check("Q10_not_reported_listed", not miss, f"{len(nr)} not_reported, {len(miss)} unlisted" + (f": {miss[:10]}" if miss else "")))

    # Q11 no blob
    avg = (sum(blob_words) / len(blob_words)) if blob_words else 0
    results.append(check("Q11_no_blob", avg < 45, f"avg quote {avg:.1f} words over {len(blob_words)} quotes"))

    # Q12 confidence rule
    bad12 = []
    for a in A:
        ev = a.get("evidence") or {}
        rel, ver, hedge, conf = ev.get("relation"), ev.get("quote_verbatim"), a.get("hedge"), a.get("confidence")
        if conf not in CONFIDENCE:
            bad12.append(a.get("id"))
        elif conf == "high" and not (rel == "direct" and ver and not hedge):
            bad12.append(a.get("id"))
        elif conf == "medium" and rel == "not_reported":
            bad12.append(a.get("id"))
        elif conf == "low" and rel == "direct" and ver and not hedge and a.get("inference_chain") is None:
            # low is allowed for conflicts; only flag when nothing explains it
            if not a.get("confidence_reason"):
                bad12.append(a.get("id"))
    results.append(check("Q12_confidence_rule", not bad12, f"{len(bad12)} confidence inconsistent" + (f": {bad12[:10]}" if bad12 else "")))

    differences = [f"{a.get('id')}: {'; '.join(issues)}" for a in A
                   if (a.get("evidence") or {}).get("relation") == "direct"
                   if (issues := claim_differences(a, text))]
    results.append(check("Q13_qualifiers_kept", not differences,
                         " | ".join(differences) or "no numeric, qualifier, negation or hedge mismatches detected"))

    # enum checks (not numbered in SKILL, but enforced by the schema)
    enum_bad = []
    for a in A:
        if a.get("claim_type") not in CLAIM_TYPES:
            enum_bad.append(f"{a.get('id')}:claim_type")
        if (a.get("evidence") or {}).get("relation") not in EVIDENCE_RELATIONS:
            enum_bad.append(f"{a.get('id')}:relation")
        if a.get("narrative_role") and a.get("narrative_role") not in NARRATIVE_ROLES:
            enum_bad.append(f"{a.get('id')}:narrative_role")
    for r in R:
        if r.get("predicate") not in RELATION_TYPES:
            enum_bad.append(f"{r.get('id')}:predicate")
    for u in U:
        if u.get("reason") not in UNRESOLVED_REASONS:
            enum_bad.append(f"unresolved:{u.get('reason')}")
    results.append(check("Q14_enums", not enum_bad, f"{len(enum_bad)} bad enum values" + (f": {enum_bad[:10]}" if enum_bad else "")))

    # relation evidence present
    bad_r_ev = [r.get("id") for r in R if not ((r.get("evidence") or {}).get("quote"))]
    results.append(check("Q15_relation_evidence", not bad_r_ev, f"{len(bad_r_ev)} relations without evidence" + (f": {bad_r_ev[:10]}" if bad_r_ev else "")))

    pending = [u for u in U if u.get("review_required")
               or u.get("reason") in {"quote_not_found", "unsupported_inference", "source_unavailable"}]
    results.append(check("Q17_pending_evidence", not pending,
                         " | ".join(str(u.get("detail") or u["item"]) for u in pending)
                         or "no pending evidence issues"))

    ocr_pages = set(data.get("ocr_pages", []))
    if ocr_pages:
        overconfident = [record.get("id") for record in A + R
                         if record.get("confidence") == "high" and evidence_pages(record) & ocr_pages]
        results.append(check("Q20_ocr_confidence", not overconfident,
                             f"OCR evidence requires medium or low confidence: {overconfident}"
                             if overconfident else "confidence capped for OCR evidence"))

    stats = {
        "n_assertions": len(A),
        "n_relations": len(R),
        "n_direct": sum(1 for a in A if (a.get("evidence") or {}).get("relation") == "direct"),
        "n_inferred": sum(1 for a in A if (a.get("evidence") or {}).get("relation") == "inferred"),
        "n_not_reported": sum(1 for a in A if (a.get("evidence") or {}).get("relation") == "not_reported"),
        "n_unique_quotes": len({(a.get("evidence") or {}).get("quote") for a in A}),
        "avg_quote_words": round(avg, 1),
        "unresolved_summary": _count_by(U, "reason"),
    }
    return results, stats


def resolve_schema(spec, root):
    seen = set()
    while isinstance(spec, dict) and "$ref" in spec:
        reference = spec["$ref"]
        try:
            if reference in seen or not reference.startswith("#/"):
                raise ValueError
            seen.add(reference)
            spec = root
            for key in reference[2:].split("/"):
                spec = spec[key.replace("~1", "/").replace("~0", "~")]
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ValueError(f"unsupported or unresolved schema reference {reference!r}") from None
    return spec


def schema_errors(data, schema, root=None):
    """Minimal draft-07 validator (type/enum/const/pattern/required/items/minItems/$ref).
    No dependency on jsonschema; enough for schemas/nanopub.schema.json."""
    errors = []
    root = schema if root is None else root

    def check(node, sch, path):
        try:
            sch = resolve_schema(sch, root)
        except ValueError as exc:
            errors.append(f"{path}: {exc}")
            return
        if sch is False:
            errors.append(f"{path}: value prohibited by schema")
        if not isinstance(sch, dict):
            return
        t = sch.get("type")
        if t:
            types = t if isinstance(t, list) else [t]
            def ok(ty):
                if ty == "null": return node is None
                if ty == "string": return isinstance(node, str)
                if ty == "integer": return isinstance(node, int) and not isinstance(node, bool)
                if ty == "number": return isinstance(node, (int, float)) and not isinstance(node, bool)
                if ty == "boolean": return isinstance(node, bool)
                if ty == "array": return isinstance(node, list)
                if ty == "object": return isinstance(node, dict)
                return False
            if not any(ok(ty) for ty in types):
                errors.append(f"{path}: expected {t}, got {type(node).__name__}")
                return
        if "enum" in sch and node not in sch["enum"]:
            errors.append(f"{path}: {node!r} not in enum")
        if "const" in sch and node != sch["const"]:
            errors.append(f"{path}: {node!r} != {sch['const']!r}")
        if "pattern" in sch and isinstance(node, str) and not re.search(sch["pattern"], node):
            errors.append(f"{path}: {node!r} fails {sch['pattern']}")
        if isinstance(node, str) and len(node) < sch.get("minLength", 0):
            errors.append(f"{path}: shorter than {sch['minLength']}")
        if isinstance(node, list):
            if "minItems" in sch and len(node) < sch["minItems"]:
                errors.append(f"{path}: fewer than {sch['minItems']} items")
            if len(node) > sch.get("maxItems", len(node)):
                errors.append(f"{path}: more than {sch['maxItems']} items")
            if "items" in sch:
                for i, x in enumerate(node):
                    check(x, sch["items"], f"{path}[{i}]")
        if isinstance(node, dict):
            for r in sch.get("required", []):
                if r not in node:
                    errors.append(f"{path}: missing required {r!r}")
            for k, v in node.items():
                if k in sch.get("properties", {}):
                    check(v, sch["properties"][k], f"{path}.{k}")

    check(data, schema, "$")
    return errors


def contract_fields(case):
    """Read required fields from a list, field map or object schema."""
    contract = case.get("output_contract") or case.get("outputContract") or []
    if isinstance(contract, list):
        fields, required = contract, []
    else:
        meta = {"type", "title", "description", "required", "properties", "artifacts", "$schema",
                "$defs", "definitions", "$id", "additionalProperties"}
        properties = contract.get("properties") or {}
        fields = contract.get("fields", {key: value for key, value in contract.items() if key not in meta})
        required = contract.get("required", list(properties))
    specs = {}
    if isinstance(contract, dict):
        specs.update((name, properties.get(name, {})) for name in required)
    if isinstance(fields, dict):
        specs.update((name, spec) for name, spec in fields.items()
                     if not isinstance(spec, dict) or spec.get("required") is not False)
    else:
        for entry in fields:
            if isinstance(entry, str):
                specs.setdefault(entry, {})
            elif isinstance(entry, dict) and entry.get("name") and entry.get("required") is not False:
                specs[entry["name"]] = entry
    return specs


def answer_references(value):
    if isinstance(value, str):
        groups = re.findall(r"\[\s*(A\d+(?:\s*[,，;；]\s*A\d+)*)\s*\]", value)
        for group in groups:
            yield from re.findall(r"A\d+", group)
    elif isinstance(value, list):
        for item in value:
            yield from answer_references(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"claim_ids", "assertion_ids"} and isinstance(item, list):
                yield from (v for v in item if isinstance(v, str))
            else:
                yield from answer_references(item)


def contract_check(result, case):
    types = {"string", "array", "object", "number", "integer", "boolean", "null"}
    issues = []
    root = case.get("output_contract") or case.get("outputContract") or {}
    for name, spec in contract_fields(case).items():
        value = result.get(name)
        if isinstance(spec, str):
            spec = {"type": spec} if spec in types else {}
        spec = dict(spec or {}) if isinstance(spec, dict) else {}
        if isinstance(spec.get("required"), bool):
            del spec["required"]
        try:
            resolved = resolve_schema(spec, root)
        except ValueError as exc:
            issues.append(f"{name}: {exc}")
            continue
        declared_type = resolved.get("type") if isinstance(resolved, dict) else None
        allows_null = declared_type == "null" or isinstance(declared_type, list) and "null" in declared_type
        if name not in result or value is None and not allows_null or isinstance(value, str) and not value.strip():
            issues.append(f"{name}: missing or empty")
        elif spec:
            for error in schema_errors(value, spec, root=root):
                issues.append(name + error[1:])
    ids = {a.get("id") for a in result.get("nanopub", {}).get("assertions", [])}
    for field in ("answer", "answers", "result"):
        unknown = sorted(set(answer_references(result.get(field))) - ids)
        if unknown:
            issues.append(f"{field} cites unavailable claims: {', '.join(unknown)}")
    return check("Q18_output_contract", not issues, " | ".join(issues) or "required fields filled")


def schema_check(result, path=SCHEMA):
    try:
        with open(path, encoding="utf-8-sig") as f:
            errors = schema_errors(result, json.load(f))
        return check("Q16_json_schema", not errors, f"{len(errors)} schema errors" +
                     (f": {errors[:3]}" if errors else ""))
    except (OSError, ValueError, KeyError) as exc:
        return check("Q16_json_schema", False, f"schema check failed to run: {exc}")


def _count_by(items, key):
    out = {}
    for it in items:
        k = it.get(key)
        out[k] = out.get(k, 0) + 1
    return out


def _words_in(phrase, text):
    """All content words of phrase appear in text (stem-ish: prefix match)."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]+", phrase) if len(w) > 2]
    if not words:
        return True
    tl = text.lower()
    for w in words:
        wl = w.lower()
        stem = wl[: max(4, len(wl) - 3)]
        if wl not in tl and stem not in tl:
            return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--text", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="write check results json here")
    ap.add_argument("--schema", help="JSON schema file; when given, validates result.json against it (Q16)")
    ap.add_argument("--case", help="case descriptor for validating output_contract (Q18)")
    a = ap.parse_args()
    try:
        data = load(a.path)
        with open(a.text, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print(f"cannot read input: {e}", file=sys.stderr)
        return 2
    results, stats = validate(data, text)
    if a.schema or a.case:
        with open(a.path, "r", encoding="utf-8-sig") as f:
            full = json.load(f)
        results.append(schema_check(full, a.schema or SCHEMA))
        if a.case:
            with open(a.case, encoding="utf-8-sig") as f:
                results.append(contract_check(full, json.load(f)))
    if a.json:
        print(json.dumps({"checks": results, "stats": stats}, indent=2))
    else:
        print(f"{'check':24s} {'result':6s} detail")
        for r in results:
            print(f"{r['id']:24s} {'PASS' if r['passed'] else 'FAIL':6s} {r['detail']}")
        print(f"\nclaims={stats['n_assertions']} relations={stats['n_relations']} "
              f"direct={stats['n_direct']} inferred={stats['n_inferred']} not_reported={stats['n_not_reported']} "
              f"unique_quotes={stats['n_unique_quotes']} avg_quote_words={stats['avg_quote_words']}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"checks": results, "stats": stats}, f, ensure_ascii=False, indent=2)
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
