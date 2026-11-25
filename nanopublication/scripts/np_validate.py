#!/usr/bin/env python3
"""np_validate.py - quality checks Q1-Q13 for a nanopub assertion file.

Usage:
    python3 np_validate.py assertions.json --text /app/work/text.txt [--json]
    python3 np_validate.py /app/output/result.json --text /app/work/text.txt   (reads .nanopub.assertions)

Exit code 0 = all checks pass, 1 = at least one check failed, 2 = input unreadable.
"""
import argparse
import json
import re
import sys

CLAIM_TYPES = {"observation", "definition", "method", "result", "interpretation", "limitation",
               "hypothesis", "question", "other"}
RELATION_TYPES = {"supports", "contradicts", "refines", "qualifies", "depends_on", "same_as",
                 "derived_from", "extends", "part_of", "compared_to"}
EVIDENCE_RELATIONS = {"direct", "inferred", "not_reported"}
CONFIDENCE = {"high", "medium", "low"}
UNRESOLVED_REASONS = {"not_reported", "ambiguous", "out_of_scope", "conflicting_evidence",
                      "source_unavailable"}
NARRATIVE_ROLES = {"background", "gap", "objective", "method", "result", "conclusion",
                   "limitation", "future_work", "other"}
HEDGES = {"may", "might", "could", "can", "suggest", "suggests", "suggested", "associated with",
          "likely", "possibly", "appear", "appears", "tends", "relatively", "somewhat",
          "putative", "potentially", "reportedly"}
MARK_RE = re.compile(r"^=== page (\d+) ===$", re.M)
# Two finite-verb coordination patterns used by Q2 (heuristic).
COORD_RE = re.compile(
    r"\b(\w+ed|\w+s|was|were|is|are|has|have|had|increased|decreased|reduced|showed|show|"
    r"induced|caused|inhibited|promoted)\b[^.;]{0,80}?\b(and|but|while|whereas|which)\b"
    r"[^.;]{0,80}?\b(was|were|is|are|has|have|had|increased|decreased|reduced|showed|show|"
    r"induced|caused|inhibited|promoted)\b", re.I)
NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def load(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"assertions": data, "relations": [], "unresolved": []}
    if "nanopub" in data:
        np_ = data["nanopub"]
        return {"assertions": np_.get("assertions", []), "relations": np_.get("relations", []),
                "unresolved": np_.get("unresolved", []), "quality": np_.get("quality")}
    return {"assertions": data.get("assertions", []), "relations": data.get("relations", []),
            "unresolved": data.get("unresolved", []), "quality": data.get("quality")}


def page_offsets(text):
    """Return [(page_no, char_start)], including a sentinel for the end."""
    offs = [(int(m.group(1)), m.start()) for m in MARK_RE.finditer(text)]
    offs.append((None, len(text)))
    return offs


