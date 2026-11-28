"""Deterministic checks for common changes in meaning during claim extraction."""
import re


DECIMAL = r"[+\-−]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?:[eE][+\-−]?\d+)?"
NUMBER = re.compile(rf"(?<![A-Za-z0-9_.]){DECIMAL}(?![A-Za-z0-9_]|\.\d|,\d{{3}})")
UNIT = r"(?:%|°\s*[CF]|mg/kg|µg/kg|μg/kg|ug/kg|kg|mg|µg|μg|ug|ng|g|mL|ml|mm|cm|km|m|mM|µM|μM|uM|nM|ms|days?|hours?|seconds?|BLEU|fold)"
MEASUREMENT = re.compile(rf"(?<![A-Za-z0-9_.])({DECIMAL}(?:\s*[-–]\s*{DECIMAL})?)\s*[-–]?\s*({UNIT})(?![A-Za-z0-9_]|\.\d)", re.I)
INCREASE = re.compile(r"\b(?:increas(?:e|es|ed|ing)|rose)\b|上升|增加|升高|提高", re.I)
DECREASE = re.compile(r"\b(?:decreas(?:e|es|ed|ing)|fell)\b|下降|减少|降低", re.I)
INEQUALITY = re.compile(rf"(<=|>=|≤|≥|<|>)\s*({DECIMAL})")
NEGATION = re.compile(r"\b(?:no|not(?!\s+only\b)|never|without|neither|failed to)\b|并未|没有|无显著|不显著")
HEDGE = re.compile(r"\b(?:may|might|could|can|suggest(?:s|ed)?|likely|possibly|potentially|appear(?:s|ed)?|associated with)\b|可能|提示|或许|相关", re.I)
SCOPE = re.compile(
    rf"\b(?:only (?:when|if|in|under)\s+[^,.;]+|in (?:vitro|vivo)|"
    rf"(?:relative to|compared (?:with|to))\s+[^,.;(]+|"
    rf"(?:at|with|after|for|over)\s+{NUMBER.pattern}\s*{UNIT}(?!\w))",
    re.I,
)
CLAUSE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|[,，]\s+|[;；]\s*|\s+(?:and|but|while|whereas|versus|vs\.?)\s+", re.I)
PAIRED = re.compile(
    rf"^(?P<first>.+?)\s+and\s+(?P<second>.+?)\s+"
    rf"(?:scored|reported|reached|achieved|were|had)\s+(?P<left>{DECIMAL})\s+"
    rf"(?:(?P<left_unit>{UNIT})\s+)?and\s+(?P<right>{DECIMAL})\s*(?P<right_unit>{UNIT})?"
    rf"\s*,?\s*respectively\b", re.I,
)


def compact(value):
    """Normalize PDF wrapping while preserving words and numeric precision."""
    return " ".join(re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "-", str(value)).split())


def contains(text, phrase):
    phrase = compact(phrase)
    return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.I))


def inequalities(phrase):
    return {(op.replace("≤", "<=").replace("≥", ">="), number)
            for op, number in INEQUALITY.findall(phrase)}


def table_context(quote, evidence, text):
    """Resolve a table cell. An empty string signals an unresolved structured table."""
    locator = evidence.get("locator") or {}
    table = locator.get("table") or {}
    offset = locator.get("char_offset")
    if not table.get("column") or not table.get("row") or not offset:
        return None
    start = text.rfind("\n", 0, offset[0]) + 1
    end = text.find("\n", offset[1] - 1)
    lines = text[start:end if end >= 0 else len(text)].splitlines()
    markdown = bool(lines and lines[0].lstrip().startswith("|"))

    def cells(line):
        line = line.strip()
        if markdown:
            return [v.strip() for v in line.strip("|").split("|")] if line.startswith("|") else []
        return re.split(r"(?: {2,}|\t+)", line)

    rows = [cells(line) for line in lines]
    while start > 0:
        previous = text.rfind("\n", 0, start - 1) + 1
        row = cells(text[previous:start - 1])
        if len(row) < 2:
            break
        rows.insert(0, row)
        start = previous
    if not rows or not (markdown or any(len(row) >= 2 for row in rows)):
        return None
    if len(rows) < 2 or any(len(row) < 2 for row in rows):
        return ""
    header, *body = rows
    columns = [i for i, cell in enumerate(header) if compact(cell) == compact(table["column"])]
    matches = [row for row in body if compact(row[0]) == compact(table["row"])
               and contains(compact(quote), row[0])]
    if len(columns) == 1 and len(matches) == 1 and len(matches[0]) == len(header):
        row = matches[0]
        cell = row[columns[0]]
        if contains(compact(quote), cell):
            heading = header[columns[0]]
            unit = re.search(r"\(([^()]+)\)\s*$", heading)
            return compact(f"{row[0]} {cell} {unit[1] if unit else ''} {heading}")
    return ""


