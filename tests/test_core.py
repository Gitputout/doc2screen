"""Regression checks for content safety and verification decisions."""
from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common import clean_inline_html  # noqa: E402
from doc2screen import pdf_ok, trim_doc  # noqa: E402
from export_epub import epub_report  # noqa: E402


class CoreChecks(unittest.TestCase):
    def test_sanitized_markup_is_xhtml_safe(self):
        fragment = clean_inline_html(
            '<table onclick="alert(1)"><tr><td>A<br>B</td></tr></table>')
        self.assertNotIn("onclick", fragment)
        ET.fromstring(f"<root>{fragment}</root>")

    def test_trim_preserves_source_page_count_and_rejects_missing_boundary(self):
        doc = {"blocks": [
            {"id": "b1", "type": "heading", "text": "Chapter 1"},
            {"id": "b2", "type": "paragraph", "text": "Text"}],
            "stats": {"pages": 12}}
        with self.assertRaises(SystemExit):
            trim_doc(doc, start_at="Chapter 9")
        trim_doc(doc, start_at="Chapter 1")
        self.assertEqual(doc["stats"]["pages"], 12)

    def test_pdf_report_failures_affect_success(self):
        report = {"pages": 2, "blankPages": 0, "aspectMismatch": [],
                  "pageSize": [292.5, 414], "expectedSize": [292.5, 414]}
        self.assertTrue(pdf_ok(report))
        self.assertFalse(pdf_ok({**report, "pageSize": [300, 414]}))
        self.assertFalse(pdf_ok({**report, "aspectMismatch": [{"page": 1}]}))

    def test_epub_checks_chapter_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.epub"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("mimetype", "application/epub+zip",
                           compress_type=zipfile.ZIP_STORED)
                z.writestr("META-INF/container.xml", "<container/>")
                z.writestr("OEBPS/content.opf", "<package/>")
                z.writestr("OEBPS/nav.xhtml", "<html/>")
                z.writestr("OEBPS/text/chapter-001.xhtml", "<p>A<br>B</p>")
            report = epub_report(str(path))
            self.assertFalse(report["ok"])
            self.assertTrue(any("chapter-001.xhtml" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