def page_of(offsets, pos):
    page = None
    for p, start in offsets:
        if start <= pos:
            page = p if p is not None else page
        else:
            break
    return page


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
    dup = sorted({i for i in ids if ids.count(i) > 1})
    results.append(check("Q1_unique_ids", not dup and all(ids), f"{len(ids)} claims" + (f", duplicates: {dup}" if dup else "")))

    # Q2 atomic text
    bad = []
    for a in A:
        t = a.get("text", "")
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
        loc = ev.get("locator") or {}
        co = loc.get("char_offset")
        if co and len(co) == 2 and 0 <= co[0] <= co[1] <= len(text) and text[co[0]:co[1]] == q:
            pg = loc.get("page")
            real = page_of(offsets, co[0])
            if pg is not None and real is not None and pg != real:
                off_bad.append(a.get("id"))
        elif q in text:
            # quote exists but offset missing/wrong: report, finalise should fix
            off_bad.append(a.get("id"))
        else:
            nf.append(a.get("id"))
    results.append(check("Q3_quote_found", not nf, f"{len(nf)} quotes not in source" + (f": {nf[:10]}" if nf else "")))
    # relation quotes must also exist in the source (Q3b)
    nf_r = []
    for r in R:
        q = (r.get("evidence") or {}).get("quote")
        if q and q not in text:
            nf_r.append(r.get("id"))
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
        q = (ev.get("quote") or "").lower()
        spo = [a.get("subject", ""), a.get("object", "")]
        missing = [w for w in spo if w and not _words_in(w, q)]
        if missing:
            bad8.append(a.get("id"))
    results.append(check("Q8_direct_has_spo", not bad8, f"{len(bad8)} direct claims lack S/O words in quote" + (f": {bad8[:10]}" if bad8 else "")))

    # Q9 inferred chain
    bad9 = []
    for a in A:
        ev = a.get("evidence") or {}
        if ev.get("relation") != "inferred":
            continue
        chain = a.get("inference_chain") or []
        if not chain or not all(c.get("from") for c in chain):
            bad9.append(a.get("id"))
            continue
        for c in chain:
            for f in c.get("from", []):
                if f not in idset and not f.startswith("Q:"):
                    bad9.append(a.get("id"))
    results.append(check("Q9_inferred_chain", not bad9, f"{len(bad9)} inferred claims with bad chain" + (f": {bad9[:10]}" if bad9 else "")))

    # Q10 not_reported listed
    nr = {a.get("id") for a in A if (a.get("evidence") or {}).get("relation") == "not_reported"}
    listed = {u.get("assertion_id") or u.get("item") for u in U}
    miss = sorted(nr - listed)
    results.append(check("Q10_not_reported_listed", not miss, f"{len(nr)} not_reported, {len(miss)} unlisted" + (f": {miss[:10]}" if miss else "")))

    # Q11 no blob
    avg = (sum(blob_words) / len(blob_words)) if blob_words else 0
    results.append(check("Q11_no_blob", avg < 45 and len(blob_words) > 0, f"avg quote {avg:.1f} words over {len(blob_words)} quotes"))

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

    # Q13 numbers kept
    bad13 = []
    for a in A:
        q = ((a.get("evidence") or {}).get("quote") or "")
        nums = set(NUM_RE.findall(q))
        if not nums:
            continue
        qual = a.get("qualifiers") or {}
        parts = [a.get("text", "")] + [str(v) for v in qual.values() if v is not None]
        hay = " ".join(parts)
        # numbers in quote that are not in text or any qualifier -> possible dropped value
        dropped = [n for n in nums if n not in hay]
        if len(dropped) >= 2:
            bad13.append(a.get("id"))
    results.append(check("Q13_qualifiers_kept", not bad13, f"{len(bad13)} claims may drop numbers" + (f": {bad13[:10]}" if bad13 else "")))

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


def schema_errors(data, schema):
    """Minimal draft-07 validator (type/enum/const/pattern/required/items/minItems/$ref).
    No dependency on jsonschema; enough for schemas/nanopub.schema.json."""
    errors = []

    def check(node, sch, path):
        if "$ref" in sch:
            return check(node, schema["definitions"][sch["$ref"].split("/")[-1]], path)
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
        if isinstance(node, list):
            if "minItems" in sch and len(node) < sch["minItems"]:
                errors.append(f"{path}: fewer than {sch['minItems']} items")
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
    a = ap.parse_args()
    try:
        data = load(a.path)
        with open(a.text, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print(f"cannot read input: {e}", file=sys.stderr)
        return 2
    results, stats = validate(data, text)
    if a.schema:
        try:
            with open(a.schema, "r", encoding="utf-8-sig") as f:
                schema = json.load(f)
            with open(a.path, "r", encoding="utf-8-sig") as f:
                full = json.load(f)
            errs = schema_errors(full, schema)
            results.append(check("Q16_json_schema", not errs, f"{len(errs)} schema errors" + (f": {errs[:3]}" if errs else "")))
        except Exception as e:
            results.append(check("Q16_json_schema", False, f"schema check failed to run: {e}"))
    if a.json:
        print(json.dumps({"checks": results, "stats": stats}, ensure_ascii=False, indent=2))
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
