from __future__ import annotations

import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from should_i_jev.code_scan import scan_code

SAMPLE = Path(str(files("should_i_jev").joinpath("fixtures"))) / "sample_code"


class CodeScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = scan_code(SAMPLE)

    def test_finds_all_sample_sites(self):
        self.assertEqual(self.scan.files_scanned, 4)
        self.assertEqual(len(self.scan.findings), 6)
        self.assertEqual(self.scan.decision_shaped, 4)
        self.assertEqual(self.scan.errors, 0)

    def test_verdicts(self):
        by_loc = {(f.path, f.line): f for f in self.scan.findings}
        self.assertEqual(by_loc[("support_router.py", 10)].detail.verdict, "likely")
        self.assertEqual(by_loc[("email_policies.py", 10)].detail.verdict, "likely")
        self.assertEqual(by_loc[("email_policies.py", 22)].detail.verdict, "maybe")
        self.assertEqual(by_loc[("content_gen.py", 8)].detail.verdict, "unlikely")
        self.assertEqual(by_loc[("intent_router.ts", 8)].detail.verdict, "likely")
        self.assertEqual(by_loc[("intent_router.ts", 21)].detail.verdict, "unlikely")

    def test_python_extraction(self):
        router = next(f for f in self.scan.findings if f.path == "support_router.py")
        self.assertEqual(router.language, "python")
        self.assertEqual(router.model, "gpt-4o-mini")
        self.assertIn("chat.completions.create", router.api)
        self.assertIn("Route this ticket", router.prompt_excerpt)
        self.assertIn("enum membership", router.handling)

    def test_name_resolved_model(self):
        escalation = next(
            f for f in self.scan.findings if f.path == "email_policies.py" and f.line == 22
        )
        self.assertEqual(escalation.model, "claude-3-5-haiku")  # via ESCALATION_MODEL constant

    def test_js_extraction(self):
        intent = next(
            f for f in self.scan.findings if f.path == "intent_router.ts" and f.line == 8
        )
        self.assertEqual(intent.language, "js")
        self.assertEqual(intent.model, "gpt-4o")
        self.assertIn("Label the intent", intent.prompt_excerpt)

    def test_no_duplicate_js_matches(self):
        lines = [f.line for f in self.scan.findings if f.path == "intent_router.ts"]
        self.assertEqual(sorted(lines), [8, 21])  # each call site reported exactly once

    def test_no_false_positives_in_ordinary_code(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "plain.py").write_text(
                "def complete(task):\n"
                "    return db.completion(model='postgres-v2') if task else None\n",
                encoding="utf-8",
            )
            (d / "app.js").write_text(
                "const done = tasks.filter(t => t.complete);\n", encoding="utf-8"
            )
            scan = scan_code(d)
            self.assertEqual(scan.findings, [])
            self.assertEqual(scan.files_scanned, 2)

    def test_single_file_scan(self):
        scan = scan_code(SAMPLE / "support_router.py")
        self.assertEqual(len(scan.findings), 1)
        self.assertEqual(scan.findings[0].path, "support_router.py")


if __name__ == "__main__":
    unittest.main()
