"""Render a DocModel into a self-contained responsive HTML reader."""
from __future__ import annotations

import base64
import html
import re
import shutil
from pathlib import Path

from common import TEMPLATES_DIR, esc, get_profile, text_of_html

IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
              "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
              "bmp": "image/bmp"}


def _asset_src(doc: dict, aid: str, out_dir: Path, embed: bool, model_dir: Path | None = None) -> str:
    a = doc.get("assets", {}).get(aid) or {}
    p = Path(a.get("path", ""))
    if not p.is_absolute():
        # asset paths are relative to the model/work directory
        p = (model_dir or out_dir) / p
    if not p.exists():
        # try relative to cwd
        alt = Path(a.get("path", ""))
        if alt.exists():
            p = alt
        else:
            return ""
    if embed:
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        ext = p.suffix.lower().lstrip(".")
        mime = IMAGE_MIME.get(ext, "application/octet-stream")
        return f"data:{mime};base64,{data}"
    dest_dir = out_dir / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / p.name
    if not dest.exists() or dest.stat().st_size != p.stat().st_size:
        shutil.copyfile(p, dest)
    return f"assets/{p.name}"


def _toc(blocks: list[dict]) -> tuple[str, list[dict]]:
    heads = [b for b in blocks if b["type"] == "heading" and int(b.get("level", 3)) <= 3
             and b.get("text")]
    if not heads:
        return "", []
    parts = ['<ol class="toc-list">']
    for n, b in enumerate(heads, 1):
        lvl = int(b.get("level", 3))
        cls = " class=\"lv3\"" if lvl >= 3 else ""
        parts.append(f'<li{cls}><a href="#{esc(b["id"])}"><span class="toc-n">{n:02d}</span>'
                     f'<span>{esc(b.get("text", ""))[:90]}</span></a></li>')
    parts.append("</ol>")
    return "\n".join(parts), heads


def _figure(doc: dict, b: dict, out_dir: Path, embed: bool, fig_no: int, model_dir: Path | None = None) -> str:
    w, h = int(b.get("width") or 0), int(b.get("height") or 0)
    aspect = float(b.get("aspect") or ((w / h) if h else 1.6))
    mode = b.get("layout") or ("strip" if aspect >= 4 else "rot" if aspect >= 1.45 else "fit")
    if mode not in ("fit", "rot", "strip"):
        mode = "fit"
    sw = min(1200, max(560, round(w / 2))) if w else 700
    src = _asset_src(doc, b.get("asset", ""), out_dir, embed, model_dir)
    if not src:
        return ""
    cap = b.get("caption") or ""
    alt = b.get("alt") or cap or f"图 {fig_no}"
    style = f'--ar:{aspect:.4f};--hr:{(1 / aspect if aspect else 1):.4f};--sw:{sw}px'
    return f'''<figure class="shot" data-base="{mode}" data-mode="{mode}">
<div class="shot-box is-{mode}" style="{style}"><img src="{src}" alt="{esc(alt)}" loading="lazy" decoding="async"></div>
<figcaption><span class="cap-text"><b>图 {fig_no}</b>{(" · " + esc(cap)) if cap else ""}</span><span class="cap-tools"><span class="mode-hint">{ {"rot":"已旋转 90°","strip":"左右滑动","fit":"点击放大"}[mode] }</span><button type="button" class="tool" data-act="rotate" aria-label="旋转图片" title="旋转 90°">⟳</button><button type="button" class="tool" data-act="zoom" aria-label="全屏查看" title="全屏查看">⤢</button></span></figcaption>
</figure>'''


