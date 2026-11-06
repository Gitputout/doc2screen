#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - "$TMP/image.png" <<'PY'
import base64
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg=="))
PY

cat > "$TMP/sample.md" <<'MD'
# doc2screen smoke test

This is **bold**, this is `code`, and this is a list.

这是一段中文正文，用来验证 UTF-8 编码。

Line one<br>
Line two.

![Sample figure](image.png)

## Section one

```python
def hello(name):
    print("hello", name)
```

- one
- two
- three

| A | B |
|---|---|
| 1 | 2 |
MD

pandoc "$TMP/sample.md" --resource-path "$TMP" -o "$TMP/sample.docx"
pandoc "$TMP/sample.md" --resource-path "$TMP" -o "$TMP/sample.epub"

if [ -n "${CHROME_PATH:-}" ] && [ -x "$CHROME_PATH" ]; then
  HAS_CHROME=1
elif [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] ||
     command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
  HAS_CHROME=1
else
  HAS_CHROME=0
fi

for f in md docx epub; do
  echo "=== build $f (html) ==="
  if [ "$HAS_CHROME" -eq 1 ]; then
    python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.$f" \
      --profile phone-notes --formats html --out "$TMP/out-$f" >/dev/null
    python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-$f" --profile phone-notes >/dev/null
  else
    python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.$f" \
      --profile phone-notes --formats html --no-verify --out "$TMP/out-$f" >/dev/null
  fi
  python3 - "$TMP/out-$f/.work/doc.json" <<'PY'
import json
import sys
from pathlib import Path
doc = json.loads(Path(sys.argv[1]).read_text())
assert any(b["type"] == "figure" for b in doc["blocks"])
assert any("中文正文" in (b.get("text") or "") for b in doc["blocks"])
PY
done

echo "=== build md (html,epub,pdf) ==="
if [ "$HAS_CHROME" -eq 1 ]; then
  python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
    --profile phone-notes --formats html,epub,pdf --out "$TMP/out-all" >/dev/null
  python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-all" --profile phone-notes >/dev/null
else
  python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
    --profile phone-notes --formats html,epub --no-verify --out "$TMP/out-all" >/dev/null
  python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-all"/*.epub --profile phone-notes >/dev/null
fi

python3 - "$TMP/out-all" <<'PY'
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
out = Path(sys.argv[1])
build = json.loads((out / "build.json").read_text())
epub = Path(build["outputs"]["epub"])
with zipfile.ZipFile(epub) as z:
    assert any(n.startswith("OEBPS/images/") for n in z.namelist())
    nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
    href = re.search(r'<link[^>]+href="([^"]+)"', nav).group(1)
    target = posixpath.normpath(posixpath.join("OEBPS", href))
    assert target in z.namelist(), target
assert build["verify_epub"]["ok"], build["verify_epub"]
PY

if python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/missing.pdf" >/dev/null 2>&1; then
  echo "verify accepted a missing target" >&2
  exit 1
fi
if python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
    --formats epub --start-at "not present" --out "$TMP/out-no-match" >/dev/null 2>&1; then
  echo "build accepted an unmatched start heading" >&2
  exit 1
fi
if python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
    --formats docx --out "$TMP/out-bad-format" >/dev/null 2>&1; then
  echo "build accepted an unknown format" >&2
  exit 1
fi

if [ "$HAS_CHROME" -eq 1 ]; then
  echo "=== default build (PDF only) ==="
  python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
    --profile phone-notes --out "$TMP/out-default" >/dev/null
  ls "$TMP/out-default"/*.pdf >/dev/null
  if ls "$TMP/out-default"/*.html >/dev/null 2>&1; then
    echo "default build unexpectedly produced HTML" >&2
    exit 1
  fi
  python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-default" --profile phone-notes >/dev/null
fi
python3 "$ROOT/scripts/profile_helper.py" \
  --inches 6.39 --aspect 16:9.5 --page-ratio 0.706 --css-width 390 >/dev/null
echo "smoke checks passed"
