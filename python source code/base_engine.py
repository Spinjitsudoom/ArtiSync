"""
base_engine.py
Shared file-matching logic inherited by every metadata engine (Deezer,
MusicBrainz, Spotify). They all expose the same interface, so the app can
swap them freely.
"""

import os
import re
from thefuzz import process, fuzz, utils

# Minimum fuzzy score (0–100) to accept a match.
# Lower = more permissive, higher = stricter.
TRACK_MATCH_THRESHOLD  = 30   # file → track name match
ALBUM_MATCH_THRESHOLD  = 80   # folder → release title match (batch mode)

# Only these files are ever matched / renamed. Anything else in an album
# folder (cover.jpg, .lrc, .nfo, .cue, …) is left alone.
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".mp4",
                    ".ogg", ".oga", ".wav", ".opus", ".wma"}


# Catalogues use typographic punctuation ("One‐X", "Don’t"); file names and
# tags read better (and match other sources) with the plain forms.
_PLAIN = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
                        "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."})


def plain_text(s):
    return (s or "").translate(_PLAIN)


def normalize_ext(raw_ext):
    """Normalize compound extensions like '.audio aac' → '.aac'."""
    ext = raw_ext.strip().lower()
    if " " in ext:
        ext = "." + ext.split()[-1]
    return ext


def is_audio_file(filename):
    return normalize_ext(os.path.splitext(filename)[1]) in AUDIO_EXTENSIONS


def list_audio_files(folder_path):
    """Audio files (names only) directly inside folder_path, unsorted.
    Raises OSError if the folder can't be read."""
    return [f for f in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, f)) and is_audio_file(f)]


