import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import np_validate


def claim(text, quote=None, **changes):
    return {"id": "A1", "text": text, "quote": quote if quote is not None else text,
            "claim_type": "result", "subject": "Group A", "predicate": "scored",
            "object": "BLEU", "confidence": "high", **changes}


class NanopublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)

    def put(self, filename, data):
        path = self.work / filename
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def run_bundle(self, text, claims, *, status="success", case=None, fields=None, relations=None):
        self.source = self.work / "text.txt"
        self.source.write_text(text, encoding="utf-8")
        assertions = claims if isinstance(claims, Path) else self.put("assertions.json", claims)
        out = self.work / "output"
        cmd = [sys.executable, "-B", str(SCRIPTS / "np_build.py"), "finalise", "--text", str(self.source),
               "--assertions", str(assertions), "--out", str(out), "--status", status]
        if case is not None:
            self.case = self.put("case.json", case)
            cmd.extend(["--case", str(self.case)])
        if fields is not None:
            cmd.extend(["--fields", str(self.put("fields.json", fields))])
        if relations is not None:
            path = relations if isinstance(relations, Path) else self.put("relations.json", relations)
            cmd.extend(["--relations", str(path)])
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.result_path = out / "result.json"
        self.assertTrue(self.result_path.exists(), completed.stderr)
        result = json.loads(self.result_path.read_text(encoding="utf-8"))
        report = (out / "report.md").read_text(encoding="utf-8")
        self.assertIn(f"- status: {result['status']}\n", report)
        self.assertEqual(result["status"], json.loads(completed.stdout)["status"])
        return completed.returncode, result, report

    def checks(self, result):
        return {entry["id"]: entry for entry in result["nanopub"]["quality"]["checks"]}

    def test_real_paper_baseline_and_changed_number(self):
        source = (HERE / "real_paper_page1.txt").read_text(encoding="utf-8")
        code, original, _ = self.run_bundle(source, HERE / "real_paper_assertions.yaml",
                                           relations=HERE / "real_paper_relations.json")
        self.assertEqual(code, 0, self.checks(original))
        claims = original["nanopub"]["assertions"]
        a8 = next(a for a in claims if a["id"] == "A8")
        a8["text"] = a8["text"].replace("28.4", "82.4")
        a8["object"] = "82.4 BLEU"
        a8["qualifiers"]["magnitude"] = 82.4
        code, changed, report = self.run_bundle(source, claims)
        self.assertEqual(code, 1)
        self.assertEqual(changed["status"], "partial")
        self.assertIn("A8: numbers absent from evidence: 82.4", self.checks(changed)["Q13_qualifiers_kept"]["detail"])
        self.assertIn("28.4 BLEU", report)
        self.assertIn("82.4 BLEU", report)

    def test_measurements_stay_with_the_correct_group(self):
        for quote in ("Group A scored 28.4 BLEU and Group B scored 24.1 BLEU.",
                      "Group A and Group B scored 28.4 and 24.1 BLEU, respectively."):
            for group, expected in (("Group A", 28.4), ("Group B", 24.1)):
                for value in (28.4, 24.1):
                    with self.subTest(quote=quote, group=group, value=value):
                        assertion = claim(f"{group} scored {value} BLEU.", quote, subject=group)
                        code, result, _ = self.run_bundle(quote, [assertion])
                        self.assertEqual(code, int(value != expected), self.checks(result))

    def test_table_quantity_must_come_from_the_requested_column(self):
        quote = "| Group A | 28.4 | 24.1 |"
        source = f"| Group | WMT EN-DE (BLEU) | WMT EN-FR (BLEU) |\n{quote}"
        locator = {"table": {"id": "Table 1", "row": "Group A", "column": "WMT EN-DE (BLEU)"}}
        for value in (28.4, 24.1):
            with self.subTest(value=value):
                assertion = claim(f"Group A scored {value} BLEU.", quote, locator=locator)
                code, result, _ = self.run_bundle(source, [assertion])
                self.assertEqual(code, int(value != 28.4), self.checks(result))

    def test_changed_unit_and_omitted_value(self):
        quote = "Group A reached 20 °C."
        for statement in ("Group A reached 20 °F.", "Group A reached the measured temperature."):
            with self.subTest(statement=statement):
                code, result, _ = self.run_bundle(quote, [claim(statement, quote, object="°C")])
                self.assertEqual(code, 1)
                self.assertFalse(self.checks(result)["Q13_qualifiers_kept"]["passed"])

    def test_negation_hedging_and_scope(self):
        scenarios = [
            ("Group A showed no difference.", "Group A showed a difference.", "difference", "negation differs"),
            ("Group A may improve accuracy.", "Group A improves accuracy.", "accuracy", "hedging differs"),
            ("Group A improved accuracy only under low lighting.", "Group A improved accuracy.",
             "accuracy", "missing scope"),
            ("Group A scored 28.4 BLEU after 3 days.", "Group A scored 28.4 BLEU.",
             "BLEU", "missing scope"),
        ]
        for quote, statement, obj, message in scenarios:
            with self.subTest(message=message):
                code, result, _ = self.run_bundle(quote, [claim(statement, quote, object=obj)])
                self.assertEqual(code, 1)
                self.assertIn(message, self.checks(result)["Q13_qualifiers_kept"]["detail"])

    def test_missing_quote_and_link_do_not_create_inference(self):
        quoted = "Group A scored 28.4 BLEU."
        missing = claim(quoted, "Group A scored 28.4 BLU.", locator={"page": 1, "paragraph": 1})
        second = claim(quoted, id="A2")
        edge = {"id": "R1", "subject": "A2", "predicate": "supports", "object": "A1",
                "evidence": {"quote": quoted}, "confidence": "high"}
        code, result, report = self.run_bundle(quoted, [missing, second], relations=[edge])
        self.assertEqual(code, 1)
        nanopub = result["nanopub"]
        self.assertEqual([a["id"] for a in nanopub["assertions"]], ["A2"])
        self.assertEqual(nanopub["relations"], [])
        self.assertEqual(nanopub["unresolved"][0]["reason"], "quote_not_found")
        self.assertEqual(nanopub["unresolved"][0]["locator_hint"], {"page": 1, "paragraph": 1})
        self.assertIn("Group A scored 28.4 BLU.", report)

    def test_supported_inference_and_example_table_pass(self):
        source = (HERE / "sample_source.txt").read_text(encoding="utf-8")
        code, result, _ = self.run_bundle(source, HERE / "expected_assertions.yaml")
        self.assertEqual(code, 0, self.checks(result))
        inference = next(a for a in result["nanopub"]["assertions"] if a["id"] == "A8")
        self.assertEqual(inference["inference_chain"][0]["from"], ["A6", "A7"])

    def test_circular_inferences_are_unresolved(self):
        quote = "Group A scored 28.4 BLEU."
        claims = [claim(quote, id=aid, relation="inferred", confidence="medium",
                        inference_chain=[{"from": [other], "rationale": "Use the other claim."}])
                  for aid, other in (("A1", "A2"), ("A2", "A1"))]
        code, result, _ = self.run_bundle(quote, claims)
        self.assertEqual(code, 1)
        self.assertEqual(result["nanopub"]["assertions"], [])
        self.assertEqual([u["reason"] for u in result["nanopub"]["unresolved"]], ["unsupported_inference"] * 2)

    def test_not_reported_only_can_complete(self):
        assertion = claim("The translation latency is not reported.", relation="not_reported", confidence="low")
        code, result, _ = self.run_bundle("Group A scored 28.4 BLEU.", [assertion])
        self.assertEqual(code, 0, self.checks(result))
        evidence = result["nanopub"]["assertions"][0]["evidence"]
        self.assertIsNone(evidence["locator"]["char_offset"])
        self.assertEqual(evidence["quote"], "")

    def test_repeated_quote_with_and_without_hints(self):
        quote = "Group A scored 28.4 BLEU."
        source = f"=== page 1 ===\nAbstract: {quote}\n=== page 2 ===\nResults: Group A scored\n28.4 BLEU."
        for hint in ({"page": 2}, {"prefix": "Results:"}):
            with self.subTest(hint=hint):
                code, result, _ = self.run_bundle(source, [claim(quote, locator=hint)])
                self.assertEqual(code, 0, self.checks(result))
                ev = result["nanopub"]["assertions"][0]["evidence"]
                self.assertEqual(ev["locator"]["page"], 2)
                start, end = ev["locator"]["char_offset"]
                self.assertEqual(source[start:end], ev["quote"])
                self.assertIn("\n", ev["quote"])
        code, result, report = self.run_bundle(source, [claim(quote)])
        self.assertEqual(code, 1)
        self.assertEqual(result["nanopub"]["unresolved"][0]["reason"], "ambiguous")
        self.assertIn("Candidate: page 1", report)
        self.assertIn("Candidate: page 2", report)

    def test_supporting_control_and_relation_offsets(self):
        quote = "Group A scored 28.4 BLEU."
        auxiliary = "Only under low lighting."
        source = f"=== page 1 ===\n{quote} {auxiliary}\n=== page 2 ===\n{quote} {auxiliary}\n"
        scope = {"condition": "only under low lighting"}
        a1 = claim(quote, locator={"page": 2}, controlling_quote=auxiliary,
                   controlling_quote_scope="scope_of_whole_claim", qualifiers=scope,
                   supporting_evidence=[{"quote": auxiliary, "locator": {"page": 1}}])
        edge = {"id": "R1", "subject": "A1", "predicate": "supports", "object": "A2",
                "evidence": {"quote": quote, "locator": {"page": 2}}, "confidence": "high"}
        code, result, _ = self.run_bundle(source, [a1, claim(quote, id="A2", locator={"page": 1})],
                                          relations=[edge])
        self.assertEqual(code, 0, self.checks(result))
        nanopub = result["nanopub"]
        self.assertEqual(nanopub["assertions"][0]["controlling_quote_locator"]["page"], 2)
        self.assertEqual(nanopub["assertions"][0]["supporting_evidence"][0]["locator"]["page"], 1)
        self.assertEqual(nanopub["relations"][0]["evidence"]["locator"]["page"], 2)
        nanopub["relations"][0]["evidence"]["locator"]["char_offset"] = [0, 1]
        checks, _ = np_validate.validate(nanopub, source)
        self.assertFalse(next(c for c in checks if c["id"] == "Q4_offset_matches")["passed"])

    def test_completion_requires_answer_and_agrees_across_outputs(self):
        quote = "Group A scored 28.4 BLEU."
        case = {"case_id": "case", "output_contract": {"type": "object", "required": ["answer"],
                                                          "properties": {"answer": {"type": "string"}}}}
        for fields, status, expected in [
            (None, "success", "partial"),
            ({"answer": ""}, "success", "partial"),
            ({"answer": 28.4}, "success", "partial"),
            ({"answer": "28.4 BLEU [A9]"}, "success", "partial"),
            ({"answer": "28.4 BLEU [A1]"}, "partial", "partial"),
            ({"answer": "28.4 BLEU [A1]"}, "success", "success"),
        ]:
            with self.subTest(fields=fields, status=status):
                _, result, _ = self.run_bundle(quote, [claim(quote)], case=case, fields=fields, status=status)
                self.assertEqual(result["status"], expected)
        code = subprocess.run([sys.executable, "-B", str(SCRIPTS / "np_validate.py"), str(self.result_path),
                               "--text", str(self.source), "--case", str(self.case)], capture_output=True).returncode
        self.assertEqual(code, 0)

    def test_negative_fixture_still_fails(self):
        source = (HERE / "sample_source.txt").read_text(encoding="utf-8")
        code, result, _ = self.run_bundle(source, HERE / "negative_assertions.yaml")
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(self.checks(result)["Q2_atomic"]["passed"])
        self.assertFalse(self.checks(result)["Q17_pending_evidence"]["passed"])

    def test_success_request_is_downgraded_by_schema_failure(self):
        quote = "Group A scored 28.4 BLEU."
        incomplete = claim(quote)
        del incomplete["text"]
        code, result, _ = self.run_bundle(quote, [incomplete])
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(self.checks(result)["Q16_json_schema"]["passed"])


if __name__ == "__main__":
    unittest.main()
