from __future__ import annotations

import unittest

from should_i_jev.audit import run_audit
from should_i_jev.code_scan import scan_code
from should_i_jev.report_html import render_html

from test_audit_report import FIXTURES, demo_audit


class HtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = demo_audit()
        cls.scan = scan_code(FIXTURES / "sample_code")
        cls.html = render_html(cls.audit, scan=cls.scan)

    def test_document_structure(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertTrue(self.html.rstrip().endswith("</html>"))
        for anchor in (
            'id="verdicts"',
            'id="models"',
            'id="signals"',
            'id="candidates"',
            'id="maps"',
            'id="code-sites"',
        ):
            self.assertIn(anchor, self.html)

    def test_self_contained(self):
        self.assertNotIn("<script src=", self.html)
        self.assertNotIn("<link ", self.html)
        self.assertNotIn("http://", self.html.replace("http://www.w3.org", ""))

    def test_numbers_present(self):
        self.assertIn("JEV migration audit", self.html)
        self.assertIn("Top migration candidates", self.html)
        self.assertIn("Code call sites", self.html)
        self.assertIn("decision-shaped", self.html)

    def test_redaction_applied(self):
        self.assertNotIn("sk-demo0123456789abcdef", self.html)
        self.assertNotIn("jane.doe", self.html)
        self.assertIn("[REDACTED@email]", self.html)

    def test_sortable_columns_have_handlers(self):
        self.assertIn("siSort(this)", self.html)
        self.assertIn("siFilter", self.html)

    def test_code_only_audit_renders(self):
        from should_i_jev.audit import Audit

        empty = Audit([], [], 0)
        html = render_html(empty, scan=self.scan)
        self.assertIn("Code call sites", html)
        self.assertIn("$0.00", html)


if __name__ == "__main__":
    unittest.main()
