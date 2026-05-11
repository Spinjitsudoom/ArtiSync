# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ArtiSync is a desktop app that fetches metadata from Spotify, renames audio files, writes embedded tags, and downloads cover art. It exists in two parallel implementations:
- **Python** (`python source code/`) — CustomTkinter GUI, primary development target
- **C++/Qt6** (`c++ source code/`) — full feature-parity reimplementation, compiled to AppImage/Flatpak

The two codebases mirror each other module-for-module. When changing behavior in one, consider whether the other needs a matching change.

---

## Python Version

### Running

```bash
cd "python source code"
python music_organizer.py
```

### Dependencies

```bash
pip install customtkinter pillow spotipy thefuzz mutagen
# FFmpeg must also be on PATH for audio conversion
```

### Module Responsibilities

| File | Role |
|---|---|
| `music_organizer.py` | Main window, UI layout, event slots, theme system |
| `spotify_engine.py` | Spotify Web API — OAuth2 client-credentials, search, releases, tracks, cover art |
| `base_engine.py` | Fuzzy file→track matching shared by all engines |
| `metadata_writer.py` | Tag writes via Mutagen (ID3v2, Vorbis, MP4); batch-parallelised with `ThreadPoolExecutor` |
| `remux_engine.py` | FFmpeg subprocess wrapper for conversion and probing |

There is no test suite; note that clearly when asked to run tests.

---

## C++ / Qt6 Version

### Build the binary

```bash
cd "c++ source code"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
./build/ArtiSync
```

**System dependencies (Fedora/RHEL):**
```bash
sudo dnf install cmake gcc-c++ qt6-qtbase-devel openssl-devel
```

**System dependencies (Ubuntu/Debian):**
```bash
sudo apt install cmake g++ qt6-base-dev libssl-dev
```

libcurl, TagLib, and nlohmann/json are auto-fetched via `FetchContent` if not found on the system.

### Build the AppImage

```bash
cd "c++ source code"
bash build.sh
# Output: ../final result/ArtiSync.AppImage
```

Requires an ostree-based Fedora system (Silverblue/Kinoite/Bazzite). On Bazzite, launch with `APPIMAGE_EXTRACT_AND_RUN=1` — FUSE is not available.

### Build the Flatpak

```bash
flatpak install flathub org.kde.Sdk//6.10 org.kde.Platform//6.10
cd "c++ source code"
bash flatpak_build.sh
# Output: ../Flatpak final result/ArtiSync.flatpak
```

### CI (GitHub Actions)

`.github/workflows/build.yml` builds Windows (MSVC + windeployqt) and macOS (clang + macdeployqt) on tag pushes (`v*`) or manual dispatch. It publishes `.zip` and `.dmg` to GitHub Releases.

---

## Architecture

### UI Layout (both versions)

Three-column layout owned by `ArtiSyncApp` / `ArtiSync`:
- **Left sidebar** — Spotify releases for the detected artist; asynchronously loads 64×64 thumbnails
- **Center** — Preview tab (filename → proposed rename with confidence %) and Log tab
- **Right panel** — Full cover art, metadata fields, chip toggles for Art / Tags / Genre

### Engine Interface

`self.engine` is swappable; all engines must expose:
```
search_artists(query)
get_releases(artist_id)
get_tracks(release_id)
get_release_metadata(release_id)
get_cover_art_bytes(release_id)
```

### Fuzzy Matching (key thresholds)

- `TRACK_MATCH_THRESHOLD = 30` — intentionally low to allow messy filenames
- `ALBUM_MATCH_THRESHOLD = 80` — used for batch folder→release matching
- Featured-artist logic: if a track title already contains a feat/ft/with marker, featured artists are not appended to the filename (prevents double-tagging)

### Compound Extensions

Files named `song.audio aac` are normalised to `.aac` by `_normalize_ext()` in both `metadata_writer` and `remux_engine` before any read/write operation.

### Tag Operations (C++)

TagLib 2.x API — use `removeFields` (not `removeField`). MP4 item keys use literal `©` characters: `©nam`, `©ART`, `©alb`, `©day`, `©gen`.

---

## Flatpak Permissions Policy

Use narrow filesystem permissions — the app can rename, tag, convert, and delete files:
- **Baseline**: `--filesystem=xdg-music:rw`
- Add `--filesystem=xdg-download:rw`, `/run/media:rw`, or `/mnt:rw` only when needed
- Keep `--share=network` for Spotify metadata and cover art
- Keep standard Qt GUI permissions: `wayland`, `fallback-x11`, `ipc`, `dri`
- **Never** grant `--filesystem=home`, `--filesystem=host`, `--device=all`, or broad bus sockets by default
- Host `/usr/bin/ffmpeg` is **not** visible inside the sandbox — bundle FFmpeg or use a Flatpak-compatible runtime dependency

---

## Key Files for AI Context

- `rules/recall.md` — AI-facing architecture and behavior summary; **update it after every code or design change**
- `rules/copilot-instructions.md` — agent style guide and repo conventions
- `handoff.md` — updated by `/handoff` command; project state summary for AI handovers
- `music_config.json` — user settings (Spotify credentials, theme, last-used folder)
