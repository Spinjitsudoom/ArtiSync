# Music Manager Ultimate

A cross-platform music library organiser that fetches metadata from **Spotify**, renames your files, writes embedded tags, downloads cover art, and optionally converts between audio formats — available as both a **Python** desktop app and a compiled **C++ / Qt6** application.

---

## Downloads

| Package | Platform | Description |
|---|---|---|
| `MusicManager.AppImage` | Linux (any) | Self-contained AppImage — download, `chmod +x`, run |
| `MusicManager.flatpak` | Linux (Flatpak) | Install via `flatpak install` |

See the [Releases](../../releases) section for the latest builds.

---

## How It Works

1. **Browse** — point the app at a folder containing artist sub-folders (e.g. `/music/Avenged Sevenfold/`)
2. **Auto-detect** — the app searches Spotify for the artist automatically and populates the releases sidebar with album art thumbnails
3. **Select a release** — click any album or single; the app fetches its full track list and cover art
4. **Match** — the fuzzy matcher maps your local audio files to the correct track names using edit-distance scoring, even if the filenames are messy or incomplete
5. **Preview** — the Preview tab shows exactly which files will be renamed and what their new names will be, with a per-track confidence score
6. **Execute** — click **Execute Rename + Tag** to rename files, write all embedded tags, and embed cover art in one step
7. **Undo** — every rename operation can be fully reversed with the **Undo** button

---

## UI Features

### Toolbar
- **Browse** — opens a folder picker; the selected path is remembered between sessions
- **Artist / Album dropdowns** — manually override the auto-detected artist or album
- **Batch** — processes all artist sub-folders in the root directory automatically

### Spotify Releases Sidebar
- Lists every release found for the detected artist (albums, singles, EPs)
- Each row shows a **64×64 album art thumbnail** that loads asynchronously in the background
- Clicking a release loads its track list and updates the art panel on the right

### Preview Tab
- Shows a row for each track with the current filename → proposed new filename and a match confidence percentage
- Green rows = high confidence match; amber/red = low confidence or unmatched
- Nothing is changed until you click Execute

### Log Tab
- Records every rename, tag-write, and error message from the current session

### Art & Metadata Panel (right side)
- Displays the full cover art for the selected release
- Shows Artist, Album, Year, and Genre
- **Art / Tags / Genre** chip toggles control which data is written during Execute
- **Fetch Artwork** manually re-downloads cover art for the selected release

### Status Bar
- **✓ Artist** — shows the auto-detected artist name (green = matched)
- **Matched / Missing** — live count of matched and unmatched files
- **Spotify** — connection status indicator

### File → Settings
- Enter your Spotify **Client ID** and **Client Secret**
- Switch between **9 colour themes**: Dark, Light, Midnight, Emerald, Amethyst, Crimson, Forest, Ocean, Slate
- Enable **Auto-convert** to automatically remux or transcode files after tagging

### File → Convert
- Convert individual files or entire folders between MP3, FLAC, M4A, OGG, and WAV
- Select quality preset (Low / Medium / High / Best)
- Option to delete source files after conversion

---

## Installing the AppImage

The AppImage requires Qt6 runtime libraries on the host system.

On Fedora/RHEL:
```bash
sudo dnf install qt6-qtbase qt6-qtbase-gui
```

On Ubuntu/Debian:
```bash
sudo apt install qt6-base qt6-base-gui
```

Then run:
```bash
chmod +x MusicManager.AppImage
./MusicManager.AppImage
```

## Installing the Flatpak

```bash
flatpak install --user MusicManager.flatpak
flatpak run com.musicmanager.MusicManager
```

---

## Spotify API Setup

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and create a free app
2. Copy the **Client ID** and **Client Secret**
3. In the app: **File → Settings**, paste both values, click **Save**
4. The engine reconnects immediately — a green status dot confirms success

---

## Audio Conversion

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

AAC↔M4A and MP4→M4A are remuxed (stream copy, no quality loss). All other pairs are transcoded via FFmpeg. Cover art is preserved where the container supports it.

FFmpeg must be on your `PATH` for conversion to work.

---

## Python Version

### Requirements

- Python 3.9+
- `customtkinter` — themed UI widgets
- `Pillow` — image display and thumbnail rendering
- `spotipy` — Spotify Web API client
- `thefuzz` — fuzzy string matching
- `mutagen` — audio tag writing
- FFmpeg on `PATH` (for audio conversion)

Install dependencies:

```bash
pip install customtkinter pillow spotipy thefuzz mutagen
```

### Running

```bash
cd "python source code"
python music_organizer.py
```

### Module overview

| File | Purpose |
|---|---|
| `music_organizer.py` | Main application window, UI logic, event wiring |
| `spotify_engine.py` | Spotify search, releases, tracks, metadata, cover art |
| `base_engine.py` | Shared file-matching logic used by both engines |
| `metadata_writer.py` | Writes ID3, Vorbis, and MP4 tags via Mutagen |
| `remux_engine.py` | FFmpeg wrapper for audio format conversion |

---

## C++ / Qt6 Version

The `c++ source code/` directory contains a full reimplementation in C++17 with Qt6 Widgets. It compiles to a standalone binary with the same feature set, built using CMake with FetchContent for dependencies.

### Build requirements

| Dependency | Notes |
|---|---|
| CMake ≥ 3.16 | Build system |
| C++17 compiler | GCC 10+, Clang 12+ |
| Qt 6 (Core, Gui, Widgets) | System package |
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
cd "c++ source code"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
./build/MusicManager
```

### Build the AppImage

Requires an ostree-based Fedora system (Silverblue / Kinoite) with Qt6 devel headers in the sysroot. On standard Fedora, use the binary build above instead.

```bash
cd "c++ source code"
bash build.sh
# Output: ../final result/MusicManager.AppImage
```

### Build the Flatpak

Requires `flatpak-builder` and `org.kde.Sdk//6.10`:

```bash
flatpak install flathub org.kde.Sdk//6.10 org.kde.Platform//6.10
cd "c++ source code"
bash flatpak_build.sh
# Output: ../Flatpak final result/MusicManager.flatpak
```

### C++ module overview

| File | Purpose |
|---|---|
| `main.cpp` | Entry point — initialises QApplication, sets window icon and desktop name |
| `music_organizer.cpp/.h` | Main window, all UI panels, event slots, theme engine |
| `spotify_engine.cpp/.h` | Spotify Web API — artist search, releases, tracks, metadata, cover art |
| `base_engine.cpp/.h` | Shared fuzzy file-to-track matching logic |
| `metadata_writer.cpp/.h` | Writes tags using TagLib (ID3v2, Vorbis, MP4) |
| `remux_engine.cpp/.h` | FFmpeg subprocess wrapper; convert + batch convert + probe |
| `http_client.cpp/.h` | Thin libcurl wrapper for HTTP GET with JSON and binary responses |
| `fuzzy.cpp/.h` | Levenshtein / token-ratio fuzzy matching |
| `types.h` | Shared data structures: `Track`, `Release`, `ReleaseMetadata`, `MatchResult`, `BatchResult` |
| `resources/resources.qrc` | Qt resource bundle (app icon) |
| `CMakeLists.txt` | Build definition; detects system libs, falls back to FetchContent |
| `build.sh` | One-shot AppImage build script |
| `flatpak_build.sh` | One-shot Flatpak build script |
| `flatpak/com.musicmanager.MusicManager.yml` | Flatpak manifest (KDE Platform 6.10) |

---

## License

MIT
