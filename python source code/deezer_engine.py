"""
deezer_engine.py
Deezer engine: same interface as SpotifyEngine, no account needed.

Uses Deezer's public read-only API (api.deezer.com), which allows 50
requests per 5 seconds per client. _get() keeps requests 0.11 s apart and
backs off when Deezer reports its quota exceeded. Deezer reports errors as
HTTP 200 with an "error" object, so those are checked too.

Featured artists are only listed on each track's own page, so get_tracks()
fetches those (a few at a time, under the same rate limit).
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from base_engine import BaseEngine, plain_text
from version import USER_AGENT

API = "https://api.deezer.com"
MIN_INTERVAL = 0.11            # 50 requests / 5 s, with a little headroom
QUOTA_ERROR = 4                # Deezer error code: quota exceeded
NOT_FOUND = 800                # Deezer error code: no data

_TYPES = {"album": "Album", "single": "Single", "ep": "EP", "compile": "Compilation"}


class DeezerError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def is_deezer_id(value):
    return str(value).isdigit()


class DeezerEngine(BaseEngine):

    name = "Deezer"

    def __init__(self):
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._closed = False
        self._albums   = {}   # album id → full album JSON
        self._groups   = {}   # album id → release dict
        self._thumbs   = {}   # album id → 250 px cover URL
        self._tracks   = {}   # album id → tracks
        self._metadata = {}   # album id → metadata dict
        self._art      = {}   # album id → bytes | None
        self._thumb_bytes = {}

    @property
    def is_configured(self):
        return True           # no credentials needed

    def close(self):
        """Stop: queued requests fail at once, so the app can exit."""
        self._closed = True

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _get(self, path, **params):
        url = f"{API}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            if self._closed:
                raise RuntimeError("closed")
            with self._lock:                 # reserve the next free slot
                now = time.monotonic()
                wait = max(0.0, self._next_slot - now)
                self._next_slot = max(now, self._next_slot) + MIN_INTERVAL
            if wait:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
            err = data.get("error") if isinstance(data, dict) else None
            if err:
                code = err.get("code")
                if code == QUOTA_ERROR and attempt < 3:
                    time.sleep(5)            # the quota window is 5 seconds
                    continue
                raise DeezerError(code, err.get("message") or "Deezer error")
            return data
        raise RuntimeError("Deezer is busy; try again in a moment.")

    def _download(self, url):
        if not url or self._closed:
            return None
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read()
        except Exception:
            return None

    # ── Search ────────────────────────────────────────────────────────────────

    def search_artists(self, query):
        """Returns [{name, id, disambiguation}, …]"""
        try:
            data = self._get("search/artist", q=query, limit=10)
        except Exception:
            return []
        return [{"name": a["name"], "id": str(a["id"]),
                 "disambiguation": f"{a.get('nb_album', 0)} albums · "
                                   f"{a.get('nb_fan', 0):,} fans"}
                for a in data.get("data", [])]

    def _release_from(self, a, with_artist=False):
        aid = str(a["id"])
        rel = {
            "title":       plain_text(a.get("title", "")),
            "id":          aid,
            "year":        (a.get("release_date") or "")[:4],
            "type":        _TYPES.get(a.get("record_type"), "Album"),
            "track_count": a.get("nb_tracks", "?"),
        }
        if with_artist:
            rel["artist"] = plain_text((a.get("artist") or {}).get("name", ""))
        if a.get("cover_medium"):
            self._thumbs[aid] = a["cover_medium"]
        return rel

    def search_releases(self, query, limit=20):
        """Album search across all of Deezer. Raises on errors so the caller
        can show them."""
        data = self._get("search/album", q=query, limit=limit)
        out = []
        for a in data.get("data", []):
            rel = self._release_from(a, with_artist=True)
            self._groups.setdefault(rel["id"], rel)
            out.append(rel)
        return out

    def get_release(self, release_id):
        """A single release dict by id, or None (also for other sources' ids)."""
        if not is_deezer_id(release_id):
            return None
        try:
            album = self._album(release_id)
        except Exception:
            return None
        rel = self._release_from(album, with_artist=True)
        self._groups[rel["id"]] = rel
        return rel

    # ── Releases ──────────────────────────────────────────────────────────────

    def get_releases(self, artist_id):
        """The artist's albums, singles, EPs and compilations, oldest first.
        Duplicate editions (same title and year) are listed once."""
        releases, seen, index = [], set(), 0
        try:
            for _page in range(20):
                data = self._get(f"artist/{artist_id}/albums", limit=100, index=index)
                items = data.get("data", [])
                for a in items:
                    rel = self._release_from(a)
                    key = (rel["title"].lower(), rel["year"])
                    if key in seen:
                        continue
                    seen.add(key)
                    releases.append(rel)
                index += len(items)
                if not items or not data.get("next"):
                    break
        except Exception:
            if not releases:
                return []
        return sorted(releases, key=lambda r: (r["year"], r["title"].lower()))

    def _album(self, album_id):
        album_id = str(album_id)
        if album_id not in self._albums:
            self._albums[album_id] = self._get(f"album/{album_id}")
        return self._albums[album_id]

    # ── Tracks ────────────────────────────────────────────────────────────────

    def get_tracks(self, release_id):
        """Returns [{name, num, disc, featured}, …]"""
        release_id = str(release_id)
        if release_id in self._tracks:
            return self._tracks[release_id]
        if not is_deezer_id(release_id):
            return []
        try:
            album = self._album(release_id)
            items, index = [], 0
            while True:
                data = self._get(f"album/{release_id}/tracks", limit=100, index=index)
                batch = data.get("data", [])
                items += batch
                index += len(batch)
                if not batch or not data.get("next"):
                    break
        except Exception:
            return []

        main = {(c.get("name") or "").lower() for c in album.get("contributors", [])
                if c.get("role", "Main") == "Main"}
        main.add(((album.get("artist") or {}).get("name") or "").lower())

        def featured(track_id):
            try:
                t = self._get(f"track/{track_id}")
            except Exception:
                return []
            return [plain_text(c["name"]) for c in t.get("contributors", [])
                    if c.get("role") == "Featured" or
                    (c.get("name") or "").lower() not in main]

        with ThreadPoolExecutor(max_workers=4) as pool:
            feats = list(pool.map(featured, [t["id"] for t in items]))

        tracks = []
        for i, (t, feat) in enumerate(zip(items, feats), 1):
            tracks.append({
                "name":     plain_text(t.get("title") or "Unknown"),
                "num":      int(t.get("track_position") or i),
                "disc":     int(t.get("disk_number") or 1),
                "featured": list(dict.fromkeys(feat)),
            })
        self._tracks[release_id] = tracks
        return tracks

    # ── Metadata ──────────────────────────────────────────────────────────────

    def get_release_metadata(self, release_id):
        """Returns {artist, album, year, genre, genres}"""
        release_id = str(release_id)
        if release_id in self._metadata:
            return self._metadata[release_id]
        if not is_deezer_id(release_id):
            return {}
        try:
            album = self._album(release_id)
        except Exception:
            return {}
        mains = [c["name"] for c in album.get("contributors", [])
                 if c.get("role", "Main") == "Main"]
        artist = ", ".join(mains) or (album.get("artist") or {}).get("name", "")
        genres = [g["name"] for g in (album.get("genres") or {}).get("data", [])]
        meta = {
            "artist": plain_text(artist),
            "album":  plain_text(album.get("title", "")),
            "year":   (album.get("release_date") or "N/A")[:4],
            "genre":  genres[0] if genres else "",
            "genres": genres,
        }
        self._metadata[release_id] = meta
        return meta

    # ── Cover art ─────────────────────────────────────────────────────────────

    def get_cover_art_bytes(self, release_id):
        """1000×1000 front cover, or None."""
        release_id = str(release_id)
        if release_id not in self._art:
            data = None
            if is_deezer_id(release_id):
                try:
                    album = self._album(release_id)
                    data = self._download(album.get("cover_xl") or album.get("cover_big"))
                except Exception:
                    data = None
            self._art[release_id] = data
        return self._art[release_id]

    def get_thumbnail_bytes(self, release_id):
        """250×250 cover for lists. Uses the URL from the release listing, so
        it costs no API request."""
        release_id = str(release_id)
        if self._art.get(release_id):
            return self._art[release_id]
        if release_id not in self._thumb_bytes:
            url = self._thumbs.get(release_id)
            if url is None and is_deezer_id(release_id):
                try:
                    url = self._album(release_id).get("cover_medium")
                except Exception:
                    url = None
            self._thumb_bytes[release_id] = self._download(url)
        return self._thumb_bytes[release_id]
