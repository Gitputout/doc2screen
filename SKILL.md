---
name: doc2screen
description: Convert PDF, DOCX, EPUB, HTML, Markdown, and text documents into screen-adaptive reading editions. Use when the user wants to reflow a document for a phone or e-reader, produce a mobile-friendly self-contained HTML, EPUB, or phone-sized PDF, adapt a document to a specific screen size or aspect ratio, remove boilerplate/promotional pages, or build a clean reading version of a long document. Supports PDF text layers, DOCX/EPUB/HTML/Markdown via Pandoc, image extraction, TOC, dark mode, code blocks, and PDF export through Chrome.
---

# doc2screen

Turn documents into **screen-adaptive reading editions**: one semantic source, multiple outputs (self-contained HTML, EPUB3, PDF), tuned to a screen profile.

The core idea: **do not wrap the original layout in HTML**. Extract headings, paragraphs, lists, code, tables, and figures into a `DocModel`, then render a reflowable single-column reader. This is what makes it readable on a 6-inch phone instead of merely zoomable.

Design details: `DESIGN.md` in this skill directory.

## When to use

Use this skill when the user asks to:

- convert a PDF/DOCX/EPUB/HTML/Markdown into a phone-friendly or e-reader-friendly reading edition;
- adapt a document to a screen size/aspect ratio (e.g. 6.39-inch 16:9.5, Kindle, A4);
- produce self-contained HTML, EPUB3, or a PDF sized for a device;
- remove ads, QR codes, repeated headers/footers, or promotional pages while keeping the real content;
- make code blocks, tables, and wide screenshots readable on a narrow screen.

Do **not** use it for:

- editing the source document (use the docx/pdf skills);
- OCR-heavy scanned books where the user only needs text (recommend MinerU first);
- pixel-perfect PDF-to-HTML fidelity (this skill reflows by design).

## Quick start

Run from anywhere; paths below are relative to this skill directory.

```bash
SKILL=~/.claude/skills/doc2screen

# 1. Inspect the source
python3 "$SKILL/scripts/doc2screen.py" inspect input.pdf --out work/

# 2. Extract to a DocModel
python3 "$SKILL/scripts/doc2screen.py" extract input.pdf --out work/

# 3. Build PDF (default; profile defaults to phone-notes)
python3 "$SKILL/scripts/doc2screen.py" build input.pdf \
  --profile phone-notes --out out/

# 4. Verify
python3 "$SKILL/scripts/doc2screen.py" verify out/ --profile phone-notes
```

The default output is **PDF only**. Add HTML/EPUB only when asked:

```bash
--formats html,epub,pdf
```

Trim a section and drop known promos before building:

```bash
python3 "$SKILL/scripts/doc2screen.py" build input.pdf \
  --profile phone-notes \
  --start-at "Chapter 1" --end-at "Appendix" \
  --drop-text "扫码" --drop-text "公众号" \
  --drop-asset a0004 --title "My Book" --out out/
```

- `--start-at/--end-at`: keep only a heading-delimited range.
- `--drop-text`: remove blocks containing the text (review first).
- `--drop-asset`: remove a figure by asset id from `work/doc.json`.
- `--no-embed`: write an assets folder instead of inlining images.

Or run `build` directly on a DOCX/EPUB/HTML/MD:

```bash
python3 "$SKILL/scripts/doc2screen.py" build report.docx \
  --profile kindle --out out/
```

## Profiles

Defined in `profiles/devices.json`:

- `phone-notes` — 390×552 CSS px, ratio 0.706 (Huawei Notes-like; **default** for phone reading)
- `phone-16x9.5` — 390×657 CSS px (6.39-inch 16:9.5 full-screen)
- `phone-16x9` — 390×693
- `phone-19.5x9` — 390×845
- `kindle` — 600×800
- `a5` — 559×794
- `a4` — 794×1123
- custom: `--width 412 --height 733`

HTML is always fluid; the profile sets reading width, base font size, margins, and the PDF page size.

A device ratio and a page ratio are not the same. A 6.39″ 16:9.5 screen is ~82.9 × 139.6 mm; the default 0.706 page is ~82.9 × 117.4 mm at fit-width. Full formulas and examples: `docs/screen-profiles.md`. To compute a profile:

```bash
python3 "$SKILL/scripts/profile_helper.py" \
  --inches 6.39 --aspect 16:9.5 --page-ratio 0.706 --css-width 390
```

## Workflow

### 1. Inspect before extracting

`inspect` reports page count, text-layer health (radical/CJK compatibility/replacement characters), image count, suspected scans, and column layout. If the text layer is empty or badly corrupted:

- recommend MinerU for OCR/complex layout;
- the OCR adapter is planned; v0.1 reports the problem and does not fabricate text.

### 2. Extract

