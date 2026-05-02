"""
metadata_writer.py
Writes audio metadata tags using mutagen.

Supported formats: MP3, FLAC, M4A/MP4/AAC, OGG Vorbis
Metadata dict keys (all optional):
    title           str
    artist          str
    album           str
    year            str   (4-digit string)
    genre           str
    cover_art_bytes bytes (raw image data, any format Pillow can read)
"""

import os
from mutagen.mp3 import MP3
from mutagen.id3 import (
    ID3, ID3NoHeaderError,
    TIT2, TPE1, TALB, TCON, TDRC, APIC,
    TRCK, TPOS,
)
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis


# ── Public interface ──────────────────────────────────────────────────────────

def _normalize_ext(raw_ext):
    """Normalize extensions like '.audio aac' or '.audio mp3' → '.aac' / '.mp3'."""
    ext = raw_ext.strip().lower()
    if " " in ext:
        ext = "." + ext.split()[-1]
    return ext


def write_metadata(file_path, metadata, apply_art=True, apply_tags=True, apply_genre=True):
    """
    Write metadata to a single audio file.

    Returns True on success, or a descriptive error string on failure.
    """
    ext = _normalize_ext(os.path.splitext(file_path)[1])
    try:
        if ext == ".mp3":
            _write_mp3(file_path, metadata, apply_art, apply_tags, apply_genre)
        elif ext == ".flac":
            _write_flac(file_path, metadata, apply_art, apply_tags, apply_genre)
        elif ext in (".m4a", ".mp4", ".aac"):
            _write_mp4(file_path, metadata, apply_art, apply_tags, apply_genre)
        elif ext in (".ogg", ".oga"):
            _write_ogg(file_path, metadata, apply_art, apply_tags, apply_genre)
        else:
            return f"Unsupported format: {ext}"
        return True
    except Exception as e:
        return str(e)


def write_metadata_batch(file_paths, metadata, apply_art=True, apply_tags=True, apply_genre=True):
    """
    Write the same metadata to a list of files.

    Returns a list of (file_path, True|error_str) tuples.
    """
    results = []
    for path in file_paths:
        result = write_metadata(path, metadata, apply_art, apply_tags, apply_genre)
        results.append((path, result))
    return results


def read_metadata(file_path):
    """
    Read existing metadata from a file.
    Returns a dict with keys: title, artist, album, year, genre, has_art.
    """
    ext = _normalize_ext(os.path.splitext(file_path)[1])
    try:
        if ext == ".mp3":
            return _read_mp3(file_path)
        elif ext == ".flac":
            return _read_flac(file_path)
        elif ext in (".m4a", ".mp4", ".aac"):
            return _read_mp4(file_path)
        elif ext in (".ogg", ".oga"):
            return _read_ogg(file_path)
        return {}
    except Exception:
        return {}


# ── MP3 / ID3 ─────────────────────────────────────────────────────────────────

def _write_mp3(path, meta, apply_art, apply_tags, apply_genre):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    if apply_tags:
        if meta.get("title"):
            tags["TIT2"] = TIT2(encoding=3, text=meta["title"])
        if meta.get("artist"):
            tags["TPE1"] = TPE1(encoding=3, text=meta["artist"])
        if meta.get("album"):
            tags["TALB"] = TALB(encoding=3, text=meta["album"])
        if meta.get("year"):
            tags["TDRC"] = TDRC(encoding=3, text=meta["year"])
        if meta.get("track_number"):
            tags["TRCK"] = TRCK(encoding=3, text=str(meta["track_number"]))
        if meta.get("disc_number") and int(meta["disc_number"]) > 1:
            tags["TPOS"] = TPOS(encoding=3, text=str(meta["disc_number"]))
        if meta.get("track_number"):
            trck = str(meta["track_number"])
            if meta.get("total_tracks"):
                trck += f"/{meta['total_tracks']}"
            tags["TRCK"] = TRCK(encoding=3, text=trck)
        if meta.get("disc_number") and int(meta["disc_number"]) > 1:
            tags["TPOS"] = TPOS(encoding=3, text=str(meta["disc_number"]))

    if apply_genre and meta.get("genre"):
        tags["TCON"] = TCON(encoding=3, text=meta["genre"])

    if apply_art and meta.get("cover_art_bytes"):
        mime = _detect_mime(meta["cover_art_bytes"])
        tags.delall("APIC")
        tags["APIC:"] = APIC(
            encoding=3,
            mime=mime,
            type=3,        # Front cover
            desc="Cover",
            data=meta["cover_art_bytes"]
        )

    tags.save(path)


def _read_mp3(path):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return {}
    return {
        "title":   str(tags.get("TIT2", "")),
        "artist":  str(tags.get("TPE1", "")),
        "album":   str(tags.get("TALB", "")),
        "year":    str(tags.get("TDRC", "")),
        "genre":   str(tags.get("TCON", "")),
        "has_art": bool(tags.getall("APIC")),
    }


# ── FLAC ──────────────────────────────────────────────────────────────────────

