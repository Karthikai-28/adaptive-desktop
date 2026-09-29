"""Finder-style colour tags.

A file's tags live in its GVfs metadata (metadata::adaptive-tags, a comma
list), so they follow the file when Files moves or renames it. Finding by tag
works through folders of links, one per colour, under
~/.local/share/adaptive-files/Tags - a sidebar bookmark opens them like any
folder, and Files' own search and sorting work inside.

Tag colours are Apple's tag colours. They are the one place hues other than
the accent appear as decoration: a tag is the user's own label, and matching
Finder is what makes a red tag read as "red tag".
"""

import json
import os
import threading
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

ATTRIBUTE = "metadata::adaptive-tags"

TAGS = (
    ("red", "Red", "#FF453A"),
    ("orange", "Orange", "#FF9F0A"),
    ("yellow", "Yellow", "#FFD60A"),
    ("green", "Green", "#30D158"),
    ("blue", "Blue", "#0A84FF"),
    ("purple", "Purple", "#BF5AF2"),
    ("grey", "Grey", "#98989D"),
)
TAG_IDS = [tag for tag, _label, _color in TAGS]
LABELS = {tag: label for tag, label, _color in TAGS}
COLORS = {tag: color for tag, _label, color in TAGS}

DATA = Path(GLib.get_user_data_dir()) / "adaptive-files"
INDEX = DATA / "tags.json"
ROOT = DATA / "Tags"
BOOKMARKS = Path(GLib.get_user_config_dir()) / "gtk-3.0" / "bookmarks"

_lock = threading.Lock()


def get(gfile):
    try:
        info = gfile.query_info(ATTRIBUTE, Gio.FileQueryInfoFlags.NONE, None)
        value = info.get_attribute_string(ATTRIBUTE) or ""
    except GLib.Error:
        return []
    return [tag for tag in value.split(",") if tag in LABELS]


def set_tags(gfile, tags):
    ordered = [tag for tag in TAG_IDS if tag in set(tags)]
    gfile.set_attribute_string(ATTRIBUTE, ",".join(ordered), Gio.FileQueryInfoFlags.NONE, None)

    path = gfile.get_path()
    if path:
        with _lock:
            index = _load_index()
            if ordered:
                index[path] = ordered
            else:
                index.pop(path, None)
            _save_index(index)
        rebuild_folders()
    return ordered


def toggle(gfiles, tag):
    """Add tag to every file, or take it off all of them if they all have
    it already - the Finder menu's behaviour."""
    current = [get(gfile) for gfile in gfiles]
    remove = all(tag in tags for tags in current)
    for gfile, tags in zip(gfiles, current):
        wanted = [t for t in tags if t != tag] if remove else tags + [tag]
        set_tags(gfile, wanted)
    return not remove


def clear(gfiles):
    for gfile in gfiles:
        set_tags(gfile, [])


def _load_index():
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(index):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = INDEX.with_suffix(".tmp")
    temp.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temp, INDEX)


def rebuild_folders():
    """Recreate the link folders from the index, dropping files that no
    longer exist. Only links are ever removed from these folders."""
    with _lock:
        index = _load_index()
        alive = {path: tags for path, tags in index.items() if os.path.lexists(path)}
        if alive != index:
            _save_index(alive)

        for tag in TAG_IDS:
            folder = ROOT / LABELS[tag]
            if folder.exists():
                for entry in folder.iterdir():
                    if entry.is_symlink():
                        entry.unlink()

        used = {}
        for path, tags in sorted(alive.items()):
            for tag in tags:
                folder = ROOT / LABELS[tag]
                folder.mkdir(parents=True, exist_ok=True)
                name = os.path.basename(path.rstrip("/")) or "item"
                stem, suffix = os.path.splitext(name)
                key = (tag, name)
                count = used.get(key, 0)
                used[key] = count + 1
                link = folder / (name if count == 0 else f"{stem} ({count + 1}){suffix}")
                try:
                    link.symlink_to(path)
                except OSError:
                    pass

        # Empty colour folders go, so the Tags folder lists only tags in use.
        for tag in TAG_IDS:
            folder = ROOT / LABELS[tag]
            if folder.exists() and not any(folder.iterdir()):
                folder.rmdir()

    ensure_bookmark()


def ensure_bookmark():
    """One "Tags" entry in the sidebar, added the first time anything is
    tagged and never duplicated."""
    ROOT.mkdir(parents=True, exist_ok=True)
    uri = Gio.File.new_for_path(str(ROOT)).get_uri()
    try:
        lines = BOOKMARKS.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if any(line.split(" ", 1)[0] == uri for line in lines):
        return
    BOOKMARKS.parent.mkdir(parents=True, exist_ok=True)
    lines.append(f"{uri} Tags")
    BOOKMARKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
