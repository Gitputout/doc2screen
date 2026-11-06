"""Regression checks for content safety and verification decisions."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
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
from doc2screen import (_formats, _input_path, _parse_page_indices, _sample_doc,
                        cmd_preview, cmd_verify, pdf_ok, trim_doc)  # noqa: E402
from export_epub import epub_report, export_epub  # noqa: E402
from ocr_pdf import _page_arg, needs_ocr, ocr_command  # noqa: E402


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

    def test_page_indices_parse(self):
        self.assertEqual(_parse_page_indices("1,3-4", 5), [0, 2, 3])
        with self.assertRaises(SystemExit):
            _parse_page_indices("0", 5)

    def test_ocr_detection_and_command(self):
        self.assertTrue(needs_ocr({"pages": 1, "scannedLikePages": 1, "textChars": 0}))
        self.assertTrue(needs_ocr({"pages": 4, "scannedLikePages": 3, "textChars": 100}))
        self.assertFalse(needs_ocr({"pages": 4, "scannedLikePages": 3, "textChars": 1000}))
        self.assertFalse(needs_ocr({"pages": 1, "scannedLikePages": 0, "textChars": 100}))
        self.assertFalse(needs_ocr({"pages": 100, "scannedLikePages": 1, "textChars": 10000}))
        self.assertEqual(_page_arg([0, 2, 3]), "1,3,4")
        cmd = ocr_command(Path("in.pdf"), Path("out.pdf"), lang="chi_sim+eng",
                          pages=[0, 2, 3])
        self.assertIn("--pages", cmd)
        self.assertEqual(cmd[cmd.index("--pages") + 1], "1,3,4")

    @unittest.skipUnless(shutil.which("ocrmypdf") and shutil.which("tesseract"),
                         "OCR tools are not installed")
    def test_ocr_adds_text_layer(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf is not installed")
        from extract_pdf import extract_pdf
        from ocr_pdf import ocr_pdf, ocr_status

        if not ocr_status("eng")["ok"]:
            self.skipTest("Tesseract English data is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            scan_pdf = Path(tmp) / "scan.pdf"
            png = Path(tmp) / "page.png"
            d = pymupdf.open()
            p = d.new_page(width=600, height=300)
            p.insert_text((80, 160), "HELLO OCR", fontsize=48)
            p.get_pixmap(dpi=200).save(str(png))
            d.close()
            d = pymupdf.open()
            p = d.new_page(width=600, height=300)
            p.insert_image(p.rect, filename=str(png))
            d.save(str(scan_pdf))
            d.close()
            ocr_pdf_path = ocr_pdf(scan_pdf, Path(tmp) / "work", lang="eng")
            doc = extract_pdf(str(ocr_pdf_path), str(Path(tmp) / "extract"),
                              skip_full_page_images=True)
            text = " ".join(b.get("text", "") for b in doc["blocks"])
            self.assertIn("HELLO", text.upper())

    def test_sample_doc_keeps_representative_blocks(self):
        doc = {
            "meta": {"title": "T"},
            "blocks": [
                {"id": "b1", "type": "heading", "level": 1, "text": "Title"},
                {"id": "b2", "type": "paragraph", "text": "Body " * 500},
                {"id": "b3", "type": "code", "text": "print(1)"},
                {"id": "b4", "type": "figure", "asset": "a1"},
            ],
            "stats": {"pages": 3, "blocks": 4, "figures": 1, "codeBlocks": 1},
        }
        sample = _sample_doc(doc, max_blocks=2, max_chars=20)
        types = {b["type"] for b in sample["blocks"]}
        self.assertIn("heading", types)
        self.assertIn("code", types)
        self.assertIn("figure", types)
        self.assertTrue(sample["preview"]["truncated"])

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

    def test_pdf_toc_pages_are_skipped(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf is not installed")
        from extract_pdf import extract_pdf, inspect_pdf

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "toc.pdf"
            d = pymupdf.open()
            p = d.new_page(width=390, height=552)
            p.insert_text((40, 50), "Contents", fontsize=16)
            lines = [
                "1 Introduction........3",
                "2 Methods........4",
                "3 Results........5",
                "4 Conclusion........6",
            ]
            for i, line in enumerate(lines):
                p.insert_text((40, 80 + i * 18), line, fontsize=10)
            p = d.new_page(width=390, height=552)
            p.insert_text((40, 60), "Chapter 1", fontsize=15)
            p.insert_text((40, 100), "Body text that should survive.", fontsize=11)
            d.save(str(pdf))
            d.close()
            info = inspect_pdf(str(pdf))
            self.assertEqual(info["tocPages"], 1)
            doc = extract_pdf(str(pdf), str(Path(tmp) / "work"))
            texts = [b.get("text") or "" for b in doc["blocks"]]
            self.assertFalse(any("...." in t for t in texts))
            self.assertTrue(any("Chapter 1" in t for t in texts))
            self.assertEqual(doc["meta"]["tocPages"], 1)

    @unittest.skipUnless(shutil.which("pandoc"), "pandoc is required")
    def test_preview_generates_html_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "s.md"
            src.write_text("# Title\n\nBody paragraph.\n\n```python\nprint(1)\n```\n",
                           encoding="utf-8")
            out = Path(tmp) / "preview"
            args = argparse.Namespace(
                input=str(src), out=str(out), profiles="phone-notes", pages=None,
                formats="html", limit_pages=3, limit_blocks=12, max_chars=4000,
                title=None, no_embed=True, ocr="off", ocr_lang="chi_sim+eng",
                profile=None, width=None, height=None)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_preview(args), 0)
            report = json.loads((out / "preview.json").read_text(encoding="utf-8"))
            self.assertEqual(report["profiles"], ["phone-notes"])
            self.assertGreater(report["sampleBlockCount"], 0)
            self.assertTrue(report["questions"])
            self.assertTrue((out / "preview-phone-notes.html").exists())


if __name__ == "__main__":
    unittest.main()
