"""
mb_engine.py
MusicBrainz engine: same interface as SpotifyEngine, no account needed.

A "release" here is a MusicBrainz *release group* (the album as a whole);
tracks come from one edition of it, picked by _pick_edition(). Cover art
comes from the Cover Art Archive.

MusicBrainz allows about one request per second per client and asks for a
User-Agent that names the application; _get() enforces both and retries
when the server says it's busy.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from base_engine import BaseEngine, plain_text as _plain
from version import USER_AGENT

API        = "https://musicbrainz.org/ws/2"
COVER_ART  = "https://coverartarchive.org/release-group"
MIN_INTERVAL = 1.1          # seconds between MusicBrainz requests
MAX_GROUP_PAGES = 10        # artist discography: at most 1000 release groups

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

def _credit(credits):
    """Artist credit list → 'A feat. B' using MusicBrainz's join phrases."""
    return _plain("".join(c.get("name", "") + c.get("joinphrase", "")
                          for c in credits or [])).strip()


def is_mbid(value):
    return bool(value) and bool(_UUID.match(str(value)))


class MusicBrainzEngine(BaseEngine):

    name = "MusicBrainz"

    def __init__(self):
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._groups   = {}   # release-group id → release dict
        self._releases = {}   # release-group id → full edition JSON
        self._tracks   = {}   # release-group id → tracks
        self._metadata = {}   # release-group id → metadata dict
        self._art      = {}   # release-group id → bytes | None
        self._thumbs   = {}   # release-group id → small bytes | None
        self._closed   = False

    def close(self):
        """Stop: requests still queued fail at once, so the app can exit."""
        self._closed = True

    @property
    def is_configured(self):
        return True           # no credentials needed

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _get(self, path, **params):
        params["fmt"] = "json"
        url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
        for attempt in range(4):
            if self._closed:
                raise RuntimeError("closed")
            with self._lock:                 # reserve the next free slot
                now = time.monotonic()
                wait = max(0.0, self._next_slot - now)
                self._next_slot = max(now, self._next_slot) + MIN_INTERVAL
            if wait:
                time.sleep(wait)
            if self._closed:
                raise RuntimeError("closed")
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 3:
                    # Rate limited: wait as told, or a little longer each try.
                    try:
                        delay = float(e.headers.get("Retry-After") or 0)
                    except ValueError:
                        delay = 0
                    time.sleep(min(delay, 10) or 1.5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("MusicBrainz is busy; try again in a moment.")

    # ── Search ────────────────────────────────────────────────────────────────

    def search_artists(self, query):
        """Returns [{name, id, disambiguation}, …]"""
        try:
            data = self._get("artist", query=query, limit=10, dismax="true")
        except Exception:
            return []
        return [{"name": a["name"], "id": a["id"],
                 "disambiguation": a.get("disambiguation", "")}
                for a in data.get("artists", [])]

    @staticmethod
    def _release_from(rg, with_artist=False):
        types = [rg.get("primary-type") or "Other"] + list(rg.get("secondary-types") or [])
        rel = {
            "title":       _plain(rg.get("title", "")),
            "id":          rg["id"],
            "year":        (rg.get("first-release-date") or "N/A")[:4],
            "type":        " · ".join(types),
            "track_count": "?",
        }
        if with_artist:
            rel["artist"] = _credit(rg.get("artist-credit"))
        return rel

    def search_releases(self, query, limit=20):
        """Album search across all of MusicBrainz. Raises on network errors
        so the caller can show them."""
        data = self._get("release-group", query=query, limit=limit, dismax="true")
        out = []
        for rg in data.get("release-groups", []):
            rel = self._release_from(rg, with_artist=True)
            self._groups[rel["id"]] = rel
            out.append(rel)
        return out

    def get_release(self, release_id):
        """A single release dict by id, or None (also for non-MusicBrainz ids)."""
        if not is_mbid(release_id):
            return None
        if release_id in self._groups:
            return self._groups[release_id]
        try:
            rg = self._get(f"release-group/{release_id}", inc="artist-credits")
        except Exception:
            return None
        rel = self._release_from(rg, with_artist=True)
        self._groups[release_id] = rel
        return rel

    # ── Releases ──────────────────────────────────────────────────────────────

    def get_releases(self, artist_id):
        """Every release group by the artist, oldest first."""
        releases, offset = [], 0
        try:
            for _page in range(MAX_GROUP_PAGES):
                data = self._get("release-group", artist=artist_id,
                                 limit=100, offset=offset)
                groups = data.get("release-groups", [])
                releases += [self._release_from(rg) for rg in groups]
                offset += len(groups)
                if not groups or offset >= data.get("release-group-count", 0):
                    break
        except Exception:
            if not releases:
                return []
        return sorted(releases, key=lambda r: (r["year"], r["title"].lower()))

    # ── One edition of a release group ────────────────────────────────────────

    @staticmethod
    def _pick_edition(editions):
        """The edition whose track list best stands for the album: official,
        original release date, digital (what most files come from) or CD."""
        def score(r):
            formats = {m.get("format") or "" for m in r.get("media", [])}
            s = 0
            if r.get("status") == "Official":
                s += 100
            if "Digital Media" in formats:
                s += 20
            elif formats & {"CD", "Enhanced CD"}:
                s += 10
            if r.get("country") in ("XW", "US", "GB"):
                s += 5
            return (-s, r.get("date") or "9999")
        return min(editions, key=score) if editions else None

    def _edition(self, group_id):
        if group_id in self._releases:
            return self._releases[group_id]
        data = self._get("release", **{"release-group": group_id},
                         inc="media", limit=100)
        best = self._pick_edition(data.get("releases", []))
        full = None
        if best:
            full = self._get(f"release/{best['id']}",
                             inc="recordings artist-credits genres tags release-groups")
        self._releases[group_id] = full
        return full

    # ── Tracks ────────────────────────────────────────────────────────────────

    def get_tracks(self, release_id):
        """Returns [{name, num, disc, featured}, …]"""
        if release_id in self._tracks:
            return self._tracks[release_id]
        if not is_mbid(release_id):
            return []
        try:
            rel = self._edition(release_id)
        except Exception:
            return []
        if not rel:
            return []
        primary = {c.get("name", "").lower() for c in rel.get("artist-credit", [])}
        tracks = []
        for medium in rel.get("media", []):
            disc = int(medium.get("position") or 1)
            for i, t in enumerate(medium.get("tracks") or [], 1):
                names = [c.get("name", "") for c in t.get("artist-credit", [])]
                tracks.append({
                    "name":     _plain(t.get("title") or "Unknown"),
                    "num":      int(t.get("position") or i),
                    "disc":     disc,
                    "featured": [_plain(n) for n in names if n.lower() not in primary],
                })
        self._tracks[release_id] = tracks
        return tracks

    # ── Metadata ──────────────────────────────────────────────────────────────

    @staticmethod
    def _genres(obj):
        genres = sorted(obj.get("genres") or [], key=lambda g: -int(g.get("count", 0)))
        return [g["name"].title() for g in genres]

    def get_release_metadata(self, release_id):
        """Returns {artist, album, year, genre, genres}"""
        if release_id in self._metadata:
            return self._metadata[release_id]
        if not is_mbid(release_id):
            return {}
        try:
            rel = self._edition(release_id)
            if not rel:
                return {}
            rg = rel.get("release-group") or {}
            genres = self._genres(rel) or self._genres(rg)
            credits = rel.get("artist-credit") or []
            if not genres and credits:
                artist = self._get(f"artist/{credits[0]['artist']['id']}", inc="genres")
                genres = self._genres(artist)
        except Exception:
            return {}
        meta = {
            "artist": _credit(credits),
            "album":  _plain(rg.get("title") or rel.get("title", "")),
            "year":   (rg.get("first-release-date") or rel.get("date") or "N/A")[:4],
            "genre":  genres[0] if genres else "",
            "genres": genres,
        }
        self._metadata[release_id] = meta
        return meta

    # ── Cover art ─────────────────────────────────────────────────────────────

    def get_cover_art_bytes(self, release_id):
        """Front cover from the Cover Art Archive (not rate-limited like the
        MusicBrainz API). Returns bytes or None."""
        if release_id not in self._art:
            self._art[release_id] = self._cover(release_id, ("front-500", "front"))
        return self._art[release_id]

    def get_thumbnail_bytes(self, release_id):
        """Small front cover for lists."""
        if release_id in self._art:
            return self._art[release_id]
        if release_id not in self._thumbs:
            self._thumbs[release_id] = self._cover(release_id, ("front-250", "front"))
        return self._thumbs[release_id]

    def _cover(self, release_id, sizes):
        data = None
        if is_mbid(release_id) and not self._closed:
            for size in sizes:
                req = urllib.request.Request(f"{COVER_ART}/{release_id}/{size}",
                                             headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = resp.read()
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        break                # no art for this album
                except Exception:
                    continue
        return data
