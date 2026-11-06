"""Non-PDF extraction: Pandoc for DOCX/ODT/EPUB/HTML/Markdown, plus TXT."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pymupdf
from lxml import html as lhtml

from common import (add_warning, block, clean_inline_html, esc, image_luma,
                    new_doc, sha256_bytes, sha256_file, text_of_html)

PANDOC_FORMATS = {
    ".docx": "docx",
    ".odt": "odt",
    ".epub": "epub",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".tex": "latex",
}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def _inner_html(el) -> str:
    parts = []
    if el.text:
        parts.append(esc(el.text))
    for child in el:
        parts.append(lhtml.tostring(child, encoding="unicode", method="html"))
    return clean_inline_html("".join(parts))


def _img_dims(path: Path) -> tuple[int, int]:
    try:
        pix = pymupdf.Pixmap(str(path))
        return int(pix.width), int(pix.height)
    except Exception:
        return 0, 0


class Builder:
    def __init__(self, work: Path, source: Path):
        self.work = work
        self.source = source
        self.assets_dir = work / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.doc = new_doc({
            "title": source.stem,
            "author": "",
            "language": "zh-CN",
            "source": str(source),
            "sourceHash": "sha256:" + sha256_file(source),
            "createdAt": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        self.used: dict[str, str] = {}
        self.blocks: list[dict] = []

    def _asset(self, path: Path, alt: str = "") -> str | None:
        if not path.exists() or not path.is_file():
            return None
        data = path.read_bytes()
        h = sha256_bytes(data)
        if h in self.used:
            return self.used[h]
        ext = path.suffix.lower().lstrip(".") or "png"
        if ext == "jpeg":
            ext = "jpg"
        if ext not in {"png", "jpg", "gif", "webp", "svg", "bmp"}:
            ext = "png"
        aid = f"a{len(self.doc['assets']) + 1:04d}"
        fn = f"{aid}.{ext}"
        dest = self.assets_dir / fn
        shutil.copyfile(path, dest)
        w, hgt = _img_dims(dest)
        self.doc["assets"][aid] = {
            "path": f"assets/{fn}", "mediaType": f"image/{'jpeg' if ext == 'jpg' else ext}",
            "width": w, "height": hgt, "sha256": h,
        }
        self.used[h] = aid
        return aid

    def _resolve_media(self, src: str) -> Path | None:
        if not src or src.startswith("data:") or re.match(r"^[a-z]+://", src, re.I):
            return None
        p = Path(src)
        if not p.is_absolute():
            p = (self.work / src).resolve()
        if p.exists():
            return p
        # pandoc sometimes puts media under assets/media
        q = (self.assets_dir / Path(src).name).resolve()
        return q if q.exists() else None

    def figure(self, src: str, caption: str = "", alt: str = "") -> None:
        path = self._resolve_media(src)
        if not path:
            return
        aid = self._asset(path, alt)
        if not aid:
            return
        w = self.doc["assets"][aid]["width"]
        h = self.doc["assets"][aid]["height"]
        aspect = (w / h) if h else 1.0
        luma = image_luma(path)
        if luma >= 165:
            role, layout = "diagram", "fit"
        elif aspect >= 4:
            role, layout = "screenshot", "strip"
        elif aspect >= 1.45:
            role, layout = "screenshot", "rot"
        else:
            role, layout = ("photo" if luma >= 100 else "screenshot"), "fit"
        n = sum(1 for b in self.blocks if b["type"] == "figure") + 1
        self.blocks.append(block("figure", id=f"b{len(self.blocks)+1:04d}", asset=aid,
                                 width=w, height=h, aspect=round(aspect, 3), layout=layout,
                                 role=role, caption=caption,
                                 alt=alt or caption or f"图片 {n}"))

    def walk(self, el) -> None:
        tag = el.tag if isinstance(el.tag, str) else ""
        tag = tag.lower()
        if tag in HEADING_TAGS:
            txt = el.text_content().strip()
            if txt:
                self.blocks.append(block("heading", id=f"b{len(self.blocks)+1:04d}",
                                         level=HEADING_TAGS[tag], text=txt,
                                         html=_inner_html(el)))
            return
        if tag == "p":
            imgs = el.xpath(".//img")
            txt_html = _inner_html(el)
            txt_html = re.sub(r"<img[^>]*>", "", txt_html)
            # remove image-only paragraphs from text
            if imgs and not el.text_content().strip():
                for img in imgs:
                    self.figure(img.get("src", ""), alt=img.get("alt", ""))
                return
            if txt_html.strip():
                txt = text_of_html(txt_html).strip()
                if txt:
                    self.blocks.append(block("paragraph", id=f"b{len(self.blocks)+1:04d}",
                                             text=txt, html=txt_html))
            for img in imgs:
                self.figure(img.get("src", ""), alt=img.get("alt", ""))
            return
        if tag in ("ul", "ol"):
            items = []
            for li in el.xpath("./li"):
                h = _inner_html(li).strip()
                if h:
                    items.append(h)
            if items:
                self.blocks.append(block("list", id=f"b{len(self.blocks)+1:04d}",
                                         ordered=(tag == "ol"), items=items))
            return
        if tag == "pre":
            code = el.text_content()
            lang = ""
            cls = el.get("class", "") + " " + (el.find("code").get("class", "") if el.find("code") is not None else "")
            m = re.search(r"language-([\w+#.-]+)", cls)
            if m:
                lang = m.group(1)
            self.blocks.append(block("code", id=f"b{len(self.blocks)+1:04d}",
                                     text=code.rstrip("\n"), language=lang))
            return
        if tag == "table":
            html = lhtml.tostring(el, encoding="unicode", method="html")
            self.blocks.append(block("table", id=f"b{len(self.blocks)+1:04d}",
                                     html=clean_inline_html(html)))
            return
        if tag == "figure":
            cap_el = el.find(".//figcaption")
            cap = cap_el.text_content().strip() if cap_el is not None else ""
            for img in el.xpath(".//img"):
                self.figure(img.get("src", ""), caption=cap, alt=img.get("alt", ""))
            return
        if tag == "img":
            self.figure(el.get("src", ""), alt=el.get("alt", ""))
            return
        if tag == "blockquote":
            h = _inner_html(el)
            if h.strip():
                self.blocks.append(block("quote", id=f"b{len(self.blocks)+1:04d}", html=h))
            return
        if tag == "hr":
            self.blocks.append(block("divider", id=f"b{len(self.blocks)+1:04d}"))
            return
        if tag in ("script", "style", "nav", "footer", "aside", "form", "iframe"):
            return
        # containers
        for child in el:
            self.walk(child)
        if el.text and el.text.strip() and tag not in ("div", "section", "article", "main", "body", "html", "header"):
            txt = el.text.strip()
            self.blocks.append(block("paragraph", id=f"b{len(self.blocks)+1:04d}",
                                     text=txt, html=esc(txt)))


def extract_via_pandoc(path: str, out_dir: str) -> dict:
    src = Path(path).resolve()
    fmt = PANDOC_FORMATS.get(src.suffix.lower())
    if not fmt:
        raise SystemExit(f"Unsupported format: {src.suffix}")
    work = Path(out_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    raw = work / "raw.html"
    cmd = ["pandoc", str(src), "-f", fmt, "-t", "html5", "--wrap=none",
           f"--resource-path={src.parent}", "--extract-media=assets", "-o", "raw.html"]
    proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("Pandoc failed:\n" + (proc.stderr or proc.stdout)[-2000:])
    # Pandoc emits UTF-8 without a meta charset; lxml would otherwise default
    # to Latin-1 and mojibake every non-ASCII character.
    tree = lhtml.parse(str(raw), parser=lhtml.HTMLParser(encoding="utf-8"))
    b = Builder(work, src)
    title_el = tree.find(".//title")
    if title_el is not None and title_el.text_content().strip():
        b.doc["meta"]["title"] = title_el.text_content().strip()
    lang = (tree.getroot().get("lang") or "").strip()
    if lang:
        b.doc["meta"]["language"] = lang
    body = tree.find("body")
    if body is None:
        body = tree.getroot()
    b.walk(body)
    if not any(x["type"] == "heading" for x in b.blocks):
        # use first paragraph as title if no headings
        for x in b.blocks:
            if x["type"] == "paragraph":
                b.doc["meta"]["title"] = x["text"][:80]
                break
    b.doc["blocks"] = b.blocks
    b.doc["meta"]["pages"] = 0
    b.doc["stats"] = {"pages": 0, "blocks": len(b.blocks),
                      "figures": sum(1 for x in b.blocks if x["type"] == "figure"),
                      "codeBlocks": sum(1 for x in b.blocks if x["type"] == "code")}
    if proc.stderr.strip():
        add_warning(b.doc, "pandoc", "Pandoc 输出警告", 0)
    return b.doc


def extract_txt(path: str, out_dir: str) -> dict:
    src = Path(path).resolve()
    text = src.read_text(encoding="utf-8", errors="replace")
    work = Path(out_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    doc = new_doc({
        "title": src.stem, "author": "", "language": "zh-CN",
        "source": str(src), "sourceHash": "sha256:" + sha256_file(src),
        "createdAt": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    paras = re.split(r"\n\s*\n", text)
    blocks = []
    for p in paras:
        p = p.strip()
        if not p:
            continue
        lines = [x.strip() for x in p.splitlines() if x.strip()]
        if not lines:
            continue
        joined = "".join(lines) if all(re.search(r"[㐀-鿿]", x) for x in lines) else " ".join(lines)
        if len(joined) <= 40 and re.match(r"^(第[一二三四五六七八九十百]+[章节]|Chapter\s+\d+|\d+(\.\d+)*\s)", joined):
            blocks.append(block("heading", id=f"b{len(blocks)+1:04d}", level=2,
                                text=joined, html=esc(joined)))
        else:
            blocks.append(block("paragraph", id=f"b{len(blocks)+1:04d}",
                                text=joined, html=esc(joined)))
    doc["blocks"] = blocks
    doc["meta"]["pages"] = 0
    doc["stats"] = {"pages": 0, "blocks": len(blocks), "figures": 0, "codeBlocks": 0}
    return doc
