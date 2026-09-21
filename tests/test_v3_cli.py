from __future__ import annotations

import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

FIXTURES = Path(str(files("should_i_jev").joinpath("fixtures")))


class CalibrateCliTests(unittest.TestCase):
    def test_calibrate_with_baseline(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "calib.md"
            html = Path(td) / "calib.html"
            code = main(
                [
                    "calibrate",
                    str(FIXTURES / "calibration" / "decisions_jev.jsonl"),
                    "--baseline", str(FIXTURES / "calibration" / "decisions_llm.jsonl"),
                    "--report", str(report),
                    "--html", str(html),
                ]
            )
            self.assertEqual(code, 0)
            md = report.read_text(encoding="utf-8")
            self.assertIn("# Decision-model calibration report", md)
            self.assertIn("jev-latest", md)
            self.assertIn("gpt-4o-mini", md)
            self.assertIn("Risk–coverage", md)
            html_text = html.read_text(encoding="utf-8")
            self.assertIn("<svg", html_text)
            self.assertIn("polyline", html_text)

    def test_calibrate_missing_file(self):
        from should_i_jev.cli import main

        self.assertEqual(main(["calibrate", "/nope.jsonl"]), 2)

    def test_calibrate_bad_bins(self):
        from should_i_jev.cli import main

        self.assertEqual(
            main(["calibrate", str(FIXTURES / "calibration" / "decisions_jev.jsonl"), "--bins", "1"]), 2
        )


class MigrateCliTests(unittest.TestCase):
    def test_migrate_no_apply(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            code = main(
                ["migrate", "--scan-code", str(FIXTURES / "sample_code"),
                 "--out-dir", str(out_dir)]
            )
            self.assertEqual(code, 0)
            self.assertTrue((out_dir / "migration.patch").is_file())
            self.assertTrue((out_dir / "jev_maps.py").is_file())
            self.assertTrue((out_dir / "MIGRATION.md").is_file())

    def test_migrate_missing_path(self):
        from should_i_jev.cli import main

        self.assertEqual(main(["migrate", "--scan-code", "/definitely/not/here"]), 2)


class SelfcheckCliTests(unittest.TestCase):
    def test_demo_selfcheck_section(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "r.md"
            html = Path(td) / "r.html"
            code = main(
                ["--demo", "--jev-selfcheck", "--report", str(report), "--html", str(html)]
            )
            self.assertEqual(code, 0)
            md = report.read_text(encoding="utf-8")
            self.assertIn("## Jev self-audit", md)
            self.assertIn("agreement", md)
            html_text = html.read_text(encoding="utf-8")
            self.assertIn("Jev self-audit", html_text)

    def test_mock_forced(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "r.md"
            code = main(
                ["--demo", "--jev-selfcheck", "--jev-mock",
                 "--jev-base-url", "http://127.0.0.1:1/", "--report", str(report)]
            )
            self.assertEqual(code, 0)  # --jev-mock must win over the unreachable URL
            self.assertIn("Offline stand-in backend (mock)", report.read_text(encoding="utf-8"))


class SubcommandDispatchTests(unittest.TestCase):
    def test_audit_subcommand_still_works(self):
        from should_i_jev.cli import main

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "r.md"
            code = main(["audit", "--demo", "--report", str(report)])
            self.assertEqual(code, 0)
            self.assertIn("# JEV migration audit", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
