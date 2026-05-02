"""
mb_engine.py
MusicBrainz engine.  Inherits shared file-matching logic from BaseEngine.
"""

import os
import re
import time
import urllib.request
import musicbrainzngs
from thefuzz import process, fuzz

from base_engine import BaseEngine

musicbrainzngs.set_useragent("MusicOrganizerApp", "2.1", "contact@example.com")


class MBEngine(BaseEngine):

    def __init__(self):
        self._release_cache  = {}
        self._metadata_cache = {}
        self._art_cache      = {}

    @property
    def is_configured(self):
        return True   # MB needs no credentials

    # ── Artist search ─────────────────────────────────────────────────────────

    def search_artists(self, query):
        try:
            result = musicbrainzngs.search_artists(query, limit=10)
            return [
                {
                    "name":           a["name"],
                    "id":             a["id"],
                    "disambiguation": a.get("disambiguation", ""),
                }
                for a in result.get("artist-list", [])
            ]
        except Exception:
            return []

    # ── Releases ──────────────────────────────────────────────────────────────

    def get_releases(self, artist_id):
        try:
            result = musicbrainzngs.get_artist_by_id(
                artist_id,
                includes=["release-groups"],
                release_type=["album", "ep", "single"],
            )
            rgs = result["artist"].get("release-group-list", [])
            releases = []
            for rg in rgs:
                releases.append({
                    "title":       rg["title"],
                    "id":          rg["id"],
                    "year":        rg.get("first-release-date", "N/A")[:4],
                    "type":        rg.get("type", "Album"),
                    "track_count": rg.get("release-count", "?"),
                })
            return sorted(releases, key=lambda r: r["year"])
        except Exception:
            return []

    # ── Tracks ────────────────────────────────────────────────────────────────

    def get_tracks(self, release_group_id):
        if release_group_id in self._release_cache:
            return self._release_cache[release_group_id]
        try:
            rg = musicbrainzngs.get_release_group_by_id(
                release_group_id, includes=["releases"]
            )
            release_list = rg["release-group"].get("release-list", [])
            if not release_list:
                return []

            time.sleep(0.3)
            release_id = release_list[0]["id"]
            release    = musicbrainzngs.get_release_by_id(
                release_id, includes=["recordings", "media"]
            )

            tracks = []
            for medium in release["release"].get("medium-list", []):
                disc = int(medium.get("position", 1))
                for track in medium.get("track-list", []):
                    rec = track.get("recording", {})
                    tracks.append({
                        "name": rec.get("title", track.get("title", "Unknown")),
                        "num":  int(track.get("position", track.get("number", 0))),
                        "disc": disc,
                    })

            self._release_cache[release_group_id] = tracks
            return tracks
        except Exception:
            return []

    # ── Rich metadata ─────────────────────────────────────────────────────────

    def get_release_metadata(self, release_group_id):
        if release_group_id in self._metadata_cache:
            return self._metadata_cache[release_group_id]
        try:
            time.sleep(0.3)
            rg = musicbrainzngs.get_release_group_by_id(
                release_group_id, includes=["releases"]
            )
            release_list = rg["release-group"].get("release-list", [])
            if not release_list:
                return {}

            time.sleep(0.3)
            data = musicbrainzngs.get_release_by_id(
                release_list[0]["id"],
                includes=["artists", "genres", "tags", "release-groups"],
            )
            r = data["release"]

            credits    = r.get("artist-credit", [])
            artists    = [c["artist"]["name"] for c in credits
                          if isinstance(c, dict) and "artist" in c]
            genres     = [g["name"].title() for g in r.get("genre-list", [])]
            if not genres:
                tags   = sorted(r.get("tag-list", []),
                                key=lambda t: int(t.get("count", 0)), reverse=True)
                genres = [t["name"].title() for t in tags[:5]]

            meta = {
                "artist": ", ".join(artists),
                "album":  r.get("title", ""),
                "year":   r.get("date", "N/A")[:4],
                "genre":  genres[0] if genres else "",
                "genres": genres,
            }
            self._metadata_cache[release_group_id] = meta
            return meta
        except Exception:
            return {}

    # ── Cover art ─────────────────────────────────────────────────────────────

    def get_cover_art_bytes(self, release_group_id):
        if release_group_id in self._art_cache:
            return self._art_cache[release_group_id]
        for url in [
            f"https://coverartarchive.org/release-group/{release_group_id}/front-500",
            f"https://coverartarchive.org/release-group/{release_group_id}/front",
        ]:
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "MusicOrganizerApp/2.1"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                self._art_cache[release_group_id] = data
                return data
            except Exception:
                continue
        self._art_cache[release_group_id] = None
        return None
