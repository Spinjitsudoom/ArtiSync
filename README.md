# Music Manager Ultimate

A cross-platform music library organiser that fetches metadata from **Spotify** and **MusicBrainz**, renames your files, writes embedded tags, downloads cover art, and optionally converts between audio formats — available as both a **Python** desktop app and a compiled **C++ / Qt6** application.

---

## Downloads

| Package | Platform | Description |
|---|---|---|
| `MusicManager.AppImage` | Linux (any) | Self-contained AppImage — download, `chmod +x`, run |
| `MusicManager.flatpak` | Linux (Flatpak) | Install via `flatpak install` |

See the [Releases](../../releases) section for the latest builds.

---

## Features

- **Dual metadata backends** — Spotify Web API (requires free developer credentials) or MusicBrainz (no credentials needed)
- **Artist & album search** — type a name, pick from results, select a release
- **Fuzzy file matching** — automatically maps local audio files to tracks using edit-distance scoring, even with messy filenames
- **Batch rename** — preview proposed changes before applying; full undo support
- **Tag writing** — embeds artist, album, title, year, genre, track number, disc number, and cover art into ID3v2 (MP3), Vorbis comments (FLAC/OGG), and MP4/M4A atoms
- **Cover art** — downloads the highest-resolution image available from Spotify's CDN or MusicBrainz Cover Art Archive
- **Audio conversion** — converts between MP3, FLAC, M4A, OGG, and WAV using FFmpeg; supports remux (lossless container swap) and transcoding with quality presets
- **9 colour themes** — Dark, Light, Midnight, Emerald, Amethyst, Crimson, Forest, Ocean, Slate
- **Persistent config** — Spotify credentials, last directory, theme, and conversion settings are saved between sessions

---

## Python Version

### Requirements

- Python 3.9+
- `customtkinter` — themed UI widgets
- `Pillow` — image display
- `spotipy` — Spotify Web API client
- `musicbrainzngs` — MusicBrainz client
- `thefuzz` — fuzzy string matching
- `mutagen` — audio tag writing
- FFmpeg on `PATH` (for audio conversion)

Install dependencies:

```bash
pip install customtkinter pillow spotipy musicbrainzngs thefuzz mutagen
```

### Running

```bash
cd python
python music_organizer.py
```

### Module overview

| File | Purpose |
|---|---|
| `music_organizer.py` | Main application window, UI logic, event wiring |
| `spotify_engine.py` | Spotify search, releases, tracks, metadata, cover art |
| `mb_engine.py` | MusicBrainz search, releases, tracks, metadata, cover art |
| `base_engine.py` | Shared file-matching logic used by both engines |
| `metadata_writer.py` | Writes ID3, Vorbis, and MP4 tags via Mutagen |
| `remux_engine.py` | FFmpeg wrapper for audio format conversion |
| `music_config.json` | Persisted user settings (auto-created on first run) |

---

## C++ / Qt6 Version

The `c++ test/` directory contains a full reimplementation in C++17 with Qt6 Widgets. It compiles to a standalone binary with the same feature set, built using CMake with FetchContent for dependencies.

### Build requirements

| Dependency | Notes |
|---|---|
| CMake ≥ 3.16 | Build system |
| C++17 compiler | GCC 10+, Clang 12+ |
| Qt 6 (Core, Gui, Widgets) | System package **or** sysroot |
| OpenSSL | For HTTPS via libcurl |
| libcurl | Auto-fetched if not found on system |
| TagLib | Auto-fetched if not found on system |
| nlohmann/json | Always auto-fetched (header-only) |

On Fedora/RHEL:
```bash
sudo dnf install cmake gcc-c++ qt6-qtbase-devel openssl-devel
```

On Ubuntu/Debian:
```bash
sudo apt install cmake g++ qt6-base-dev libssl-dev
```

### Build the binary

```bash
cd "c++ test"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
./build/MusicManager
```

### Build the AppImage

```bash
cd "c++ test"
bash build.sh
# Output: ../final result/MusicManager.AppImage
```

The script auto-downloads `linuxdeploy` and `appimagetool` on first run, compiles the app into `../c++ compiled/cmake_build/`, and packages the result.

### Build the Flatpak

Requires `flatpak-builder` and `org.kde.Sdk//6.10` installed:

```bash
flatpak install flathub org.kde.Sdk//6.10 org.kde.Platform//6.10
cd "c++ test"
bash flatpak_build.sh
# Output: ../Flatpak final result/MusicManager.flatpak
```

All intermediate build artifacts land in `../c++ compiled/flatpak_*/`.

### C++ module overview

| File | Purpose |
|---|---|
| `main.cpp` | Entry point — initialises QApplication, sets window icon and desktop name |
| `music_organizer.cpp/.h` | Main window, all UI panels, event slots, theme engine |
| `spotify_engine.cpp/.h` | Spotify Web API — artist search, releases, tracks, metadata, cover art |
| `mb_engine.cpp/.h` | MusicBrainz — same interface as SpotifyEngine, no credentials needed |
| `base_engine.cpp/.h` | Abstract base shared by both engines; fuzzy file-to-track matching |
| `metadata_writer.cpp/.h` | Writes tags using TagLib (ID3v2, Vorbis, MP4) |
| `remux_engine.cpp/.h` | FFmpeg subprocess wrapper; convert + batch convert + probe |
| `http_client.cpp/.h` | Thin libcurl wrapper for HTTP GET with JSON response handling |
| `fuzzy.cpp/.h` | Levenshtein / token-ratio fuzzy matching used by the matching engine |
| `types.h` | Shared data structures: `Track`, `Release`, `ReleaseMetadata`, `MatchResult`, `BatchResult` |
| `resources/resources.qrc` | Qt resource bundle (app icon) |
| `CMakeLists.txt` | Build definition; detects system libs, falls back to FetchContent |
| `build.sh` | One-shot AppImage build script |
| `flatpak_build.sh` | One-shot Flatpak build script |
| `flatpak/com.musicmanager.MusicManager.yml` | Flatpak manifest (KDE Platform 6.10) |

---

## Installing the AppImage

```bash
chmod +x MusicManager.AppImage
./MusicManager.AppImage
```

The AppImage uses system Qt6 libraries (required: `qt6-qtbase` and `qt6-qtbase-gui`). On Fedora:
```bash
sudo dnf install qt6-qtbase qt6-qtbase-gui
```

## Installing the Flatpak

```bash
flatpak install --user MusicManager.flatpak
flatpak run com.musicmanager.MusicManager
```

---

## Spotify API setup

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and create a free app
2. Copy the **Client ID** and **Client Secret**
3. In the app: **File → Settings**, paste both values, click Save
4. The engine reconnects immediately — a green status dot confirms success

MusicBrainz requires no credentials and is available as a fallback from the same Settings dialog.

---

## Audio conversion

The conversion dialog (**File → Convert**) supports:

| Input | Output |
|---|---|
| MP3, FLAC, M4A, AAC, MP4, OGG, WAV, OPUS, WMA | MP3, FLAC, M4A, OGG, WAV |

Quality presets for lossy output:

| Preset | MP3 | AAC/M4A |
|---|---|---|
| Low | 128 kbps | 128 kbps |
| Medium *(default)* | 192 kbps | 192 kbps |
| High | 320 kbps | 256 kbps |
| Best | VBR V0 | 256 kbps |

AAC↔M4A and MP4→M4A are remuxed (stream copy, no quality loss). All other pairs are transcoded. Cover art is preserved where the container supports it.

---

## License

MIT
