#!/usr/bin/env bash
# Build ArtiSync.flatpak (a single-file bundle) with flatpak-builder.
#
#   flatpak install flathub org.freedesktop.Platform//25.08 org.freedesktop.Sdk//25.08
#   bash packaging/flatpak/build_flatpak.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(dirname "$HERE")"
ROOT="$(dirname "$PKG")"
OUT_DIR="${OUT_DIR:-$ROOT/final result}"
WORK="$PKG/build/flatpak"
ID=com.artisync.ArtiSync

mkdir -p "$WORK" "$OUT_DIR"
flatpak-builder --force-clean --jobs="$(nproc)" \
    --state-dir="$WORK/state" --repo="$WORK/repo" \
    "$WORK/build" "$HERE/$ID.yml"
flatpak build-bundle "$WORK/repo" "$OUT_DIR/ArtiSync.flatpak" "$ID"
echo "Flatpak: $OUT_DIR/ArtiSync.flatpak"
echo "Install: flatpak install --user '$OUT_DIR/ArtiSync.flatpak'"
