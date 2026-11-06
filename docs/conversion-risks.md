# Conversion risk checklist

doc2screen reflows documents instead of copying their layout. Most failures are visible in the first few pages, so `preview` is the main guard: it extracts a small sample, reports the signals below, and renders candidate profiles before a full build.

## Risks and current handling

| Risk | Signal | Current handling | Recommended action |
|---|---|---|---|
| Printed TOC merged into body text | `tocPages > 0`; `....`/`……` + page numbers | TOC pages are detected and skipped; the reader rebuilds its own TOC from headings | Check `preview.json`; if headings are missing, review `doc.json` |
| Scanned PDF without a text layer | `scannedLikePages > 0`, `textChars` low, `ocrNeeded: true` | `--ocr auto` runs OCRmyPDF/Tesseract, adds a text layer, then re-extracts | Install OCR deps; choose `chi_sim`/`chi_tra`; use MinerU for complex scans |
| Text-layer corruption | `radicals`, `replacementChars`, stray `⽤`/`���` | NFKC normalization, replacement-character warnings, `--fix` | Inspect the sample; add targeted `--fix`, or OCR/replace source |
| Multi-column reading order | `two-column` warning; text jumps between columns | Projection-based column detection and sorting | Check the sample; use MinerU/Docling for complex papers |
| Repeated headers/footers/page numbers | Repeated top/bottom text | Removed on pages with enough repetition; warning counted | Review `warnings`; adjust only if real content was removed |
| Tables crossing pages / complex tables | Table HTML looks broken or truncated | Tables are kept as HTML where possible; not reconstructed across pages | Use MinerU or manual editing for critical tables |
| Code block detection | Code appears as paragraphs or vice versa | Monospace font and layout heuristics | Check a code-heavy sample; add `--fix` only for text errors |
| Wide screenshots / terminal captures | `figure` aspect ratio ≥ 1.45 or ≥ 4 | Rotate, horizontal strip, or fit; PDF print scales to fit | Review figure mode in the sample |
| Page-break splits a paragraph/figure | Broken sentence or orphan caption | Adjacent-block merging and caption association | Inspect the sample around page boundaries |
| Cover, promo pages, QR codes, ads | Text like 扫码/公众号/训练营; QR images | Not deleted automatically; reported as blocks/assets | Use `--start-at/--end-at`, `--drop-text`, `--drop-asset` after preview |
| Footnotes, cross-references, indexes | Superscripts become inline text; page refs stale | Not reconstructed; content is retained as text | Manual review; MinerU for academic layouts |
| Formulas and math | Formula text degrades into symbols | Not reconstructed | Use MinerU/Pandoc source for math-heavy documents |
| Fonts, ligatures, soft hyphens | Broken words, missing glyphs | HTML entity escaping, soft-hyphen removal, font stacks | Check output rendering; embed/provide fonts if needed |
| Lists and numbering | Ordered lists restart or lose numbers | Pandoc/PDF heuristics; `start` attribute preserved where possible | Review list-heavy samples |
| Large documents / OCR cost | Hundreds of pages, many images, OCR runtime | `preview` limits pages/blocks; OCR caches by source hash | Approve sample and OCR language before full build |
| Wrong screen profile | Text too large/small, page ratio wrong | `preview` renders several profiles; `profile_helper.py` computes custom | Ask the user for device size/aspect, then choose one profile |
| EPUB reference/layout issues | `epub_report` errors | XML, manifest, and local XHTML reference checks | Fix before delivery; rebuild old EPUBs after upgrades |

## Preflight workflow

1. `inspect` the source for `pages`, `textChars`, `tocPages`, `scannedLikePages`, `ocrNeeded`, and text-layer warnings.
2. `preview` a few representative pages/blocks at 2–3 candidate profiles.
3. Show the user the HTML/PDF samples and `preview.json`.
4. Confirm: content/layout, profile, OCR language, removals, title.
5. Run the full `build` with the confirmed options.
6. `verify` the outputs; report warnings and removals.

## What preview deliberately does not guarantee

- Full-document reading order on every page.
- OCR accuracy or semantic layout from scans.
- Table/formula reconstruction.
- That the first sampled pages represent the whole document; for heterogeneous books, add `--pages` with pages from different chapters.
