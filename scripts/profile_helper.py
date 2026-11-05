#!/usr/bin/env python3
"""Suggest a doc2screen reading profile from a device's diagonal and aspect ratio.

Examples:
  python3 profile_helper.py --inches 6.39 --aspect 16:9.5
  python3 profile_helper.py --inches 6.3 --aspect 16:10 --css-width 390
  python3 profile_helper.py --inches 10.9 --aspect 4:3 --css-width 820
"""
from __future__ import annotations

import argparse
import json
import math


def parse_aspect(s: str) -> tuple[float, float]:
    s = s.lower().replace("×", ":").replace("x", ":").replace("/", ":")
    parts = [p for p in s.replace("：", ":").split(":") if p.strip()]
    if len(parts) != 2:
        raise SystemExit("aspect must look like 16:9.5 or 4:3")
    a, b = float(parts[0]), float(parts[1])
    if a <= 0 or b <= 0:
        raise SystemExit("aspect values must be positive")
    return a, b


def main() -> int:
    ap = argparse.ArgumentParser(description="Suggest a doc2screen screen profile")
    ap.add_argument("--inches", type=float, required=True, help="screen diagonal in inches")
    ap.add_argument("--aspect", required=True, help="device screen aspect, e.g. 16:9.5 or 4:3")
    ap.add_argument("--page-ratio", type=float, default=0,
                    help="content page width/height, e.g. 0.706 for A5-like; default: device portrait ratio")
    ap.add_argument("--css-width", type=int, default=0, help="override CSS width (px)")
    ap.add_argument("--font", type=float, default=0, help="override base font (px)")
    ap.add_argument("--margin", type=int, default=0, help="override page margin (px)")
    ap.add_argument("--name", default="custom", help="profile id in the snippet")
    args = ap.parse_args()

    aw, ah = parse_aspect(args.aspect)
    short, long = sorted((aw, ah))          # portrait: short side is width
    diag_mm = args.inches * 25.4
    w_mm = diag_mm * short / math.hypot(short, long)
    h_mm = diag_mm * long / math.hypot(short, long)

    # A phone held at ~30 cm reads well around 4.5-5 CSS px per mm.
    # Tablets sit farther away; cap the auto width so text does not become huge.
    css_w = args.css_width or round(min(820, max(320, w_mm * 4.7)))
    page_ratio = args.page_ratio or (short / long)
    css_h = round(css_w / page_ratio, 1)
    margin = args.margin or round(min(36, max(14, css_w * 0.041)))
    target_chars = 21 if css_w <= 480 else 27 if css_w <= 700 else 32
    font = args.font or round((css_w - 2 * margin) / target_chars, 1)
    font = round(min(22, max(14, font)), 1)

    result = {
        "device": {
            "diagonal_inches": args.inches,
            "aspect": f"{aw:g}:{ah:g}",
            "physical_width_mm": round(w_mm, 1),
            "physical_height_mm": round(h_mm, 1),
            "physical_area_mm2": round(w_mm * h_mm),
        },
        "css": {
            "width": css_w,
            "height": css_h,
            "aspect_ratio_w_over_h": round(css_w / css_h, 4),
            "base_font_px": font,
            "margin_px": margin,
            "approx_chars_per_line": target_chars,
        },
        "pdf": {
            "width_pt": round(css_w * 0.75, 2),
            "height_pt": round(css_h * 0.75, 2),
            "width_mm": round(css_w * 0.75 * 25.4 / 72, 1),
            "height_mm": round(css_h * 0.75 * 25.4 / 72, 1),
        },
        "profile_snippet": {
            args.name: {
                "label": f"{args.inches:g}\" {args.aspect} · page {page_ratio:.3f}",
                "cssWidth": css_w,
                "cssHeight": css_h,
                "baseFont": font,
                "margin": margin,
                "lineHeight": 1.8,
            }
        },
        "notes": [
            "Device aspect controls physical width/height; page-ratio controls the reading page shape.",
            "HTML is fluid; cssWidth is a design target, cssHeight mainly controls the PDF page.",
            "EPUB reflows and has no fixed page ratio.",
            "The PDF page is CSS px * 0.75 pt; Chrome may add <1 pt rounding.",
            "Adjust baseFont up/down if the reading distance or eyesight differs.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