def render(doc: dict, out_file: str, profile: dict | None = None,
           embed: bool = True, model_dir: str | None = None) -> str:
    model_path = Path(model_dir).resolve() if model_dir else None
    out_path = Path(out_file).resolve()
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = profile or doc.get("profile") or get_profile()
    title = doc.get("meta", {}).get("title") or "doc2screen"
    author = doc.get("meta", {}).get("author") or ""
    lang = doc.get("meta", {}).get("language") or "zh-CN"
    blocks = doc.get("blocks", [])
    css = (TEMPLATES_DIR / "reader.css").read_text(encoding="utf-8")
    js = (TEMPLATES_DIR / "reader.js").read_text(encoding="utf-8")

    # avoid duplicate title heading
    if blocks and blocks[0]["type"] == "heading" and blocks[0].get("level") == 1 \
            and text_of_html(blocks[0].get("html", "")).strip() == title.strip():
        blocks = blocks[1:]

    toc, heads = _toc(blocks)
    body = []
    fig_no = 0
    for b in blocks:
        t = b["type"]
        if t == "heading":
            lvl = max(1, min(6, int(b.get("level", 2))))
            body.append(f'<h{lvl} id="{esc(b["id"])}">{b.get("html") or esc(b.get("text", ""))}'
                        f'<a class="anchor" href="#{esc(b["id"])}" aria-hidden="true">#</a></h{lvl}>')
        elif t == "paragraph":
            body.append(f'<p>{b.get("html") or esc(b.get("text", ""))}</p>')
        elif t == "list":
            ordered = bool(b.get("ordered"))
            tag = "ol" if ordered else "ul"
            items = list(b.get("items", []))
            start = 1
            if ordered and items:
                first = text_of_html(items[0]).strip()
                m = re.match(r"^(\d{1,3})[.)、]\s*", first)
                if m:
                    start = int(m.group(1))
                    items = [re.sub(r"^\s*\d{1,3}[.)、]\s*", "", x, count=1) for x in items]
            attr = f' start="{start}"' if ordered and start != 1 else ""
            lis = "".join(f"<li>{x}</li>" for x in items)
            body.append(f'<{tag} class="doc-list"{attr}>{lis}</{tag}>')
        elif t == "code":
            lang2 = b.get("language") or "code"
            body.append('<div class="code-block"><div class="code-head"><span>'
                        + esc(lang2) + '</span><button type="button" class="copy">复制</button></div>'
                        + '<pre><code>' + esc(b.get("text", "")) + '</code></pre></div>')
        elif t == "table":
            body.append('<div class="table-wrap">' + (b.get("html") or "") + '</div>')
        elif t == "figure":
            fig_no += 1
            body.append(_figure(doc, b, out_dir, embed, fig_no, model_path))
        elif t == "quote":
            body.append('<blockquote>' + (b.get("html") or "") + '</blockquote>')
        elif t == "callout":
            body.append('<div class="callout">' + (b.get("html") or "") + '</div>')
        elif t == "divider":
            body.append('<hr class="divider">')
        elif t == "pagebreak":
            body.append('<div style="break-after:page"></div>')

    stats = doc.get("stats", {})
    chips = []
    if stats.get("pages"):
        chips.append(f'<span class="chip">{stats["pages"]} 页</span>')
    if stats.get("blocks"):
        chips.append(f'<span class="chip">{stats["blocks"]} 段</span>')
    if stats.get("figures"):
        chips.append(f'<span class="chip">{stats["figures"]} 图</span>')
    chips.append(f'<span class="chip">{esc(profile.get("label") or profile.get("id", ""))}</span>')

    cover = f'''<section class="cover">
<p class="eyebrow">doc2screen · reading edition</p>
<h1>{esc(title)}</h1>
{('<p class="lede">' + esc(author) + '</p>') if author else ''}
<div class="chips">{''.join(chips)}</div>
<p class="cover-note"><b>阅读提示：</b>宽图已按屏幕自动旋转或设为左右滑动；点「⟳」切换方向，点「⤢」全屏查看。右上角「☰」打开目录。</p>
</section>'''

    warnings = doc.get("warnings", [])
    warn_html = ""
    if warnings:
        warn_html = '<p><b>提取警告：</b>' + "；".join(
            esc(w.get("message", "")) + (f'（{w.get("count")}）' if w.get("count") else "")
            for w in warnings[:8]) + "</p>"

    drawer = f'''<div id="scrim" hidden></div>
<aside id="drawer" aria-hidden="true" aria-label="目录">
<div class="drawer-head"><span>目录</span><button class="icon" id="btnClose" aria-label="关闭目录">✕</button></div>
<div class="drawer-body">{toc or '<p style="color:var(--muted);font-size:13px">本文档没有可用的标题层级。</p>'}</div>
<div class="drawer-settings"><button class="drawer-top" id="btnDrawerTop">↑ 顶部</button><span class="fsgroup"><button class="fsbtn" id="fsMinus" aria-label="减小字号">A−</button><span id="fsVal">{int(profile.get("baseFont", 17))}</span><button class="fsbtn" id="fsPlus" aria-label="增大字号">A+</button></span></div>
</aside>'''

    viewer = '''<div id="viewer" hidden aria-modal="true" role="dialog" aria-label="图片查看">
<div class="viewer-bar"><span class="viewer-title" id="viewerTitle"></span><button class="vbtn" id="vRot" aria-label="旋转图片" title="旋转">⟳</button><button class="vbtn" id="vClose" aria-label="关闭" title="关闭">✕</button></div>
<div class="viewer-stage" id="stage"><div class="viewer-frame"><img id="viewerImg" alt=""></div></div>
</div>'''

    html_doc = f'''<!doctype html>
<html lang="{esc(lang)}" data-theme="light" data-profile="{esc(profile.get("id", ""))}" style="--fs:{int(profile.get("baseFont", 17))}px;--page-w:{int(profile.get("cssWidth", 390))}px;--page-h:{int(profile.get("cssHeight", 657))}px;--margin:{int(profile.get("margin", 16))}px">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f5f1e8" id="metaTheme">
<title>{esc(title)}</title>
<style>
@page {{ size: {int(profile.get("cssWidth", 390))}px {int(profile.get("cssHeight", 657))}px; }}
{css}
</style>
</head>
<body>
<div id="progress" aria-hidden="true"></div>
<header class="topbar" id="topbar">
<button class="icon" id="btnToc" aria-label="打开目录" aria-controls="drawer" aria-expanded="false">☰</button>
<span class="tb-title">{esc(title)}</span>
<button class="icon" id="btnTheme" aria-label="切换深色/浅色模式" title="切换主题">◐</button>
</header>
<main>
{cover}
{''.join(body)}
<footer class="doc-footer">
<p><b>来源：</b>{esc(Path(doc.get("meta", {}).get("source", "")).name or "—")}</p>
<p>由 doc2screen 生成 · 版面按 {esc(profile.get("label") or profile.get("id", ""))} 重排 · 输出继承原文档版权。</p>
{warn_html}
</footer>
</main>
{drawer}
{viewer}
<script>{js}</script>
</body>
</html>'''
    out_path.write_text(html_doc, encoding="utf-8")
    return str(out_path)
