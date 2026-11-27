"""
file_ops.py
Collision-safe batch renaming.

Renames are staged through unique temporary names so that chains
(A → B while B → C) and case-only renames ("song.flac" → "Song.flac" on a
case-insensitive drive) work, and so that no file that isn't itself part of
the batch is ever overwritten.
"""

import os
import uuid


def _file_id(path):
    st = os.stat(path)
    return (st.st_dev, st.st_ino)


def _target_key(path):
    # Treat case variants as the same target: the library may live on a
    # case-insensitive drive (NTFS / exFAT / APFS) even when the OS is Linux.
    return os.path.normcase(os.path.abspath(path)).casefold()


def safe_rename_batch(moves):
    """
    Rename every (old_path, new_path) in `moves` without overwriting anything.

    A move is skipped (and reported) when its target is occupied by a file
    that is not itself being moved away, or when two moves claim the same
    target. A skipped move leaves its file under its original name.

    Returns (done, errors):
        done   – [(old_path, new_path), …] for every move that completed
        errors – human-readable strings for every move that was skipped
    """
    errors  = []
    pending = [(o, n) for o, n in moves
               if o != n and os.path.lexists(o)]

    # ── Plan: drop moves whose target is taken ────────────────────────────────
    # Repeat until stable — dropping a move means its file stays put, which can
    # block another move that was targeting that name.
    while True:
        moving = set()
        for o, _ in pending:
            try:
                moving.add(_file_id(o))
            except OSError:
                pass

        claimed, keep, dropped = set(), [], False
        for o, n in pending:
            key = _target_key(n)
            occupied = False
            if os.path.lexists(n):
                try:
                    occupied = _file_id(n) not in moving
                except OSError:
                    occupied = True
            if key in claimed:
                errors.append(f"{os.path.basename(o)}: another file is already "
                              f"being renamed to '{os.path.basename(n)}' — skipped")
                dropped = True
            elif occupied:
                errors.append(f"{os.path.basename(o)}: '{os.path.basename(n)}' "
                              f"already exists — skipped")
                dropped = True
            else:
                claimed.add(key)
                keep.append((o, n))
        pending = keep
        if not dropped:
            break

    # ── Phase 1: move every source to a unique temporary name ─────────────────
    staged = []
    for o, n in pending:
        tmp = os.path.join(os.path.dirname(o),
                           f".artisync-{uuid.uuid4().hex}.tmp")
        try:
            os.rename(o, tmp)
            staged.append((o, n, tmp))
        except OSError as e:
            errors.append(f"{os.path.basename(o)}: {e}")

    # ── Phase 2: move each temporary file to its final name ───────────────────
    # Falls back to the original name if the target turned out to be taken
    # (e.g. a phase-1 failure left a file in place).
    done = []
    for o, n, tmp in staged:
        placed = None
        for dest in (n, o):
            if os.path.lexists(dest):
                continue
            try:
                os.rename(tmp, dest)
                placed = dest
                break
            except OSError:
                continue
        if placed == n:
            done.append((o, n))
        elif placed == o:
            errors.append(f"{os.path.basename(o)}: could not be renamed to "
                          f"'{os.path.basename(n)}' — left unchanged")
        else:
            errors.append(f"{os.path.basename(o)}: could not be renamed; the file "
                          f"was left as '{os.path.basename(tmp)}'")
    return done, errors
