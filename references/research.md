# Research notes and clean-room provenance

This file records the ideas studied while designing doc2screen. It is not a copy of any project's documentation or code.

## Landscape (as of 2026-11)

| Project | Stars | What it does | Gap for this use case |
|---|---:|---|---|
| MinerU | 83k | Chinese/complex layout, OCR, tables, formulas; Markdown/HTML/JSON | no reader, EPUB/PDF packaging, curation, screen profiles |
| Docling | 70k (MIT) | DoclingDocument, reading order, tables; HTML/Markdown export | same; GenAI-oriented |
| Marker | 41k (Apache-2.0) | layout + OCR + tables/equations; Markdown/JSON/HTML | same; GPU-heavy |
| PDF-Reflow | 2 | fixed-layout PDF → responsive HTML / reflowable PDF | PDF-only, very new, no EPUB/curation/profiles |
| k2pdfopt | — | small-screen PDF reflow | output is PDF, not semantic HTML |
| pdf2htmlEX | 10.6k archived / 5.6k fork | high-fidelity PDF→HTML | absolute layout; not reflowable |
| Pandoc / Calibre | 26k (Calibre) | single-source conversion / EPUB packaging | needs clean semantic input |

## Ideas borrowed (independently implemented)

1. **DoclingDocument-like model** — blocks with type, text/HTML, page/bbox provenance, assets, warnings. Our `DocModel` is a small JSON schema, not Docling code.
2. **MinerU-style fallback** — when text layers are empty/corrupt or layout is complex, call an external OCR/layout tool rather than guessing. Planned optional adapter.
3. **Marker-style output abstraction** — one extraction result feeds multiple outputs.
4. **PDF-Reflow reader design** — responsive single column, dark/light, self-contained HTML, PDF export. Our reader is original CSS/JS; no code copied.
5. **k2pdfopt column/crop thinking** — projection-profile gutters, reflow and image panel splitting. Implemented from scratch in `extract_pdf.py`/future image module.
6. **pdf2htmlEX lesson** — fidelity and reflow are different products; this project defaults to reflow.
7. **Pandoc** — use it as a subprocess for non-PDF input; do not vendor.
8. **Calibre/EPUB** — OPF/nav/spine packaging; implemented with stdlib zipfile.
9. **Readability/trafilatura-style boilerplate thinking** — repeated headers/footers and promo blocks are flagged, not blindly deleted.

## Clean-room rules used

- Read public docs/README/behavior; do not copy code, comments, naming, docs prose, screenshots, fixtures, or models.
- Write behavior specs in our own words; implement independently.
- Cite the idea source here; keep code original.
- Reuse only MIT/Apache code, with attribution, if ever needed.

## Why not use Docling/MinerU as the core

- Heavy model dependencies, slower startup, GPU recommended.
- Their output is generic Markdown/HTML; reading UX, packaging, curation, and device profiles still need building.
- License complexity (MinerU NOASSERTION, PyMuPDF AGPL) argues for a light core with optional adapters.

## Open questions

- pypdfium2 backend parity with PyMuPDF.
- Panel splitting for ultra-wide screenshots in EPUB/PDF.
- OCR adapter interface (MinerU vs Tesseract).
- Whether to ship a WeasyPrint PDF fallback.
- License finalization (Apache-2.0 target).
