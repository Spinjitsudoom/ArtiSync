#!/usr/bin/env bash
# Build ArtiSync.app, a zipped copy of it, and a drag-to-Applications DMG.
# macOS only (uses hdiutil and ditto).
#
#   PYTHON=python3 bash packaging/macos/build_dmg.sh
#
# The app is not code-signed or notarized, so on first launch macOS asks the
# user to confirm (right-click → Open, or System Settings → Privacy &
# Security → Open Anyway).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(dirname "$HERE")"
PYTHON="${PYTHON:-python3}"
OUT_DIR="${OUT_DIR:-$PKG/out}"

"$PYTHON" "$PKG/build.py"

mkdir -p "$OUT_DIR"
APP="$PKG/dist/ArtiSync.app"

# Ad-hoc signature: required for Apple Silicon to run the bundle at all.
codesign --force --deep --sign - "$APP"

ditto -c -k --keepParent "$APP" "$OUT_DIR/ArtiSync-macOS-app.zip"

STAGE="$PKG/build/dmg"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$OUT_DIR/ArtiSync-macOS.dmg"
hdiutil create -volname ArtiSync -srcfolder "$STAGE" -ov -format UDZO \
    "$OUT_DIR/ArtiSync-macOS.dmg"

echo "App: $OUT_DIR/ArtiSync-macOS-app.zip"
echo "DMG: $OUT_DIR/ArtiSync-macOS.dmg"
