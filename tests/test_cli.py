from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def test_demo_end_to_end(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.md"
            code = main(["--demo", "--report", str(report)])
            self.assertEqual(code, 0)
            text = report.read_text(encoding="utf-8")
            self.assertIn("# JEV migration audit", text)
            self.assertIn("## TL;DR", text)
            self.assertIn("## Code call sites", text)  # demo scans bundled sample code

    def test_demo_writes_html_dashboard(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            dash = Path(td) / "dash.html"
            code = main(["--demo", "--report", str(Path(td) / "r.md"), "--html", str(dash)])
            self.assertEqual(code, 0)
            html = dash.read_text(encoding="utf-8")
            self.assertTrue(html.startswith("<!doctype html>"))

    def test_code_only_mode(self):
        from importlib.resources import files
        from should_i_jev.cli import main

        sample = Path(str(files("should_i_jev").joinpath("fixtures"))) / "sample_code"
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "r.md"
            code = main(["--scan-code", str(sample), "--report", str(report)])
            self.assertEqual(code, 0)
            text = report.read_text(encoding="utf-8")
            self.assertIn("## Code call sites", text)
            self.assertIn("support_router.py", text)

    def test_missing_inputs_exit_code(self):
        from should_i_jev.cli import main

        self.assertEqual(main([]), 2)

    def test_missing_file_warns(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            code = main(["/definitely/not/here.jsonl", "--report", str(Path(td) / "r.md")])
            self.assertEqual(code, 2)

    def test_threshold_validation(self):
        from should_i_jev.cli import main

        self.assertEqual(main(["--demo", "--min-score", "0.1", "--maybe-threshold", "0.9"]), 2)


if __name__ == "__main__":
    unittest.main()
