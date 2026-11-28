"""Exercise scope, contract and evidence checks on synthetic cases."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(os.environ.get("NANOPUB_TEST_SCRIPTS", Path(__file__).resolve().parents[1] / "scripts"))


class CasePipelineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)

    def write(self, name, content):
        file = self.work / name
        file.write_text(content, encoding="utf-8")
        return file

    def run_tool(self, filename, *args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(SCRIPTS / filename), *map(str, args)],
            cwd=self.work, capture_output=True, text=True, encoding="utf-8",
        )

    def build(self, claims, *, case=None, fields=None, metadata=False, status="success"):
        self.write("assertions.json", json.dumps(claims, ensure_ascii=False))
        args = ["finalise", "--text", "text.txt", "--assertions", "assertions.json",
                "--out", "out", "--status", status]
        if case is not None:
            self.write("case.json", json.dumps(case))
            args.extend(["--case", "case.json"])
        if fields is not None:
            self.write("fields.json", json.dumps(fields))
            args.extend(["--fields", "fields.json"])
        if metadata:
            args.extend(["--text-meta", "meta.json"])
        completed = self.run_tool("np_build.py", *args)
        path = self.work / "out/result.json"
        self.assertTrue(path.exists(), completed.stderr)
        return completed, json.loads(path.read_text(encoding="utf-8"))

    def claim(self, quote="Model A scored 28.4 BLEU.", **overrides):
        return {"id": "A1", "text": quote, "claim_type": "result", "subject": "Model A",
                "predicate": "scored", "object": "BLEU", "quote": quote,
                "relation": "direct", "confidence": "high", **overrides}

    def fixture_pdf(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF is needed for the mixed-text PDF fixture")
        with fitz.open() as document:
            document.new_page().insert_text((72, 72), "Model A scored 28.4 BLEU.")
            document.new_page()
            document.save(self.work / "mixed.pdf")

    def extract(self, name, *args):
        return self.run_tool("np_extract.py", name, "--out", "text.txt", "--meta", "meta.json", *args)

    def test_mixed_pdf_reports_missing_page_and_build_stays_partial(self):
        self.fixture_pdf()
        extracted = self.extract("mixed.pdf")
        self.assertEqual(extracted.returncode, 0, extracted.stderr)
        meta = json.loads(extracted.stdout)
        self.assertEqual(meta["pages"], 2)
        self.assertEqual(meta["pages_without_text"], [2])
        completed, result = self.build([self.claim()], metadata=True)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"][0]["pages_without_text"], [2])

    def test_scoped_ocr_preserves_physical_page_and_confidence(self):
        self.fixture_pdf()
        quote = "Model A scored 28.4 BLEU."
        self.write("page-2.txt", quote)
        extracted = self.extract("mixed.pdf", "--pages", "2", "--ocr-text", "2=page-2.txt")
        self.assertEqual(extracted.returncode, 0, extracted.stderr)
        self.assertNotIn("=== page 1 ===", (self.work / "text.txt").read_text())
        self.assertEqual(json.loads(extracted.stdout)["ocr_pages"], [2])
        _, result = self.build([self.claim()], metadata=True)
        self.assertEqual(result["status"], "partial")
        _, result = self.build([self.claim(confidence="medium")], metadata=True)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["nanopub"]["assertions"][0]["evidence"]["locator"]["page"], 2)

    def test_missing_input_leaves_a_failed_bundle_with_source_diagnostic(self):
        self.write("text.txt", "Old evidence from a different run.")
        extracted = self.extract("missing.pdf")
        self.assertEqual(extracted.returncode, 2)
        self.assertEqual((self.work / "text.txt").read_text(), "")
        self.assertEqual(json.loads((self.work / "meta.json").read_text())["reason"], "source_unavailable")
        _, result = self.build([], metadata=True, case={"case_id": "missing"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["nanopub"]["unresolved"][0]["reason"], "source_unavailable")

    def test_nested_contract_reference_and_structured_answers(self):
        self.write("text.txt", self.claim()["quote"])
        response = {"type": "object", "required": ["response", "claim_ids"],
                    "properties": {"response": {"type": "string"},
                                   "claim_ids": {"type": "array", "items": {"type": "string"}}}}
        case = {"case_id": "structured", "output_contract": {
            "type": "object", "required": ["answer"],
            "properties": {"answer": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/response"}}},
            "$defs": {"response": response},
        }}
        for ids, expected in ((["A1"], "success"), (["A9"], "partial")):
            with self.subTest(ids=ids):
                fields = {"answer": [{"response": "28.4 BLEU.", "claim_ids": ids}]}
                _, result = self.build([self.claim()], case=case, fields=fields)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["answer"], fields["answer"])

    def test_layout_table_binds_metric_to_the_correct_column(self):
        row = "Model A               28.4              24.1"
        self.write("text.txt", "Model                 WMT DE (BLEU)     WMT FR (BLEU)\n" + row)
        locator = {"table": {"row": "Model A", "column": "WMT DE (BLEU)"}}
        for value, expected in ((28.4, "success"), (24.1, "partial")):
            with self.subTest(value=value):
                assertion = self.claim(row, text=f"Model A scored {value} BLEU.",
                                       locator=locator, qualifiers={"metric": "WMT DE (BLEU)"})
                _, result = self.build([assertion])
                self.assertEqual(result["status"], expected)

    def test_incomplete_layout_row_needs_review(self):
        row = "Model A               24.1"
        self.write("text.txt", "Model                 WMT DE (BLEU)     WMT FR (BLEU)\n" + row)
        assertion = self.claim(row, text="Model A scored 24.1.", object="24.1",
                               locator={"table": {"row": "Model A", "column": "WMT DE (BLEU)"}})
        _, result = self.build([assertion])
        self.assertEqual(result["status"], "partial")
        check = next(c for c in result["nanopub"]["quality"]["checks"] if c["id"] == "Q13_qualifiers_kept")
        self.assertIn("table row and column", check["detail"])

    def test_inference_rejected_if_a_bound_premise_fails_fidelity(self):
        quote = "Model A scored 28.4 BLEU."
        self.write("text.txt", quote)
        direct = self.claim(quote, text="Model A scored 82.4 BLEU.")
        inferred = self.claim(quote, id="A2", text="The score is above 80 BLEU.", confidence="medium",
                              relation="inferred", inference_chain=[{"from": ["A1"], "rationale": "82.4 > 80"}])
        _, result = self.build([direct, inferred])
        self.assertEqual(result["status"], "partial")
        self.assertEqual([a["id"] for a in result["nanopub"]["assertions"]], ["A1"])
        self.assertEqual(result["nanopub"]["unresolved"][0]["evidence_id"], "A2")
