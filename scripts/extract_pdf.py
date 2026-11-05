"""PDF extraction backend (PyMuPDF)."""
from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from pathlib import Path

import pymupdf

from common import (add_warning, block, clean_inline_html, esc, image_luma,
                    is_cjk, join_visual_lines, new_doc, norm_text,
                    sha256_file, sha256_bytes, text_of_html)

MONO_HINTS = ("mono", "courier", "menlo", "consolas", "code", "fixed", "typewriter")
PAGE_NUM_RE = re.compile(r"^\s*(?:[-—–]\s*)?(?:\d{1,4}|[ivxlcdmIVXLCDM]{1,8})(?:\s*[-—–])?\s*$")
BULLET_RE = re.compile(r"^\s*(?:[-•·▪◦●○–—*]|(?:\d{1,2}|[a-zA-Z])[.)、]|[（(]\d{1,2}[)）])\s+")
CAPTION_RE = re.compile(r"^\s*(?:图|圖|Figure|Fig\.?|表|Table)\s*[0-9一二三四五六七八九十百]+")


def _is_mono(font: str, flags: int) -> bool:
    low = (font or "").lower()
    return bool(flags & 8) or any(h in low for h in MONO_HINTS)


def _is_italic(flags: int) -> bool:
    return bool(flags & 2)


def _is_bold(flags: int) -> bool:
    return bool(flags & 16)


def _span_text(spans) -> str:
    return "".join(s.get("text", "") for s in spans)


def _span_html(spans) -> str:
    parts: list[list[str]] = []
    for s in spans:
        t = s.get("text", "")
        if not t:
            continue
        if not t.strip():
            if parts:
                parts[-1][1] += t
            continue
        kind = "code" if _is_mono(s.get("font", ""), int(s.get("flags", 0))) else (
            "bold" if _is_bold(int(s.get("flags", 0))) else
            "italic" if _is_italic(int(s.get("flags", 0))) else "text")
        if parts and parts[-1][0] == kind:
            parts[-1][1] += t
        else:
            parts.append([kind, t])
    out = []
    for kind, t in parts:
        t2 = t.strip() if kind == "code" else t
        if kind == "code":
            out.append("<code>" + esc(t2) + "</code>")
        elif kind == "bold":
            out.append("<strong>" + esc(t) + "</strong>")
        elif kind == "italic":
            out.append("<em>" + esc(t) + "</em>")
        else:
            out.append(esc(t))
    return "".join(out)


def _lines_html(lines) -> str:
    """Render PyMuPDF lines to inline HTML, joining wrapped lines sensibly."""
    htmls, raw_texts = [], []
    for line in lines:
        spans = line.get("spans", [])
        raw = _span_text(spans).strip()
        if not raw:
            continue
        htmls.append(_span_html(spans))
        raw_texts.append(raw)
    if not htmls:
        return ""
    out = htmls[0]
    for i in range(1, len(htmls)):
        prev, nxt = raw_texts[i - 1][-1], raw_texts[i][0]
        if is_cjk(prev) or is_cjk(nxt) or prev in "，。；：、！？）》”" or nxt in "，。；：、！？《（“":
            out += htmls[i]
        elif re.match(r"[A-Za-z0-9]", prev) and re.match(r"[A-Za-z0-9]", nxt):
            out += " " + htmls[i]
        else:
            out += htmls[i]
    return out


def _plain_lines(lines) -> str:
    return "\n".join(_span_text(l.get("spans", [])) for l in lines)


def _block_stats(b, body_size: float) -> dict:
    lines = b.get("lines", [])
    spans = [s for l in lines for s in l.get("spans", []) if s.get("text", "").strip()]
    text = join_visual_lines([_span_text(l.get("spans", [])) for l in lines])
    if not spans:
        return {}
    sizes = [float(s.get("size", 0)) for s in spans]
    chars = sum(len(s.get("text", "")) for s in spans) or 1
    mono = sum(len(s.get("text", "")) for s in spans
               if _is_mono(s.get("font", ""), int(s.get("flags", 0))))
    bold = sum(len(s.get("text", "")) for s in spans if _is_bold(int(s.get("flags", 0))))
    x0, y0, x1, y1 = b.get("bbox", (0, 0, 0, 0))
    return {
        "text": text,
        "max_size": max(sizes),
        "avg_size": sum(sizes) / len(sizes),
        "mono_ratio": mono / chars,
        "bold_ratio": bold / chars,
        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        "width": x1 - x0,
        "n_lines": len(lines),
        "lines": lines,
    }


