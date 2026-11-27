# Handoff

This file is generated and updated by the `/handoff` command.

## Project overview
- Root path: `/var/mnt/Drive J/3ds/My Projects/Artisync`
- Purpose: ArtiSync, a Python / PySide6 app that matches album folders to Deezer, MusicBrainz or Spotify releases, renames and tags the files, and converts audio. Packaged for Windows, macOS and Linux.

## Key files and locations
- `python source code/`: the app (entry point `artisync.py`, version in `version.py`)
- `packaging/`: PyInstaller bundle, AppImage, Flatpak, Inno Setup installer, macOS DMG
- `.github/workflows/build.yml`: builds all downloads; `v*` tags publish a release
- `run.sh`: run from source
- `python source code/updater.py`: update check and self-update
- `CLAUDE.md`, `rules/recall.md`, `rules/copilot-instructions.md`

## Current state (2026-11-26)
- Version 3.0.0 replaces the 2.x C++ app and the CustomTkinter GUI. Both were removed from the repo; a backup is in `~/Documents/ArtiSync-old-code-backup-2026-11-26.tar.gz`.
- The AppImage and Flatpak are built and tested locally (Deezer lookups, matching, artwork). Windows and macOS builds exist only in CI and haven't run yet.
- In-app update checks and self-updates added 2026-11-27 (`updater.py`, `gui/update_dialog.py`); Linux AppImage path tested end to end, Windows/macOS paths untested until a 3.x release exists to update from.
- Nothing from this work is committed yet.

## Next actions / open tasks
- Run the CI workflow once (manual dispatch) to check the Windows and macOS builds, then tag `v3.0.0`.
- Update `index.html`: the text and screenshots still describe the 2.x Spotify-only app (download links already match the new asset names).
- Batch mode (whole artist at once) from the old GUI isn't in the new app.
- macOS: Apple Silicon only, not notarized. Windows: no code signing.
- No test suite yet; the matcher (`base_engine.generate_fuzzy_preview`) is the first candidate.
