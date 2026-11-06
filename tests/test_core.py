"""Regression checks for content safety and verification decisions."""
from __future__ import annotations

import argparse
import contextlib
import io
import posixpath
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common import clean_inline_html  # noqa: E402
from doc2screen import _formats, _input_path, cmd_verify, pdf_ok, trim_doc  # noqa: E402
from export_epub import epub_report, export_epub  # noqa: E402


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

    def test_formats_are_validated(self):
        self.assertEqual(_formats(None), ["pdf"])
        self.assertEqual(_formats("HTML, epub"), ["html", "epub"])
        with self.assertRaises(SystemExit):
            _formats("pdf,docx")
        with self.assertRaises(SystemExit):
            _formats(",")

    def test_missing_input_reports_clear_error(self):
        with self.assertRaises(SystemExit) as ctx:
            _input_path("/definitely/not/a/real/file")
        self.assertIn("does not exist", str(ctx.exception))

    def test_drop_text_matches_html_only_blocks(self):
        doc = {"blocks": [
            {"id": "b1", "type": "table",
             "html": "<table><tr><td>PROMO</td></tr></table>"},
            {"id": "b2", "type": "quote", "html": "<blockquote>PROMO quote</blockquote>"},
            {"id": "b3", "type": "callout", "html": "<div>PROMO callout</div>"},
            {"id": "b4", "type": "paragraph", "text": "keep"}]}
        report = trim_doc(doc, drop_text=["PROMO"])
        self.assertEqual([b["id"] for b in doc["blocks"]], ["b4"])
        self.assertEqual(len(report["removed"]), 3)

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

    @unittest.skipUnless(shutil.which("pandoc"), "pandoc is required")
    def test_pandoc_extraction_preserves_utf8_text(self):
        try:
            from extract_pandoc import extract_via_pandoc
        except ImportError:
            self.skipTest("pymupdf/lxml are not installed")

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "zh.md"
            src.write_text("# 中文标题\n\n这是一段中文正文。\n", encoding="utf-8")
            doc = extract_via_pandoc(str(src), str(Path(tmp) / "work"))
            texts = [b.get("text", "") for b in doc["blocks"]]
            self.assertIn("中文标题", texts)
            self.assertIn("这是一段中文正文。", texts)

    def test_epub_nav_stylesheet_path_resolves(self):
        doc = {
            "meta": {"title": "测试书", "language": "zh-CN"},
            "blocks": [{"id": "b1", "type": "heading", "level": 1, "text": "第一章"}],
            "assets": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            export_epub(doc, str(epub), tmp)
            with zipfile.ZipFile(epub) as z:
                names = set(z.namelist())
                nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
                href = re.search(r'<link[^>]+href="([^"]+)"', nav).group(1)
                target = posixpath.normpath(posixpath.join("OEBPS", href))
                self.assertIn(target, names)
            report = epub_report(str(epub))
            self.assertTrue(report["ok"], report["errors"])

    def test_epub_xhtml_uses_document_language(self):
        doc = {
            "meta": {"title": "Book", "language": "en"},
            "blocks": [{"id": "b1", "type": "heading", "level": 1, "text": "Chapter"}],
            "assets": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            export_epub(doc, str(epub), tmp)
            with zipfile.ZipFile(epub) as z:
                for name in ("OEBPS/nav.xhtml", "OEBPS/text/chapter-001.xhtml"):
                    content = z.read(name).decode("utf-8")
                    self.assertIn('xml:lang="en"', content)

    def test_verify_rejects_wrong_size_pdf(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "wrong.pdf"
            d = pymupdf.open()
            p = d.new_page(width=595, height=842)
            p.insert_text((72, 72), "wrong size")
            d.save(str(pdf))
            d.close()
            args = argparse.Namespace(target=str(pdf), out=tmp,
                                      profile="phone-notes", width=None, height=None)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_verify(args), 1)

    def test_verify_reads_build_profile(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "kindle.pdf"
            d = pymupdf.open()
            p = d.new_page(width=450, height=600)
            p.insert_text((72, 72), "kindle size")
            d.save(str(pdf))
            d.close()
            (Path(tmp) / "build.json").write_text(
                '{"profile": "kindle"}', encoding="utf-8")
            args = argparse.Namespace(target=str(pdf), out=tmp,
                                      profile=None, width=None, height=None)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_verify(args), 0)

    def test_pdf_text_blocks_keep_source_bbox(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf is not installed")
        from extract_pdf import extract_pdf

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "text.pdf"
            d = pymupdf.open()
            p = d.new_page(width=390, height=552)
            p.insert_text((72, 72), "Hello source")
            d.save(str(pdf))
            d.close()
            doc = extract_pdf(str(pdf), str(Path(tmp) / "work"))
            block = next(b for b in doc["blocks"]
                         if b["type"] in ("heading", "paragraph"))
            self.assertTrue(any(block["source"]["bbox"]))


if __name__ == "__main__":
    unittest.main()