def _page_raw_blocks(page, page_no: int, fixes) -> list[dict]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") == 1:
            out.append({"kind": "image", "bbox": tuple(b.get("bbox", (0, 0, 0, 0))),
                        "image": b.get("image"), "ext": b.get("ext", "png"),
                        "width": b.get("width", 0), "height": b.get("height", 0),
                        "page": page_no})
            continue
        lines = b.get("lines", [])
        spans = [s for l in lines for s in l.get("spans", []) if s.get("text", "")]
        if not spans:
            continue
        raw = _span_text(spans)
        txt, stats = norm_text(raw, fixes)
        # normalize span texts in place for later HTML building
        for l in lines:
            for s in l.get("spans", []):
                s["text"], _ = norm_text(s.get("text", ""), fixes)
        out.append({"kind": "text", "bbox": tuple(b.get("bbox", (0, 0, 0, 0))),
                    "lines": lines, "page": page_no, "raw": raw,
                    "norm_stats": stats})
    return out


def _body_metrics(pages_raw: list[list[dict]]) -> tuple[float, float, float]:
    sizes = Counter()
    x0s = []
    for page in pages_raw:
        for b in page:
            if b["kind"] != "text":
                continue
            for l in b["lines"]:
                for s in l.get("spans", []):
                    t = s.get("text", "").strip()
                    if t:
                        sizes[round(float(s.get("size", 0)) * 2) / 2] += len(t)
            x0s.append(b["bbox"][0])
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    x0s.sort()
    body_x0 = x0s[len(x0s) // 4] if x0s else 0.0
    return body, body_x0, (max(x0s) if x0s else 0.0)


def _header_footer_keys(pages_raw: list[list[dict]], page_heights: list[float]) -> set[str]:
    """Find texts repeated in top/bottom bands across pages."""
    if len(pages_raw) < 5:
        return set()
    counts = Counter()
    for pi, page in enumerate(pages_raw):
        h = page_heights[pi] or 1
        seen = set()
        for b in page:
            if b["kind"] != "text":
                continue
            y0, y1 = b["bbox"][1], b["bbox"][3]
            if not (y1 < h * 0.12 or y0 > h * 0.88):
                continue
            t = re.sub(r"\s+", "", join_visual_lines([_span_text(l.get("spans", [])) for l in b["lines"]]))
            t = re.sub(r"\d+", "#", t)
            if 2 <= len(t) <= 80 and t not in seen:
                seen.add(t)
                counts[t] += 1
    threshold = max(3, int(len(pages_raw) * 0.3))
    return {t for t, c in counts.items() if c >= threshold}


def _order_page_blocks(blocks: list[dict], page_w: float) -> tuple[list[dict], bool]:
    """Return blocks in reading order, and whether a 2-column layout was detected."""
    text_blocks = [b for b in blocks if b["kind"] == "text"]
    if len(text_blocks) < 4:
        return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0])), False
    mid = page_w / 2
    crossing = [b for b in text_blocks if b["bbox"][0] < mid < b["bbox"][2]]
    if len(crossing) / max(1, len(text_blocks)) > 0.15:
        return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0])), False
    left = [b for b in text_blocks if b["bbox"][2] <= mid * 1.02]
    right = [b for b in text_blocks if b["bbox"][0] >= mid * 0.98]
    left_ids = {id(b) for b in left}
    right_ids = {id(b) for b in right}
    others = [b for b in text_blocks if id(b) not in left_ids and id(b) not in right_ids]
    if len(left) >= 4 and len(right) >= 4 and not others:
        lmax = max(b["bbox"][2] for b in left)
        rmin = min(b["bbox"][0] for b in right)
        if rmin - lmax > page_w * 0.03:
            left.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
            right.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
            imgs = [b for b in blocks if b["kind"] == "image"]
            return left + right + sorted(imgs, key=lambda b: (b["bbox"][1], b["bbox"][0])), True
    return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0])), False


