#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MANIFEST="$SCRIPT_DIR/flatpak/com.artisync.ArtiSync.yml"
BUILD_DIR="$PROJECT_ROOT/c++ compiled/flatpak_build"
REPO_DIR="$PROJECT_ROOT/c++ compiled/flatpak_repo"
STATE_DIR="$PROJECT_ROOT/c++ compiled/flatpak_state"
FINAL_DIR="$PROJECT_ROOT/Flatpak final result"

mkdir -p "$FINAL_DIR"

echo "=== Building Flatpak (build artifacts → 'c++ compiled/flatpak_*') ==="
flatpak-builder \
    --repo="$REPO_DIR" \
    --state-dir="$STATE_DIR" \
    --force-clean \
    --jobs="$(nproc)" \
    "$BUILD_DIR" \
    "$MANIFEST"

echo ""
echo "=== Exporting bundle → 'Flatpak final result/ArtiSync.flatpak' ==="
flatpak build-bundle \
    "$REPO_DIR" \
    "$FINAL_DIR/ArtiSync.flatpak" \
    com.artisync.ArtiSync

echo ""
echo "Done! Bundle is at: $FINAL_DIR/ArtiSync.flatpak"
echo "Install with: flatpak install --user '$FINAL_DIR/ArtiSync.flatpak'"
echo "Run with:     flatpak run com.artisync.ArtiSync"
