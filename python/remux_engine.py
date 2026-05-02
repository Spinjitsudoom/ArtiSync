"""
remux_engine.py
Converts audio files between formats using FFmpeg.

Remux  (no re-encode) : AAC → M4A, MP4 → M4A
Transcode             : any supported pair

Quality presets for lossy output (MP3 / AAC):
    "low"    → 128 kbps
    "medium" → 192 kbps  (default)
    "high"   → 320 kbps
    "best"   → VBR V0 (MP3) / 256 kbps (AAC)
"""

import os
import shutil
import subprocess


def _normalize_ext(raw_ext):
    """Normalize compound extensions like '.audio aac' → '.aac'."""
    ext = raw_ext.strip().lower()
    if " " in ext:
        ext = "." + ext.split()[-1]
    return ext


# Formats this engine can write to
SUPPORTED_OUTPUT = {".mp3", ".flac", ".m4a", ".ogg", ".wav"}

# Formats that can be opened as input
SUPPORTED_INPUT  = {".mp3", ".flac", ".m4a", ".aac", ".mp4",
                    ".ogg", ".oga", ".wav", ".opus", ".wma"}

# Pairs where we can remux (copy codec, just repackage) instead of re-encoding
_REMUX_PAIRS = {
    (".aac",  ".m4a"),
    (".mp4",  ".m4a"),
    (".m4a",  ".mp4"),
}

_MP3_QUALITY = {
    "low":    ["-b:a", "128k"],
    "medium": ["-b:a", "192k"],
    "high":   ["-b:a", "320k"],
    "best":   ["-q:a", "0"],       # VBR V0
}
_AAC_QUALITY = {
    "low":    ["-b:a", "128k"],
    "medium": ["-b:a", "192k"],
    "high":   ["-b:a", "256k"],
    "best":   ["-b:a", "256k"],
}


class RemuxEngine:
    """
    Thin wrapper around FFmpeg for audio format conversion.

    Usage:
        engine = RemuxEngine()
        if not engine.is_available:
            ...  # ffmpeg not installed

        result = engine.convert("track.aac", "track.m4a")
        # True on success, error string on failure

        results = engine.convert_batch([("a.aac", "a.m4a"), ...])
        # [(src, dst, True|error_str), ...]
    """

    def __init__(self):
        self._ffmpeg = shutil.which("ffmpeg")
        self._ffprobe = shutil.which("ffprobe")

    # ── Public ────────────────────────────────────────────────────────────────

    @property
    def is_available(self):
        return self._ffmpeg is not None

    def convert(self, src_path, dst_path, quality="medium", delete_source=False):
        """
        Convert src_path → dst_path.

        dst_path extension determines the output format.
        Returns True on success, or a descriptive error string.
        """
        if not self.is_available:
            return "FFmpeg not found — install it and ensure it's on PATH"

        src_ext = _normalize_ext(os.path.splitext(src_path)[1])
        dst_ext = _normalize_ext(os.path.splitext(dst_path)[1])

        if src_ext not in SUPPORTED_INPUT:
            return f"Unsupported input format: {src_ext}"
        if dst_ext not in SUPPORTED_OUTPUT:
            return f"Unsupported output format: {dst_ext}"
        if not os.path.exists(src_path):
            return f"Source file not found: {src_path}"

        cmd = self._build_command(src_path, dst_path, src_ext, dst_ext, quality)
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            if result.returncode != 0:
                err = result.stderr.decode(errors="replace").strip()
                # Return last 200 chars of stderr — the useful part
                return err[-200:] if len(err) > 200 else err

            if delete_source and os.path.exists(dst_path):
                os.remove(src_path)

            return True
        except subprocess.TimeoutExpired:
            return "FFmpeg timed out (>120s)"
        except Exception as e:
            return str(e)

    def convert_batch(self, pairs, quality="medium", delete_source=False,
                      progress_callback=None):
        """
        Convert a list of (src_path, dst_path) pairs.

        progress_callback(done, total) is called after each file if provided.
        Returns [(src, dst, True|error_str), ...].
        """
        results = []
        total = len(pairs)
        for i, (src, dst) in enumerate(pairs, 1):
            res = self.convert(src, dst, quality=quality,
                               delete_source=delete_source)
            results.append((src, dst, res))
            if progress_callback:
                progress_callback(i, total)
        return results

    def probe(self, path):
        """
        Return basic info about an audio file via ffprobe.
        Returns dict with keys: codec, bitrate_kbps, duration_s, sample_rate.
        Returns {} if ffprobe is unavailable or the file can't be read.
        """
        if not self._ffprobe or not os.path.exists(path):
            return {}
        try:
            result = subprocess.run(
                [
                    self._ffprobe, "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams", "-show_format",
                    path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            if result.returncode != 0:
                return {}
            import json
            data = json.loads(result.stdout)
            stream = next(
                (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
                {}
            )
            fmt = data.get("format", {})
            bitrate = int(fmt.get("bit_rate", 0)) // 1000
            return {
                "codec":       stream.get("codec_name", "unknown"),
                "bitrate_kbps": bitrate,
                "duration_s":  float(fmt.get("duration", 0)),
                "sample_rate": int(stream.get("sample_rate", 0)),
            }
        except Exception:
            return {}

    def suggested_output_path(self, src_path, dst_ext):
        """
        Return a destination path with the same stem but a new extension.
        Handles compound extensions like '.audio aac' by stripping them from
        the stem before appending the new extension.
        Ensures no collision with an existing file by appending _converted.
        """
        folder   = os.path.dirname(src_path)
        basename = os.path.basename(src_path)
        stem, raw_ext = os.path.splitext(basename)
        # If the stem itself ends with a junk word (e.g. "song.audio" from
        # ".audio aac"), strip it too so we don't get "song.audio.flac".
        if " " in raw_ext:
            stem = os.path.splitext(stem)[0] if "." in stem else stem
        dst = os.path.join(folder, stem + dst_ext)
        if os.path.exists(dst) and dst != src_path:
            dst = os.path.join(folder, stem + "_converted" + dst_ext)
        return dst

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_command(self, src, dst, src_ext, dst_ext, quality):
        cmd = [self._ffmpeg, "-y", "-i", src]

        if (src_ext, dst_ext) in _REMUX_PAIRS:
            # Container swap only — copy all streams including attached art
            cmd += ["-c", "copy", "-map", "0"]
        elif dst_ext == ".mp3":
            cmd += ["-c:a", "libmp3lame"] + _MP3_QUALITY.get(quality, _MP3_QUALITY["medium"])
            # Carry cover art: re-encode attached video (art) stream as MJPEG for ID3
            cmd += ["-map", "0:a", "-map", "0:v?",
                    "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
        elif dst_ext == ".flac":
            cmd += ["-c:a", "flac", "-map", "0:a", "-map", "0:v?", "-c:v", "copy"]
        elif dst_ext in (".m4a", ".mp4"):
            cmd += ["-c:a", "aac"] + _AAC_QUALITY.get(quality, _AAC_QUALITY["medium"])
            cmd += ["-map", "0:a", "-map", "0:v?", "-c:v", "copy",
                    "-disposition:v", "attached_pic"]
        elif dst_ext == ".ogg":
            # OGG doesn't support attached picture streams — art dropped, re-apply via metadata_writer
            cmd += ["-c:a", "libvorbis", "-q:a", "6", "-map", "0:a"]
        elif dst_ext == ".wav":
            # WAV has no standard art embedding
            cmd += ["-c:a", "pcm_s16le", "-map", "0:a"]

        cmd += ["-map_metadata", "0"]
        cmd.append(dst)
        return cmd