class BaseEngine:

    # ── Filename sanitizer ────────────────────────────────────────────────────

    def _normalize_for_matching(self, title):
        """
        Normalise a title for fuzzy comparison only.
        
        Handles all common 'featuring' formats:
          ft. / feat. / featuring / with / w/ / (ft. …) / [feat. …]
        Strips 'The ' prefix from artist names.
        Lowercases and collapses whitespace.
        """
        s = title.lower()
        s = re.sub(r"[\(\[\{]", " ", s)
        s = re.sub(r"[\)\]\}]", " ", s)
        s = re.sub(
            r"\b(featuring|feat\.?|ft\.?|with|w/)\s+",
            " feat ", s
        )
        # Strip leading 'the ' from each artist name after feat marker
        s = re.sub(r"\bthe\s+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _subset_sort_ratio(self, s1, s2):
        """
        token_sort_ratio plus a subset boost:
        if ALL of s1's tokens appear in s2 (and s1 has ≥ 2 tokens), boost to
        at least 85. This handles files named with just the song title when
        Spotify appends '(with X feat. Y)' or version tags.

        Minimum 2 tokens prevents single-word titles ('War', 'Zombie') from
        accidentally hitting longer tracks they don't belong to.
        """
        base      = fuzz.token_sort_ratio(s1, s2)
        fn_tokens = set(s1.split())
        tr_tokens = set(s2.split())
        if len(fn_tokens) >= 2 and fn_tokens.issubset(tr_tokens):
            base = max(base, 85)
        return base

    def _sanitize(self, title):
        """Replace illegal filename characters with a space, collapse doubles."""
        cleaned = "".join(c if c not in r'\/*?:"<>|' else " " for c in title)
        return re.sub(r" {2,}", " ", cleaned).strip()

    _FEAT_IN_TITLE = re.compile(
        r'\(feat\.|\(ft\.|\(with\b|\bfeat\.|\bft\.|\bfeaturing\b', re.I
    )

    # When True, file names start with the track number: "01 - Title.mp3",
    # or "1-01 - Title.mp3" on multi-disc releases. The app sets this from
    # AppConfig.track_numbers.
    track_number_prefix = False

    @staticmethod
    def _naming(tracks):
        """(multi_disc, number_width) for a release's track list."""
        multi = len({t.get("disc", 1) for t in tracks}) > 1
        top = max((t.get("num", 0) for t in tracks), default=0)
        return multi, max(2, len(str(top)))

    def _track_filename(self, track, ext, multi_disc=False, width=2):
        """
        Append featured artists only when the Spotify title doesn't already
        embed featuring info. If the title contains any feat/ft/with marker
        the Spotify data already has the full info — don't double-append
        (catches alias mismatches like 'Machine Gun Kelly' vs 'MGK').
        """
        name     = self._sanitize(track["name"])
        featured = track.get("featured", [])
        if featured and not self._FEAT_IN_TITLE.search(track["name"]):
            title_lc  = track["name"].lower()
            new_feats = [a for a in featured if a.lower() not in title_lc]
            if new_feats:
                feat_str = " & ".join(self._sanitize(a) for a in new_feats)
                name = f"{name} ft. {feat_str}"
        if self.track_number_prefix:
            num = f"{track['num']:0{width}d}"
            if multi_disc:
                num = f"{track.get('disc', 1)}-{num}"
            name = f"{num} - {name}"
        return f"{name}{ext}"

    # ── Single-album preview ──────────────────────────────────────────────────

    def generate_preview(self, folder_path, tracks, f_offset=0):
        """
        NUMERIC: Match files (sorted alphabetically) to tracks in order.
        Output names follow _track_filename (optionally numbered).
        Returns ([(old, new, track_num, disc_num), …], log_string).
        """
        try:
            files = sorted(list_audio_files(folder_path))
        except Exception as e:
            return [], f"Error reading folder: {e}"

        ep_data, log = [], "NUMERIC MATCH:\n"
        naming = self._naming(tracks)
        for i, f in enumerate(files):
            idx = i + f_offset
            if 0 <= idx < len(tracks):
                ext      = os.path.splitext(f)[1]
                new_name = self._track_filename(tracks[idx], ext, *naming)
                ep_data.append((f, new_name, tracks[idx]["num"], tracks[idx].get("disc", 1), 100))
                log += f"  {f}\n  → {new_name}\n\n"
        return ep_data, log

    def generate_fuzzy_preview(self, folder_path, tracks, f_offset=0):
        """
        FUZZY: Match filenames to track names using token_sort_ratio (respects
        full track title including suffixes like Pt. II, feat., etc.).
        Strips leading track numbers and common scene tags before matching.
        Guards against duplicate output filenames by appending disc/track info.
        Returns ([(old, new, track_num, disc_num), …], log_string).
        """
        try:
            files = list_audio_files(folder_path)
        except Exception as e:
            return [], f"Error: {e}"

        track_map    = {t["name"]: t for t in tracks}
        track_titles = list(track_map.keys())

        # ── Detect ambiguous track names ──────────────────────────────────────
        # Count from the RAW tracks list (not track_map which deduplicates by name)
        # so that e.g. "War" on disc 1 AND disc 2 both get counted.
        from collections import Counter
        norm_counts     = Counter(self._normalize_for_matching(t["name"]) for t in tracks)
        ambiguous_norms = {n for n, c in norm_counts.items() if c > 1}

        # Pre-build normalized → original title map
        norm_map    = {self._normalize_for_matching(t): t for t in track_titles}
        norm_titles = list(norm_map.keys())

        temp_matches, log = [], "FUZZY MATCH:\n"
        files = sorted(files, key=str.casefold)   # deterministic tie-breaking

        # ── Score every file against every track ──────────────────────────────
        # Matches are then handed out best-score-first. Matching file by file
        # (in directory order) let one oddly named file steal a track and push
        # correctly named files onto the wrong tracks.
        def proc(s):
            return utils.full_process(s)          # what extractOne applied

        norm_procs = [(nt, proc(nt)) for nt in norm_titles]
        candidates, best_for_file = [], {}
        for fi, f in enumerate(files):
            fn_base = os.path.splitext(f)[0].replace(".", " ").replace("_", " ")
            fn_base = re.sub(
                r"(1080p|720p|x264|x265|HEVC|WEB-DL|BluRay|\d{3}kbps)",
                "", fn_base, flags=re.I
            )
            # Strip a leading "01 - " or multi-disc "1-01 - " track number.
            fn_base = re.sub(r"^(?:\d+\s*[-.]\s*)?\d+\s*[-.]\s*", "", fn_base).strip()
            fn_proc = proc(self._normalize_for_matching(fn_base))
            for ti, (nt, nt_proc) in enumerate(norm_procs):
                score = self._subset_sort_ratio(fn_proc, nt_proc) if fn_proc else 0
                if score > TRACK_MATCH_THRESHOLD:
                    candidates.append((-score, fi, ti, f, nt, score))
                    if score > best_for_file.get(f, (0, None))[0]:
                        best_for_file[f] = (score, nt)

        # ── Ambiguity guard ───────────────────────────────────────────────────
        # If a file's best match is a name shared by several tracks (e.g. "War"
        # on disc 1 and disc 2), don't guess — leave it for manual pairing.
        ambiguous_files = {f for f, (_, nt) in best_for_file.items()
                           if nt in ambiguous_norms}
        for f in files:
            if f in ambiguous_files:
                log += f"  AMBIGUOUS: {f}  (multiple tracks share this name — pair it manually)\n"

        used_files, used_tracks = set(), set()
        for _, _, _, f, nt, score in sorted(candidates):
            if f in used_files or nt in used_tracks or f in ambiguous_files \
                    or nt in ambiguous_norms:
                continue
            used_files.add(f)
            used_tracks.add(nt)
            track = track_map[norm_map[nt]]
            temp_matches.append({
                "old_name": f,
                "num":      track["num"],
                "disc":     track.get("disc", 1),
                "title":    track["name"],
                "track":    track,          # full track object for featured artists
                "score":    score,
            })

        for f in files:
            if f not in used_files and f not in ambiguous_files:
                log += f"  UNMATCHED: {f}  (pair it manually)\n"

        temp_matches.sort(key=lambda x: (x["disc"], x["num"]))

        # ── Duplicate output-name guard ───────────────────────────────────────
        # If two matches would produce the same filename (e.g. disc 1 "Zombie"
        # and disc 2 "Zombie (feat. Smashing Pumpkins)" both sanitize to
        # "Zombie.flac"), disambiguate by prefixing with disc or track number.
        seen_names = {}   # sanitized_name → first match index
        for m in temp_matches:
            key = self._sanitize(m["title"]).lower()
            if key in seen_names:
                # Mark both the earlier and current match as needing disambiguation
                seen_names[key].append(m)
            else:
                seen_names[key] = [m]

        # Numbered names are already unique per (disc, track).
        needs_disambig = set() if self.track_number_prefix else {
            id(m)
            for matches in seen_names.values() if len(matches) > 1
            for m in matches
        }

        ep_data = []
        naming = self._naming(tracks)
        for m in temp_matches:
            ext      = os.path.splitext(m["old_name"])[1]
            base_name = self._track_filename(m["track"], ext, *naming)

            if id(m) in needs_disambig:
                prefix   = (f"Disc {m['disc']} - " if m["disc"] > 1
                            else f"{m['num']:02d} - ")
                stem     = os.path.splitext(base_name)[0]
                new_name = f"{prefix}{stem}{ext}"
                note     = f" [disambiguated: {prefix.strip()}]"
            else:
                new_name = base_name
                note     = ""

            ep_data.append((m["old_name"], new_name, m["num"], m["disc"], m["score"]))
            log += f"  [{m['score']}%] {m['old_name']}\n  → {new_name}{note}\n\n"

        return ep_data, log

    # ── Batch preview ─────────────────────────────────────────────────────────

    def generate_batch_preview(self, artist_path, artist_id,
                               match_mode="Numeric", f_offset=0):
        """
        BATCH: Walk every album subfolder under artist_path, fuzzy-match each
        to a release from get_releases(), fetch its tracks, and build preview pairs.

        Returns a list of dicts:
            {folder, path, release (or None), score, ep_data, log}
        """
        try:
            album_folders = sorted([
                d for d in os.listdir(artist_path)
                if os.path.isdir(os.path.join(artist_path, d))
            ])
        except Exception:
            return []

        releases = self.get_releases(artist_id)
        if not releases:
            return []

        release_map    = {r["title"]: r for r in releases}
        release_titles = list(release_map.keys())
        results        = []

        for folder in album_folders:
            album_path = os.path.join(artist_path, folder)
            # Strip leading year / number prefix for cleaner matching
            clean_folder = re.sub(r"^\d{4}\s*[-\.]\s*", "", folder).strip()

            match = process.extractOne(
                clean_folder, release_titles, scorer=fuzz.token_set_ratio
            )
            score = match[1] if match else 0

            if match and score >= ALBUM_MATCH_THRESHOLD:
                release = release_map[match[0]]
                tracks  = self.get_tracks(release["id"])

                if tracks:
                    if match_mode == "Numeric":
                        ep_data, log = self.generate_preview(album_path, tracks, f_offset)
                    else:
                        ep_data, log = self.generate_fuzzy_preview(album_path, tracks, f_offset)

                    header = (
                        f"📁 {folder}\n"
                        f"   ↳ {release['title']} ({release['year']})  [{score}% match]\n"
                        f"   {len(ep_data)} files matched\n"
                    )
                    results.append({
                        "folder":  folder,
                        "path":    album_path,
                        "release": release,
                        "score":   score,
                        "ep_data": ep_data,
                        "log":     header + log,
                    })
                else:
                    results.append({
                        "folder": folder, "path": album_path,
                        "release": release, "score": score,
                        "ep_data": [],
                        "log": f"📁 {folder}\n   ↳ {release['title']} — no tracks found.\n",
                    })
            else:
                results.append({
                    "folder": folder, "path": album_path,
                    "release": None, "score": score,
                    "ep_data": [],
                    "log": f"📁 {folder}\n   ✗ No match found (best score: {score}%)\n",
                })

        return results