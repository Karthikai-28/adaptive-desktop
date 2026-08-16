#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import datetime
import difflib
import re
import shutil
import sys

REPO = Path.home() / "adaptive-desktop"
SOURCE_FILE = REPO / "vendor" / "NAUTILUS_SOURCE_PATH"

OLD_ID = "org.gnome.Nautilus"
NEW_ID = "com.karthi.AdaptiveFiles"

if not SOURCE_FILE.exists():
    raise SystemExit(f"Missing source pointer: {SOURCE_FILE}")

source = Path(SOURCE_FILE.read_text(encoding="utf-8").strip())
if not source.is_dir():
    raise SystemExit(f"Invalid source directory: {source}")

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
backup_root = REPO / "backups" / f"nautilus-phase1-identity-{stamp}"
backup_root.mkdir(parents=True, exist_ok=True)

changed: list[Path] = []
notes: list[str] = []


def backup(path: Path) -> None:
    rel = path.relative_to(source)
    dst = backup_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)


def write_change(path: Path, old: str, new: str) -> None:
    if old == new:
        return
    backup(path)
    path.write_text(new, encoding="utf-8")
    changed.append(path)


def patch_meson_application_id() -> bool:
    candidates = [
        source / "meson.build",
        source / "data" / "meson.build",
    ]

    patterns = [
        re.compile(
            r"(?m)^(\s*application_id\s*=\s*['\"])"
            + re.escape(OLD_ID)
            + r"(['\"]\s*)$"
        ),
        re.compile(
            r"(?m)^(\s*application[-_]id\s*:\s*['\"])"
            + re.escape(OLD_ID)
            + r"(['\"]\s*,?\s*)$"
        ),
    ]

    found = []

    for path in candidates:
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8")

        for pattern in patterns:
            matches = list(pattern.finditer(text))
            if matches:
                found.append((path, pattern, len(matches)))

    if not found:
        return False

    total = sum(count for _, _, count in found)

    if total != 1:
        print("FAIL CLOSED: expected exactly one Meson application-id definition.")
        for path, _, count in found:
            print(f"  {path}: {count} candidate(s)")
        raise SystemExit(20)

    path, pattern, _ = found[0]
    old = path.read_text(encoding="utf-8")
    new, n = pattern.subn(r"\1" + NEW_ID + r"\2", old, count=1)

    if n != 1:
        raise SystemExit("Internal patch error: Meson replacement count != 1")

    write_change(path, old, new)
    notes.append(f"Changed Meson application ID in {path.relative_to(source)}")
    return True


def patch_c_application_id() -> bool:
    candidates = []
    for path in (source / "src").rglob("*.[ch]"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        # Only consider occurrences that are clearly attached to the
        # GApplication application-id construction/setter. This is intentionally
        # narrow so we do not rename settings, schemas or unrelated interfaces.
        patterns = [
            re.compile(
                r'("application-id"\s*,\s*)"' + re.escape(OLD_ID) + r'"'
            ),
            re.compile(
                r'(g_application_set_application_id\s*\(\s*[^,]+,\s*)"'
                + re.escape(OLD_ID)
                + r'"'
            ),
        ]

        for pattern in patterns:
            if pattern.search(text):
                candidates.append((path, pattern))

    if not candidates:
        return False

    if len(candidates) != 1:
        print("FAIL CLOSED: application-id C location is ambiguous.")
        for path, _ in candidates:
            print(" ", path)
        raise SystemExit(21)

    path, pattern = candidates[0]
    old = path.read_text(encoding="utf-8")
    new, n = pattern.subn(r'\1"' + NEW_ID + '"', old, count=1)

    if n != 1:
        raise SystemExit("Internal patch error: C replacement count != 1")

    write_change(path, old, new)
    notes.append(f"Changed GApplication ID in {path.relative_to(source)}")
    return True


patched = patch_meson_application_id()
if not patched:
    patched = patch_c_application_id()

if not patched:
    print("FAIL CLOSED: could not identify the application ID definition safely.")
    print()
    print("Run:")
    print("  ./scripts/phase1-audit-identity.sh")
    print()
    print("Then inspect nautilus-identity-audit.txt.")
    raise SystemExit(22)

# Deliberately do NOT globally replace these:
#   org.gnome.nautilus          GSettings schemas
#   Nautilus-3.0                extension ABI/introspection
#   org.freedesktop.FileManager1 standard file-manager D-Bus API
notes.extend([
    "Preserved org.gnome.nautilus settings schema names.",
    "Preserved Nautilus-3.0 extension ABI/introspection names.",
    "Preserved org.freedesktop.FileManager1 for parity; dev coexistence is verified separately.",
])

report = REPO / "nautilus-phase1-identity.patch"
lines = []

for path in changed:
    rel = path.relative_to(source)
    before = (backup_root / rel).read_text(encoding="utf-8").splitlines(True)
    after = path.read_text(encoding="utf-8").splitlines(True)
    lines.extend(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )

report.write_text("".join(lines), encoding="utf-8")

print("Phase 1 identity isolation applied.")
print(f"Application ID: {OLD_ID} -> {NEW_ID}")
print()
for note in notes:
    print(" -", note)
print()
print("Backup:")
print(" ", backup_root)
print("Patch report:")
print(" ", report)
print()
print("Next:")
print("  ./scripts/phase1-rebuild-adaptive-files.sh")
