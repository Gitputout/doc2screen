# Third-Party Notices

**Project license:** AGPL-3.0 (see `LICENSE`). v0.2 imports PyMuPDF, which is AGPL-3.0 or commercial; the whole distributed work is therefore AGPL-3.0. A future pypdfium2 backend can allow a permissive license.

doc2screen is an original implementation. It does **not** copy source code, documentation text, images, test fixtures, or model weights from the projects below. The list separates runtime dependencies from concept references.

## Runtime dependencies (imported)

| Package | License | Use |
|---|---|---|
| PyMuPDF (pymupdf) | **AGPL-3.0 or Artifex commercial** | PDF extraction (v0.2 local backend) |
| lxml | BSD-3-Clause | HTML parsing |
| pypdfium2 (planned default) | Apache-2.0 / BSD-3-Clause | Permissive PDF backend |
| WeasyPrint (planned) | BSD-3-Clause | PDF fallback |

> PyMuPDF is AGPL-3.0. Local/personal use is fine. If you distribute doc2screen with PyMuPDF imported, AGPL obligations apply (source, notices, network-service source offer). The open-source plan is to default to pypdfium2 and keep PyMuPDF optional.

## External commands (not bundled)

| Tool | License | Use |
|---|---|---|
| Pandoc | GPL-2.0-or-later | DOCX/ODT/EPUB/HTML/Markdown → semantic HTML |
| OCRmyPDF | MPL-2.0 | Optional scanned-PDF OCR (external command) |
| Tesseract | Apache-2.0 | Optional OCR engine; language data has upstream licenses |
| Google Chrome / Chromium | proprietary / BSD | HTML → PDF (headless) |
| Node.js | MIT | runtime for PDF/verification helpers |
| puppeteer-core | Apache-2.0 | drive Chrome for PDF/verification |
| MinerU (optional) | see upstream `LICENSE.md` (GitHub reports NOASSERTION) | OCR/complex layout adapter (planned) |
| Tesseract (optional) | Apache-2.0 | OCR fallback (planned) |
| LibreOffice (optional) | MPL-2.0 | PPTX/ODT conversion (planned) |

## Concept references (no code copied)

| Project | License | What was studied |
|---|---|---|
| Docling | MIT | document model with blocks, provenance, reading order |
| MinerU | check upstream | layout/OCR pipeline, image/table treatment |
| Marker | Apache-2.0 | output-format abstraction |
| PDF-Reflow | MIT (own code; AGPL/GPL deps) | responsive single-column reader, self-contained export |
| k2pdfopt | GPL | column detection / reflow / crop ideas |
| pdf2htmlEX | GPL | fidelity-vs-reflow trade-off |
| Pandoc | GPL-2+ | single-source → multiple outputs |
| Calibre | GPL-3.0 | EPUB packaging concepts |

No source, documentation prose, screenshots, sample documents, or models from these projects are included in this repository.

## Content

Sample documents used during development must be public domain, self-authored, or used with permission. Do not commit copyrighted PDFs or their converted outputs.
