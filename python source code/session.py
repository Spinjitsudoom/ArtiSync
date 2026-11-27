"""
session.py
Application core with no GUI code in it: scanning the library, tracking each
album's status, resolving folders to releases (Deezer, MusicBrainz or
Spotify), building and editing an album preview, and executing / undoing
renames, conversions and tags.

The Qt GUI (gui/) only displays this state and forwards user actions here.
"""

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from thefuzz import fuzz, process

from app_config import CONFIG_DIR
from base_engine import BaseEngine, list_audio_files, normalize_ext
from file_ops import safe_rename_batch
from metadata_writer import write_metadata
from remux_engine import SUPPORTED_INPUT

STATUS_FILE = CONFIG_DIR / "library_status.json"

DONE      = "done"        # every audio file matched and already correctly named
ATTENTION = "attention"   # opened, but something is unmatched or not yet renamed
TODO      = None          # never opened


# ── Library scan ──────────────────────────────────────────────────────────────

@dataclass
class AlbumFolder:
    artist: str
    name: str
    path: str

    @property
    def key(self):
        return (self.artist, self.name)


@dataclass
class ArtistFolder:
    name: str
    path: str
    albums: list = field(default_factory=list)


def scan_library(root):
    """Artist folders → album folders under `root`, both sorted by name."""
    artists = []
    if not root or not os.path.isdir(root):
        return artists
    for a in sorted(os.listdir(root), key=str.casefold):
        apath = os.path.join(root, a)
        if not os.path.isdir(apath) or a.startswith("."):
            continue
        artist = ArtistFolder(a, apath)
        try:
            names = sorted(os.listdir(apath), key=str.casefold)
        except OSError:
            names = []
        for b in names:
            bpath = os.path.join(apath, b)
            if os.path.isdir(bpath) and not b.startswith("."):
                artist.albums.append(AlbumFolder(a, b, bpath))
        artists.append(artist)
    return artists


# ── Per-album status (persisted) ──────────────────────────────────────────────

class StatusStore:
    """Remembers each album's status and any manual release override."""

    def __init__(self, path=STATUS_FILE):
        self._path = path
        try:
            with open(path) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        # Accept the prototype's plain-string format too.
        self._data = {k: (v if isinstance(v, dict) else {"status": v})
                      for k, v in raw.items()}

    @staticmethod
    def key(root, album):
        return f"{root}|{album.artist}|{album.name}"

    def status(self, root, album):
        return self._data.get(self.key(root, album), {}).get("status")

    @staticmethod
    def _override_field(source):
        # Spotify picks keep the original field name, so status files from
        # before other sources existed still work.
        return "release_id" if source in (None, "Spotify") else f"release_id_{source.lower()}"

    def release_override(self, root, album, source=None):
        """The release picked by hand for this album, for this source."""
        return self._data.get(self.key(root, album), {}).get(self._override_field(source))

    def set_status(self, root, album, status):
        self._data.setdefault(self.key(root, album), {})["status"] = status
        self._save()

    def set_release_override(self, root, album, release_id, source=None):
        self._data.setdefault(self.key(root, album), {})[self._override_field(source)] = release_id
        self._save()

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=1)
        except OSError:
            pass


# ── Folder → release resolution ───────────────────────────────────────────────

@dataclass
class ArtistMatch:
    id: str
    name: str
    releases: list


_YEAR_SUFFIX = re.compile(r"\s*[\(\[]((?:19|20)\d{2})[\)\]]\s*$")


ARTIST_MATCH_THRESHOLD = 70     # folder name vs. artist name (token_sort_ratio)


