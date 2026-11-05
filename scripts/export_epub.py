"""EPUB3 export from a DocModel."""
from __future__ import annotations

import html
import os
import re
import uuid
import zipfile
from pathlib import Path

from common import esc, text_of_html

EPUB_CSS = """
html,body{margin:0;padding:0;background:#fff;color:#111}
body{font-family:"Songti SC","Noto Serif CJK SC","Source Han Serif SC",serif;line-height:1.75;font-size:1em}
h1,h2,h3,h4{font-family:"Songti SC","Noto Serif CJK SC",serif;line-height:1.4;margin:1.2em 0 .5em;page-break-after:avoid}
h1{font-size:1.6em}h2{font-size:1.35em}h3{font-size:1.15em}
p{margin:.65em 0;text-align:justify}
ul,ol{padding-left:1.3em}li{margin:.25em 0}
pre{white-space:pre-wrap;word-wrap:break-word;background:#1b2124;color:#e8eef2;padding:.8em;border-radius:6px;font-family:monospace;font-size:.82em;line-height:1.5;overflow-wrap:anywhere}
code{font-family:monospace;background:#eef1f1;padding:.08em .25em;border-radius:3px}
pre code{background:none;padding:0;color:inherit}
img{max-width:100%;height:auto;display:block;margin:.6em auto}
figure{margin:1em 0;page-break-inside:avoid}
figcaption{font-size:.8em;color:#666;text-align:center;margin-top:.35em}
table{border-collapse:collapse;width:100%;font-size:.8em}
th,td{border:1px solid #ccc;padding:.35em;text-align:left}
blockquote{border-left:3px solid #bbb;margin:1em 0;padding-left:.8em;color:#555}
.titlepage{text-align:center;padding-top:32%;}
.titlepage h1{font-size:2em;border:0}
.titlepage .author{color:#555}
.small{font-size:.8em;color:#666}
"""


def _xhtml(title: str, body: str) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head><meta charset="utf-8"/><title>{esc(title)}</title>
<link rel="stylesheet" type="text/css" href="../css/reader.css"/></head>
<body>{body}</body></html>'''


def _block_html(doc: dict, b: dict, img_prefix: str) -> str:
    t = b["type"]
    if t == "heading":
        lvl = max(1, min(6, int(b.get("level", 2))))
        return f'<h{lvl}>{b.get("html") or esc(b.get("text", ""))}</h{lvl}>'
    if t == "paragraph":
        return f'<p>{b.get("html") or esc(b.get("text", ""))}</p>'
    if t == "list":
        tag = "ol" if b.get("ordered") else "ul"
        items = "".join(f"<li>{x}</li>" for x in b.get("items", []))
        return f"<{tag}>{items}</{tag}>"
    if t == "code":
        return f'<pre><code>{esc(b.get("text", ""))}</code></pre>'
    if t == "table":
        return b.get("html") or ""
    if t == "figure":
        a = doc.get("assets", {}).get(b.get("asset", ""), {})
        src = a.get("path", "")
        if not src:
            return ""
        fn = Path(src).name
        cap = b.get("caption") or ""
        alt = b.get("alt") or cap
        return (f'<figure><img src="{img_prefix}{esc(fn)}" alt="{esc(alt)}"/>'
                + (f"<figcaption>{esc(cap)}</figcaption>" if cap else "") + "</figure>")
    if t == "quote":
        return f'<blockquote>{b.get("html") or ""}</blockquote>'
    if t == "callout":
        return f'<div class="callout">{b.get("html") or ""}</div>'
    if t == "divider":
        return "<hr/>"
    return ""


def _split_chapters(doc: dict) -> list[dict]:
    blocks = doc.get("blocks", [])
    chapters: list[dict] = []
    cur = {"title": doc.get("meta", {}).get("title") or "正文", "blocks": []}
    for b in blocks:
        if b["type"] == "heading" and int(b.get("level", 3)) <= 2 and b.get("text"):
            if cur["blocks"]:
                chapters.append(cur)
            cur = {"title": b["text"][:100], "blocks": [b]}
        else:
            cur["blocks"].append(b)
    if cur["blocks"]:
        chapters.append(cur)
    # drop an initial chapter that only repeats the title
    if len(chapters) > 1 and len(chapters[0]["blocks"]) <= 2 and \
            chapters[0]["title"] == (doc.get("meta", {}).get("title") or ""):
        chapters.pop(0)
    return chapters


def export_epub(doc: dict, out_file: str, work_dir: str) -> dict:
    out = Path(out_file).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir).resolve()
    title = doc.get("meta", {}).get("title") or "doc2screen"
    author = doc.get("meta", {}).get("author") or ""
    lang = doc.get("meta", {}).get("language") or "zh-CN"
    chapters = _split_chapters(doc)
    uid = "urn:uuid:" + str(uuid.uuid4())
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    images = []
    used_assets = {b.get("asset") for b in doc.get("blocks", []) if b.get("type") == "figure"}
    for aid, a in (doc.get("assets") or {}).items():
        if aid not in used_assets:
            continue
        p = work / a.get("path", "")
        if p.exists():
            images.append((Path(a["path"]).name, p, a.get("mediaType", "image/png")))

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>''')
        z.writestr("OEBPS/css/reader.css", EPUB_CSS)
        z.writestr("OEBPS/text/title.xhtml", _xhtml(title,
            f'<div class="titlepage"><h1>{esc(title)}</h1>'
            + (f'<p class="author">{esc(author)}</p>' if author else "")
            + f'<p class="small">由 doc2screen 生成</p></div>'))

        manifest, spine, nav_items = [], [], []
        for i, ch in enumerate(chapters, 1):
            fn = f"chapter-{i:03d}.xhtml"
            body = "\n".join(_block_html(doc, b, "../images/") for b in ch["blocks"])
            z.writestr(f"OEBPS/text/{fn}", _xhtml(ch["title"], body))
            manifest.append(f'<item id="ch{i}" href="text/{fn}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="ch{i}"/>')
            nav_items.append(f'<li><a href="text/{fn}">{esc(ch["title"])}</a></li>')

        for fn, p, mt in images:
            z.write(p, f"OEBPS/images/{fn}")
            manifest.append(f'<item id="img-{esc(fn)}" href="images/{fn}" media-type="{mt}"/>')
        manifest.append('<item id="css" href="css/reader.css" media-type="text/css"/>')
        manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        manifest.append('<item id="title" href="text/title.xhtml" media-type="application/xhtml+xml"/>')
        manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')

        nav_body = ('<nav xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
                    'epub:type="toc" id="toc"><h1>目录</h1><ol>' + "".join(nav_items) + "</ol></nav>")
        z.writestr("OEBPS/nav.xhtml", _xhtml("目录", nav_body))

        opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bookid">{uid}</dc:identifier>
