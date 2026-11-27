#!/usr/bin/env bash
# Build ArtiSync-<version>-x86_64.AppImage from the PyInstaller bundle.
#
#   PYTHON=/path/to/python bash packaging/linux/build_appimage.sh
#
# PYTHON needs PyInstaller, Pillow and the app's dependencies. appimagetool
# must be on PATH (or set APPIMAGETOOL). For a release, build on the oldest
# distro you want to support (CI uses Ubuntu 22.04): the AppImage only runs
# on systems whose glibc is at least as new as the build machine's.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(dirname "$HERE")"
ROOT="$(dirname "$PKG")"
PYTHON="${PYTHON:-python3}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
OUT_DIR="${OUT_DIR:-$ROOT/final result}"
ID=com.artisync.ArtiSync

VERSION="$("$PYTHON" -c "import sys; sys.path.insert(0, '$ROOT/python source code'); from version import VERSION; print(VERSION)")"

"$PYTHON" "$PKG/build.py"

APPDIR="$PKG/build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/512x512/apps" "$APPDIR/usr/share/metainfo"
cp -a "$PKG/dist/ArtiSync" "$APPDIR/usr/lib/ArtiSync"

cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/ArtiSync/ArtiSync" "$@"
RUN
chmod +x "$APPDIR/AppRun"

cp "$HERE/$ID.desktop" "$APPDIR/$ID.desktop"
cp "$HERE/$ID.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/python source code/ArtiSync.png" "$APPDIR/$ID.png"
cp "$ROOT/python source code/ArtiSync.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/$ID.png"
cp "$HERE/$ID.metainfo.xml" "$APPDIR/usr/share/metainfo/$ID.appdata.xml"

mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/ArtiSync-$VERSION-x86_64.AppImage"
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUT"
echo "AppImage: $OUT"