def _write_flac(path, meta, apply_art, apply_tags, apply_genre):
    audio = FLAC(path)

    if apply_tags:
        if meta.get("title"):  audio["title"]  = meta["title"]
        if meta.get("artist"): audio["artist"] = meta["artist"]
        if meta.get("album"):  audio["album"]  = meta["album"]
        if meta.get("year"):   audio["date"]   = meta["year"]
        if meta.get("track_number"):
            audio["tracknumber"] = [str(meta["track_number"])]
        if meta.get("disc_number") and int(meta["disc_number"]) > 1:
            audio["discnumber"] = [str(meta["disc_number"])]

    if apply_genre and meta.get("genre"):
        audio["genre"] = meta["genre"]

    if apply_art and meta.get("cover_art_bytes"):
        pic = Picture()
        pic.type        = 3   # Front cover
        pic.mime        = _detect_mime(meta["cover_art_bytes"])
        pic.desc        = "Cover"
        pic.data        = meta["cover_art_bytes"]
        audio.clear_pictures()
        audio.add_picture(pic)

    audio.save()


def _read_flac(path):
    audio = FLAC(path)
    return {
        "title":   audio.get("title",  [""])[0],
        "artist":  audio.get("artist", [""])[0],
        "album":   audio.get("album",  [""])[0],
        "year":    audio.get("date",   [""])[0],
        "genre":   audio.get("genre",  [""])[0],
        "has_art": bool(audio.pictures),
    }


# ── M4A / MP4 / AAC ──────────────────────────────────────────────────────────

def _write_mp4(path, meta, apply_art, apply_tags, apply_genre):
    audio = MP4(path)

    if apply_tags:
        if meta.get("title"):  audio["\xa9nam"] = [meta["title"]]
        if meta.get("artist"): audio["\xa9ART"] = [meta["artist"]]
        if meta.get("album"):  audio["\xa9alb"] = [meta["album"]]
        if meta.get("year"):   audio["\xa9day"] = [meta["year"]]
        if meta.get("track_number"):
            total = meta.get("track_total", 0)
            audio["trkn"] = [(int(meta["track_number"]), int(total))]
        if meta.get("disc_number") and int(meta["disc_number"]) > 1:
            audio["disk"] = [(int(meta["disc_number"]), 0)]

    if apply_genre and meta.get("genre"):
        audio["\xa9gen"] = [meta["genre"]]

    if apply_art and meta.get("cover_art_bytes"):
        fmt = (
            MP4Cover.FORMAT_PNG
            if meta["cover_art_bytes"][:4] == b"\x89PNG"
            else MP4Cover.FORMAT_JPEG
        )
        audio["covr"] = [MP4Cover(meta["cover_art_bytes"], imageformat=fmt)]

    audio.save()


def _read_mp4(path):
    audio = MP4(path)
    return {
        "title":   (audio.get("\xa9nam", [""]))[0],
        "artist":  (audio.get("\xa9ART", [""]))[0],
        "album":   (audio.get("\xa9alb", [""]))[0],
        "year":    (audio.get("\xa9day", [""]))[0],
        "genre":   (audio.get("\xa9gen", [""]))[0],
        "has_art": "covr" in audio,
    }


# ── OGG Vorbis ────────────────────────────────────────────────────────────────

def _write_ogg(path, meta, apply_art, apply_tags, apply_genre):
    audio = OggVorbis(path)

    if apply_tags:
        if meta.get("title"):  audio["title"]  = [meta["title"]]
        if meta.get("artist"): audio["artist"] = [meta["artist"]]
        if meta.get("album"):  audio["album"]  = [meta["album"]]
        if meta.get("year"):   audio["date"]   = [meta["year"]]
        if meta.get("track_number"):
            audio["tracknumber"] = [str(meta["track_number"])]
        if meta.get("disc_number") and int(meta["disc_number"]) > 1:
            audio["discnumber"] = [str(meta["disc_number"])]

    if apply_genre and meta.get("genre"):
        audio["genre"] = [meta["genre"]]

    # OGG artwork via METADATA_BLOCK_PICTURE (base64 encoded FLAC Picture)
    if apply_art and meta.get("cover_art_bytes"):
        import base64, struct
        pic = Picture()
        pic.type = 3
        pic.mime = _detect_mime(meta["cover_art_bytes"])
        pic.desc = "Cover"
        pic.data = meta["cover_art_bytes"]
        encoded = base64.b64encode(pic.write()).decode("ascii")
        audio["metadata_block_picture"] = [encoded]

    audio.save()


def _read_ogg(path):
    audio = OggVorbis(path)
    return {
        "title":   (audio.get("title",  [""]))[0],
        "artist":  (audio.get("artist", [""]))[0],
        "album":   (audio.get("album",  [""]))[0],
        "year":    (audio.get("date",   [""]))[0],
        "genre":   (audio.get("genre",  [""]))[0],
        "has_art": "metadata_block_picture" in audio,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_mime(data):
    """Detect image MIME type from magic bytes."""
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    return "image/jpeg"  # default