class ReleaseResolver:
    """Matches artist folders to the engine's artists and album folders to
    releases. Results are cached for the session. Thread-safe enough for
    one worker at a time per artist (the engine caches its own calls)."""

    def __init__(self, engine):
        self.engine = engine
        self._artists = {}

    def artist(self, folder_name):
        if folder_name in self._artists:
            return self._artists[folder_name]
        if not getattr(self.engine, "is_configured", False):
            return None
        found = self.engine.search_artists(folder_name)
        if not found:
            return None
        # token_sort (not token_set): token_set scores "Unknown" 100 against
        # "Qzxv Unknown Band" because one name's words are a subset of the other's.
        best = process.extractOne(folder_name, {a["id"]: a["name"] for a in found},
                                  scorer=fuzz.token_sort_ratio)
        if not best or best[1] < ARTIST_MATCH_THRESHOLD:
            # Search engines always return *something*; an unrelated artist
            # would only produce wrong matches (and, on MusicBrainz, a long
            # wait while their discography loads).
            self._artists[folder_name] = None
            return None
        aid = best[2]
        name = next(a["name"] for a in found if a["id"] == aid)
        match = ArtistMatch(aid, name, self.engine.get_releases(aid))
        if match.releases:                 # an empty list may be a failed lookup
            self._artists[folder_name] = match
        return match

    @staticmethod
    def match_release(artist_match, album_folder_name):
        """Best release for a folder like 'Infestissumam (2013)'.

        token_set_ratio alone ties 'Infestissumam' with 'Infestissumam
        (Commentary Version)', so plain ratio breaks ties and a matching year
        adds a bonus."""
        if not artist_match or not artist_match.releases:
            return None
        m = _YEAR_SUFFIX.search(album_folder_name)
        year  = m.group(1) if m else None
        title = _YEAR_SUFFIX.sub("", album_folder_name).strip() or album_folder_name

        best, best_score = None, -1
        for r in artist_match.releases:
            ts = fuzz.token_set_ratio(title, r["title"])
            if ts < 40:
                continue
            score = ts * 2 + fuzz.ratio(title.lower(), r["title"].lower())
            if year and r.get("year") == year:
                score += 15
            if score > best_score:
                best, best_score = r, score
        return best



SpotifyResolver = ReleaseResolver      # old name

# ── Album preview ─────────────────────────────────────────────────────────────

@dataclass
class TrackRow:
    track: dict
    file: str = None        # current filename, or None if no file assigned
    new_name: str = None    # proposed filename
    score: int = 0          # match confidence 0–100 (100 for manual pairs)

    @property
    def key(self):
        return (self.track.get("disc", 1), self.track["num"])

    @property
    def already_named(self):
        return self.file is not None and self.file == self.new_name


class AlbumPreview:
    """The proposed renames for one album folder, editable by the user."""

    def __init__(self, folder, release, tracks, engine):
        self.folder  = folder
        self.release = release
        self.tracks  = tracks
        self._engine = engine
        self.rows    = [TrackRow(t) for t in tracks]
        self.log     = ""
        self.files   = []
        self.refresh()

    def refresh(self):
        """Re-scan the folder and re-run fuzzy matching (drops manual edits)."""
        ep, self.log = self._engine.generate_fuzzy_preview(self.folder, self.tracks)
        self.files = sorted(list_audio_files(self.folder), key=str.casefold)
        by_key = {(d, n): (old, new, score) for old, new, n, d, score in ep}
        for row in self.rows:
            old, new, score = by_key.get(row.key, (None, None, 0))
            row.file, row.new_name, row.score = old, new, score

    # ── Manual pairing ────────────────────────────────────────────────────────

    def assign(self, row_key, filename):
        """Give `filename` to the track `row_key`, taking it from any other
        track that had it."""
        for row in self.rows:
            if row.file == filename and row.key != row_key:
                row.file, row.new_name, row.score = None, None, 0
        row = self.row(row_key)
        ext = os.path.splitext(filename)[1]
        row.file, row.new_name, row.score = (
            filename,
            self._engine._track_filename(row.track, ext, *self._engine._naming(self.tracks)),
            100)

    def unassign(self, row_key):
        row = self.row(row_key)
        row.file, row.new_name, row.score = None, None, 0

    def row(self, row_key):
        return next(r for r in self.rows if r.key == row_key)

    # ── Derived state ─────────────────────────────────────────────────────────

    @property
    def matched(self):
        return [r for r in self.rows if r.file]

    @property
    def missing(self):
        return [r for r in self.rows if not r.file]

    @property
    def unmatched_files(self):
        used = {r.file for r in self.rows if r.file}
        return [f for f in self.files if f not in used]

    @property
    def pending(self):
        """Matched rows whose file still needs renaming."""
        return [r for r in self.matched if not r.already_named]

    @property
    def status(self):
        if self.files and not self.unmatched_files and not self.pending:
            return DONE
        return ATTENTION


# ── Execute / undo ────────────────────────────────────────────────────────────

@dataclass
class ExecuteOptions:
    apply_art: bool = True
    apply_tags: bool = True
    apply_genre: bool = True
    auto_remux: bool = False
    remux_target: str = ".flac"
    remux_quality: str = "best"
    remux_delete_source: bool = False


@dataclass
class UndoRecord:
    renames: list = field(default_factory=list)   # [(new_path, old_path)]
    remuxes: list = field(default_factory=list)   # [(output, source, source_deleted)]

    def __bool__(self):
        return bool(self.renames or self.remuxes)


