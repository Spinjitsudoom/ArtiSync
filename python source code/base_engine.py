"""
base_engine.py
Shared file-matching logic inherited by MBEngine and SpotifyEngine.
Both engines expose the same interface so music_organizer can swap them freely.
"""

import os
import re
from thefuzz import process, fuzz

# Minimum fuzzy score (0–100) to accept a match.
# Lower = more permissive, higher = stricter.
TRACK_MATCH_THRESHOLD  = 30   # file → track name match
ALBUM_MATCH_THRESHOLD  = 80   # folder → release title match (batch mode)


class BaseEngine:

    # ── Filename sanitizer ────────────────────────────────────────────────────

    def _normalize_for_matching(self, title):
        """
        Normalise a title for fuzzy comparison only — never used for output names.
        Handles all common 'featuring' formats and strips 'The' prefixes.
        """
        s = title.lower()
        s = re.sub(r"[\(\[\{]", " ", s)
        s = re.sub(r"[\)\]\}]", " ", s)
        s = re.sub(r"\b(featuring|feat\.?|ft\.?|with|w/)\s+", " feat ", s)
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
        """
        Normalise a title for fuzzy comparison only — never used for output names.

        Handles all common 'featuring' formats:
          ft. / feat. / featuring / with / w/ / (ft. …) / [feat. …]
        Strips 'The ' prefix from artist names so 'The Smashing Pumpkins'
        matches 'Smashing Pumpkins'.
        Lowercases and collapses whitespace.
        """
        s = title.lower()

        # Normalise all featuring variations to a plain space-separated token
        # so "feat.", "ft.", "featuring", "w/", "with" all look the same
        s = re.sub(r"[\(\[\{]", " ", s)
        s = re.sub(r"[\)\]\}]", " ", s)
        s = re.sub(
            r"\b(featuring|feat\.?|ft\.?|with|w/)\s+",
            " feat ", s
        )

        # Strip leading 'the ' from each artist name after feat marker
        # e.g. "feat the smashing pumpkins" → "feat smashing pumpkins"
        s = re.sub(r"\bthe\s+", " ", s)

        # Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _sanitize(self, title):
        """Replace illegal filename characters with a space, collapse doubles."""
        cleaned = "".join(c if c not in r'\/*?:"<>|' else " " for c in title)
        return re.sub(r" {2,}", " ", cleaned).strip()

    _FEAT_IN_TITLE = re.compile(
        r'\(feat\.|\(ft\.|\(with\b|\bfeat\.|\bft\.|\bfeaturing\b', re.I
    )

    def _track_filename(self, track, ext):
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
        return f"{name}{ext}"

    # ── Single-album preview ──────────────────────────────────────────────────

    def generate_preview(self, folder_path, tracks, f_offset=0):
        """
        NUMERIC: Match files (sorted alphabetically) to tracks in order.
        No track-number prefix on output filenames.
        Returns ([(old, new, track_num, disc_num), …], log_string).
        """
        try:
            files = sorted([
                f for f in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, f))
            ])
        except Exception as e:
            return [], f"Error reading folder: {e}"

        ep_data, log = [], "NUMERIC MATCH:\n"
        for i, f in enumerate(files):
            idx = i + f_offset
            if 0 <= idx < len(tracks):
                ext      = os.path.splitext(f)[1]
                new_name = self._track_filename(tracks[idx], ext)
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
            files = [
                f for f in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, f))
            ]
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
        used_tracks  = set()   # track names already claimed — one file per track

        for f in files:
            fn_base = os.path.splitext(f)[0].replace(".", " ").replace("_", " ")
            fn_base = re.sub(
                r"(1080p|720p|x264|x265|HEVC|WEB-DL|BluRay|\d{3}kbps)",
                "", fn_base, flags=re.I
            )
            fn_base = re.sub(r"^\d+\s*[-\.]\s*", "", fn_base).strip()
            fn_norm = self._normalize_for_matching(fn_base)

            remaining_norm = [t for t in norm_titles
                              if norm_map[t] not in used_tracks]
            if not remaining_norm:
                log += f"  SKIPPED (no tracks left): {f}\n"
                continue

            match = process.extractOne(fn_norm, remaining_norm,
                                       scorer=self._subset_sort_ratio)
            if match and match[1] > TRACK_MATCH_THRESHOLD:
                matched_norm   = match[0]
                original_title = norm_map[matched_norm]

                # ── Ambiguity guard ───────────────────────────────────────────
                # If this normalized name maps to multiple tracks (e.g. "War"
                # on disc 1 and disc 2), skip auto-matching and let the user
                # decide manually in the pairing dialog.
                if matched_norm in ambiguous_norms:
                    log += f"  AMBIGUOUS: {f}  (multiple tracks share this name — use manual pairing)\n"
                    continue

                track = track_map[original_title]
                used_tracks.add(original_title)
                temp_matches.append({
                    "old_name": f,
                    "num":      track["num"],
                    "disc":     track.get("disc", 1),
                    "title":    track["name"],
                    "track":    track,          # full track object for featured artists
                    "score":    match[1],
                })
            else:
                log += f"  UNMATCHED: {f}  (see manual pairing dialog)\n"

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

        needs_disambig = {
            id(m)
            for matches in seen_names.values() if len(matches) > 1
            for m in matches
        }

        ep_data = []
        for m in temp_matches:
            ext      = os.path.splitext(m["old_name"])[1]
            base_name = self._track_filename(m["track"], ext)

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