def _classify(st: dict, body: float, body_x0: float) -> str:
    txt = st["text"]
    if not txt.strip():
        return "skip"
    if st["mono_ratio"] >= 0.55 and st["max_size"] <= body * 1.2:
        return "code"
    if (st["max_size"] >= body * 1.3 and len(txt) <= 160) or \
       (st["bold_ratio"] >= 0.6 and st["max_size"] >= body * 1.08 and len(txt) <= 90):
        return "heading"
    if st["bold_ratio"] >= 0.5 and len(txt) <= 80 and txt.rstrip().endswith(("？", "?")):
        return "paragraph"
    # Typora-style h4: short, slightly indented, no terminal punctuation, smaller than a heading
    if 2 <= len(txt) <= 40 and body_x0 + 12 <= st["x0"] <= body_x0 + 28 \
            and txt.rstrip()[-1:] not in "。！？；：:,，.）)":
        return "h4"
    if BULLET_RE.match(txt) or (st["x0"] >= body_x0 + 10 and len(txt) <= 220):
        return "list"
    return "paragraph"


def _heading_level(size: float, body: float) -> int:
    if size >= body * 2.2:
        return 1
    if size >= body * 1.55:
        return 2
    if size >= body * 1.25:
        return 3
    return 3


def _save_image(b: dict, assets_dir: Path, doc: dict, used: dict) -> str | None:
    data = b.get("image")
    if not data or b.get("width", 0) < 48 or b.get("height", 0) < 48:
        return None
    h = sha256_bytes(data)
    if h in used:
        return used[h]
    ext = (b.get("ext") or "png").lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in {"png", "jpg", "jpeg", "webp", "gif", "bmp"}:
        ext = "png"
    aid = f"a{len(doc['assets']) + 1:04d}"
    fn = f"{aid}.{ext}"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / fn).write_bytes(data)
    w, hgt = int(b.get("width", 0)), int(b.get("height", 0))
    doc["assets"][aid] = {"path": f"assets/{fn}", "mediaType": f"image/{'jpeg' if ext == 'jpg' else ext}",
                          "width": w, "height": hgt, "sha256": h}
    used[h] = aid
    return aid


def inspect_pdf(path: str) -> dict:
    d = pymupdf.open(path)
    pages = d.page_count
    text_chars = 0
    image_count = 0
    radical = replacement = 0
    blank = 0
    for page in d:
        t = page.get_text()
        text_chars += len(t)
        image_count += len(page.get_images(full=True))
        if len(t.strip()) < 20 and page.get_images(full=True):
            blank += 1
        n, st = norm_text(t)
        radical += st["radicals"]
        replacement += st["replacement"]
    return {
        "kind": "pdf", "pages": pages, "textChars": text_chars,
        "images": image_count, "scannedLikePages": blank,
        "radicals": radical, "replacementChars": replacement,
        "metadata": {k: v for k, v in (d.metadata or {}).items() if v},
        "pageSizes": [[round(p.rect.width, 1), round(p.rect.height, 1)] for p in d[:min(3, pages)]],
    }


