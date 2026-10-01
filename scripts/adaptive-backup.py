#!/usr/bin/env python3
"""Take Adaptive Desktop's settings with you, and keep backups clean.

    adaptive-backup.py export [FILE]      one archive of your Adaptive settings
    adaptive-backup.py import FILE        put them back (--dry-run to look first)
    adaptive-backup.py show FILE          what an archive holds
    adaptive-backup.py dconf-snapshot [FILE]
                                          a full dconf dump with private data
                                          removed, for the repo's backups/

What an export holds: the files in ~/.config/adaptive-desktop (the project
registry, dock, shade, snippets, your commands and templates), optionally your
notes (--notes), and the handful of GNOME settings Adaptive owns - its
shortcuts, workspace names and count, favourite apps. It is a named list, not
a dump of everything, so nothing private rides along.

Import never overwrites silently: the files it replaces are first copied to
~/.config/adaptive-desktop.before-import-<time>.

The dconf snapshot exists because a raw `dconf dump /` once carried a
calendar's worth of colleagues' addresses into this repository. It removes the
sections that hold accounts, mail, calendars and contacts, and any single
value that contains an email address or is too large to be a setting.
"""

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "adaptive-desktop"
NOTES_DIR = Path.home() / ".local" / "share" / "adaptive-desktop" / "notes"
FORMAT = 1

# Files in the config folder that are this machine's history, not settings.
SKIP_CONFIG = re.compile(r"^(last-.*-backup|.*-relogin-required|session-state\.json|.*\.tmp)$")
SKIP_CONFIG_DIRS = {"snapshots"}

# dconf directory -> the keys to carry (None for all of them).
DCONF_KEYS = {
    "/org/gnome/desktop/wm/preferences/": ("workspace-names", "num-workspaces"),
    "/org/gnome/mutter/": ("dynamic-workspaces", "workspaces-only-on-primary"),
    "/org/gnome/shell/": ("favorite-apps",),
    "/org/gnome/settings-daemon/plugins/media-keys/": ("custom-keybindings",),
}
CUSTOM_KEYS_DIR = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"

# ------------------------------------------------------------ dconf redaction

# A section is private if any word of its path is one of these. Whole words,
# so "thumbnailers" is not mistaken for "mail".
PRIVATE_WORDS = {
    "evolution", "accounts", "goa", "contacts", "geary", "calendar", "recent", "history",
    "keyring", "seahorse", "epiphany", "tracker", "mail", "chat", "telepathy", "maps",
}


def is_private_section(header):
    return any(word in PRIVATE_WORDS for word in re.split(r"[^a-z0-9]+", header.lower()))


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
MAX_VALUE_CHARS = 4000


def redact_dconf(text):
    """(clean_text, report) for a `dconf dump` output.

    report counts what was removed: {"sections": n, "values": n}.
    """
    kept = []
    report = {"sections": 0, "values": 0}
    section = []
    private = False

    def flush():
        # A section left with only its header says nothing; drop it too.
        if section and not private and any(line.strip() for line in section[1:]):
            kept.extend(section)

    for line in text.splitlines():
        if line.startswith("[") and line.rstrip().endswith("]"):
            flush()
            section = [line]
            private = is_private_section(line)
            if private:
                report["sections"] += 1
            continue
        if private:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            # GNOME extension ids are written like addresses (name@author.site)
            # and are not; the lists of them are settings worth keeping.
            looks_private = EMAIL.search(value) and "extensions" not in key
            if len(line) > MAX_VALUE_CHARS or looks_private:
                report["values"] += 1
                continue
        section.append(line)
    flush()
    return "\n".join(kept).rstrip("\n") + "\n", report


def filter_keys(dump, keys):
    """A `dconf dump <dir>` output reduced to the top section's named keys."""
    out = []
    top = False
    for line in dump.splitlines():
        if line.startswith("["):
            top = line.strip() == "[/]"
            if top:
                out.append(line)
            continue
        if top and line.split("=", 1)[0] in keys:
            out.append(line)
    return "\n".join(out) + "\n" if len(out) > 1 else ""


