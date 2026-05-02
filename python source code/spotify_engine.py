"""
spotify_engine.py
Spotify Web API engine.  Same public interface as MBEngine so
music_organizer.py can swap engines without changing any other logic.

Requires a Spotify Developer app (free):
  https://developer.spotify.com/dashboard
Set Client ID + Client Secret in File > Settings inside the app.
"""

import re
import time
import urllib.request

from base_engine import BaseEngine

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    _SPOTIPY_AVAILABLE = True
except ImportError:
    _SPOTIPY_AVAILABLE = False


class SpotifyEngine(BaseEngine):

    def __init__(self, client_id="", client_secret=""):
        self._sp              = None
        self._release_cache   = {}   # album_id  -> tracks
        self._metadata_cache  = {}   # album_id  -> metadata dict
        self._art_cache       = {}   # album_id  -> bytes | None

        if client_id and client_secret:
            self.configure(client_id, client_secret)

    # ── Setup / auth ──────────────────────────────────────────────────────────

    def configure(self, client_id, client_secret):
        """(Re-)initialise Spotify client.  Safe to call after construction."""
        if not _SPOTIPY_AVAILABLE:
            return
        try:
            self._sp = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret,
                ),
                requests_timeout=10,
            )
            # Warm-up call to catch bad credentials early
            self._sp.search(q="test", type="artist", limit=1)
        except Exception:
            self._sp = None

    @property
    def is_configured(self):
        return self._sp is not None

    # ── Artist search ─────────────────────────────────────────────────────────

    def search_artists(self, query):
        """Returns [{name, id, disambiguation}, …]"""
        if not self._sp:
            return []
        try:
            results = self._sp.search(q=query, type="artist", limit=10)
            artists = []
            for a in results["artists"]["items"]:
                followers = a.get("followers", {}).get("total", 0)
                pop       = a.get("popularity", 0)
                note      = f"{followers:,} followers · popularity {pop}"
                artists.append({
                    "name":           a["name"],
                    "id":             a["id"],
                    "disambiguation": note,
                })
            return artists
        except Exception:
            return []

    # ── Releases ──────────────────────────────────────────────────────────────

    def get_releases(self, artist_id):
        """
        Returns [{title, id, year, type, track_count}, …] sorted by year.
        Fetches albums, singles, and compilations.  Deduplicates by (name, year)
        so regional re-releases don't flood the list.
        """
        if not self._sp:
            return []
        try:
            seen     = set()
            releases = []

            for album_type in ("album", "single", "compilation"):
                offset = 0
                while True:
                    batch = self._sp.artist_albums(
                        artist_id,
                        album_type=album_type,
                        limit=50,
                        offset=offset,
                    )
                    for a in batch["items"]:
                        year  = (a.get("release_date") or "N/A")[:4]
                        key   = (a["name"].lower(), year)
                        if key in seen:
                            continue
                        seen.add(key)
                        releases.append({
                            "title":       a["name"],
                            "id":          a["id"],
                            "year":        year,
                            "type":        a["album_type"].title(),
                            "track_count": a.get("total_tracks", "?"),
                        })
                    if batch.get("next"):
                        offset += 50
                    else:
                        break

            return sorted(releases, key=lambda r: r["year"])
        except Exception:
            return []

    # ── Tracks ────────────────────────────────────────────────────────────────

    def get_tracks(self, album_id):
        """Returns [{name, num, disc, featured}, …].  Cached after first fetch.
        featured is a list of artist name strings (empty for solo tracks)."""
        if album_id in self._release_cache:
            return self._release_cache[album_id]
        if not self._sp:
            return []
        try:
            # Fetch the album to get the primary artist name(s) for exclusion
            album_info     = self._sp.album(album_id)
            primary_artists = {a["name"].lower()
                               for a in album_info.get("artists", [])}

            tracks = []
            offset = 0
            while True:
                batch = self._sp.album_tracks(album_id, limit=50, offset=offset)
                for t in batch["items"]:
                    # Featured = any artist not in the album's primary artist set
                    all_artists = [a["name"] for a in t.get("artists", [])]
                    featured    = [a for a in all_artists
                                   if a.lower() not in primary_artists]
                    tracks.append({
                        "name":     t["name"],
                        "num":      t.get("track_number", len(tracks) + 1),
                        "disc":     t.get("disc_number", 1),
                        "featured": featured,
                    })
                if batch.get("next"):
                    offset += 50
                else:
                    break
            self._release_cache[album_id] = tracks
            return tracks
        except Exception:
            return []

    # ── Rich metadata ─────────────────────────────────────────────────────────

    def get_release_metadata(self, album_id):
        """
        Returns {artist, album, year, genre, genres}.
        Spotify albums often lack genre tags; falls back to artist genres.
        Cached after first fetch.
        """
        if album_id in self._metadata_cache:
            return self._metadata_cache[album_id]
        if not self._sp:
            return {}
        try:
            album   = self._sp.album(album_id)
            artists = ", ".join(a["name"] for a in album.get("artists", []))

            # Album-level genres first, then artist-level
            genres = [g.title() for g in album.get("genres", [])]
            if not genres and album.get("artists"):
                artist_data = self._sp.artist(album["artists"][0]["id"])
                genres = [g.title() for g in artist_data.get("genres", [])]

            meta = {
                "artist": artists,
                "album":  album["name"],
                "year":   (album.get("release_date") or "N/A")[:4],
                "genre":  genres[0] if genres else "",
                "genres": genres,
            }
            self._metadata_cache[album_id] = meta
            return meta
        except Exception:
            return {}

    # ── Cover art ─────────────────────────────────────────────────────────────

    def get_cover_art_bytes(self, album_id):
        """
        Downloads the largest available album image from Spotify's CDN.
        Returns raw bytes or None.  Cached after first fetch.
        """
        if album_id in self._art_cache:
            return self._art_cache[album_id]
        if not self._sp:
            return None
        try:
            album  = self._sp.album(album_id)
            images = album.get("images", [])
            if not images:
                self._art_cache[album_id] = None
                return None

            # Pick the largest available image
            url = sorted(images, key=lambda i: i.get("width", 0), reverse=True)[0]["url"]
            req = urllib.request.Request(
                url, headers={"User-Agent": "MusicOrganizerApp/2.1"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            self._art_cache[album_id] = data
            return data
        except Exception:
            self._art_cache[album_id] = None
            return None
