#!/bin/bash
#
# Software License Agreement (MIT License)
#
# Author: Duke Fong <d@d-l.io>
#
# Build a portable package for Windows (x64, Windows 10 or later) on Linux: the embeddable
# python from python.org, the win_amd64 wheels of the dependencies, the tracked files of this
# repo and a .bat to start it. Unzip it anywhere and run cdpnp.bat, nothing to install.
#
# Usage: tools/build_win.sh            # -> dist/cdpnp-<version>-win64.zip
#        PY_VER=3.13.12 tools/build_win.sh
#
# The downloads are kept under dist/cache/, delete it to fetch them again.

set -e

PY_VER=${PY_VER:-3.14.8}
PY_TAG=$(echo "$PY_VER" | cut -d. -f1,2 | tr -d .)     # 3.14.8 -> 314
DEPS="websockets pyserial u-msgpack-python aiohttp opencv-python<5 scipy"   # opencv 4, what the vision code was written against

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

VER=$(grep -oP "VERSION\s*=\s*'\K[^']+" html/index.js)
NAME=cdpnp-$VER-win64
DIST=$ROOT/dist
CACHE=$DIST/cache
OUT=$DIST/$NAME
ZIP=$DIST/$NAME.zip

EMBED=python-$PY_VER-embed-amd64.zip
mkdir -p "$CACHE"
if [ ! -f "$CACHE/$EMBED" ]; then
    echo "download $EMBED"
    curl -fsSL -o "$CACHE/$EMBED.part" "https://www.python.org/ftp/python/$PY_VER/$EMBED"
    mv "$CACHE/$EMBED.part" "$CACHE/$EMBED"
fi

rm -rf "$OUT" "$ZIP"
mkdir -p "$OUT/python"
unzip -q "$CACHE/$EMBED" -d "$OUT/python"

# with a ._pth file the embeddable python takes sys.path from it alone, the directory of the
# script is not added either: list the app (one level up) and the site-packages here
cat > "$OUT/python/python$PY_TAG._pth" <<EOF
python$PY_TAG.zip
.
Lib\\site-packages
..
..\\pycdnet
import site
EOF

echo "fetch the wheels for cp$PY_TAG win_amd64: $DEPS"
python3 -m pip install --quiet --disable-pip-version-check --no-compile \
    --cache-dir "$CACHE/pip" --target "$OUT/python/Lib/site-packages" \
    --platform win_amd64 --python-version "$PY_VER" --implementation cp --abi "cp$PY_TAG" \
    --only-binary=:all: $DEPS
rm -rf "$OUT/python/Lib/site-packages/bin"
find "$OUT/python/Lib/site-packages" -maxdepth 1 -name "*.whl" -delete    # the scipy wheel leaves an empty file named after itself
find "$OUT/python/Lib/site-packages" -name __pycache__ -prune -exec rm -rf {} +

# the files of the repo (and of pycdnet) as tracked
{ git ls-files; git -C pycdnet ls-files | sed 's|^|pycdnet/|'; } |
    grep -vE '^tests/|^tools/build_win\.sh$|^pycdnet$|(^|/)\.git' |
    while read -r f; do [ -f "$f" ] && echo "$f"; done |
    tar -cf - -T - | tar -xf - -C "$OUT"
mkdir -p "$OUT/tmp"    # pnp_cv.py keeps the camera background and broken frames here

# cmd wants crlf
sed 's/$/\r/' > "$OUT/cdpnp.bat" <<EOF
@echo off
cd /d "%~dp0"
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 2; Start-Process 'http://localhost:8900'"
python\\python.exe pnp_main.py -d %*
pause
EOF

(cd "$DIST" && zip -qr9 "$NAME.zip" "$NAME")
echo "python $PY_VER, packages:"
ls "$OUT/python/Lib/site-packages" | grep -oP '.*(?=\.dist-info$)' | sed 's/^/  /'
echo "done: $ZIP ($(du -h "$ZIP" | cut -f1))"