@dataclass
class ExecuteResult:
    renamed: int = 0
    tagged: int = 0
    converted: int = 0
    warnings: list = field(default_factory=list)
    undo: UndoRecord = field(default_factory=UndoRecord)


def execute(preview, metadata, art_bytes, opts, remux_engine):
    """Convert (optional), rename and tag every matched file in `preview`.
    Never overwrites a file. Safe to call from a worker thread."""
    res    = ExecuteResult()
    folder = preview.folder
    # (old, new, track_num, disc_num, title)
    pairs  = [(r.file, r.new_name, r.track["num"], r.track.get("disc", 1),
               r.track["name"]) for r in preview.matched]
    if not pairs:
        return res

    # ── Pre-execution conversion ──────────────────────────────────────────────
    if opts.auto_remux and remux_engine.is_available:
        converted = []
        for old, new, tnum, dnum, title in pairs:
            src_ext = normalize_ext(os.path.splitext(old)[1])
            if src_ext in {".mp3", ".flac"} or src_ext not in SUPPORTED_INPUT:
                converted.append((old, new, tnum, dnum, title))
                continue
            dst_name = os.path.splitext(old)[0] + opts.remux_target
            src_path = os.path.join(folder, old)
            dst_path = os.path.join(folder, dst_name)
            if os.path.lexists(dst_path):
                # FFmpeg runs with -y; never let it clobber an existing file.
                res.warnings.append(f"{old}: '{dst_name}' already exists — not converted")
            else:
                r = remux_engine.convert(src_path, dst_path, quality=opts.remux_quality,
                                         delete_source=opts.remux_delete_source)
                if r is True:
                    res.undo.remuxes.append(
                        (dst_path, src_path, not os.path.exists(src_path)))
                    res.converted += 1
                    old = dst_name
                    new = os.path.splitext(new)[0] + opts.remux_target
                else:
                    res.warnings.append(f"{old}: conversion failed — {r}")
            converted.append((old, new, tnum, dnum, title))
        pairs = converted

    # ── Disambiguate duplicate target names ───────────────────────────────────
    counts = Counter(new for _, new, *_ in pairs)
    pairs = [(old, (f"Disc {dnum} - " if dnum > 1 else f"{tnum:02d} - ") + new
              if counts[new] > 1 else new, tnum, dnum, title)
             for old, new, tnum, dnum, title in pairs]

    # ── Rename ────────────────────────────────────────────────────────────────
    moves = [(os.path.join(folder, old), os.path.join(folder, new))
             for old, new, *_ in pairs]
    done, errors = safe_rename_batch(moves)
    res.renamed = len(done)
    res.undo.renames = [(n, o) for o, n in done]
    res.warnings.extend(errors)

    # ── Tag ───────────────────────────────────────────────────────────────────
    if not (opts.apply_art or opts.apply_tags or opts.apply_genre) or not metadata:
        return res
    # Only files that actually reached their target name (a skipped rename's
    # target may be an unrelated file).
    ok = {n for _, n in done} | {os.path.join(folder, new)
                                 for old, new, *_ in pairs if old == new}
    base = dict(metadata)
    base["cover_art_bytes"] = art_bytes
    # Track totals are per disc ("5/12" on disc 2, not "5/24").
    disc_totals = Counter(t.get("disc", 1) for t in preview.tracks)
    for old, new, tnum, dnum, title in pairs:
        path = os.path.join(folder, new)
        if path not in ok or not os.path.exists(path):
            continue
        total = disc_totals.get(dnum) or len(preview.tracks)
        meta = dict(base, title=title, track_number=tnum, disc_number=dnum,
                    total_tracks=total, track_total=total)
        r = write_metadata(path, meta, opts.apply_art, opts.apply_tags, opts.apply_genre)
        if r is True:
            res.tagged += 1
        else:
            res.warnings.append(f"{new}: tagging failed — {r}")
    return res


@dataclass
class UndoResult:
    reverted: int = 0
    removed: int = 0           # converted copies deleted (originals still there)
    unrecoverable: int = 0     # converted files whose originals were deleted
    errors: list = field(default_factory=list)


def undo(record):
    """Reverse an ExecuteResult.undo record. Tags are not reverted."""
    out = UndoResult()
    done, out.errors = safe_rename_batch(record.renames)
    out.reverted = len(done)
    for output, source, source_deleted in record.remuxes:
        if source_deleted or not os.path.exists(source):
            out.unrecoverable += 1
            continue
        try:
            if os.path.exists(output):
                os.remove(output)
                out.removed += 1
        except OSError as e:
            out.errors.append(f"{os.path.basename(output)}: {e}")
    return out
