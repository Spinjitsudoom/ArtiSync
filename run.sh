#!/usr/bin/env bash
# Run the ArtiSync Qt app from source.
#
# The first run creates a Python virtual environment in
# ~/.local/share/ArtiSync/venv and installs the dependencies into it;
# later runs start straight away. Pass --update to upgrade the dependencies.

set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SRC="$HERE/python source code"
VENV="${ARTISYNC_VENV:-$HOME/.local/share/ArtiSync/venv}"
PY="$VENV/bin/python"
DEPS=(PySide6 spotipy thefuzz mutagen)

update=0
args=()
for a in "$@"; do
    case "$a" in
        --update) update=1 ;;
        *)        args+=("$a") ;;
    esac
done

if [ ! -x "$PY" ]; then
    echo "Setting up ArtiSync (first run only)…"
    mkdir -p "$(dirname "$VENV")"
    python3 -m venv "$VENV"
    update=1
fi

if [ "$update" = 1 ] || ! "$PY" -c "import PySide6, spotipy, thefuzz, mutagen" 2>/dev/null; then
    echo "Installing dependencies: ${DEPS[*]}"
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet --upgrade "${DEPS[@]}"
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Note: ffmpeg isn't on PATH, so converting audio won't work." >&2
fi

cd "$SRC"
exec "$PY" artisync.py ${args[@]+"${args[@]}"}
