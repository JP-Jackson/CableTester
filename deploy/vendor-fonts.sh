#!/usr/bin/env bash
# Regenerate static/fonts/ from upstream.
#
# The tester ships its fonts locally because the bench box has no route to the
# internet. Run this on a machine that DOES have one, then commit the result.
# You need it only when a font weight or a UI icon is added.
#
#   ./deploy/vendor-fonts.sh
#
# Requires: python3, curl, and fontTools with brotli (pip install fonttools brotli).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_ROOT/static/fonts"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The icons the UI actually uses. Keep this in step with the markup: grep the
# templates and app.js for 'ti-' before changing it. Four glyphs is 1 KB; the
# whole Tabler webfont is 452 KB.
ICON_CLASSES=(sun moon refresh plug-connected)

# Weights the stylesheet asks for. Barlow is the body face, Barlow Condensed
# the display face for headings and the gauge.
BARLOW_WEIGHTS="300;400;500;600"
CONDENSED_WEIGHTS="400;500;700;800"

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

command -v curl >/dev/null || { echo "vendor-fonts.sh: curl not found" >&2; exit 1; }
python3 -c "import fontTools, brotli" 2>/dev/null || {
  echo "vendor-fonts.sh: needs fontTools and brotli (pip install fonttools brotli)" >&2
  exit 1
}

mkdir -p "$OUT"

echo "vendor-fonts.sh: fetching Barlow and Barlow Condensed (latin subset)"
BARLOW_WEIGHTS="$BARLOW_WEIGHTS" CONDENSED_WEIGHTS="$CONDENSED_WEIGHTS" \
OUT="$OUT" UA="$UA" python3 - <<'PY'
import os, re, urllib.request, pathlib

UA, OUT = os.environ["UA"], pathlib.Path(os.environ["OUT"])
FAMS = [
    ("Barlow",           "barlow",           os.environ["BARLOW_WEIGHTS"]),
    ("Barlow Condensed", "barlow-condensed", os.environ["CONDENSED_WEIGHTS"]),
]

def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read() if binary else r.read().decode()

# Google returns one @font-face per unicode subset, each preceded by a comment
# naming it. The UI is English and cable IDs are ASCII, so latin is all we ship.
BLOCK = re.compile(r"/\*\s*([a-z-]+)\s*\*/\s*(@font-face\s*\{.*?\})", re.S)

total = 0
for family, slug, weights in FAMS:
    css = fetch("https://fonts.googleapis.com/css2?family=%s:wght@%s&display=swap"
                % (family.replace(" ", "+"), weights))
    for subset, block in BLOCK.findall(css):
        if subset != "latin":
            continue
        w = re.search(r"font-weight:\s*(\d+)", block).group(1)
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        path = OUT / ("%s-%s.woff2" % (slug, w))
        path.write_bytes(fetch(url, binary=True))
        total += path.stat().st_size
        print("  %-30s %7d B" % (path.name, path.stat().st_size))
print("  text faces total: %d B" % total)
PY

echo "vendor-fonts.sh: fetching Tabler icons from npm and subsetting"
# jsDelivr is blocked on some networks; the npm registry tarball is the same
# artifact and is reachable more often.
TARBALL="$(curl -fsS --max-time 30 https://registry.npmjs.org/@tabler/icons-webfont \
  | python3 -c "import sys,json; d=json.load(sys.stdin); v=d['dist-tags']['latest']; print(d['versions'][v]['dist']['tarball'])")"
curl -fsS --max-time 90 "$TARBALL" -o "$WORK/tabler.tgz"
tar xzf "$WORK/tabler.tgz" -C "$WORK" package/dist/tabler-icons.min.css package/dist/fonts/tabler-icons.woff2

# Read each icon's codepoint out of the upstream CSS rather than hardcoding it,
# so a Tabler renumbering cannot silently swap one glyph for another.
CODEPOINTS=""
CSS_RULES=""
for name in "${ICON_CLASSES[@]}"; do
  cp_hex="$(grep -oE "\.ti-$name:+before\{content:\"\\\\[0-9a-fA-F]+\"" "$WORK/package/dist/tabler-icons.min.css" \
    | head -1 | grep -oE '[0-9a-fA-F]+"$' | tr -d '"')"
  if [ -z "$cp_hex" ]; then
    echo "vendor-fonts.sh: no codepoint for ti-$name in upstream CSS" >&2
    exit 1
  fi
  CODEPOINTS="${CODEPOINTS:+$CODEPOINTS,}$cp_hex"
  CSS_RULES="$CSS_RULES.ti-$name::before{content:\"\\\\$cp_hex\";}
"
  echo "  ti-$name -> U+$cp_hex"
done

python3 -m fontTools.subset "$WORK/package/dist/fonts/tabler-icons.woff2" \
  --unicodes="$CODEPOINTS" --flavor=woff2 --no-hinting --desubroutinize \
  --output-file="$OUT/tabler-icons-subset.woff2"

echo "  tabler-icons-subset.woff2 $(stat -c%s "$OUT/tabler-icons-subset.woff2") B"
echo
echo "vendor-fonts.sh: files written to static/fonts/."
echo "If an icon was added or a codepoint changed, update the .ti-*::before"
echo "rules at the bottom of static/fonts/fonts.css to match:"
echo
printf '%s' "$CSS_RULES"
