# Screen profiles: from inches to a reading layout

doc2screen does **not** guess a layout from the diagonal alone. A device is described by a **profile**, and a profile is a design decision with four inputs:

1. **Physical screen size** — diagonal in inches + aspect ratio → width/height in mm.
2. **Reading page shape** — the width/height ratio of the page you want to read (device ratio, A5/0.706, 4:3, custom).
3. **CSS width** — how wide the text column is in CSS pixels; this drives font size and line length.
4. **Typography** — base font, margins, line height.

The same 6.39-inch screen can produce a full-screen 16:9.5 page **or** a shorter 0.706 page. Those are two different reading experiences, not two different screens.

## 1. Physical size from inches

Given diagonal `D` (inches) and aspect `a:b`, with `short = min(a,b)` and `long = max(a,b)`:

```
width_mm  = D * 25.4 * short / sqrt(short² + long²)
height_mm = D * 25.4 * long  / sqrt(short² + long²)
```

For 6.39″ 16:9.5:

```
width  ≈ 82.9 mm
height ≈ 139.6 mm
area   ≈ 11,564 mm²
```

This is the **screen**, not the page. A 6.39″ 19.5:9 phone is about 68 × 147 mm — 22% narrower; a 16:10 mini-tablet is about 85 × 137 mm. That is why 16:9.5 feels like a small tablet.

## 2. Page shape from page ratio

`page_ratio = page_width / page_height` in portrait.

| page ratio | Shape | Typical use |
|---:|---|---|
| 0.594 | 9.5:16 | full-screen phone, video, slides |
| 0.625 | 10:16 | 16:10 tablet |
| **0.706** | **A5 / 1:√2** | **text, PDF, notes (doc2screen default)** |
| 0.750 | 3:4 | comics, some tablets |
| 0.707 | A4/A5 paper | print |

The page height in CSS px:

```
css_height = css_width / page_ratio
```

For 390 CSS px width and 0.706: **552.4 px**. The PDF page is CSS px × 0.75:

```
pdf_width_pt  = 390 * 0.75 = 292.5 pt
pdf_height_pt = 552.4 * 0.75 = 414.3 pt
```

## 3. CSS width and font size

`css_width` is not the physical width in mm; it is a design target. For phones, 360–430 px is the usual range; for small tablets, 600–820 px.

A simple heuristic used by `profile_helper.py`:

- CSS width ≈ physical width in mm × 4.7, clamped to 320–820 px. For 82.9 mm → **389 px**.
- Margin ≈ 4.1% of width, clamped 14–36 px. For 390 → **16 px**.
- Target Chinese characters per line: 21 for ≤480 px, 27 for ≤700, 32 for larger.
- Base font ≈ (css_width − 2 × margin) / target_chars, clamped 14–22 px. For 390 → **17 px**.
- Line height 1.75–1.85.

These are starting points, not laws: reading distance, eyesight and font design matter. The user can override `--font` and `--margin`.

## 4. Device ratio vs page ratio

| Case | device | page | Result |
|---|---|---|---|
| Full-screen phone | 6.39″ 16:9.5 | 16:9.5 | page fills the screen; good for slides/video |
| **Text/PDF default** | **6.39″ 16:9.5** | **0.706** | **82.9 × 117.4 mm; leaves vertical margins; page-like** |
| A5 print | paper 148×210 mm | 0.7048 | actual A5 page |
| Tablet | 16:10 | 16:10 | full-screen tablet |

On a 6.39″ screen, a 390×552 page displayed fit-width is **82.9 × 117.4 mm**, not 82.9 × 139.6 mm. The extra 22 mm is deliberate: app toolbars, status bars and page margins no longer eat the last lines, and the page reads as a page rather than an endless strip.

## 5. Profiles in the CLI

`profiles/devices.json` holds named profiles:

```json
{
  "phone-notes": {
    "label": "Phone · 0.706 (Notes-like)",
    "cssWidth": 390,
    "cssHeight": 552,
    "baseFont": 17,
    "margin": 16,
    "lineHeight": 1.8
  }
}
```

Add a device by appending a profile, or use `--width/--height` for a one-off:

```bash
python3 scripts/doc2screen.py build input.pdf \
  --width 412 --height 583 --out out/
```

Use the helper to compute a suggestion:

```bash
python3 scripts/profile_helper.py \
  --inches 6.39 --aspect 16:9.5 \
  --page-ratio 0.706 --css-width 390 \
  --name phone-notes
```

It prints physical mm, CSS/PDF dimensions, suggested font/margin, and a JSON profile snippet.

## 6. What each output does with the profile

| Output | Effect |
|---|---|
| HTML | `max-width = cssWidth`, padding = margin, base font; layout is fluid, so the page height only matters for print |
| PDF | page size = cssWidth × cssHeight in CSS px (×0.75 pt); images capped by `cssHeight`; page numbers/bookmarks |
| EPUB | reflowable; profile only informs CSS width/font hints, no fixed page |

## 7. Choosing a default

- **Text-heavy PDFs/notes** → `phone-notes` (0.706). This is the doc2screen default.
- **Slides/video/visual** → `phone-16x9.5` (full screen).
- **Comics** → 4:3 or the source page ratio.
- **Print** → `a5` or `a4`.

The default was chosen from real reading on a 6.39″ 16:9.5 device: a 0.706 page fits the usable area better than a full-height 16:9.5 page, even though the screen itself is 16:9.5.

## 8. Common mistakes

- **Using inches alone.** 6.39″ tells you the diagonal; it does not tell you the text column width or page shape.
- **Using the device ratio as the page ratio.** A full-height page can be too tall once app chrome is subtracted.
- **Confusing CSS px with physical px.** CSS px are a layout unit; the PDF converts them at 0.75 pt/px.
- **Ignoring DPR.** DPR affects sharpness, not layout; images should stay high-resolution, but CSS sizes stay in CSS px.
- **Assuming EPUB has a page ratio.** EPUB reflows; only HTML print/PDF have page geometry.
