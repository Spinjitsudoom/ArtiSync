# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ArtiSync is a desktop app that matches the audio files in album folders to releases on Deezer, MusicBrainz or Spotify, renames them, writes embedded tags and cover art, and converts between audio formats. It is a Python / PySide6 (Qt) app in `python source code/`, packaged for Windows, macOS and Linux from `packaging/`.

The repository holds only the current app. The 2.x C++ app and the CustomTkinter GUI were removed in November 2026, so don't reintroduce them.

---

## Running

```bash
./run.sh            # first run creates ~/.local/share/ArtiSync/venv and installs deps
./run.sh --update   # upgrade the deps
```

Or manually:

```bash
pip install PySide6 spotipy thefuzz mutagen
cd "python source code" && python artisync.py
```

FFmpeg on `PATH` is needed for Convert. A copy shipped next to a packaged app is preferred (`remux_engine._find_tool`).

There is no test suite; say so clearly when asked to run tests.

---

## Module Responsibilities

| File | Role |
|---|---|
| `artisync.py` | Entry point. Ends with `os._exit()` after cleanup to avoid a PySide6 shutdown crash |
| `version.py` | `VERSION` (window title, User-Agent, packaging, release tag check) |
| `session.py` | GUI-free core: library scan, per-album status store, folder→release resolution (`ReleaseResolver`), `AlbumPreview` (matching + manual pairing), `execute()` / `undo()`. The GUI only calls into this |
| `app_config.py` | `AppConfig`: settings JSON in `~/Documents/ArtiSync/music_config.json` |
| `gui/` | Qt widgets: `main_window`, `library_panel`, `releases_panel`, `album_view`, `details_panel`, `dialogs`, `update_dialog`, `widgets` (incl. the `run_async` worker helper), `theme.py` + `style.qss` (stylesheet with `@token` placeholders) |
| `deezer_engine.py` | Deezer engine (default source; no credentials). Public API, 50 requests / 5 s; featured artists come from per-track lookups; 1000 px covers |
| `mb_engine.py` | MusicBrainz engine (no credentials). Releases are release groups; one edition supplies the tracks. ~1 request/s; art from the Cover Art Archive |
| `spotify_engine.py` | Spotify Web API (client credentials). 10 results per request; 429s fail fast via `_RateLimitGuard` |
| `base_engine.py` | Fuzzy file→track matching shared by all engines, audio-file listing, file naming |
| `metadata_writer.py` | Tag writes via Mutagen (ID3v2, Vorbis, MP4); batch-parallelised with `ThreadPoolExecutor` |
| `remux_engine.py` | FFmpeg subprocess wrapper for conversion and probing |
| `file_ops.py` | `safe_rename_batch`: collision-safe two-phase renames used by Execute and Undo |
| `updater.py` | GUI-free update check (GitHub `releases/latest`) and self-update per install kind; downloads are checked against GitHub's size and SHA-256 digest |

---

## Packaging (`packaging/`)

| Script | Output |
|---|---|
| `build.py` | PyInstaller bundle in `packaging/dist/` (`ArtiSync/` or `ArtiSync.app`). Adds only listed data files (never `music_config.json`) and prunes unused Qt (QML/Quick, PDF, GTK theme, translations) |
| `linux/build_appimage.sh` | `ArtiSync-<version>-x86_64.AppImage` (needs `appimagetool`; set `PYTHON` to an env with PyInstaller) |
| `flatpak/build_flatpak.sh` | `ArtiSync.flatpak`: runs from source on `org.freedesktop.Platform//25.08`, deps pip-installed at build time from `requirements.txt`; the runtime's own `ffmpeg` handles Convert |
| `windows/ArtiSync.iss` | Inno Setup installer (`iscc /DAppVersion=… `) |
| `macos/build_dmg.sh` | `ArtiSync-macOS.dmg` and `ArtiSync-macOS-app.zip` (ad-hoc signed, not notarized) |
| `requirements.txt` | Pinned runtime deps for packaged builds (`PySide6_Essentials`, not full PySide6) |

Local Linux builds write to `final result/`. Windows and macOS can only be built in CI.

### In-app updates

