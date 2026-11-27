# ArtiSync

A desktop music-library organiser for Windows, macOS and Linux. Point it at a folder of artist folders and it matches each album's files to the real release on **Deezer**, **MusicBrainz** or **Spotify**. It then renames the files, writes tags and cover art, and can convert between audio formats.

**[Website and interactive demo →](https://spinjitsudoom.github.io/my-portfolio/artisync.html)**

---

## Downloads

Get the latest builds from [Releases](../../releases/latest).

| File | Platform | Notes |
|---|---|---|
| `ArtiSync-Setup.exe` | Windows 10/11 | Installer with Start Menu entry and optional desktop shortcut |
| `ArtiSync-Portable.zip` | Windows 10/11 | Extract and run `ArtiSync\ArtiSync.exe`, no install |
| `ArtiSync-macOS.dmg` | macOS 11+ (Apple Silicon) | Drag ArtiSync to Applications |
| `ArtiSync-macOS-app.zip` | macOS 11+ (Apple Silicon) | The app on its own |
| `ArtiSync.AppImage` | Linux (x86_64) | `chmod +x ArtiSync.AppImage` and run |
| `ArtiSync.flatpak` | Linux (Flatpak) | `flatpak install --user ArtiSync.flatpak` |

**macOS:** the app isn't notarized by Apple, so the first launch is blocked. Right-click ArtiSync → **Open**, or allow it under System Settings → Privacy & Security.

**Converting audio** needs [FFmpeg](https://ffmpeg.org/download.html) on your `PATH` (the Flatpak includes it).

---

## How it works

1. **Choose your music folder**, the one that holds your artist folders (`Music/Three Days Grace/Alienation (2025)/…`). Everything else is automatic.
2. **Library** lists every artist and album with its status: not opened yet, needs attention, or done. ArtiSync opens the first unfinished album.
3. **Matching**: the album folder is matched to the right release, and each file to a track, even with messy names (`Track 3 - mayday.mp3`). Every track shows a confidence score.
4. **Fix anything by hand**: pick a different release from the **Releases** column (or search for one), and use **Change** / **Assign to** to pair files and tracks yourself.
5. **Rename & Tag** renames the files and writes title, artist, album, year, genre, track numbers and cover art in one go. **Undo** reverses it.
6. **Next album** (Ctrl+→) moves on through the library.

Renames never overwrite another file, and Undo restores the original names exactly.

## Features

- **Three metadata sources** (Settings → *Look up albums on*):
  - **Deezer**: fast, no account needed (default)
  - **MusicBrainz**: no account needed, lists every edition, slower
  - **Spotify**: needs a free developer app (see below)
- **Releases column**: the artist's albums, singles and EPs with artwork. Type to filter it, or press Enter to search the whole source for albums filed under another artist.
- **File names**: `01 - Title.mp3` with track numbers (or `1-01 - …` on multi-disc albums), or just `Title.mp3`. Toggle under *File names*.
- **Write to files**: choose whether to write artwork, tags and genre.
- **Convert**: MP3, FLAC, M4A, OGG and WAV, optionally before every rename.
- **Updates**: ArtiSync checks GitHub for a new version when it starts (turn this off in Settings) and can download and install it in one click, then reopens. The Flatpak saves the new version to Downloads for your software centre to install. Every download is checked against the release's SHA-256 checksum.
- **9 colour themes**: Dark, Light, Midnight, Emerald, Amethyst, Crimson, Forest, Ocean, Slate.
- **Keyboard shortcuts**: Ctrl+→ / Ctrl+← next/previous album, Ctrl+Enter Rename & Tag, Ctrl+Z Undo, F5 Refresh, Ctrl+F filter library, Ctrl+Shift+F search releases, Ctrl+O choose folder, Ctrl+, Settings.

## Spotify setup (optional)

1. Create a free app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Copy its **Client ID** and **Client secret**.
3. In ArtiSync open **Settings**, choose **Spotify**, paste both, and **Save**.

Spotify limits how many requests a developer app can make. If it pauses yours, ArtiSync says how long for and offers to switch to Deezer.

## Audio conversion

| Input | Output |
|---|---|
| MP3, FLAC, M4A, AAC, MP4, OGG, WAV, OPUS, WMA | MP3, FLAC, M4A, OGG, WAV |

| Quality | MP3 | AAC / M4A |
|---|---|---|
| Low | 128 kbps | 128 kbps |
| Medium | 192 kbps | 192 kbps |
| High | 320 kbps | 256 kbps |
| Best | VBR V0 | 256 kbps |

AAC/MP4 → M4A is a lossless container change; everything else is re-encoded with FFmpeg. Cover art is kept where the format supports it. Convert never overwrites an existing file.

---

## Running from source

```bash
./run.sh
```

The first run creates a Python environment in `~/.local/share/ArtiSync/venv` and installs PySide6, spotipy, thefuzz and mutagen; later runs start straight away. `./run.sh --update` upgrades them. Python 3.10 or newer is required.

## Building

| Platform | Command | Output |
|---|---|---|
| Linux AppImage | `PYTHON=python3 bash packaging/linux/build_appimage.sh` | `final result/ArtiSync-<version>-x86_64.AppImage` |
| Linux Flatpak | `bash packaging/flatpak/build_flatpak.sh` | `final result/ArtiSync.flatpak` |
| macOS | `bash packaging/macos/build_dmg.sh` | `packaging/out/ArtiSync-macOS.dmg` |
| Windows | `python packaging\build.py` then `iscc /DAppVersion=<version> packaging\windows\ArtiSync.iss` | `packaging\out\ArtiSync-Setup.exe` |

The Python used needs `pip install -r packaging/requirements.txt pyinstaller pillow`. The Flatpak needs `flatpak-builder` and `org.freedesktop.Sdk//25.08`.

GitHub Actions builds all of them. Run **Actions → Build** manually for test builds, or push a tag matching `python source code/version.py` (e.g. `v3.0.0`) to publish a release.

## License

MIT
