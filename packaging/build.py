#!/usr/bin/env python3
"""
packaging/build.py — bundle the ArtiSync Qt app with PyInstaller.

    pip install pyinstaller pillow PySide6 spotipy thefuzz mutagen
    (Pillow is only used here, to make the .ico / .icns icons)
    python packaging/build.py

Output (in packaging/dist/):
    Linux / Windows   ArtiSync/            folder with the ArtiSync executable
    macOS             ArtiSync.app

Only the files listed below go into the bundle. The source folder also holds
music_config.json (with Spotify credentials), so nothing is picked up by
pattern. Platform packaging (AppImage, Flatpak, installer, DMG) starts from
this output; see the other scripts in packaging/.
"""

import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "python source code"
BUILD = HERE / "build"
DIST = HERE / "dist"
ICON_PNG = SRC / "ArtiSync.png"

sys.path.insert(0, str(SRC))
from version import VERSION  # noqa: E402

# Shipped next to the code, at the same relative paths the app reads them from.
DATA = [
    (SRC / "gui" / "style.qss", "gui"),
    (ICON_PNG, "."),
]

# Standard-library and build-time modules the app never imports.
EXCLUDE = ["tkinter", "PIL"]


def make_icons():
    """ArtiSync.ico / ArtiSync.icns from the PNG (Pillow is a build-time
    dependency only)."""
    from PIL import Image
    BUILD.mkdir(parents=True, exist_ok=True)
    img = Image.open(ICON_PNG).convert("RGBA")
    ico = BUILD / "ArtiSync.ico"
    img.save(ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    icns = BUILD / "ArtiSync.icns"
    img.resize((1024, 1024), Image.LANCZOS).save(icns)
    return ico, icns


def main():
    import PyInstaller.__main__

    ico, icns = make_icons()
    sep = os.pathsep
    args = [
        str(SRC / "artisync.py"),
        "--name", "ArtiSync",
        "--noconfirm", "--clean",
        "--windowed", "--onedir",
        "--paths", str(SRC),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
    ]
    for src, dest in DATA:
        args += ["--add-data", f"{src}{sep}{dest}"]
    for mod in EXCLUDE:
        args += ["--exclude-module", mod]

    if sys.platform == "win32":
        args += ["--icon", str(ico)]
    elif sys.platform == "darwin":
        args += ["--icon", str(icns),
                 "--osx-bundle-identifier", "com.artisync.ArtiSync"]

    if DIST.exists():
        shutil.rmtree(DIST)
    PyInstaller.__main__.run(args)

    if sys.platform == "darwin":
        _set_mac_version(DIST / "ArtiSync.app")
        _prune(DIST / "ArtiSync.app")
    else:
        _prune(DIST / "ArtiSync")
    print(f"\nArtiSync {VERSION} bundled in {DIST}")


# Qt pieces PyInstaller collects that ArtiSync never uses. The QML/Quick
# stack is only needed by the virtual-keyboard input plugin, Qt PDF only by the
# PDF image plugin, and GTK only by the GTK3 platform theme (the app uses the
# Fusion style and Qt's own file dialog).
_UNUSED_QT = (
    "plugins/platforminputcontexts/libqtvirtualkeyboardplugin",
    "plugins/imageformats/libqpdf", "plugins/imageformats/qpdf",
    "plugins/platformthemes/libqgtk3",
    "translations",
    "lib/libQt6VirtualKeyboard", "lib/libQt6Quick", "lib/libQt6Qml",
    "lib/libQt6Pdf", "lib/QtVirtualKeyboard", "lib/QtQuick", "lib/QtQml",
    "lib/QtPdf",
)


def _prune(bundle):
    removed = 0
    for qt in bundle.rglob("Qt"):
        if not qt.is_dir() or qt.parent.name != "PySide6":
            continue
        for rel in _UNUSED_QT:
            for path in qt.glob(rel + "*"):
                removed += _size(path)
                shutil.rmtree(path) if path.is_dir() else path.unlink()
    if sys.platform.startswith("linux"):
        removed += _prune_orphan_libs(bundle / "_internal")
    print(f"Pruned {removed / 1e6:.0f} MB of unused libraries")


def _prune_orphan_libs(internal):
    """Delete bundled shared libraries that no remaining binary needs (the
    GTK stack once the GTK theme plugin is gone). PyInstaller only bundles
    libraries it found as dependencies, so an unreferenced one is dead weight.
    Repeats until nothing changes."""
    import subprocess
    removed = 0
    while True:
        elfs = [p for p in internal.rglob("*") if p.is_file() and not p.is_symlink()
                and (".so" in p.name or p.name.startswith("python"))]
        elfs.append(internal.parent / "ArtiSync")
        needed = set()
        for p in elfs:
            out = subprocess.run(["readelf", "-d", str(p)], capture_output=True,
                                 text=True).stdout
            needed.update(line.split("[", 1)[1].split("]", 1)[0]
                          for line in out.splitlines() if "(NEEDED)" in line)
        orphans = [p for p in internal.iterdir()
                   if p.is_file() and ".so" in p.name and p.name not in needed
                   and not p.name.startswith(("libpython", "python"))]
        if not orphans:
            return removed
        for p in orphans:
            removed += _size(p)
            p.unlink()


def _size(path):
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return path.stat().st_size


def _set_mac_version(app):
    import plistlib
    plist = app / "Contents" / "Info.plist"
    with open(plist, "rb") as f:
        info = plistlib.load(f)
    info.update({
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleDisplayName": "ArtiSync",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    })
    with open(plist, "wb") as f:
        plistlib.dump(info, f)


if __name__ == "__main__":
    main()