- PDF text layer: PyMuPDF backend (local, v0.1). The open-source default is planned to be pypdfium2; a `--pdf-backend` switch is planned for Phase 3.
- DOCX/ODT/EPUB/HTML/Markdown: Pandoc → semantic HTML → blocks.
- TXT: paragraphizer.
- PPTX: not supported in v1; say so and suggest converting via LibreOffice.

Artifacts: `work/doc.json`, `work/assets/`, `work/extract.log`.

### 3. Review the model (important)

`doc.json` is intentionally readable. Before rendering a long document, inspect:

- headings and TOC structure;
- repeated headers/footers/page numbers;
- promo blocks, QR images, “扫码/关注/公众号/训练营” text;
- figure captions and image order;
- warnings (OCR pages, missing fonts, text-layer damage).

**Never delete content automatically.** `curate`/`curation.json` uses `keep`, `remove`, `flag` with reasons. If you remove something, report exactly what and why.

### 4. Render

`render` produces a self-contained HTML reader by default:

- sticky top bar + progress;
- TOC drawer, font-size control, dark/light theme;
- code blocks with copy;
- image viewer with fit / rotate / horizontal-strip modes;
- screen-profile typography;
- print CSS for PDF export.

### 5. Build

`build` = extract → trim → render (internal HTML for PDF) → PDF → verify. **Default `--formats` is `pdf`**; optional: `html`, `epub`. `phone-notes` is the default profile.

PDF export uses Chrome headless through `scripts/export_pdf.js` (puppeteer-core). In print CSS, images are scaled with `max-height`, so tall screenshots are not clipped; code wraps; chapters start on new pages; page numbers and bookmarks are added.

EPUB export uses stdlib zip: XHTML chapters, nav, OPF, NCX, CSS, images; no JS.

### 6. Verify

`verify` checks:

- HTML has no horizontal overflow at the profile width and at 15/21px font sizes;
- all images loaded and figure boxes have non-zero height;
- TOC links resolve;
- PDF page size, blank pages, image aspect ratios, outline;
- EPUB `mimetype`/OPF/nav/manifest integrity.

Fix failures, do not ship a broken PDF/EPUB.

## Content curation

Use explicit, auditable options; do not silently delete content:

- `--start-at "Chapter 1"` / `--end-at "Appendix"`: keep a heading-delimited range;
- `--drop-text "扫码" --drop-text "训练营"`: remove blocks containing text;
- `--drop-asset a0004`: remove a figure (find asset ids in `work/doc.json`).

Always report what was removed and why. The extractor automatically removes repeated headers/footers/page numbers and deduplicates images; promo blocks and QR images are not silently deleted.

## Dependencies

Core:

- Python 3.11+
- `pymupdf` (local PDF backend; AGPL-3.0/commercial — see license note)
- `lxml` (HTML parsing)
- `pandoc` (DOCX/EPUB/HTML/Markdown)
- Node.js + `puppeteer-core` (PDF export/verification), installed in `tools/`
- Google Chrome (PDF export)

Optional/Phase 3: pypdfium2 (permissive PDF backend), MinerU (OCR/complex layout), Tesseract. EPUB export is implemented in v0.1 (basic, no panel splitting yet).

Check with:

```bash
python3 "$SKILL/scripts/doc2screen.py" doctor
```

## License boundaries

- **v0.1 is AGPL-3.0**, because the PDF backend imports PyMuPDF (AGPL-3.0). See `LICENSE`.
- A future pypdfium2 backend can allow a permissive license; do not claim Apache/MIT for the current code.
- PyMuPDF is **AGPL-3.0 or commercial**. Local/personal use is fine; if you distribute this skill with PyMuPDF imported, AGPL obligations apply. The planned open-source default is pypdfium2; PyMuPDF stays an optional backend.
- Pandoc/Chrome are external commands; do not bundle them.
- MinerU (optional) is invoked as a CLI, not vendored; check its `LICENSE.md` and model licenses before commercial use.
- Do not put copyrighted source documents or converted outputs into a public repo.
- See `THIRD_PARTY.md` and `references/research.md`.

## Report to the user

Always include:

- input and output paths;
- page/block/figure counts;
- what was removed or flagged (with reasons);
- warnings (scanned pages, OCR, missing fonts, tables/figures kept as images);
- which profile was used and how to change it.

## Troubleshooting

- **Text looks corrupted** (`⽤`, `���`): text-layer radical/CJK issue; inspect warns; re-extract with `--fix` or use MinerU/OCR.
- **No images** in DOCX/EPUB: Pandoc `--extract-media` path; check `work/assets/`.
- **PDF export fails**: check `node`, `puppeteer-core`, Chrome path; run `doctor`.
- **PDF images clipped**: print CSS must override `.is-strip`/`.is-rot`; verify reports aspect mismatches.
- **EPUB check fails**: inspect `epub_report`; ensure `mimetype` is first/uncompressed, OPF/nav XML is valid, all manifest hrefs exist. Wide images are full-width in v0.1 (panel splitting planned).
