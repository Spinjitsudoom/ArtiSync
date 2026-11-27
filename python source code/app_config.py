"""
app_config.py
User settings, stored as JSON in ~/Documents/ArtiSync/music_config.json.
Unknown keys in the file are kept when saving.
"""

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

CONFIG_DIR  = Path.home() / "Documents" / "ArtiSync"
CONFIG_FILE = CONFIG_DIR / "music_config.json"


@dataclass
class AppConfig:
    path: str = ""
    theme: str = "Dark"
    metadata_source: str = "deezer"        # "deezer", "musicbrainz" or "spotify"
    spotify_id: str = ""
    spotify_secret: str = ""
    auto_remux: bool = False
    auto_remux_target: str = ".flac"
    auto_remux_quality: str = "best"
    auto_remux_delete_source: bool = False
    apply_art: bool = True
    apply_tags: bool = True
    apply_genre: bool = True
    track_numbers: bool = True     # "01 - Title.mp3"
    check_updates: bool = True     # ask GitHub for a newer release at startup
    skip_version: str = ""         # a release the user chose to skip

    @classmethod
    def load(cls):
        cfg = cls()
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cfg
        known = {f.name for f in fields(cls)}
        for k, v in data.items():
            if k in known:
                setattr(cfg, k, v)
        return cfg

    def save(self):
        """Write settings, keeping any keys this version doesn't know about."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            data.update(asdict(self))
            with open(CONFIG_FILE, "w") as f:
                json.dump(data, f, indent=4)
        except OSError:
            pass
