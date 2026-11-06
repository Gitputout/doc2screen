"""Optional OCR for scanned PDFs, backed by OCRmyPDF + Tesseract."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from common import sha256_file

DEFAULT_OCR_LANG = "chi_sim+eng"


def ocr_tools() -> tuple[str | None, str | None]:
    return shutil.which("ocrmypdf"), shutil.which("tesseract")


def tesseract_langs() -> list[str]:
    tess = shutil.which("tesseract")
    if not tess:
        return []
    try:
        proc = subprocess.run([tess, "--list-langs"], capture_output=True,
                              text=True, timeout=30)
    except Exception:
        return []
    lines = [x.strip() for x in (proc.stdout or "").splitlines() if x.strip()]
    return [x for x in lines if re.fullmatch(r"[A-Za-z0-9_+-]+", x)]


def ocr_status(lang: str = DEFAULT_OCR_LANG) -> dict:
    ocr, tess = ocr_tools()
    langs = tesseract_langs()
    wanted = [x for x in re.split(r"[+,]", lang) if x]
    missing = [x for x in wanted if x not in langs] if langs else wanted
    shown = [x for x in ("chi_sim", "chi_tra", "eng", "osd") if x in langs]
    return {
        "ocrmypdf": ocr,
        "tesseract": tess,
        "languages": shown,
        "languageCount": len(langs),
        "missingLanguages": missing,
        "ok": bool(ocr and tess and not missing),
    }


def needs_ocr(info: dict) -> bool:
    """Whether a PDF reported by inspect_pdf should go through OCR."""
    pages = int(info.get("pages") or 0)
    if pages <= 0:
        return False
    # inspect_pdf detects scans one page at a time. Text on other pages must
    # not suppress OCR for an image-only page in a mixed PDF.
    return int(info.get("scannedLikePages") or 0) > 0


def _page_arg(pages) -> str | None:
    if not pages:
        return None
    nums = sorted({int(p) + 1 for p in pages})
    return ",".join(str(n) for n in nums)


def ocr_command(src: Path, out: Path, lang: str = DEFAULT_OCR_LANG,
                dpi: int = 300, pages=None) -> list[str]:
    cmd = [
        shutil.which("ocrmypdf") or "ocrmypdf",
        "--skip-text",
        "--deskew",
        "--rotate-pages",
        "--language", lang,
        "--output-type", "pdf",
        "--image-dpi", str(dpi),
        "--optimize", "0",
    ]
    page_arg = _page_arg(pages)
    if page_arg:
        cmd += ["--pages", page_arg]
    cmd += [str(src), str(out)]
    return cmd


def ocr_pdf(src: Path, out_dir: Path, lang: str = DEFAULT_OCR_LANG,
            dpi: int = 300, pages=None) -> Path:
    """Return a PDF with an OCR text layer, cached under out_dir."""
    status = ocr_status(lang)
    if not status["ok"]:
        missing = []
        if not status["ocrmypdf"]:
            missing.append("ocrmypdf")
        if not status["tesseract"]:
            missing.append("tesseract")
        if status["missingLanguages"]:
            missing.append("tesseract language data: " + ", ".join(status["missingLanguages"]))
        raise SystemExit(
            "OCR requested but dependencies are missing: " + ", ".join(missing) + "\n"
            "macOS: brew install ocrmypdf tesseract-lang\n"
            "Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-chi-sim ocrmypdf")
    out_dir.mkdir(parents=True, exist_ok=True)
    page_key = _page_arg(pages) or "all"
    key = sha256_file(src)[:12]
    safe_lang = re.sub(r"[^A-Za-z0-9_-]+", "-", lang) or "ocr"
    safe_pages = re.sub(r"[^0-9,-]+", "-", page_key) if pages else "all"
    out = out_dir / f"ocr-{key}-{safe_lang}-{safe_pages}.pdf"
    if out.exists() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(".tmp.pdf")
    if tmp.exists():
        tmp.unlink()
    cmd = ocr_command(src, tmp, lang=lang, dpi=dpi, pages=pages)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise SystemExit("OCR failed:\n" + (proc.stderr or proc.stdout or "")[-2000:])
    if not tmp.exists() or tmp.stat().st_size == 0:
        raise SystemExit("OCR failed: no output PDF was produced")
    os.replace(tmp, out)
    return out