`updater.install_kind()` decides how an update is applied; the asset names it downloads are the fixed release names below, so don't rename them:
- `windows-installer` (an `unins000.exe` sits next to the exe): runs the new `ArtiSync-Setup.exe` with `/SILENT`; the `.iss` `[Run]` entry with `Check: WizardSilent` reopens the app
- `windows-portable`: unzips `ArtiSync-Portable.zip`; a PowerShell script swaps `ArtiSync.exe` and `_internal` after the app exits, then relaunches
- `macos`: unzips `ArtiSync-macOS-app.zip` with `ditto`; a shell script swaps the `.app` after exit and runs `open`
- `appimage` (`$APPIMAGE` set): downloads beside it, renames over it, relaunches after exit
- `flatpak`: the sandbox can't reinstall itself, so the bundle is saved to Downloads and opened (software centre)
- `source` / `bundle`: links to the release page

If the install location isn't writable, the update goes to Downloads instead (`MANUAL_ASSETS`). The check runs 3 s after startup when `AppConfig.check_updates` is on; `skip_version` hides one release.

### CI (GitHub Actions)

`.github/workflows/build.yml` builds all six downloads (Setup.exe, Portable.zip, macOS DMG + app zip, AppImage on Ubuntu 22.04, Flatpak). Manual dispatch uploads them as artifacts. A `v*` tag also publishes a GitHub Release; the tag must equal `v` + `version.py`'s `VERSION`. Asset names are fixed because `index.html` links to `releases/latest/download/<name>`.

---

## Architecture

### UI Layout

Four columns in `MainWindow`: **Library** (artist/album tree with status), **Releases** (the artist's releases with thumbnails, a filter box, and a search across the whole source), **Album** (track rows with match confidence, manual pairing, Log tab), **Details** (cover art, metadata, Write-to-files chips, Track numbers toggle). An action bar at the bottom holds Undo, Convert, Refresh, Previous, Next and Rename & Tag.

All network and disk work runs off the GUI thread via `run_async`. `MainWindow._busy` blocks overlapping work; requests made while busy are queued (`_pending_album`, `_refresh_again`).

### Engine Interface

`self.engine` is swappable; all engines expose:
```
name
search_artists(query)
get_releases(artist_id)
get_tracks(release_id)
get_release_metadata(release_id)
get_cover_art_bytes(release_id)
search_releases(query)
get_release(release_id)
```
`get_thumbnail_bytes(id)` and `close()` are optional. `AppConfig.metadata_source` picks the engine: `"deezer"` (default), `"musicbrainz"` or `"spotify"`. Keyless sources are listed in `OPEN_SOURCES` in `gui/main_window.py`. Release overrides are stored per source.

### Fuzzy Matching (key thresholds)

- `TRACK_MATCH_THRESHOLD = 30`: intentionally low to allow messy filenames. Assignment is global best-first, not file order
- `ARTIST_MATCH_THRESHOLD = 70` (token_sort_ratio): an artist below this is treated as not found
- Featured-artist logic: if a track title already contains a feat/ft/with marker, featured artists are not appended to the filename (prevents double-tagging)
- Track numbers in names (`01 - Title.mp3`, `1-01 - …` multi-disc) when `AppConfig.track_numbers` is on

### Compound Extensions

Files named `song.audio aac` are normalised to `.aac` (`base_engine.normalize_ext`) before any read/write operation.

---

## Flatpak Permissions Policy

Keep filesystem access narrow; the app can rename, tag, convert and delete files:
- `xdg-music`, `xdg-download`: music folders
- `xdg-documents`: settings live in `~/Documents/ArtiSync`
- `/run/media`, `/mnt`, `/var/mnt`: removable drives and network shares (`/var/mnt` is where Fedora Atomic / Bazzite mounts them)
- `--share=network` for metadata and cover art; Qt GUI basics: `wayland`, `fallback-x11`, `ipc`, `dri`
- **Never** grant `--filesystem=home`, `--filesystem=host`, `--device=all`, or broad bus sockets

---

## Key Files for AI Context

- `rules/recall.md`: AI-facing architecture and behavior summary; **update it after every code or design change**
- `rules/copilot-instructions.md`: agent style guide and repo conventions
- `handoff.md`: updated by the `/handoff` command; project state summary for AI handovers
- `~/Documents/ArtiSync/music_config.json`: user settings (source, Spotify credentials, theme, library folder)
