#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/sample.md" <<'MD'
# doc2screen smoke test

This is **bold**, this is `code`, and this is a list.

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

pandoc "$TMP/sample.md" -o "$TMP/sample.docx"
pandoc "$TMP/sample.md" -o "$TMP/sample.epub"

for f in md docx epub; do
  echo "=== build $f (html) ==="
  python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.$f" \
    --profile phone-notes --formats html --out "$TMP/out-$f" >/dev/null
  python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-$f" --profile phone-notes >/dev/null
done

echo "=== build md (html,epub,pdf) ==="
if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] || command -v google-chrome >/dev/null 2>&1; then
  python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
    --profile phone-notes --formats html,epub,pdf --out "$TMP/out-all" >/dev/null
  python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-all" --profile phone-notes >/dev/null
else
  python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
    --profile phone-notes --formats html,epub --out "$TMP/out-all" >/dev/null
  python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-all" --profile phone-notes >/dev/null
fi

echo "smoke test passed"

echo "=== default build (PDF only) ==="
python3 "$ROOT/scripts/doc2screen.py" build "$TMP/sample.md" \
  --profile phone-notes --out "$TMP/out-default" >/dev/null
ls "$TMP/out-default"/*.pdf >/dev/null
if ls "$TMP/out-default"/*.html >/dev/null 2>&1; then
  echo "default build unexpectedly produced HTML" >&2
  exit 1
fi
python3 "$ROOT/scripts/doc2screen.py" verify "$TMP/out-default" --profile phone-notes >/dev/null
python3 "$ROOT/scripts/profile_helper.py" \
  --inches 6.39 --aspect 16:9.5 --page-ratio 0.706 --css-width 390 >/dev/null
echo "default PDF-only check passed"
