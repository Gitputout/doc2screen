#!/usr/bin/env python3
"""doc2screen CLI: inspect / extract / render / build / verify / doctor."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import (SKILL_DIR, dump_json, get_profile, load_json,
                    safe_filename, sha256_file, text_of_html)  # noqa: E402


def _fixes(values) -> list[tuple[str, str]]:
    out = []
    for v in values or []:
        if "=" in v:
            a, b = v.split("=", 1)
            if a:
                out.append((a, b))
    return out


FORMATS = ("pdf", "html", "epub")


def _formats(value) -> list[str]:
    """Parse and validate --formats; default to PDF."""
    formats = [x.strip().lower() for x in (value or "pdf").split(",") if x.strip()]
    unknown = sorted(set(formats) - set(FORMATS))
    if unknown:
        raise SystemExit(
            f"Unknown format(s): {', '.join(unknown)}. Available: {', '.join(FORMATS)}")
    if not formats:
        raise SystemExit(f"No formats specified. Available: {', '.join(FORMATS)}")
    return list(dict.fromkeys(formats))


def _input_path(value: str, label: str = "Input") -> Path:
    p = Path(value).resolve()
    if not p.exists():
        raise SystemExit(f"{label} does not exist: {p}")
    if not p.is_file():
        raise SystemExit(f"{label} is not a file: {p}")
    return p


def _apply_fixes(doc: dict, fixes: list[tuple[str, str]]) -> int:
    if not fixes:
        return 0
    n = 0

    def sub(s: str) -> str:
        nonlocal n
        for a, b in fixes:
            if a in s:
                n += s.count(a)
                s = s.replace(a, b)
        return s

    for blk in doc.get("blocks", []):
        for k in ("text", "html", "caption", "alt"):
            if isinstance(blk.get(k), str):
                blk[k] = sub(blk[k])
        if isinstance(blk.get("items"), list):
            blk["items"] = [sub(x) for x in blk["items"]]
    return n


def trim_doc(doc: dict, start_at: str | None = None, end_at: str | None = None,
             drop_text: list[str] | None = None,
             drop_assets: list[str] | None = None) -> dict:
    """Trim/curate blocks. Returns a report dict; mutates doc."""
    blocks = doc.get("blocks", [])
    removed = []
    def find_idx(needle, kinds):
        for kind in kinds:
            for i, b in enumerate(blocks):
                if b.get("type") != kind:
                    continue
                if needle in (b.get("text") or "") or needle in (b.get("caption") or ""):
                    return i
        return None
    if start_at:
        idx = find_idx(start_at, ("heading", "paragraph"))
        if idx is None:
            raise SystemExit(f"--start-at not found: {start_at}")
        removed.extend({"id": b["id"], "reason": "before-start"} for b in blocks[:idx])
        blocks = blocks[idx:]
    if end_at:
        idx = find_idx(end_at, ("heading", "paragraph"))
        if idx is None:
            raise SystemExit(f"--end-at not found after start: {end_at}")
        removed.extend({"id": x["id"], "reason": "after-end"} for x in blocks[idx:])
        blocks = blocks[:idx]
    if drop_text:
        keep = []
        for b in blocks:
            hay = " ".join(str(b.get(k, "")) for k in ("text", "caption", "alt"))
            if b.get("type") == "list":
                hay += " " + " ".join(str(x) for x in b.get("items", []))
            if b.get("html") and not b.get("text"):
                hay += " " + text_of_html(str(b["html"]))
            if any(t and t in hay for t in drop_text):
                removed.append({"id": b["id"], "reason": "drop-text",
                                "preview": re.sub(r"\s+", " ", hay).strip()[:80]})
            else:
                keep.append(b)
        blocks = keep
    if drop_assets:
        keep = []
        for b in blocks:
            if b.get("type") == "figure" and b.get("asset") in set(drop_assets):
                removed.append({"id": b["id"], "reason": "drop-asset", "preview": b.get("asset", "")})
            else:
                keep.append(b)
        blocks = keep
    doc["blocks"] = blocks
    doc["stats"] = {"pages": doc.get("stats", {}).get("pages", 0), "blocks": len(blocks),
                    "figures": sum(1 for b in blocks if b.get("type") == "figure"),
                    "codeBlocks": sum(1 for b in blocks if b.get("type") == "code")}
    return {"removed": removed, "kept": len(blocks)}


def extract(src: Path, out_dir: Path, fixes: list[tuple[str, str]],
            ocr: str = "auto", ocr_lang: str = "chi_sim+eng",
            page_indices=None) -> dict:
    suffix = src.suffix.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    used_ocr = False
    ocr_path = None
    original_src = src
    if suffix == ".pdf":
        from extract_pdf import extract_pdf, inspect_pdf
        skip_background_pages: set[int] = set()
        if ocr != "off":
            from ocr_pdf import needs_ocr, ocr_pdf
            info = inspect_pdf(str(src))
            if ocr == "force" or (ocr == "auto" and needs_ocr(info)):
                ocr_path = ocr_pdf(src, out_dir, lang=ocr_lang, pages=page_indices)
                # Keep an image-only page when OCR found no text. Suppress a
                # scan background only where OCR actually added readable text.
                import pymupdf
                with pymupdf.open(str(src)) as original, \
                     pymupdf.open(str(ocr_path)) as processed:
                    selected = (page_indices if page_indices is not None
                                else range(original.page_count))
                    for i in selected:
                        before = original[i].get_text().strip()
                        after = processed[i].get_text().strip()
                        if (len(before) < 20 and original[i].get_images(full=True)
                                and len(after) > len(before)):
                            skip_background_pages.add(i)
                src = ocr_path
                used_ocr = True
        doc = extract_pdf(str(src), str(out_dir), page_indices=page_indices,
                          skip_full_page_images=skip_background_pages)
        if used_ocr:
            doc["meta"]["source"] = str(original_src)
            doc["meta"]["sourceHash"] = "sha256:" + sha256_file(original_src)
            doc["meta"]["ocr"] = {
                "engine": "ocrmypdf+tesseract",
                "language": ocr_lang,
                "file": str(ocr_path),
                "pages": ([i + 1 for i in sorted(page_indices)]
                          if page_indices is not None else "all"),
            }
            doc.setdefault("warnings", []).append({
                "code": "ocr",
                "message": "已通过 OCRmyPDF/Tesseract 生成文本层；标题层级和图表仍需复核",
            })
    elif suffix == ".txt":
        from extract_pandoc import extract_txt
        doc = extract_txt(str(src), str(out_dir))
    elif suffix in {".docx", ".odt", ".epub", ".html", ".htm", ".md", ".markdown", ".rst", ".tex"}:
        from extract_pandoc import extract_via_pandoc
        doc = extract_via_pandoc(str(src), str(out_dir))
    else:
        raise SystemExit(f"Unsupported input: {suffix}")
    n = _apply_fixes(doc, fixes)
    if n:
        doc.setdefault("warnings", []).append(
            {"code": "manual-fixes", "message": "应用了用户指定的文本修正", "count": n})
    dump_json(doc, out_dir / "doc.json")
    return doc


def cmd_inspect(args) -> int:
    src = _input_path(args.input)
    out = Path(args.out or "work")
    out.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".pdf":
        from extract_pdf import inspect_pdf
        info = inspect_pdf(str(src))
    else:
        info = {"kind": src.suffix.lower().lstrip("."), "size": src.stat().st_size,
                "pandoc": shutil.which("pandoc"), "tocPages": 0,
                "scannedLikePages": 0, "ocrNeeded": False}
    info["file"] = str(src)
    dump_json(info, out / "inspect.json")
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


def cmd_extract(args) -> int:
    src = _input_path(args.input)
    out = Path(args.out or "work")
    doc = extract(src, out, _fixes(args.fix),
                  ocr=args.ocr, ocr_lang=args.ocr_lang)
    stats = doc.get("stats", {})
    print(json.dumps({"doc": str(out / "doc.json"), **stats,
                      "warnings": len(doc.get("warnings", []))}, ensure_ascii=False))
    return 0


def _profile_from(args, doc=None):
    if args.width and args.height:
        return get_profile(width=args.width, height=args.height)
    name = args.profile or (doc or {}).get("profile", {}).get("id") or "phone-notes"
    return get_profile(name)


def _profile_for_verify(args, target: Path):
    """Resolve the profile from CLI flags, then build.json, then the default."""
    if args.width and args.height:
        return get_profile(width=args.width, height=args.height)
    if args.profile:
        return get_profile(args.profile)
    build_json = (target if target.is_dir() else target.parent) / "build.json"
    if build_json.exists():
        try:
            profile_id = load_json(build_json).get("profile")
        except Exception:
            profile_id = None
        if profile_id:
            try:
                return get_profile(profile_id)
            except SystemExit:
                m = re.fullmatch(r"custom-(\d+)x(\d+)", profile_id)
                if m:
                    return get_profile(width=int(m.group(1)), height=int(m.group(2)))
    return get_profile()


def _parse_page_indices(value: str, page_count: int) -> list[int]:
    """Parse a 1-based page list like 1,3-5 into 0-based indices."""
    out = set()
    for part in re.split(r"[,\s]+", value.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise SystemExit(f"Invalid page range: {part}")
        start = int(m.group(1))
        end = int(m.group(2) or start)
        if start < 1 or end < start:
            raise SystemExit(f"Invalid page range: {part}")
        for page in range(start, min(end, page_count) + 1):
            out.add(page - 1)
    if not out:
        raise SystemExit("No pages selected")
    return sorted(out)


def _auto_preview_pages(src: Path, limit: int = 3) -> list[int]:
    """Pick a few representative PDF pages for a preflight preview."""
    import pymupdf
    from extract_pdf import detect_toc_pages

    d = pymupdf.open(str(src))
    try:
        toc = set(detect_toc_pages(d))
        pages = [i for i in range(d.page_count) if i not in toc]
        if not pages:
            pages = list(range(d.page_count))
        text_pages = [i for i in pages if len(d[i].get_text().strip()) >= 80]
        first = text_pages[0] if text_pages else pages[0]
        chosen = [first]
        image_page = next((i for i in pages
                           if i not in chosen and d[i].get_images(full=True)), None)
        if image_page is not None:
            chosen.append(image_page)
        middle = pages[len(pages) // 2]
        if middle not in chosen:
            chosen.append(middle)
        for i in pages:
            if len(chosen) >= max(1, limit):
                break
            if i not in chosen:
                chosen.append(i)
        return sorted(chosen[:max(1, limit)])
    finally:
        d.close()


def _sample_doc(doc: dict, max_blocks: int = 12, max_chars: int = 4000) -> dict:
    """Return a small DocModel slice for non-PDF previews."""
    blocks = doc.get("blocks", [])
    if not blocks:
        return doc
    start = next((i for i, b in enumerate(blocks) if b.get("type") == "heading"), 0)
    selected = []
    used = 0
    for b in blocks[start:]:
        text = str(b.get("text") or b.get("caption") or "")
        size = len(text) or len(b.get("items", [])) * 20 or 80
        if selected and (len(selected) >= max_blocks or used + size > max_chars):
            break
        selected.append(b)
        used += size
    for kind in ("figure", "code", "table"):
        if not any(b.get("type") == kind for b in selected):
            candidate = next((b for b in blocks if b.get("type") == kind), None)
            if candidate is not None:
                selected.append(candidate)
    order = {id(b): i for i, b in enumerate(blocks)}
    selected.sort(key=lambda b: order.get(id(b), 0))
    sample = json.loads(json.dumps(doc))
    sample["blocks"] = selected
    sample["stats"] = {
        **doc.get("stats", {}),
        "blocks": len(selected),
        "figures": sum(1 for b in selected if b.get("type") == "figure"),
        "codeBlocks": sum(1 for b in selected if b.get("type") == "code"),
    }
    sample["preview"] = {
        "sourceBlocks": len(blocks),
        "blocks": [b.get("id") for b in selected],
        "truncated": len(selected) < len(blocks),
    }
    return sample


def cmd_render(args) -> int:
    from render import render
    doc_path = _input_path(args.doc, "Document")
    doc = load_json(doc_path)
    profile = _profile_from(args, doc)
    out = Path(args.out or (doc_path.parent / "book.html")).resolve()
    render(doc, str(out), profile=profile, embed=not args.no_embed,
           model_dir=str(doc_path.parent))
    print(str(out))
    return 0


def _node_env() -> tuple[str | None, str | None]:
    node = shutil.which("node")
    pp = SKILL_DIR / "tools" / "node_modules" / "puppeteer-core"
    return node, (str(pp) if pp.exists() else None)


def export_pdf(html: Path, pdf: Path, profile: dict, title: str) -> dict:
    node, pp = _node_env()
    if not node or not pp:
        raise SystemExit("PDF export needs Node.js + puppeteer-core. Run: cd tools && npm install")
    script = HERE / "export_pdf.js"
    proc = subprocess.run([node, str(script), str(html), str(pdf),
                           str(profile["cssWidth"]), str(profile["cssHeight"]), title],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise SystemExit("PDF export failed:\n" + (proc.stderr or proc.stdout)[-2000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


def add_pdf_outline(pdf: Path, doc: dict) -> int:
    """Add bookmarks from level 1/2 headings (PyMuPDF, optional)."""
    import pymupdf
    heads = [b for b in doc.get("blocks", []) if b["type"] == "heading"
             and int(b.get("level", 3)) <= 2 and b.get("text")]
    if len(heads) < 2:
        return 0
    d = pymupdf.open(str(pdf))
    toc = [[1, "封面", 1]]
    last = 0
    for b in heads:
        text = b["text"].strip()
        found = None
        for n in (24, 18, 12, 10, 8, 6):
            needle = text[:n]
            if len(needle) < 2:
                continue
            for p in range(last, d.page_count):
                if d[p].search_for(needle):
                    found = p
                    break
            if found is not None:
                break
        if found is None:
            continue
        toc.append([2 if b.get("level", 2) >= 2 else 1, b["text"][:100], found + 1])
        last = found
    if len(toc) >= 2:
        d.set_toc(toc)
        d.set_metadata({"title": doc.get("meta", {}).get("title", ""),
                        "author": doc.get("meta", {}).get("author", ""),
                        "creator": "doc2screen"})
        tmp = str(pdf) + ".tmp"
        d.save(tmp, garbage=3, deflate=True)
        d.close()
        os.replace(tmp, pdf)
        return len(toc)
    d.close()
    return 0


def pdf_report(pdf: Path, profile: dict) -> dict:
    import pymupdf
    d = pymupdf.open(str(pdf))
    blank = 0
    imgs = 0
    aspect_bad = []
    for i, page in enumerate(d):
        txt = page.get_text().strip()
        infos = page.get_images(full=True)
        imgs += len(infos)
        if not txt and not infos:
            blank += 1
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") == 1 and b.get("width") and b.get("height"):
                bw = b["bbox"][2] - b["bbox"][0]
                bh = b["bbox"][3] - b["bbox"][1]
                if bw > 0 and bh > 0:
                    ratio = (b["width"] / b["height"]) / (bw / bh)
                    if ratio < 0.97 or ratio > 1.03:
                        aspect_bad.append({"page": i + 1, "ratio": round(ratio, 3)})
    w_pt, h_pt = d[0].rect.width, d[0].rect.height
    expected = (profile["cssWidth"] * 0.75, profile["cssHeight"] * 0.75)
    return {"pages": d.page_count, "pageSize": [round(w_pt, 2), round(h_pt, 2)],
            "expectedSize": [round(expected[0], 2), round(expected[1], 2)],
            "blankPages": blank, "images": imgs, "aspectMismatch": aspect_bad[:20],
            "outline": len(d.get_toc())}


def pdf_ok(report: dict) -> bool:
    return (report.get("pages", 0) > 0
            and report.get("blankPages") == 0
            and not report.get("aspectMismatch")
            and all(abs(actual - expected) <= 1 for actual, expected in
                    zip(report.get("pageSize", []), report.get("expectedSize", [])))
            and len(report.get("pageSize", [])) == len(report.get("expectedSize", [])) == 2)


def verify_html(html: Path, profile: dict, out_json: Path) -> dict:
    node, pp = _node_env()
    if not node or not pp:
        return {"ok": False, "error": "node/puppeteer-core not installed"}
    script = HERE / "verify_html.js"
    proc = subprocess.run([node, str(script), str(html), str(profile["cssWidth"]),
                           str(profile["cssHeight"]), str(out_json)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout)[-2000:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "could not parse verify output"}


def cmd_build(args) -> int:
    from render import render
    from export_epub import export_epub, epub_report
    src = _input_path(args.input)
    formats = _formats(args.formats)
    out = Path(args.out or "out").resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / ".work"
    doc = extract(src, work, _fixes(args.fix),
                  ocr=args.ocr, ocr_lang=args.ocr_lang)
    trim_report = trim_doc(doc, getattr(args, "start_at", None), getattr(args, "end_at", None),
                           getattr(args, "drop_text", None), getattr(args, "drop_asset", None))
    if getattr(args, "title", None):
        doc["meta"]["title"] = args.title
    profile = _profile_from(args, doc)
    doc["profile"] = profile
    dump_json(doc, work / "doc.json")
    name = args.name or safe_filename(doc.get("meta", {}).get("title", src.stem))
    result = {"input": str(src), "profile": profile.get("id"),
              "trim": {"kept": trim_report.get("kept"),
                       "removed": len(trim_report.get("removed", [])),
                       "removedBlocks": trim_report.get("removed", [])},
              "warnings": doc.get("warnings", []),
              "outputs": {}}

    need_html = "html" in formats or "pdf" in formats
    html_path = (out / f"{name}.html") if "html" in formats else (work / "render.html")
    if need_html:
        render(doc, str(html_path), profile=profile, embed=not args.no_embed,
               model_dir=str(work))
        if "html" in formats:
            result["outputs"]["html"] = str(html_path)

    if "pdf" in formats:
        pdf_path = out / f"{name}.pdf"
        export_pdf(html_path, pdf_path, profile, doc.get("meta", {}).get("title", name))
        if not args.no_bookmarks:
            result["bookmarks"] = add_pdf_outline(pdf_path, doc)
        result["outputs"]["pdf"] = str(pdf_path)
    if "epub" in formats:
        epub_path = out / f"{name}.epub"
        export_epub(doc, str(epub_path), str(work))
        result["outputs"]["epub"] = str(epub_path)
        result["verify_epub"] = epub_report(str(epub_path))

    if not args.no_verify and need_html and html_path.exists():
        vh = verify_html(html_path, profile, work / "verify-html.json")
        result["verify_html"] = {"ok": vh.get("ok"), "error": vh.get("error")}
        if "pdf" in formats:
            result["verify_pdf"] = pdf_report(pdf_path, profile)
    dump_json(result, out / "build.json")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    ok = result.get("verify_html", {}).get("ok", True)
    if "pdf" in formats:
        ok = ok and (args.no_verify or pdf_ok(result.get("verify_pdf", {})))
    if "epub" in formats:
        ok = ok and result.get("verify_epub", {}).get("ok", True)
    return 0 if ok else 1


def cmd_preview(args) -> int:
    from render import render
    src = _input_path(args.input)
    out = Path(args.out or "preview").resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / ".work"
    suffix = src.suffix.lower()

    fmt = [x.strip().lower() for x in (args.formats or "html,pdf").split(",")
           if x.strip()]
    unknown = sorted(set(fmt) - {"html", "pdf"})
    if unknown:
        raise SystemExit(f"Unknown preview format(s): {', '.join(unknown)}. Available: html, pdf")
    if not fmt:
        raise SystemExit("No preview formats specified")
    if (args.width is None) != (args.height is None):
        raise SystemExit("--width and --height must be used together")

    if args.profile or (args.width and args.height):
        profiles = [_profile_from(args, {})]
    else:
        names = [x.strip() for x in (args.profiles or "phone-notes,phone-16x9.5").split(",")
                 if x.strip()]
        if not names:
            names = ["phone-notes"]
        profiles = []
        seen = set()
        for name in names:
            profile = get_profile(name)
            pid = profile.get("id")
            if pid not in seen:
                seen.add(pid)
                profiles.append(profile)
    if not profiles:
        raise SystemExit("No profiles selected")

    info = {"kind": suffix.lstrip("."), "size": src.stat().st_size}
    page_indices = None
    ocr_mode = args.ocr
    extra_warnings = []
    if suffix == ".pdf":
        from extract_pdf import inspect_pdf
        info = inspect_pdf(str(src))
        page_count = int(info.get("pages") or 0)
        if page_count <= 0:
            raise SystemExit("PDF has no pages")
        if args.pages:
            page_indices = _parse_page_indices(args.pages, page_count)
        else:
            page_indices = _auto_preview_pages(src, max(1, args.limit_pages))
        if ocr_mode == "auto" and info.get("ocrNeeded"):
            from ocr_pdf import ocr_status
            if not ocr_status(args.ocr_lang)["ok"]:
                ocr_mode = "off"
                extra_warnings.append({
                    "code": "ocr-missing",
                    "message": "检测到扫描页，但 OCR 依赖未安装；预览显示页面图片。"
                               "完整构建前请安装 OCR，或显式使用 --ocr off。",
                })
    elif args.pages:
        raise SystemExit("--pages is only supported for PDF input")

    doc = extract(src, work, [], ocr=ocr_mode, ocr_lang=args.ocr_lang,
                  page_indices=page_indices)
    if suffix != ".pdf":
        info.setdefault("pages", 0)
        info.setdefault("textChars", sum(
            len(str(b.get("text") or "")) for b in doc.get("blocks", [])))
        info.setdefault("tocPages", 0)
        info.setdefault("scannedLikePages", 0)
        info.setdefault("ocrNeeded", False)
    if args.title:
        doc["meta"]["title"] = args.title
    if suffix != ".pdf":
        doc = _sample_doc(doc, max_blocks=args.limit_blocks,
                          max_chars=args.max_chars)

    title = doc.get("meta", {}).get("title") or src.stem
    outputs = {}
    for profile in profiles:
        pid = safe_filename(profile.get("id") or "preview")
        html_path = out / f"preview-{pid}.html"
        render(doc, str(html_path), profile=profile, embed=not args.no_embed,
               model_dir=str(work))
        entry = {"profile": profile.get("label") or profile.get("id"),
                 "html": str(html_path)}
        if "pdf" in fmt:
            pdf_path = out / f"preview-{pid}.pdf"
            try:
                export_pdf(html_path, pdf_path, profile, title)
                entry["pdf"] = str(pdf_path)
            except SystemExit as exc:
                entry["pdfError"] = str(exc)
        outputs[profile.get("id") or pid] = entry

    warnings = list(doc.get("warnings", [])) + extra_warnings
    sample_blocks = doc.get("preview", {}).get("blocks")
    if sample_blocks is None:
        sample_blocks = [b.get("id") for b in doc.get("blocks", [])]
    questions = [
        "Is the preview content and layout acceptable?",
        "Which profile should be used? If unsure, provide the device diagonal and aspect ratio.",
        "Should any blocks be dropped, or the title changed?",
    ]
    if info.get("ocrNeeded"):
        questions.append("Should OCR continue, and in which language (chi_sim/chi_tra/eng)?")
    report = {
        "input": str(src),
        "kind": info.get("kind"),
        "sourcePages": info.get("pages"),
        "textChars": info.get("textChars"),
        "scannedLikePages": info.get("scannedLikePages"),
        "tocPages": info.get("tocPages"),
        "tocPageNumbers": info.get("tocPageNumbers"),
        "ocrNeeded": info.get("ocrNeeded"),
        "ocrMode": ocr_mode,
        "samplePages": [n + 1 for n in page_indices] if page_indices else None,
        "sampleBlockCount": len(sample_blocks or []),
        "sampleBlocks": (sample_blocks or [])[:40],
        "stats": doc.get("stats"),
        "warnings": warnings,
        "profiles": [p.get("id") for p in profiles],
        "outputs": outputs,
        "questions": questions,
        "next": "Review the preview and ask the user to confirm content, removals, "
                "profile, and OCR before running build.",
    }
    dump_json(report, out / "preview.json")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if any(entry.get("html") for entry in outputs.values()) else 1


def cmd_verify(args) -> int:
    from export_epub import epub_report
    target = Path(args.target).resolve()
    if not target.exists():
        raise SystemExit(f"Verification target does not exist: {target}")
    out = Path(args.out or (target.parent if target.is_file() else target))
    out.mkdir(parents=True, exist_ok=True)
    result = {"ok": True, "checks": {}}
    html = target if target.suffix.lower() in (".html", ".htm") else None
    pdf = target if target.suffix.lower() == ".pdf" else None
    epub = target if target.suffix.lower() == ".epub" else None
    if html is None and target.is_dir():
        hs = sorted(target.glob("*.html"))
        ps = sorted(target.glob("*.pdf"))
        es = sorted(target.glob("*.epub"))
        html = hs[0] if hs else None
        pdf = ps[0] if ps else None
        epub = es[0] if es else None
    profile = _profile_for_verify(args, target)
    if html:
        vh = verify_html(html, profile, out / "verify-html.json")
        result["checks"]["html"] = vh
        result["ok"] = result["ok"] and bool(vh.get("ok"))
    if pdf:
        result["checks"]["pdf"] = pdf_report(pdf, profile)
        result["ok"] = result["ok"] and pdf_ok(result["checks"]["pdf"])
    if epub:
        result["checks"]["epub"] = epub_report(str(epub))
        result["ok"] = result["ok"] and result["checks"]["epub"]["ok"]
    if not result["checks"]:
        raise SystemExit(f"No supported output found to verify: {target}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["ok"] else 1


def cmd_doctor(args) -> int:
    from importlib import metadata, util
    from ocr_pdf import ocr_status
    node, pp = _node_env()
    chrome = None
    for p in [os.environ.get("CHROME_PATH"),
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/usr/bin/google-chrome", "/usr/bin/chromium"]:
        if p and Path(p).exists():
            chrome = p
            break
    info = {
        "python": sys.version.split()[0],
        "pymupdf": metadata.version("PyMuPDF") if util.find_spec("pymupdf") else "missing",
        "lxml": metadata.version("lxml") if util.find_spec("lxml") else "missing",
        "pandoc": shutil.which("pandoc"),
        "node": node,
        "puppeteer-core": pp or "missing (cd tools && npm install)",
        "chrome": chrome or "missing (set CHROME_PATH)",
        "ocr": ocr_status(),
        "skill": str(SKILL_DIR),
    }
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


def cmd_profiles(args) -> int:
    from common import load_profiles
    print(json.dumps(load_profiles(), ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="doc2screen")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--profile", default=None)
        p.add_argument("--width", type=int)
        p.add_argument("--height", type=int)

    def ocr_options(p):
        p.add_argument("--ocr", choices=("auto", "off", "force"), default="auto",
                       help="OCR scanned PDFs (default: auto)")
        p.add_argument("--ocr-lang", default="chi_sim+eng",
                       help="Tesseract language(s), e.g. chi_sim+eng or chi_tra+eng")

    p = sub.add_parser("inspect")
    p.add_argument("input")
    p.add_argument("--out", default="work")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("extract")
    p.add_argument("input")
    p.add_argument("--out", default="work")
    p.add_argument("--fix", action="append", help="old=new replacement, repeatable")
    ocr_options(p)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("render")
    p.add_argument("doc")
    p.add_argument("--out", default=None)
    p.add_argument("--no-embed", action="store_true")
    common(p)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("build")
    p.add_argument("input")
    p.add_argument("--out", default="out")
    p.add_argument("--formats", default="pdf", help="comma list: pdf (default), html, epub")
    p.add_argument("--name", default=None)
    p.add_argument("--fix", action="append")
    p.add_argument("--no-embed", action="store_true")
    p.add_argument("--no-bookmarks", action="store_true")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--start-at", default=None, help="drop blocks before this heading/text")
    p.add_argument("--end-at", default=None, help="drop blocks from this heading/text")
    p.add_argument("--drop-text", action="append", help="drop blocks containing this text, repeatable")
    p.add_argument("--drop-asset", action="append", help="drop figure by asset id, repeatable")
    p.add_argument("--title", default=None, help="override document title")
    ocr_options(p)
    common(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("preview")
    p.add_argument("input")
    p.add_argument("--out", default="preview")
    p.add_argument("--profiles", default="phone-notes,phone-16x9.5",
                   help="comma list of profiles to preview")
    p.add_argument("--pages", default=None, help="PDF sample pages, e.g. 2-4 or 1,3,5")
    p.add_argument("--formats", default="html,pdf", help="html,pdf")
    p.add_argument("--limit-pages", type=int, default=3,
                   help="auto-select this many PDF pages")
    p.add_argument("--limit-blocks", type=int, default=12,
                   help="sample this many blocks for non-PDF input")
    p.add_argument("--max-chars", type=int, default=4000,
                   help="sample character budget for non-PDF input")
    p.add_argument("--title", default=None)
    p.add_argument("--no-embed", action="store_true")
    ocr_options(p)
    common(p)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("verify")
    p.add_argument("target")
    p.add_argument("--out", default=None)
    common(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("doctor")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("profiles")
    p.set_defaults(func=cmd_profiles)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