def claim_differences(assertion, source_text):
    ev = assertion["evidence"]
    quote = ev.get("quote") or ""
    if not quote:
        return []
    qualifiers = assertion.get("qualifiers") or {}
    statement = compact(assertion.get("text") or "")
    table = table_context(quote, ev, source_text)
    if table == "":
        return ["table row and column could not be uniquely verified against the source header"]
    main = table or compact(quote)
    controlling = compact(assertion.get("controlling_quote") or "")
    source = " ".join(filter(None, (main, controlling)))
    result_scope = main
    clauses = CLAUSE.split(main)
    result_clauses = [clause for clause in clauses if NUMBER.search(clause)]
    subject_clauses = [clause for clause in result_clauses if contains(clause, assertion.get("subject") or "")]
    pairing = PAIRED.search(main)
    if pairing:
        # In ordered parallel lists the last unit can apply to both values.
        left_unit = pairing["left_unit"] or pairing["right_unit"] or ""
        right_unit = pairing["right_unit"] or pairing["left_unit"] or ""
        pairs = [f"{pairing['left']} {left_unit}".strip(), f"{pairing['right']} {right_unit}".strip()]
        source += " " + " ".join(pairs)
        matched = [value for label, value in zip(("first", "second"), pairs)
                   if contains(pairing[label], assertion.get("subject") or "")]
        if len(matched) == 1:
            result_scope = matched[0]
    elif "respectively" not in main.lower() and len(result_clauses) > 1 and len(subject_clauses) == 1:
        result_scope = subject_clauses[0]

    issues = []
    direction = (bool(INCREASE.search(result_scope)), bool(DECREASE.search(result_scope)))
    for wording in (statement, compact(assertion.get("predicate") or "")):
        claimed = (bool(INCREASE.search(wording)), bool(DECREASE.search(wording)))
        if direction in ((True, False), (False, True)) and claimed == direction[::-1]:
            issues.append("direction reversed relative to evidence")
            break
    if inequalities(statement) - inequalities(source):
        issues.append("comparison sign or threshold differs from evidence")
    claim_fields = [statement] + [compact(assertion.get(key) or "") for key in ("subject", "predicate", "object")]
    claim_fields.extend(compact(v) for v in qualifiers.values() if v is not None)
    magnitude = compact(qualifiers["magnitude"]) if qualifiers.get("magnitude") is not None else ""
    unit = compact(qualifiers.get("unit") or "")
    if magnitude and unit:
        claim_fields.append(f"{magnitude} {unit}")
    measurements = {measurement for field in claim_fields for measurement in MEASUREMENT.findall(field)}
    source_measurements = set(MEASUREMENT.findall(source))
    actual_numbers = {number for field in claim_fields for number in NUMBER.findall(field)}
    actual_numbers.update(value for value, _ in measurements)
    source_numbers = set(NUMBER.findall(source)) | {value for value, _ in source_measurements}
    absent = actual_numbers - source_numbers
    if absent:
        issues.append(f"numbers absent from evidence: {', '.join(sorted(absent))}")
    for value, measure_unit in sorted(measurements - source_measurements):
        issues.append(f"measurement not supported: {value} {measure_unit}")
    subject_measurements = set(MEASUREMENT.findall(result_scope))
    numeric_conditions = set(MEASUREMENT.findall(" ".join(SCOPE.findall(source))))
    if result_scope != main:
        scope_numbers = {number for marker in SCOPE.findall(source) for number in NUMBER.findall(marker)}
        subject_numbers = set(NUMBER.findall(result_scope)) | {value for value, _ in subject_measurements}
        unbound = (actual_numbers & source_numbers) - subject_numbers - scope_numbers
        unbound -= set(NUMBER.findall(compact(assertion.get("subject") or "")))
        unbound -= set(NUMBER.findall(compact(qualifiers.get("comparator") or "")))
        if unbound:
            issues.append(f"values do not occur with the claimed subject: {', '.join(sorted(unbound))}")
    result_measurements = subject_measurements - numeric_conditions
    if assertion.get("claim_type") == "result" and len(result_measurements) == 1:
        missing = result_measurements - measurements
        if missing:
            value, unit = next(iter(missing))
            issues.append(f"reported result missing from claim: {value} {unit}")
    if magnitude and unit:
        pair = rf"(?<![A-Za-z0-9_.]){re.escape(magnitude)}\s*-?\s*{re.escape(unit)}(?![A-Za-z0-9_])"
        if not re.search(pair, result_scope):
            issues.append(f"value/unit pair not supported for subject: {magnitude} {unit}")

    for key in ("population", "condition", "timeframe", "metric", "comparator"):
        value = qualifiers.get(key)
        if value and not contains(source, value):
            issues.append(f"{key} absent from evidence: {value}")
    claim_scope = " ".join([statement] + [compact(qualifiers.get(key) or "")
                                        for key in ("condition", "timeframe", "population", "comparator")])
    for marker in SCOPE.findall(source):
        value = re.sub(r"^(?:at|with|after|for|over|relative to|compared (?:with|to))\s+", "", marker,
                       flags=re.I).strip()
        if not contains(claim_scope, value):
            issues.append(f"missing scope: {marker}")
    if bool(NEGATION.search(source.lower())) != bool(NEGATION.search(statement.lower())):
        issues.append("negation differs between claim and evidence")
    if qualifiers.get("negated") is not None and qualifiers["negated"] != bool(NEGATION.search(statement.lower())):
        issues.append("negated qualifier disagrees with claim")
    source_hedges = {word.lower() for word in HEDGE.findall(source)}
    claim_hedges = {word.lower() for word in HEDGE.findall(statement)}
    if source_hedges != claim_hedges:
        issues.append(f"hedging differs: evidence {sorted(source_hedges)}, claim {sorted(claim_hedges)}")
    if source_hedges and assertion.get("confidence") == "high":
        issues.append("hedged evidence requires medium or low confidence")
    return issues
