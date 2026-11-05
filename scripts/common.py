"""Shared helpers for doc2screen."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PROFILES_PATH = SKILL_DIR / "profiles" / "devices.json"
TEMPLATES_DIR = SKILL_DIR / "templates"

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_RADICAL_RANGES = ((0x2E80, 0x2FDF), (0xF900, 0xFAFF), (0x2F800, 0x2FA1F))


def load_profiles() -> dict:
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def get_profile(name: str = "phone-notes", width: int | None = None,
                height: int | None = None) -> dict:
    profiles = load_profiles()
    if width and height:
        return {
            "id": f"custom-{width}x{height}",
            "label": f"custom {width}×{height}",
            "cssWidth": int(width),
            "cssHeight": int(height),
            "baseFont": 17,
            "margin": 16,
            "lineHeight": 1.8,
        }
    if name not in profiles:
        raise SystemExit(f"Unknown profile '{name}'. Available: {', '.join(profiles)}")
    p = dict(profiles[name])
    p["id"] = name
    return p


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_text(s: str, fixes: list[tuple[str, str]] | None = None) -> tuple[str, dict]:
    """Normalize PDF text-layer artifacts; return text + stats.

    Fixes are applied before normalization, e.g. [('端又','端口')].
    """
    stats = {"radicals": 0, "replacement": 0, "fixes": 0}
    for old, new in fixes or []:
        if old and old in s:
            stats["fixes"] += s.count(old)
            s = s.replace(old, new)
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "�":
            stats["replacement"] += 1
        if any(a <= o <= b for a, b in _RADICAL_RANGES):
            ch2 = unicodedata.normalize("NFKC", ch)
            if ch2 != ch:
                stats["radicals"] += 1
            ch = ch2
        out.append(ch)
    text = "".join(out)
    text = text.replace(" ", " ").replace("­", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, stats


def is_cjk(ch: str) -> bool:
    return bool(ch and _CJK.match(ch))


def join_visual_lines(lines: list[str]) -> str:
    """Join PDF visual lines without inserting spaces between CJK characters."""
    texts = [t.strip() for t in lines if t and t.strip()]
    if not texts:
        return ""
    out = texts[0]
    for nxt in texts[1:]:
        prev = out[-1]
        if is_cjk(prev) or is_cjk(nxt[0]):
            out += nxt
        elif prev in "，。；：、！？）》”" or nxt[0] in "，。；：、！？《（“":
            out += nxt
        elif re.match(r"[A-Za-z0-9]", prev) and re.match(r"[A-Za-z0-9]", nxt[0]):
            out += " " + nxt
        else:
            out += nxt
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text_of_html(html: str) -> str:
    from lxml import html as lhtml
    try:
        return lhtml.fromstring(html).text_content()
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


def clean_inline_html(html: str) -> str:
    """Allow basic inline markup; strip scripts, styles, event handlers, javascript: URLs."""
    from lxml import html as lhtml
    from lxml import etree
    try:
        root = lhtml.fragment_fromstring(html or "", create_parent="div")
    except Exception:
        return esc(text_of_html(html or ""))
    for el in root.xpath(".//script|.//style|.//iframe|.//object|.//embed|.//form"):
        el.drop_tree()
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            val = el.attrib.get(attr, "")
            if attr.lower().startswith("on") or re.search(r"javascript\s*:", val, re.I):
                del el.attrib[attr]
    parts = []
    if root.text:
        parts.append(esc(root.text))
    for child in root:
        parts.append(lhtml.tostring(child, encoding="unicode", method="html"))
    return "".join(parts).strip()


def block(kind: str, **kw) -> dict:
    b = {"id": kw.pop("id", ""), "type": kind}
    b.update({k: v for k, v in kw.items() if v is not None})
    return b


def add_warning(doc: dict, code: str, message: str, count: int | None = None) -> None:
    item = {"code": code, "message": message}
    if count is not None:
        item["count"] = count
    doc.setdefault("warnings", []).append(item)


def new_doc(meta: dict, profile: dict | None = None) -> dict:
    return {
        "schema": "doc2screen/1",
        "meta": meta,
        "profile": profile or {},
        "blocks": [],
        "assets": {},
        "warnings": [],
    }


def dump_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_filename(name: str, default: str = "book") -> str:
    stem = re.sub(r"[^\w一-鿿.-]+", "-", name or "").strip(" .-_")
    return stem[:80] or default


def image_luma(path) -> float:
    """Average luminance (0-255) of an image; used to separate screenshots from diagrams."""
    try:
        import pymupdf
        pix = pymupdf.Pixmap(str(path))
        gray = pymupdf.Pixmap(pymupdf.csGRAY, pix)
        data = gray.samples
        if not data:
            return 128.0
        step = max(1, len(data) // 30000)
        vals = data[::step]
        return sum(vals) / len(vals)
    except Exception:
        return 128.0