def extract_pdf(path: str, out_dir: str, fixes: list[tuple[str, str]] | None = None) -> dict:
    src = Path(path)
    d = pymupdf.open(str(src))
    pages_raw = [_page_raw_blocks(p, i + 1, fixes or []) for i, p in enumerate(d)]
    page_heights = [p.rect.height for p in d]
    page_widths = [p.rect.width for p in d]
    body, body_x0, _ = _body_metrics(pages_raw)
    hf_keys = _header_footer_keys(pages_raw, page_heights)

    meta_title = (d.metadata or {}).get("title") or ""
    meta_author = (d.metadata or {}).get("author") or ""
    meta = {
        "title": meta_title or src.stem,
        "author": meta_author,
        "language": "zh-CN",
        "source": str(src),
        "sourceHash": "sha256:" + sha256_file(src),
        "createdAt": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    doc = new_doc(meta)
    assets_dir = Path(out_dir) / "assets"
    used_imgs: dict[str, str] = {}
    warnings = Counter()
    columns = 0
    removed_hf = 0
    total_radicals = total_fixes = total_repl = 0
    fig_no = 0
    consumed: set[int] = set()
    blocks_out: list[dict] = []

    # first pass: collect blocks per page in order
    page_items: list[list[dict]] = []
    for pi, page in enumerate(d):
        ordered, two_col = _order_page_blocks(pages_raw[pi], page_widths[pi] or 1)
        if two_col:
            columns += 1
        page_items.append(ordered)

    # turn raw blocks into candidate blocks
    candidates: list[dict] = []
    seen_asset_ids: set[str] = set()
    for pi, items in enumerate(page_items):
        for b in items:
            if b["kind"] == "image":
                aid = _save_image(b, assets_dir, doc, used_imgs)
                if aid and aid not in seen_asset_ids:
                    seen_asset_ids.add(aid)
                    fig_no += 1
                    w, h = doc["assets"][aid]["width"], doc["assets"][aid]["height"]
                    aspect = w / h if h else 1
                    luma = image_luma(assets_dir / Path(doc["assets"][aid]["path"]).name)
                    if luma >= 165:
                        role, layout = "diagram", "fit"
                    elif aspect >= 4:
                        role, layout = "screenshot", "strip"
                    elif aspect >= 1.45:
                        role, layout = "screenshot", "rot"
                    else:
                        role, layout = ("photo" if luma >= 100 else "screenshot"), "fit"
                    candidates.append({"kind": "figure", "asset": aid, "width": w, "height": h,
                                       "aspect": round(aspect, 3), "layout": layout,
                                       "page": pi + 1, "bbox": b["bbox"],
                                       "role": role, "caption": "", "alt": ""})
                continue
            st = _block_stats(b, body)
            if not st:
                continue
            # header/footer / page number
            key = re.sub(r"\s+", "", st["text"])
            key = re.sub(r"\d+", "#", key)
            h = page_heights[pi] or 1
            in_band = st["y1"] < h * 0.12 or st["y0"] > h * 0.88
            if (in_band and key in hf_keys) or (PAGE_NUM_RE.match(st["text"]) and len(st["text"]) < 24):
                removed_hf += 1
                continue
            cl = _classify(st, body, body_x0)
            if cl == "skip":
                continue
            cand = {"kind": cl, "stats": st, "page": pi + 1, "bbox": b["bbox"]}
            candidates.append(cand)
            total_radicals += b["norm_stats"]["radicals"]
            total_fixes += b["norm_stats"]["fixes"]
            total_repl += b["norm_stats"]["replacement"]

    # merge adjacent blocks and emit
    i = 0
    pending: dict | None = None

    def flush():
        nonlocal pending
        if pending:
            blocks_out.append(pending)
            pending = None

    while i < len(candidates):
        c = candidates[i]
        if c["kind"] == "figure":
            flush()
            fig_no2 = sum(1 for x in blocks_out if x["type"] == "figure") + 1
            fig = block("figure", id=f"b{len(blocks_out)+1:04d}", asset=c["asset"],
                        width=c["width"], height=c["height"], aspect=c["aspect"],
                        layout=c["layout"], role=c["role"],
                        alt=f"图片 {fig_no2}", caption="", source={"page": c["page"],
                        "bbox": [round(v, 1) for v in c["bbox"]]})
            blocks_out.append(fig)
            consumed.add(len(blocks_out) - 1)
            i += 1
            continue
        cl = c["kind"]
        st = c["stats"]
        # merge consecutive same-type blocks on the same page
        if pending and pending["type"] == ("heading" if cl in ("heading", "h4") else cl) and \
           pending.get("_page") == c["page"]:
            gap = st["y0"] - pending["_y1"]
            same_x = abs(st["x0"] - pending["_x0"]) < 3
            if cl in ("heading", "h4") and pending["type"] == "heading" and gap < 10:
                pending["_lines"].extend(st["lines"])
                pending["_y1"] = st["y1"]
                i += 1
                continue
            if cl == "paragraph" and gap < 10 and same_x:
                prev_txt = text_of_html(_lines_html(pending["_lines"])).strip()
                if prev_txt and prev_txt[-1] not in "。！？.!?；;":
                    pending["_lines"].extend(st["lines"])
                    pending["_y1"] = st["y1"]
                    i += 1
                    continue
            if cl == "code" and gap < 20 and same_x:
                pending["_lines"].extend(st["lines"])
                pending["_y1"] = st["y1"]
                i += 1
                continue
            if cl == "list" and gap < 5 and same_x:
                prev_txt = text_of_html(pending["_items"][-1]).strip()
                if prev_txt and prev_txt[-1] not in "。！？.!?；;":
                    pending["_items"][-1] += _lines_html(st["lines"])
                    pending["_y1"] = st["y1"]
                    i += 1
                    continue
        flush()
        if cl in ("heading", "h4"):
            pending = {"type": "heading", "_page": c["page"], "_y1": st["y1"], "_x0": st["x0"],
                       "_bbox": c["bbox"], "_lines": list(st["lines"]),
                       "level": 4 if cl == "h4" else _heading_level(st["max_size"], body)}
        elif cl == "code":
            pending = {"type": "code", "_page": c["page"], "_y1": st["y1"], "_x0": st["x0"],
                       "_bbox": c["bbox"], "_lines": list(st["lines"])}
        elif cl == "list":
            pending = {"type": "list", "_page": c["page"], "_y1": st["y1"], "_x0": st["x0"],
                       "_bbox": c["bbox"], "_items": [_lines_html(st["lines"])]}
        else:
            pending = {"type": "paragraph", "_page": c["page"], "_y1": st["y1"], "_x0": st["x0"],
                       "_bbox": c["bbox"], "_lines": list(st["lines"])}
        i += 1
    flush()

    # finalize blocks
    final: list[dict] = []
    for b in blocks_out:
        if b["type"] == "figure":
            final.append(b)
            continue
        if b["type"] == "code":
            txt = "\n".join(re.sub(r"[ \t]+$", "", l) for l in
                            [_span_text(x.get("spans", [])) for x in b["_lines"]])
            txt = txt.strip("\n")
            final.append(block("code", id=f"b{len(final)+1:04d}", text=txt,
                               language="", source={"page": b["_page"],
                               "bbox": [round(v, 1) for v in b["_bbox"]]}))
        elif b["type"] == "list":
            items = [x for x in b["_items"] if x.strip()]
            if items:
                final.append(block("list", id=f"b{len(final)+1:04d}", ordered=bool(re.match(r"^\s*\d", text_of_html(items[0]))),
                                   items=items, source={"page": b["_page"], "bbox": [0, 0, 0, 0]}))
        elif b["type"] == "heading":
            html = _lines_html(b["_lines"])
            txt = text_of_html(html).strip()
            if txt:
                final.append(block("heading", id=f"b{len(final)+1:04d}", level=b["level"],
                                   text=txt, html=html, source={"page": b["_page"], "bbox": [0, 0, 0, 0]}))
        else:
            html = _lines_html(b["_lines"])
            txt = text_of_html(html).strip()
            if txt:
                final.append(block("paragraph", id=f"b{len(final)+1:04d}", text=txt, html=html,
                                   source={"page": b["_page"], "bbox": [0, 0, 0, 0]}))

    # group adjacent list blocks into a single list (separate bullets are separate blocks)
    grouped: list[dict] = []
    for b in final:
        if b["type"] == "list" and grouped and grouped[-1]["type"] == "list" \
                and bool(grouped[-1].get("ordered")) == bool(b.get("ordered")):
            grouped[-1]["items"].extend(b.get("items", []))
        else:
            grouped.append(b)
    final = grouped

    # attach captions to figures
    for idx, b in enumerate(final):
        if b["type"] != "figure":
            continue
        for j in (idx + 1, idx + 2, idx - 1):
            if 0 <= j < len(final):
                n = final[j]
                if n["type"] in ("paragraph", "heading") and CAPTION_RE.match(n.get("text", "")):
                    b["caption"] = n["text"]
                    b["alt"] = n["text"]
                    n["_consumed"] = True
                    break
    final = [b for b in final if not b.get("_consumed")]

    # clean internal keys
    for b in final:
        for k in list(b):
            if k.startswith("_"):
                del b[k]

    # title from first h1 if metadata empty
    if not meta_title:
        for b in final:
            if b["type"] == "heading" and b.get("level") == 1:
                doc["meta"]["title"] = b["text"][:120]
                break

    doc["blocks"] = final
    for code, msg, n in [
        ("text-layer-radicals", "检测到康熙部首/CJK 兼容字，已归一化", total_radicals),
        ("replacement-chars", "检测到替换字符（�），文本层可能损坏", total_repl),
        ("manual-fixes", "应用了用户指定的文本修正", total_fixes),
        ("removed-header-footer", "移除了重复页眉/页脚/页码", removed_hf),
        ("two-column", "检测到多栏并尝试按列排序", columns),
    ]:
        if n:
            add_warning(doc, code, msg, n)
    scanned = 0
    for page in d:
        if len(page.get_text().strip()) < 40 and page.get_images(full=True):
            scanned += 1
    if scanned:
        add_warning(doc, "scanned-pages", "部分页面文本层稀少，可能是扫描页；建议 OCR/MinerU", scanned)
    doc["meta"]["pages"] = d.page_count
    doc["meta"]["bodyFontSize"] = body
    doc["stats"] = {"pages": d.page_count, "blocks": len(final),
                    "figures": sum(1 for b in final if b["type"] == "figure"),
                    "codeBlocks": sum(1 for b in final if b["type"] == "code")}
    return doc
