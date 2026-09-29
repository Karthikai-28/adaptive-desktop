"""Finding reclaimable space: duplicate files, old installers, checksums.

Duplicates are found by content, not name: files are grouped by size, then
by a hash of their first 64 KB, and only files still tied are hashed in
full. Both passes are bounded so a huge folder costs seconds, not minutes.
"""

import hashlib
import os
import time

DUPLICATE_MIN_BYTES = 64 * 1024
PARTIAL_BYTES = 64 * 1024
DUPLICATE_SECONDS = 8.0
DUPLICATE_MAX_HASH_BYTES = 6 * 1024 ** 3

OLD_DAYS = 90
OLD_SUFFIXES = (
    ".appimage", ".deb", ".rpm", ".snap", ".flatpak", ".run", ".exe", ".msi",
    ".dmg", ".pkg", ".iso", ".img", ".zip", ".7z", ".rar", ".tar", ".gz",
    ".tgz", ".xz", ".bz2", ".zst", ".whl",
)


def _hash(path, limit=None, chunk=1024 * 1024):
    digest = hashlib.blake2b(digest_size=20)
    remaining = limit
    with open(path, "rb") as handle:
        while True:
            size = chunk if remaining is None else min(chunk, remaining)
            if size <= 0:
                break
            block = handle.read(size)
            if not block:
                break
            digest.update(block)
            if remaining is not None:
                remaining -= len(block)
    return digest.hexdigest()


def find_duplicates(records):
    """records: [(size, path)]. Returns (groups, complete) where groups is
    [{"bytes": size, "paths": [...], "reclaimable": size * (n - 1)}],
    largest reclaimable first."""
    started = time.monotonic()
    by_size = {}
    for size, path in records:
        if size >= DUPLICATE_MIN_BYTES:
            by_size.setdefault(size, []).append(path)

    candidates = [(size, paths) for size, paths in by_size.items() if len(paths) > 1]
    candidates.sort(key=lambda item: item[0], reverse=True)

    groups = []
    hashed = 0
    complete = True
    for size, paths in candidates:
        if time.monotonic() - started > DUPLICATE_SECONDS or hashed > DUPLICATE_MAX_HASH_BYTES:
            complete = False
            break

        by_head = {}
        for path in paths:
            try:
                by_head.setdefault(_hash(path, PARTIAL_BYTES), []).append(path)
            except OSError:
                continue
        for same_head in by_head.values():
            if len(same_head) < 2:
                continue
            if size <= PARTIAL_BYTES:
                matches = [same_head]
            else:
                by_full = {}
                for path in same_head:
                    try:
                        by_full.setdefault(_hash(path), []).append(path)
                        hashed += size
                    except OSError:
                        continue
                matches = [group for group in by_full.values() if len(group) > 1]
            for match in matches:
                groups.append(
                    {"bytes": size, "paths": sorted(match), "reclaimable": size * (len(match) - 1)}
                )

    groups.sort(key=lambda group: group["reclaimable"], reverse=True)
    return groups, complete


def old_installers(children, now=None):
    """Top-level installers and archives neither changed nor opened for
    OLD_DAYS. children are the scan's entries (need atime/mtime)."""
    now = now or time.time()
    cutoff = now - OLD_DAYS * 86400
    found = []
    for child in children:
        if child.get("is_dir"):
            continue
        name = child["name"].casefold()
        if not name.endswith(OLD_SUFFIXES):
            continue
        last = max(child.get("mtime", now), child.get("atime", 0))
        if last < cutoff:
            found.append(child)
    found.sort(key=lambda child: child["bytes"], reverse=True)
    return found


def sha256(path, progress=None, cancelled=None):
    """Full SHA-256 of path. progress(fraction) is called now and then;
    cancelled() returning True stops early with None."""
    total = os.path.getsize(path) or 1
    digest = hashlib.sha256()
    done = 0
    last_report = 0.0
    with open(path, "rb") as handle:
        while True:
            if cancelled is not None and cancelled():
                return None
            block = handle.read(4 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
            done += len(block)
            if progress is not None and time.monotonic() - last_report > 0.15:
                last_report = time.monotonic()
                progress(done / total)
    return digest.hexdigest()
