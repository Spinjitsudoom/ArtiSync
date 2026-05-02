#!/usr/bin/env bash
set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOURCE_DIR="$SCRIPT_DIR"
BUILD_DIR="$PROJECT_ROOT/c++ compiled"
FINAL_DIR="$PROJECT_ROOT/final result"
CMAKE_BUILD="$BUILD_DIR/cmake_build"
APPDIR="$BUILD_DIR/AppDir"
TOOLS_DIR="$BUILD_DIR/.appimage_tools"

# ── Locate Qt6 in ostree sysroot ──────────────────────────────────────────────
SYSROOT_DEPLOY="/sysroot/ostree/deploy/default/deploy"
if [ -d "$SYSROOT_DEPLOY" ]; then
    SYSROOT_HASH=$(ls "$SYSROOT_DEPLOY" | grep -v '\.origin' | head -1)
    SYSROOT="$SYSROOT_DEPLOY/$SYSROOT_HASH/usr"
    echo "Using sysroot Qt6 from: $SYSROOT"
else
    echo "ERROR: ostree sysroot not found at $SYSROOT_DEPLOY"
    exit 1
fi

# ── Create output directories ─────────────────────────────────────────────────
mkdir -p "$CMAKE_BUILD" "$FINAL_DIR" "$TOOLS_DIR"

# ── Configure ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Configuring (this will fetch curl, taglib, nlohmann_json from GitHub) ==="
cmake -S "$SOURCE_DIR" -B "$CMAKE_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="$SYSROOT" \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_VERBOSE_MAKEFILE=OFF

# ── Build ─────────────────────────────────────────────────────────────────────
echo ""
echo "=== Building ==="
cmake --build "$CMAKE_BUILD" -j"$(nproc)"

# ── Download appimagetool if needed ───────────────────────────────────────────
APPIMAGETOOL="$TOOLS_DIR/appimagetool-x86_64.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    echo "Downloading appimagetool..."
    wget -q --show-progress -O "$APPIMAGETOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

# ── Build minimal AppDir (binary + bundled imageformats; uses system Qt6) ─────
# Bundling Qt6 from the sysroot causes init crashes on Fedora Atomic due to
# HWCAPS library variants. Qt6 is used at runtime; only imageformats plugins
# are bundled so JPEG cover art works without depending on a specific system path.
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/plugins/imageformats"

cp "$CMAKE_BUILD/MusicManager" "$APPDIR/usr/bin/"

# Bundle the JPEG imageformats plugin (libqjpeg.so depends only on system
# Qt6 libs + libjpeg, which are guaranteed on any Qt6-capable system)
SYSTEM_IMAGEFORMATS="/usr/lib64/qt6/plugins/imageformats"
for plugin in libqjpeg.so libqgif.so libqwebp.so libqsvg.so; do
    [ -f "$SYSTEM_IMAGEFORMATS/$plugin" ] && \
        cp "$SYSTEM_IMAGEFORMATS/$plugin" "$APPDIR/usr/plugins/imageformats/"
done

cp "$SOURCE_DIR/resources/MusicManager.png" \
   "$APPDIR/com.musicmanager.MusicManager.png"

cat > "$APPDIR/com.musicmanager.MusicManager.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Music Manager Ultimate
Comment=Organize and tag your music library
Exec=MusicManager
Icon=com.musicmanager.MusicManager
Categories=AudioVideo;Audio;Music;
Terminal=false
StartupWMClass=MusicManager
DESKTOP

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
SELF="$(readlink -f "$0")"
HERE="${SELF%/*}"

# Bundled imageformats plugins + system fallback for platform/other plugins
export QT_PLUGIN_PATH="$HERE/usr/plugins:/usr/lib64/qt6/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH=/usr/lib64/qt6/plugins/platforms

exec "$HERE/usr/bin/MusicManager" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ── Package AppImage ──────────────────────────────────────────────────────────
echo ""
echo "=== Packaging AppImage ==="
cd "$BUILD_DIR"
"$APPIMAGETOOL" "$APPDIR" "$BUILD_DIR/MusicManager-x86_64.AppImage" 2>&1

# ── Move to final result ──────────────────────────────────────────────────────
echo ""
echo "=== Moving AppImage to 'final result' ==="
mv "$BUILD_DIR/MusicManager-x86_64.AppImage" "$FINAL_DIR/MusicManager.AppImage"
chmod +x "$FINAL_DIR/MusicManager.AppImage"
echo ""
echo "Done! AppImage is at: $FINAL_DIR/MusicManager.AppImage"