def filter_adaptive_shortcuts(dump):
    """custom-keybindings dump -> only the adaptive-* slots."""
    out = []
    keep = False
    for line in dump.splitlines():
        if line.startswith("["):
            keep = line.strip("[]").startswith("adaptive-")
        if keep:
            out.append(line)
    return "\n".join(out) + "\n" if out else ""


def dconf(*args, stdin=None):
    try:
        done = subprocess.run(["dconf", *args], input=stdin, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return done.returncode == 0, done.stdout if done.returncode == 0 else done.stderr


# ------------------------------------------------------------------- export

def config_files(config_dir=None):
    """The settings files to carry, relative to the config folder."""
    config_dir = config_dir or CONFIG_DIR
    found = []
    if not config_dir.is_dir():
        return found
    for path in sorted(config_dir.rglob("*")):
        relative = path.relative_to(config_dir)
        if (path.is_symlink() or not path.is_file() or SKIP_CONFIG.match(path.name)
                or relative.parts[0] in SKIP_CONFIG_DIRS):
            continue
        found.append(relative)
    return found


def gather_dconf(dump=dconf):
    """{archive name: text} for the GNOME settings Adaptive owns."""
    parts = {}
    for directory, keys in DCONF_KEYS.items():
        ok, text = dump("dump", directory)
        chosen = filter_keys(text, keys) if ok else ""
        if chosen:
            parts[directory] = chosen
    ok, text = dump("dump", CUSTOM_KEYS_DIR)
    shortcuts = filter_adaptive_shortcuts(text) if ok else ""
    if shortcuts:
        parts[CUSTOM_KEYS_DIR] = shortcuts
    return parts


def _add(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(data))


def export(target, notes=False, config_dir=None, notes_dir=None, dump=dconf):
    config_dir = config_dir or CONFIG_DIR
    notes_dir = notes_dir or NOTES_DIR
    files = config_files(config_dir)
    dconf_parts = gather_dconf(dump)
    note_files = sorted(p.relative_to(notes_dir) for p in notes_dir.rglob("*")
                        if p.is_file() and not p.is_symlink()) if notes and notes_dir.is_dir() else []

    manifest = {
        "format": FORMAT,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": [str(f) for f in files],
        "dconf": sorted(dconf_parts),
        "notes": [str(f) for f in note_files],
    }
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w:gz") as archive:
        _add(archive, "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
        for relative in files:
            _add(archive, f"config/{relative}", (config_dir / relative).read_bytes())
        for index, directory in enumerate(sorted(dconf_parts)):
            _add(archive, f"dconf/{index}.ini", dconf_parts[directory].encode())
        for relative in note_files:
            _add(archive, f"notes/{relative}", (notes_dir / relative).read_bytes())
    target.chmod(0o600)
    return manifest


# ------------------------------------------------------------------- import

def read_archive(source):
    """(manifest, {member name: bytes}); raises ValueError on anything odd.

    Only plain files under config/, dconf/ and notes/ are accepted, with no
    absolute paths and no "..": an archive is someone else's input.
    """
    members = {}
    with tarfile.open(source, "r:gz") as archive:
        for info in archive.getmembers():
            name = info.name
            parts = Path(name).parts
            if (not info.isfile() or name.startswith("/") or ".." in parts
                    or (name != "manifest.json" and parts[0] not in ("config", "dconf", "notes"))):
                raise ValueError(f"unexpected entry in the archive: {name}")
            members[name] = archive.extractfile(info).read()
    try:
        manifest = json.loads(members.pop("manifest.json"))
    except (KeyError, ValueError):
        raise ValueError("not an Adaptive settings archive (no manifest)") from None
    if manifest.get("format") != FORMAT:
        raise ValueError(f"archive format {manifest.get('format')} is not supported")
    return manifest, members


def restore(source, dry_run=False, config_dir=None, notes_dir=None, load=dconf):
    """Put an archive's contents back. Returns the lines describing what was
    (or would be) done."""
    config_dir = config_dir or CONFIG_DIR
    notes_dir = notes_dir or NOTES_DIR
    manifest, members = read_archive(source)
    done = []

    config = {n[len("config/"):]: d for n, d in members.items() if n.startswith("config/")}
    replaced = [n for n in config if (config_dir / n).exists() and (config_dir / n).read_bytes() != config[n]]
    if replaced and not dry_run:
        backup = config_dir.with_name(f"{config_dir.name}.before-import-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copytree(config_dir, backup, symlinks=True)
        done.append(f"kept the current settings in {backup}")
    for name, data in sorted(config.items()):
        target = config_dir / name
        if target.exists() and target.read_bytes() == data:
            continue
        done.append(f"{'would write' if dry_run else 'wrote'} {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            # Your own commands have to stay runnable.
            if Path(name).parts[0] == "commands":
                target.chmod(0o700)

    for name, data in sorted((n[len("notes/"):], d) for n, d in members.items() if n.startswith("notes/")):
        target = notes_dir / name
        if target.exists():
            done.append(f"left {target} as it is (notes are never overwritten)")
            continue
        done.append(f"{'would write' if dry_run else 'wrote'} {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    directories = manifest.get("dconf", [])
    for index, directory in enumerate(directories):
        text = members.get(f"dconf/{index}.ini", b"").decode()
        if not text or not isinstance(directory, str) or not directory.startswith("/org/gnome/"):
            continue
        done.append(f"{'would load' if dry_run else 'loaded'} settings under {directory}")
        if not dry_run:
            ok, message = load("load", directory, stdin=text)
            if not ok:
                done.append(f"  failed: {message.strip()}")
    return done


# --------------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description="Export, import and back up Adaptive settings")
    sub = parser.add_subparsers(dest="action", required=True)
    export_p = sub.add_parser("export", help="Write an archive of your Adaptive settings")
    export_p.add_argument("file", nargs="?", help="Default: ~/adaptive-settings-<date>.tar.gz")
    export_p.add_argument("--notes", action="store_true", help="Include your quick notes")
    import_p = sub.add_parser("import", help="Restore an archive")
    import_p.add_argument("file")
    import_p.add_argument("--dry-run", action="store_true", help="Say what would change, change nothing")
    show_p = sub.add_parser("show", help="List what an archive holds")
    show_p.add_argument("file")
    snap_p = sub.add_parser("dconf-snapshot", help="A redacted full dconf dump")
    snap_p.add_argument("file", nargs="?", help="Default: print it")
    args = parser.parse_args(argv)

    if args.action == "export":
        target = args.file or str(Path.home() / f"adaptive-settings-{time.strftime('%Y%m%d')}.tar.gz")
        manifest = export(target, notes=args.notes)
        print(f"Wrote {target}: {len(manifest['config'])} settings file(s), "
              f"{len(manifest['dconf'])} group(s) of GNOME settings, {len(manifest['notes'])} note file(s).")
        return 0

    if args.action in ("import", "show"):
        try:
            if args.action == "show":
                manifest, _members = read_archive(args.file)
                print(f"Created {manifest.get('created', '?')}")
                for kind in ("config", "dconf", "notes"):
                    for name in manifest.get(kind, []):
                        print(f"  {kind:<6} {name}")
                return 0
            lines = restore(args.file, dry_run=args.dry_run)
        except (OSError, tarfile.TarError, ValueError) as error:
            print(f"Cannot read {args.file}: {error}", file=sys.stderr)
            return 1
        print("\n".join(lines) if lines else "Nothing to change: this machine already matches the archive.")
        if lines and not args.dry_run:
            print("Log out and in (or restart the Project Context Service) for everything to take effect.")
        return 0

    ok, text = dconf("dump", "/")
    if not ok:
        print(f"dconf dump failed: {text}", file=sys.stderr)
        return 1
    clean, report = redact_dconf(text)
    if args.file:
        Path(args.file).write_text(clean, encoding="utf-8")
        print(f"Wrote {args.file}; removed {report['sections']} private section(s) "
              f"and {report['values']} value(s).")
    else:
        sys.stdout.write(clean)
    return 0


if __name__ == "__main__":
    sys.exit(main())
