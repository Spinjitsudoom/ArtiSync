"""
spotify_engine.py
Spotify Web API engine. Same public interface as the Deezer and MusicBrainz
engines, so the app can swap between them.

Requires a Spotify Developer app (free):
  https://developer.spotify.com/dashboard
Set the Client ID and secret in Settings inside the app.
"""

import re
import time
import urllib.request

class _RateLimitGuard:
    """Wraps the spotipy client. When Spotify answers 429 it remembers the
    Retry-After time and refuses further calls until then. Calling during a
    rate-limit ban can extend it, and spotipy would otherwise sleep for the
    whole Retry-After (which can be most of a day) inside a worker thread."""

    def __init__(self, client, engine):
        self._client, self._engine = client, engine

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            eng = self._engine
            if eng.rate_limited_seconds():
                raise RuntimeError(eng.rate_limit_message())
            try:
                return attr(*args, **kwargs)
            except spotipy.SpotifyException as e:
                if e.http_status == 429:
                    try:
                        wait = int((e.headers or {}).get("Retry-After", 60))
                    except (TypeError, ValueError):
                        wait = 60
                    eng.limited_until = time.time() + max(wait, 1)
                raise
        return call


def _hours(seconds):
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"about {round(seconds / 3600)} h"


# Spotify caps these endpoints at 10 results per request for development-mode
# apps (larger limits now fail with "400 Invalid limit"); page through instead.
PAGE_LIMIT = 10

from base_engine import BaseEngine
from version import USER_AGENT

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    import requests.adapters
    from urllib3.util.retry import Retry
    _SPOTIPY_AVAILABLE = True
except ImportError:
    _SPOTIPY_AVAILABLE = False


class SpotifyEngine(BaseEngine):

    name = "Spotify"

    def __init__(self, client_id="", client_secret=""):
        self._sp              = None
        self._release_cache   = {}   # album_id  -> tracks
        self._metadata_cache  = {}   # album_id  -> metadata dict
        self._art_cache       = {}   # album_id  -> bytes | None
        self._album_cache     = {}   # album_id  -> raw Spotify album object
        self.limited_until    = 0.0  # time.time() when a 429 ban ends

        if client_id and client_secret:
            self.configure(client_id, client_secret)

    # ── Setup / auth ──────────────────────────────────────────────────────────

    def configure(self, client_id, client_secret):
        """(Re-)initialise Spotify client.  Safe to call after construction."""
        if not _SPOTIPY_AVAILABLE:
            return
        try:
            client = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret,
                ),
                requests_timeout=10,
            )
            # spotipy's retry policy sleeps for the full Retry-After on 429,
            # which can be most of a day. Retry only server errors and let
            # 429 through to _RateLimitGuard.
            retry = Retry(total=3, connect=None, read=False,
                          allowed_methods=frozenset(["GET", "POST"]),
                          status=3, backoff_factor=0.3,
                          status_forcelist=(500, 502, 503, 504),
                          respect_retry_after_header=False,
                          raise_on_status=False)
            adapter = requests.adapters.HTTPAdapter(max_retries=retry)
            client._session.mount("https://", adapter)
            client._session.mount("http://", adapter)
            self._sp = _RateLimitGuard(client, self)
            # Warm-up call to catch bad credentials early
            self._sp.search(q="test", type="artist", limit=1)
        except Exception:
            if not self.rate_limited_seconds():  # rate-limited ≠ bad credentials
                self._sp = None

    # ── Rate limit ────────────────────────────────────────────────────────────

    def rate_limited_seconds(self):
        """Seconds until Spotify accepts requests again (0 if not limited)."""
        return max(0.0, self.limited_until - time.time())

    def rate_limit_message(self):
        left = self.rate_limited_seconds()
        if not left:
            return None
        return (f"Spotify has paused requests from this app for {_hours(left)} "
                "(rate limit).")

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
                        limit=PAGE_LIMIT,
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
                        offset += PAGE_LIMIT
                    else:
                        break

            return sorted(releases, key=lambda r: r["year"])
        except Exception:
            return []

    @staticmethod
    def _release_from(a):
        """Spotify album object → the release dict used everywhere else."""
        return {
            "title":       a["name"],
            "id":          a["id"],
            "year":        (a.get("release_date") or "N/A")[:4],
            "type":        (a.get("album_type") or "album").title(),
            "track_count": a.get("total_tracks", "?"),
            "artist":      ", ".join(x["name"] for x in a.get("artists", [])),
        }

    def _album(self, album_id):
        """Full album object, fetched once per session."""
        if album_id not in self._album_cache:
            self._album_cache[album_id] = self._sp.album(album_id)
        return self._album_cache[album_id]

    def search_releases(self, query, limit=PAGE_LIMIT):
        """Album search across all of Spotify, for releases that aren't
        under the folder's artist (collaborations, compilations, renamed
        artists). Raises on network/API errors so the caller can show them."""
        if not self._sp:
            return []
        results = self._sp.search(q=query, type="album", limit=limit)
        return [self._release_from(a)
                for a in (results.get("albums") or {}).get("items", []) if a]

    def get_release(self, album_id):
        """A single release dict by id, or None."""
        if not self._sp or "-" in str(album_id):       # MusicBrainz ids have dashes
            return None
        try:
            return self._release_from(self._album(album_id))
        except Exception:
            return None

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
            album_info     = self._album(album_id)
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
            album   = self._album(album_id)
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

    def get_thumbnail_bytes(self, album_id):
        """Small cover (about 300 px) for lists; full art if already loaded."""
        if self._art_cache.get(album_id):
            return self._art_cache[album_id]
        if not self._sp:
            return None
        try:
            images = sorted(self._album(album_id).get("images", []),
                            key=lambda i: i.get("width") or 0)
            img = next((i for i in images if (i.get("width") or 0) >= 200),
                       images[-1] if images else None)
            if img is None:
                return None
            req = urllib.request.Request(img["url"],
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except Exception:
            return None

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
            album  = self._album(album_id)
            images = album.get("images", [])
            if not images:
                self._art_cache[album_id] = None
                return None

            # Pick the largest available image
            url = sorted(images, key=lambda i: i.get("width", 0), reverse=True)[0]["url"]
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            self._art_cache[album_id] = data
            return data
        except Exception:
            self._art_cache[album_id] = None
            return None
