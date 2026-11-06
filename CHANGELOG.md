# Changelog

## Unreleased

- Detect OCR needs per scanned page, including PDFs that mix text and scans.
- Retain a scan image when OCR does not add text to that page.
- Tighten printed-TOC detection and retain isolated TOC-looking lines in body pages.

## v0.2.0 — 2026-11-06

### Added

- `preview` command: samples representative pages/blocks, renders candidate screen profiles (HTML/PDF), and writes `preview.json` for user confirmation before a full build.
- Scanned-PDF OCR via OCRmyPDF + Tesseract: `--ocr auto|off|force`, `--ocr-lang`, page-limited preview OCR, source-hash cache, and `doctor` checks.
- Printed TOC detection: dot-leader/page-number lines and TOC pages are skipped, with `toc-pages`/`toc-lines` warnings and `meta.tocPages`; the reader rebuilds its TOC from headings.
- `docs/conversion-risks.md`: preflight checklist for TOC, OCR, columns, tables, figures, text-layer damage, and profile selection.

### Fixed

- UTF-8 text in DOCX/EPUB/HTML/Markdown/RST/LaTeX via Pandoc was decoded as Latin-1 and became mojibake.
- `verify` now enforces PDF page size/aspect (not just blank pages) and reads the profile from `build.json` when omitted.
- EPUB `nav.xhtml` stylesheet path; `epub_report` now validates local XHTML `href`/`src` references.
- EPUB XHTML uses the document language instead of hard-coded `zh-CN`.
- PDF text blocks now keep their real `source.bbox`.
- `--formats` rejects unknown/empty values; missing inputs produce clear errors.
- `--drop-text` now matches tables, quotes, and callouts; previews in `build.json` are whitespace-normalized.
- OCR mode skips full-page background images so scanned page images do not duplicate the reflowed text.
- README/SKILL/DESIGN aligned with the implemented trim/drop/OCR/preview behavior.

### Changed

- `build` includes extraction warnings in `build.json`.
- CI installs OCR dependencies and runs the OCR integration test.
- Docs and license notes now refer to v0.2.

## v0.1.0 — 2026-11-05

- Initial public release: PDF/DOCX/ODT/EPUB/HTML/Markdown/RST/LaTeX/TXT input, self-contained HTML, EPUB3, screen-sized PDF, profiles, reader UI, verification, PDF bookmarks, AGPL-3.0.
