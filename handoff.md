# Handoff

This file is generated and updated by the `/handoff` command.

## Project overview
- Root path: `/var/mnt/Drive J/3ds/files`
- Purpose: ArtiSync app with Python and C++ source code, plus packaging support for AppImage and Flatpak.

## Key files and locations
- `README.md`
- `rules/copilot-instructions.md`
- `rules/recall.md`
- `c++ source code/`
- `python source code/`

## Current state
- **Logic Consolidation**: Cleaned up `base_engine.py` by removing duplicated matching logic.
- **Performance**: `metadata_writer.py` now uses `ThreadPoolExecutor` for parallelized batch tagging.
- **Modernized C++ Backend**: `RemuxEngine` refactored to use `QProcess` for safer execution and `nlohmann/json` for robust metadata probing.
- **Flatpak Permissions Guidance**: Prefer narrow filesystem permissions for the C++ Flatpak. Use `--filesystem=xdg-music:rw` as the baseline, add `--filesystem=xdg-download:rw` or specific external-library mount paths only when needed, and avoid broad `--filesystem=home`, `--filesystem=host`, `--device=all`, and broad bus sockets. Keep `--share=network` for Spotify/cover-art metadata. Bundle FFmpeg or use a Flatpak-compatible FFmpeg dependency; host `/usr/bin/ffmpeg` will not be visible just because filesystem permissions are granted.
- **Infrastructure**: AI guidance follows the instructions in `rules/copilot-instructions.md`.

## Next actions / open tasks
- **Testing**: Implement a test suite for the fuzzy matching algorithm to prevent regressions in title normalization.
- **UI Responsiveness**: Consider adding asynchronous image loading for the C++ cover art panel to match the sidebar's behavior.
- **Documentation**: Update the README with the new performance metrics following the threading improvements.
