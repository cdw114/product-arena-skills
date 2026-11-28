"""Publication integrity checks, runnable against a previously submitted scripts directory."""
import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.environ.get("NANOPUB_TEST_SCRIPTS", str(Path(__file__).resolve().parents[1] / "scripts")))
import np_build as build
import np_validate as validate
from np_fidelity import claim_differences


def direct(quote, statement=None, **extra):
    return {"id": "A1", "claim_type": "result", "text": statement or quote, "confidence": "high",
            "subject": "yield", "predicate": "increased", "object": "product",
            "evidence": {"quote": quote, "relation": "direct", "quote_verbatim": True,
                         "locator": {"char_offset": [0, len(quote)]}}, **extra}


class PublicationIntegrity(unittest.TestCase):
    def test_direction(self):
        q = "Product yield increased."
        self.assertFalse(claim_differences(direct(q), q))
        self.assertTrue(claim_differences(direct(q, "Product yield decreased.", predicate="decreased"), q))

    def test_chinese_value(self):
        q = "该样品的吸收率为28.4%。"
        correct = direct(q, subject="该样品", predicate="为", object="吸收率")
        self.assertFalse(claim_differences(correct, q))
        self.assertTrue(claim_differences(dict(correct, text=q.replace("28.4", "82.4")), q))

    def test_comparison_sign(self):
        q = "The difference met p < 0.01."
        self.assertFalse(claim_differences(direct(q), q))
        self.assertTrue(claim_differences(direct(q, q.replace("<", ">")), q))

    def test_duplicate_relation_ids(self):
        q = "Product yield increased."
        edge = {"id": "R1", "subject": "A1", "object": "A2", "predicate": "supports",
                "evidence": direct(q)["evidence"], "confidence": "high"}
        graph = {"assertions": [direct(q), direct(q, id="A2")], "relations": [edge]}
        def ids_pass():
            checks, _ = validate.validate(graph, q)
            return next(c["passed"] for c in checks if c["id"] == "Q1_unique_ids")
        self.assertTrue(ids_pass())
        graph["relations"].append(dict(edge, subject="A2", object="A1"))
        self.assertFalse(ids_pass())

    def test_empty_extraction(self):
        checks, _ = validate.validate({"assertions": []}, "The result is 45%.")
        self.assertFalse(all(c["passed"] for c in checks))

    def test_short_paragraphs(self):
        q = "Long paragraph with at least five words."
        src = q + "\n\nYield rose."
        second = direct("Yield rose.", id="A2")
        second["evidence"]["locator"]["char_offset"] = [len(q) + 2, len(src)]
        coverage = build.coverage(src, [direct(q), second])
        self.assertEqual((coverage["paragraphs_total"], coverage["ratio"]), (2, 1))

    def test_grouped_citations(self):
        result = {"answer": "Recovered [A1, A9].", "nanopub": {"assertions": [{"id": "A1"}]}}
        self.assertFalse(validate.contract_check(result, {})["passed"])
        result["answer"] = "Recovered [A1]."
        self.assertTrue(validate.contract_check(result, {})["passed"])

    def test_quote_does_not_match_inside_latin_word(self):
        candidates, matches = build.locate("A region was sampled. An ion was observed.", "ion")
        self.assertEqual(matches, candidates)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["sentence"], 2)
        self.assertEqual(len(build.locate("观察到吸收率提高。", "吸收率")[1]), 1)

    def test_extracted_pages_do_not_imply_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            q = "Product yield increased."
            (root/"text.txt").write_text("=== page 1 ===\n" + q + "\n=== page 2 ===\nAppendix.", encoding="utf-8")
            (root/"draft.json").write_text(json.dumps([direct(q)]), encoding="utf-8")
            (root/"meta.json").write_text(json.dumps({"pages_with_text": [1, 2]}), encoding="utf-8")
            argv = ["np_build.py", "finalise", "--text", str(root/"text.txt"), "--assertions",
                    str(root/"draft.json"), "--text-meta", str(root/"meta.json"), "--out", str(root)]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                build.main()
            source = json.loads((root/"result.json").read_text(encoding="utf-8"))["sources"][0]
            self.assertNotIn(2, source["pages_read"])
            self.assertEqual(source["pages_with_text"], [1, 2])

    def test_trig(self):
        try:
            from rdflib import Dataset, Namespace
        except ImportError:
            self.skipTest("RDFLib required for independent TriG parsing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            q = '产物的收率提高。'
            claims = [direct(q, subject="产物", predicate="提高", object="收率")]
            (root/"claims.json").write_text(json.dumps(claims), encoding="utf-8")
            args = argparse.Namespace(assertions=str(root/"claims.json"), out=str(root/"out.trig"), orcid=None,
                                      base="https://example.org/test/", doc=None)
            with redirect_stdout(io.StringIO()):
                build.cmd_trig(args)
            ds = Dataset()
            ds.parse(args.out, format="trig")
            np = Namespace("http://www.nanopub.org/nschema#")
            graphs = [g for g in ds.graphs() if list(g.triples((None, np.hasAssertion, None)))]
            self.assertEqual(len(graphs), 1)
            for key in (np.hasAssertion, np.hasProvenance, np.hasPublicationInfo):
                names = list(graphs[0].objects(None, key))
                self.assertEqual(len(names), 1)
                self.assertGreater(len(ds.graph(names[0])), 0)
            self.assertNotIn("0000-0000-0000-0000", Path(args.out).read_text(encoding="utf-8"))
            self.assertFalse(any(getattr(o,"language", None) == "en" for _,_,o,_ in ds.quads((None,None,None,None))))