<dc:title>{esc(title)}</dc:title>
<dc:language>{esc(lang)}</dc:language>
{('<dc:creator>' + esc(author) + '</dc:creator>') if author else ''}
<meta property="dcterms:modified">{now}</meta>
</metadata>
<manifest>{''.join(manifest)}</manifest>
<spine toc="ncx"><itemref idref="title"/>{''.join(spine)}</spine>
</package>'''
        z.writestr("OEBPS/content.opf", opf)

        ncx = f'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="{uid}"/></head>
<docTitle><text>{esc(title)}</text></docTitle>
<navMap>{''.join(f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{esc(c["title"])}</text></navLabel><content src="text/chapter-{i:03d}.xhtml"/></navPoint>' for i, c in enumerate(chapters, 1))}</navMap>
</ncx>'''
        z.writestr("OEBPS/toc.ncx", ncx)

    return {"path": str(out), "chapters": len(chapters), "images": len(images),
            "size": out.stat().st_size}


def epub_report(path: str) -> dict:
    import xml.etree.ElementTree as ET
    p = Path(path)
    out = {"ok": True, "errors": []}
    try:
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            if not names or names[0] != "mimetype":
                out["errors"].append("mimetype is not the first entry")
            if z.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
                out["errors"].append("mimetype is compressed")
            for n in ("META-INF/container.xml", "OEBPS/content.opf", "OEBPS/nav.xhtml"):
                if n not in names:
                    out["errors"].append(f"missing {n}")
                else:
                    try:
                        ET.fromstring(z.read(n))
                    except Exception as e:
                        out["errors"].append(f"invalid XML {n}: {e}")
            if "OEBPS/content.opf" in names:
                root = ET.fromstring(z.read("OEBPS/content.opf"))
                ns = {"opf": "http://www.idpf.org/2007/opf"}
                hrefs = [x.get("href") for x in root.findall(".//opf:item", ns)]
                for h in hrefs:
                    full = "OEBPS/" + h if not h.startswith("OEBPS/") else h
                    if full not in names:
                        out["errors"].append(f"manifest href missing: {h}")
                out["items"] = len(hrefs)
            out["entries"] = len(names)
    except Exception as e:
        out["errors"].append(str(e))
    out["ok"] = not out["errors"]
    return out
