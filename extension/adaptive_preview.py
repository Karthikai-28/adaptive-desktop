#!/usr/bin/env python3
"""
Adaptive Files Preview / Storage / Network inspector
Target: Nautilus 42.x / libnautilus-extension 3.0 / GTK 3

This extension is intentionally presentation-only:
- Nautilus remains responsible for selection, double-click, file operations,
  Trash, MIME, permissions, bookmarks, devices, GVfs and remote access.
- Single-click selection is observed and represented in a right-side inspector.
"""

from __future__ import annotations

import concurrent.futures
import datetime as _dt
import hashlib
import html
import math
import os
from pathlib import Path
import shutil
import json
import stat
import subprocess
import time
import traceback
import weakref

import gi

gi.require_version("Nautilus", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GnomeDesktop", "3.0")

try:
    gi.require_version("GtkSource", "4")
    from gi.repository import GtkSource
    HAS_GTKSOURCE = True
except (ValueError, ImportError):
    GtkSource = None
    HAS_GTKSOURCE = False

from gi.repository import (
    GObject,
    Gio,
    GLib,
    Gtk,
    Gdk,
    GdkPixbuf,
    GnomeDesktop,
    Nautilus,
    Pango,
)

PANEL_WIDE = 326
PANEL_MEDIUM = 294
PANEL_NARROW = 264

CACHE_DIR = Path.home() / ".cache" / "adaptive-files" / "previews"
LOG_PATH = Path.home() / ".cache" / "adaptive-files" / "preview-extension.log"

TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log",
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".c", ".h", ".cpp", ".cxx", ".cc", ".hpp", ".hxx",
    ".java", ".kt", ".kts", ".rs", ".go",
    ".sh", ".bash", ".zsh", ".fish",
    ".json", ".jsonc", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".scss",
    ".csv", ".sql", ".cmake", ".lua", ".rb", ".php", ".swift",
    ".ino", ".cu", ".cuh", ".proto", ".ipynb",
}

IMAGE_MIME_PREFIX = "image/"
PDF_MIME = "application/pdf"

LANGUAGE_RULES = {
    ".py": ("Python source", "text-x-python"),
    ".pyw": ("Python source", "text-x-python"),
    ".c": ("C source", "text-x-csrc"),
    ".h": ("C / C++ header", "text-x-chdr"),
    ".cpp": ("C++ source", "text-x-c++src"),
    ".cxx": ("C++ source", "text-x-c++src"),
    ".cc": ("C++ source", "text-x-c++src"),
    ".hpp": ("C++ header", "text-x-c++hdr"),
    ".hxx": ("C++ header", "text-x-c++hdr"),
    ".js": ("JavaScript source", "application-javascript"),
    ".mjs": ("JavaScript module", "application-javascript"),
    ".cjs": ("JavaScript source", "application-javascript"),
    ".jsx": ("JavaScript / JSX", "application-javascript"),
    ".ts": ("TypeScript source", "text-x-typescript"),
    ".tsx": ("TypeScript / TSX", "text-x-typescript"),
    ".java": ("Java source", "text-x-java"),
    ".kt": ("Kotlin source", "text-x-kotlin"),
    ".kts": ("Kotlin script", "text-x-kotlin"),
    ".rs": ("Rust source", "text-x-rust"),
    ".go": ("Go source", "text-x-go"),
    ".sh": ("Shell script", "text-x-shellscript"),
    ".bash": ("Bash script", "text-x-shellscript"),
    ".zsh": ("Zsh script", "text-x-shellscript"),
    ".fish": ("Fish script", "text-x-shellscript"),
    ".json": ("JSON document", "application-json"),
    ".jsonc": ("JSON document", "application-json"),
    ".yaml": ("YAML document", "text-x-yaml"),
    ".yml": ("YAML document", "text-x-yaml"),
    ".toml": ("TOML document", "text-x-toml"),
    ".xml": ("XML document", "application-xml"),
    ".html": ("HTML document", "text-html"),
    ".htm": ("HTML document", "text-html"),
    ".css": ("CSS stylesheet", "text-css"),
    ".scss": ("SCSS stylesheet", "text-x-scss"),
    ".md": ("Markdown document", "text-markdown"),
    ".rst": ("reStructuredText", "text-x-rst"),
    ".sql": ("SQL source", "text-x-sql"),
    ".cmake": ("CMake source", "text-x-cmake"),
    ".lua": ("Lua source", "text-x-lua"),
    ".rb": ("Ruby source", "text-x-ruby"),
    ".php": ("PHP source", "text-x-php"),
    ".swift": ("Swift source", "text-x-swift"),
    ".ino": ("Arduino source", "text-x-arduino"),
    ".cu": ("CUDA source", "text-x-cuda"),
    ".cuh": ("CUDA header", "text-x-cuda"),
    ".proto": ("Protocol Buffers", "text-x-protobuf"),
    ".ipynb": ("Jupyter notebook", "application-x-ipynb+json"),
}

BASENAME_RULES = {
    "makefile": ("Makefile", "text-x-makefile"),
    "gnumakefile": ("Makefile", "text-x-makefile"),
    "cmakelists.txt": ("CMake source", "text-x-cmake"),
    "dockerfile": ("Dockerfile", "text-x-dockerfile"),
    "containerfile": ("Containerfile", "text-x-dockerfile"),
}

MIME_RULES = {
    "text/x-python": ("Python source", "text-x-python"),
    "text/x-c": ("C source", "text-x-csrc"),
    "text/x-c++": ("C++ source", "text-x-c++src"),
    "text/x-java": ("Java source", "text-x-java"),
    "text/javascript": ("JavaScript source", "application-javascript"),
    "application/javascript": ("JavaScript source", "application-javascript"),
    "application/json": ("JSON document", "application-json"),
    "application/xml": ("XML document", "application-xml"),
    "text/html": ("HTML document", "text-html"),
    "text/css": ("CSS stylesheet", "text-css"),
    "text/markdown": ("Markdown document", "text-markdown"),
    "text/x-shellscript": ("Shell script", "text-x-shellscript"),
}

_CONTROLLERS = {}

# Nautilus instantiates this extension once per provider interface it
# implements, so every instance is asked to contribute context-menu items and
# the same entry appeared three times. One instance owns the menu.
_MENU_OWNER = None
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
# Home measurement can take minutes on a cold cache; it gets its own thread so
# it never queues ahead of a preview.
_SLOW_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def _log(message):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().isoformat(timespec="seconds")
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def _log_exception(prefix):
    _log(prefix + "\n" + traceback.format_exc())


def _css(widget, *classes):
    context = widget.get_style_context()
    for name in classes:
        context.add_class(name)
    return widget


def _type_name(widget):
    try:
        return GObject.type_name(widget.__gtype__)
    except Exception:
        return type(widget).__name__


def _walk(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        try:
            children = widget.get_children()
        except Exception:
            children = []
        for child in children:
            yield from _walk(child)


def _ancestors(widget):
    current = widget
    result = []
    while current is not None:
        result.append(_type_name(current))
        try:
            current = current.get_parent()
        except Exception:
            current = None
    return result


def _human_size(value):
    # GLib's decimal units, the same ones the Files status bar and the
    # Properties dialog print, so a file never shows two different sizes.
    try:
        return GLib.format_size(max(0, int(value)))
    except Exception:
        return "—"


def _format_timestamp(seconds):
    try:
        dt = _dt.datetime.fromtimestamp(int(seconds))
        return dt.strftime("%b %d, %Y · %I:%M %p")
    except Exception:
        return "—"


def _mode_text(value):
    try:
        return stat.filemode(int(value))
    except Exception:
        return "—"


def _snapshot_file(info):
    result = {
        "name": "Unknown",
        "uri": None,
        "mime": None,
        "is_dir": False,
    }

    try:
        result["name"] = info.get_name() or result["name"]
    except Exception:
        pass

    try:
        result["uri"] = info.get_uri()
    except Exception:
        pass

    try:
        result["mime"] = info.get_mime_type()
    except Exception:
        pass

    try:
        result["is_dir"] = bool(info.is_directory())
    except Exception:
        try:
            result["is_dir"] = (
                info.get_file_type() == Gio.FileType.DIRECTORY
            )
        except Exception:
            pass

    return result


def _file_identity(name, mime):
    name = name or ""
    mime = mime or ""
    suffix = Path(name).suffix.casefold()
    basename = Path(name).name.casefold()

    if basename in BASENAME_RULES:
        label, icon_name = BASENAME_RULES[basename]
        return {
            "label": label,
            "icon_name": icon_name,
            "suffix": suffix,
            "is_code": True,
        }

    if suffix in LANGUAGE_RULES:
        label, icon_name = LANGUAGE_RULES[suffix]
        return {
            "label": label,
            "icon_name": icon_name,
            "suffix": suffix,
            "is_code": True,
        }

    if mime in MIME_RULES:
        label, icon_name = MIME_RULES[mime]
        return {
            "label": label,
            "icon_name": icon_name,
            "suffix": suffix,
            "is_code": True,
        }

    if mime == PDF_MIME:
        return {
            "label": "PDF document",
            "icon_name": "application-pdf",
            "suffix": suffix,
            "is_code": False,
        }

    if mime.startswith("image/"):
        return {
            "label": Gio.content_type_get_description(mime) or "Image",
            "icon_name": "image-x-generic",
            "suffix": suffix,
            "is_code": False,
        }

    if mime.startswith("audio/"):
        return {
            "label": Gio.content_type_get_description(mime) or "Audio",
            "icon_name": "audio-x-generic",
            "suffix": suffix,
            "is_code": False,
        }

    if mime.startswith("video/"):
        return {
            "label": Gio.content_type_get_description(mime) or "Video",
            "icon_name": "video-x-generic",
            "suffix": suffix,
            "is_code": False,
        }

    description = Gio.content_type_get_description(
        mime or "application/octet-stream"
    ) or "File"

    return {
        "label": description,
        "icon_name": None,
        "suffix": suffix,
        "is_code": suffix in TEXT_EXTENSIONS or mime.startswith("text/"),
    }


def _theme_icon_for_identity(identity, mime):
    icon_name = identity.get("icon_name")

    if icon_name:
        return Gtk.Image.new_from_icon_name(
            icon_name,
            Gtk.IconSize.DIALOG,
        )

    return Gtk.Image.new_from_gicon(
        Gio.content_type_get_icon(
            mime or "application/octet-stream"
        ),
        Gtk.IconSize.DIALOG,
    )


# ------------------------------------------------------------------
# Data visualisation
#
# Colours come from the palette table at the end of the shell stylesheet.
# Blue, indigo and cyan tell series apart, then the label greys. Green,
# orange and red are status only - capacity thresholds - never a series.
# ------------------------------------------------------------------


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


SERIES_COLORS = [
    _rgb(value)
    for value in ("#0A84FF", "#5E5CE6", "#64D2FF", "#98989D", "#636366", "#48484A")
]
TRACK_RGBA = (1.0, 1.0, 1.0, 0.10)
ACCENT = _rgb("#0A84FF")
STATUS_WARN = _rgb("#FF9F0A")
STATUS_CRIT = _rgb("#FF453A")

# Capacity is "getting full" from 85% and "almost full" from 93%.
CAPACITY_WARN = 0.85
CAPACITY_CRIT = 0.93

KINDS = ("Documents", "Images", "Media", "Code", "Archives", "Other")
KIND_COLORS = dict(zip(KINDS, SERIES_COLORS))

_EXT_KIND = {}
for _kind, _exts in {
    "Documents": (
        "pdf doc docx odt rtf txt md rst tex epub xls xlsx ods csv tsv "
        "ppt pptx odp key pages numbers"
    ),
    "Images": (
        "png jpg jpeg gif bmp tif tiff webp svg heic heif ico psd xcf "
        "raw cr2 nef dng exr hdr"
    ),
    "Media": (
        "mp4 mkv mov avi webm m4v flv wmv mpg mpeg mp3 wav flac ogg oga "
        "m4a aac opus wma mid midi"
    ),
    "Code": (
        "py pyw ipynb js mjs cjs ts tsx jsx c h cpp cxx cc hpp hxx java kt "
        "kts rs go sh bash zsh fish json jsonc yaml yml toml ini cfg conf "
        "xml html htm css scss sql cmake lua rb php swift ino cu cuh proto "
        "launch urdf xacro msg srv"
    ),
    "Archives": (
        "zip tar gz tgz xz txz bz2 tbz2 7z rar zst deb rpm snap appimage "
        "iso img whl jar apk dmg"
    ),
}.items():
    for _ext in _exts.split():
        _EXT_KIND[_ext] = _kind


def _kind_for_name(name):
    stem, dot, ext = (name or "").rpartition(".")
    if not dot or not stem:
        return "Other"
    return _EXT_KIND.get(ext.casefold(), "Other")


def _capacity_color(fraction):
    if fraction >= CAPACITY_CRIT:
        return STATUS_CRIT
    if fraction >= CAPACITY_WARN:
        return STATUS_WARN
    return ACCENT


def _count_text(number, singular, plural=None):
    word = singular if number == 1 else (plural or singular + "s")
    return f"{number:,} {word}"


def _relative_time(seconds):
    try:
        then = _dt.datetime.fromtimestamp(int(seconds))
    except Exception:
        return "—"

    delta = _dt.datetime.now() - then
    minutes = int(delta.total_seconds() // 60)

    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 24 * 60:
        return f"{minutes // 60} h ago"
    if delta.days == 1:
        return "yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    if then.year == _dt.datetime.now().year:
        return then.strftime("%b %-d")
    return then.strftime("%b %-d, %Y")


def _short_path(path):
    home = str(Path.home())
    path = str(path or "")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def _rounded_rect(cr, x, y, width, height, radius):
    radius = max(0.0, min(radius, height / 2.0, width / 2.0))
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2.0, 0.0)
    cr.arc(x + width - radius, y + height - radius, radius, 0.0, math.pi / 2.0)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2.0, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
    cr.close_path()


class SegmentBar(Gtk.DrawingArea):
    """A rounded track filled left to right by coloured segments.

    Segments are (fraction_of_track, rgb). Adjacent segments are split by a
    1px gap left unpainted, so the card behind shows through whatever its
    colour, and whatever the fractions leave over stays as track.
    """

    def __init__(self, height=10):
        super().__init__()
        self._segments = []
        self.set_size_request(-1, height)
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)

    def set_segments(self, segments):
        self._segments = [
            (max(0.0, float(fraction)), color)
            for fraction, color in segments
            if fraction and fraction > 0
        ]
        self.queue_draw()
        return self

    def do_draw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0 or height <= 0:
            return False

        _rounded_rect(cr, 0, 0, width, height, height / 2.0)
        cr.clip()

        x = 0.0
        count = len(self._segments)
        for index, (fraction, color) in enumerate(self._segments):
            span = min(width - x, max(fraction * width, 2.0))
            if span <= 0:
                break
            last = index == count - 1
            painted = span if last and x + span >= width - 0.5 else span - 1.0
            cr.set_source_rgb(*color)
            cr.rectangle(x, 0, max(painted, 1.0), height)
            cr.fill()
            x += span

        if x < width:
            cr.set_source_rgba(*TRACK_RGBA)
            cr.rectangle(x, 0, width - x, height)
            cr.fill()

        return False


def _add_scheme_path(manager):
    """Let GtkSourceView find adaptive-dark.xml, installed beside
    preview.css (see scripts/install-files-extension.sh)."""
    css_path = os.environ.get("ADAPTIVE_FILES_PREVIEW_CSS")
    if not css_path:
        return
    folder = str(Path(css_path).parent)
    if folder not in (manager.get_search_path() or []):
        manager.append_search_path(folder)


class RoundedPicture(Gtk.DrawingArea):
    """A thumbnail scaled to fit, never enlarged, with rounded corners and a
    hairline edge - GTK3 CSS cannot round an image by itself."""

    def __init__(self, pixbuf, max_width, max_height, radius=8.0):
        super().__init__()
        scale = min(max_width / pixbuf.get_width(), max_height / pixbuf.get_height(), 1.0)
        width = max(1, int(pixbuf.get_width() * scale))
        height = max(1, int(pixbuf.get_height() * scale))
        self._pixbuf = pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
        self._radius = radius
        self.set_size_request(width, height)

    def do_draw(self, cr):
        width = self._pixbuf.get_width()
        height = self._pixbuf.get_height()
        _rounded_rect(cr, 0, 0, width, height, self._radius)
        cr.save()
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        cr.restore()
        _rounded_rect(cr, 0.5, 0.5, width - 1, height - 1, self._radius)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.10)
        cr.set_line_width(1.0)
        cr.stroke()
        return False


class UsageRing(Gtk.DrawingArea):
    """Percentage donut; the arc takes its status colour from the fraction."""

    def __init__(self, size=84, line_width=9.0):
        super().__init__()
        self._fraction = 0.0
        self._line_width = line_width
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)

    def set_fraction(self, fraction):
        self._fraction = max(0.0, min(1.0, float(fraction)))
        self.queue_draw()
        return self

    def do_draw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        cx = width / 2.0
        cy = height / 2.0
        radius = min(width, height) / 2.0 - self._line_width / 2.0 - 1.0

        cr.set_line_width(self._line_width)
        cr.set_line_cap(1)

        cr.set_source_rgba(*TRACK_RGBA)
        cr.arc(cx, cy, radius, 0.0, math.tau)
        cr.stroke()

        if self._fraction > 0:
            cr.set_source_rgb(*_capacity_color(self._fraction))
            start = -math.pi / 2.0
            cr.arc(cx, cy, radius, start, start + math.tau * self._fraction)
            cr.stroke()

        return False


class ActivityChart(Gtk.DrawingArea):
    """Daily bars, oldest on the left. Today is the accent, earlier days a
    lighter blue, and empty days a short tick so the axis stays readable."""

    def __init__(self, height=46):
        super().__init__()
        self._values = []
        self.set_size_request(-1, height)
        self.set_hexpand(True)

    def set_values(self, values):
        self._values = list(values or [])
        self.queue_draw()
        return self

    def do_draw(self, cr):
        values = self._values
        if not values:
            return False

        width = self.get_allocated_width()
        height = self.get_allocated_height()
        count = len(values)
        gap = 3.0
        bar = max(2.0, (width - gap * (count - 1)) / count)
        peak = max(values) or 1

        for index, value in enumerate(values):
            x = index * (bar + gap)
            if value <= 0:
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.12)
                _rounded_rect(cr, x, height - 2.0, bar, 2.0, 1.0)
                cr.fill()
                continue

            span = max(4.0, (value / peak) * (height - 2.0))
            if index == count - 1:
                cr.set_source_rgb(*ACCENT)
            else:
                cr.set_source_rgba(ACCENT[0], ACCENT[1], ACCENT[2], 0.55)
            _rounded_rect(cr, x, height - span, bar, span, min(3.0, bar / 2.0))
            cr.fill()

        return False


class Swatch(Gtk.DrawingArea):
    """A legend dot."""

    def __init__(self, color, size=8):
        super().__init__()
        self._color = color
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)

    def do_draw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        radius = min(width, height) / 2.0
        cr.set_source_rgb(*self._color)
        cr.arc(width / 2.0, height / 2.0, radius, 0, math.tau)
        cr.fill()
        # The darkest greys all but vanish on the panel; a faint ring keeps
        # their dots findable without changing the colour they stand for.
        if sum(self._color) / 3.0 < 0.35:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.28)
            cr.set_line_width(1.0)
            cr.arc(width / 2.0, height / 2.0, radius - 0.5, 0, math.tau)
            cr.stroke()
        return False


# ------------------------------------------------------------------
# Measurement workers - plain data only, never GTK objects
# ------------------------------------------------------------------

SCAN_MAX_ENTRIES = 60000
SCAN_MAX_SECONDS = 2.0
ACTIVITY_DAYS = 14


def _midnight(timestamp):
    moment = _dt.datetime.fromtimestamp(timestamp)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _scan_paths(paths, max_entries=SCAN_MAX_ENTRIES, max_seconds=SCAN_MAX_SECONDS):
    """Size, kind mix and recent activity for a set of top-level paths.

    Each path becomes one "child" whose size includes everything under it.
    The walk never follows symlinks, and stops early once either budget is
    spent; the result then says truncated=True and the sizes are lower
    bounds.
    """
    started = time.monotonic()
    today = _midnight(time.time())
    remaining = [max_entries]

    result = {
        "bytes": 0,
        "files": 0,
        "folders": 0,
        "truncated": False,
        "kinds": {kind: 0 for kind in KINDS},
        "kind_counts": {kind: 0 for kind in KINDS},
        "days": [0] * ACTIVITY_DAYS,
        "children": [],
    }

    def spent():
        if remaining[0] <= 0 or time.monotonic() - started > max_seconds:
            result["truncated"] = True
            return True
        return False

    def account_file(name, st):
        size = st.st_size
        kind = _kind_for_name(name)
        result["bytes"] += size
        result["files"] += 1
        result["kinds"][kind] += size
        result["kind_counts"][kind] += 1

        age_days = int((today - _midnight(st.st_mtime)) // 86400)
        if 0 <= age_days < ACTIVITY_DAYS:
            result["days"][ACTIVITY_DAYS - 1 - age_days] += 1
        return size

    def walk_dir(path):
        total = 0
        stack = [path]
        while stack:
            if spent():
                break
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        remaining[0] -= 1
                        try:
                            st = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if stat.S_ISDIR(st.st_mode):
                            result["folders"] += 1
                            stack.append(entry.path)
                        elif stat.S_ISREG(st.st_mode):
                            total += account_file(entry.name, st)
            except OSError:
                continue
        return total

    for path in paths:
        name = os.path.basename(path.rstrip(os.sep)) or path
        try:
            st = os.lstat(path)
        except OSError:
            continue

        if stat.S_ISDIR(st.st_mode):
            result["folders"] += 1
            size = 0 if spent() else walk_dir(path)
            result["children"].append(
                {"name": name, "path": path, "is_dir": True, "bytes": size, "kind": "Folder"}
            )
        else:
            size = account_file(name, st) if stat.S_ISREG(st.st_mode) else 0
            result["children"].append(
                {
                    "name": name,
                    "path": path,
                    "is_dir": False,
                    "bytes": size,
                    "kind": _kind_for_name(name),
                }
            )

    result["children"].sort(key=lambda child: child["bytes"], reverse=True)
    result["seconds"] = time.monotonic() - started
    return result


def _scan_folder(path):
    """_scan_paths over a folder's own children, hidden ones included: they
    take real space, and a storage view that hides .cache is lying."""
    try:
        with os.scandir(path) as entries:
            children = [entry.path for entry in entries]
    except OSError as error:
        raise RuntimeError(error.strerror or str(error)) from error

    result = _scan_paths(children)
    result["items"] = len(children)
    result["visible_items"] = sum(
        1 for child in children if not os.path.basename(child).startswith(".")
    )
    return result


HOME_USAGE_CACHE = Path.home() / ".cache" / "adaptive-files" / "home-usage.json"
HOME_USAGE_MAX_AGE = 20 * 60


def _measure_home():
    """Allocated bytes per top-level Home entry, via du at idle priority.

    du reports allocated blocks (-B1), the same unit statvfs uses for "used",
    so the Home share and the system remainder add up to the real disk.
    Unreadable directories make du exit 1 with partial output; that output
    is still the best available answer, so it is kept.
    """
    home = str(Path.home())
    trash = str(Path.home() / ".local" / "share" / "Trash")
    idle = ["nice", "-n", "19", "ionice", "-c", "3"]

    def du(*args):
        # Separate runs: du counts an inode once across all its operands,
        # so Trash (inside Home) would read as empty in the same call.
        return subprocess.run(
            idle + ["du", "-x", "-B1", *args],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        ).stdout.splitlines()

    total = 0
    rows = []
    for line in du("-d", "1", home):
        size_text, _, path = line.partition("\t")
        try:
            size = int(size_text)
        except ValueError:
            continue
        if path == home:
            total = size
        elif os.path.dirname(path) == home:
            rows.append({"name": os.path.basename(path), "path": path, "bytes": size})

    trash_bytes = 0
    if os.path.isdir(trash):
        for line in du("-s", trash):
            try:
                trash_bytes = int(line.partition("\t")[0])
            except ValueError:
                pass

    rows.sort(key=lambda row: row["bytes"], reverse=True)
    data = {
        "measured_at": time.time(),
        "total": total,
        "trash": trash_bytes,
        "rows": rows,
    }

    try:
        HOME_USAGE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HOME_USAGE_CACHE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass

    return data


def _cached_home_usage():
    try:
        data = json.loads(HOME_USAGE_CACHE.read_text(encoding="utf-8"))
        if data.get("rows") is not None:
            return data
    except (OSError, ValueError):
        pass
    return None


def _volume_label(path):
    """Friendly name for the filesystem holding path: its label, else the
    device's model-ish name, else the mount point."""
    try:
        proc = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE,FSTYPE,TARGET,LABEL", "--target", str(path)],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        parts = proc.stdout.strip().splitlines()[0].split(None, 3)
    except Exception:
        return {"source": "", "fstype": "", "target": str(path), "label": ""}

    while len(parts) < 4:
        parts.append("")
    source, fstype, target, label = parts
    return {"source": source, "fstype": fstype, "target": target, "label": label}


class PreviewController:
    def __init__(self, window):
        self._window = window
        self.panel = None
        # One reusable location strip per window; see get_widget().
        self.host_split = None
        self.stack = None

        self.preview_body = None
        self.project_body = None

        self.storage_body = None
        self.network_body = None

        self.host_overlay = None
        self.host_box = None
        self.host_main_child = None
        self.panel_visible = True
        self.host_original_margin_end = 0
        self.panel_width = PANEL_WIDE
        self.attach_attempts = 0

        self.selection_generation = 0
        self.last_selection = []
        self.active_metadata_box = None
        self.location_uri = None
        self._selection_key = None
        self._selection_at = 0.0
        self._current_name = ""
        self._file_subtitle = None
        self._scan_cache = {}
        self._home_usage = None
        self._home_measuring = False
        self._projects_cache = None

        self._active_project_id = None
        self._dbus_proxy = None
        self._init_dbus_proxy()

        self._configure_process_theme()

        try:
            self.thumbnail_factory = GnomeDesktop.DesktopThumbnailFactory.new(
                GnomeDesktop.DesktopThumbnailSize.LARGE
            )
            _log("Native GNOME thumbnail factory initialized.")
        except Exception:
            self.thumbnail_factory = None
            _log_exception(
                "Unable to initialize GNOME thumbnail factory"
            )

        self._build_panel()
        self._load_css()

        try:
            window.connect("size-allocate", self._on_window_size_allocate)
        except Exception:
            pass

        # Try once immediately while LocationWidgetProvider still holds the
        # NautilusWindow wrapper, then retry after GTK has completed layout.
        self.ensure_attached()
        GLib.idle_add(self.ensure_attached)

    @property
    def window(self):
        return self._window

    def release(self):
        self._window = None

    def _init_dbus_proxy(self):
        try:
            self._dbus_proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.adaptive.ProjectContext",
                "/org/adaptive/ProjectContext",
                "org.adaptive.ProjectContext",
                None,
            )
            self._dbus_proxy.connect("g-signal", self._on_dbus_signal)
        except Exception as e:
            self._dbus_proxy = None
            _log(f"DBus ProjectContext error: {e}")

    def _on_dbus_signal(self, proxy, sender_name, signal_name, parameters):
        if signal_name == "ActiveProjectChanged":
            try:
                self._active_project_id = parameters.unpack()[0]
            except Exception:
                self._active_project_id = None
            GLib.idle_add(self._render_project)
        elif signal_name == "ProjectListChanged":
            GLib.idle_add(self._render_project)

    def _configure_process_theme(self):
        try:
            settings = Gtk.Settings.get_default()
            if settings is not None:
                settings.set_property("gtk-icon-theme-name", "AdaptiveFilesIcons")
                settings.set_property("gtk-application-prefer-dark-theme", True)
                _log("Process icon theme set to AdaptiveFilesIcons.")
        except Exception:
            _log_exception("Unable to set Adaptive Files icon theme")

    def _load_css(self):
        css_path = os.environ.get("ADAPTIVE_FILES_PREVIEW_CSS")
        if not css_path:
            prefix = os.environ.get("ADAPTIVE_FILES_PREFIX")
            if prefix:
                css_path = str(Path(prefix) / "share" / "adaptive-files" / "preview.css")

        if not css_path or not Path(css_path).exists():
            _log(f"Preview CSS not found: {css_path}")
            return

        try:
            provider = Gtk.CssProvider()
            provider.load_from_path(css_path)

            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 20,
                )
        except Exception:
            _log_exception("Unable to load preview CSS")

    def _build_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.set_size_request(PANEL_WIDE, -1)
        panel.set_halign(Gtk.Align.END)
        panel.set_valign(Gtk.Align.FILL)
        panel.set_vexpand(True)
        _css(panel, "adaptive-preview-panel")

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(120)
        stack.set_hexpand(True)
        stack.set_vexpand(True)

        # A segmented control is the whole header: each tab opens on its own
        # title, so a panel-wide "Inspector" heading only repeated the tab.
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(stack)
        switcher.set_homogeneous(True)
        switcher.set_halign(Gtk.Align.FILL)
        switcher.set_hexpand(True)
        switcher.set_margin_start(14)
        switcher.set_margin_end(14)
        switcher.set_margin_top(12)
        switcher.set_margin_bottom(6)
        _css(switcher, "adaptive-inspector-switcher")
        panel.pack_start(switcher, False, False, 0)

        preview_scroll, preview_body = self._make_scroll_body()
        storage_scroll, storage_body = self._make_scroll_body()
        network_scroll, network_body = self._make_scroll_body()
        project_scroll, project_body = self._make_scroll_body()

        stack.add_titled(preview_scroll, "preview", "Info")
        stack.add_titled(storage_scroll, "storage", "Storage")
        stack.add_titled(network_scroll, "network", "Network")
        stack.add_titled(project_scroll, "project", "Projects")

        panel.pack_start(stack, True, True, 0)

        self.panel = panel
        self.stack = stack

        self.preview_body = preview_body
        self.storage_body = storage_body
        self.network_body = network_body
        self.project_body = project_body

        stack.connect("notify::visible-child-name", self._on_stack_changed)

        self._render_empty_preview()
        self._render_project()

    def _make_scroll_body(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_start(14)
        body.set_margin_end(14)
        body.set_margin_top(8)
        body.set_margin_bottom(18)

        scroll.add(body)
        return scroll, body

    def _on_stack_changed(self, stack, _pspec):
        name = stack.get_visible_child_name()
        if name == "storage":
            self._render_storage()
        elif name == "network":
            self._render_network()
        elif name == "project":
            self._render_project()

    def _on_window_size_allocate(self, _window, allocation):
        width = allocation.width

        if width >= 1320:
            target = PANEL_WIDE
        elif width >= 1080:
            target = PANEL_MEDIUM
        else:
            target = PANEL_NARROW

        if target != self.panel_width:
            self.panel_width = target
            self.panel.set_size_request(target, -1)
            self._reserve_space()

    # --------------------------------------------------------------
    # Panel controls
    # --------------------------------------------------------------

    def set_panel_visible(self, visible):
        self.panel_visible = bool(visible)

        if self.panel is not None:
            self.panel.set_visible(self.panel_visible)

        self._reserve_space()
        return self.panel_visible

    def toggle_panel(self):
        return self.set_panel_visible(not self.panel_visible)

    def show_tab(self, name):
        self.set_panel_visible(True)
        self.ensure_attached()
        if self.stack is not None:
            try:
                self.stack.set_visible_child_name(name)
            except Exception:
                pass

    # --------------------------------------------------------------
    # Host / injection
    # --------------------------------------------------------------

    def ensure_attached(self):
        window = self.window
        if window is None:
            _log("Inspector attach skipped: NautilusWindow is unavailable.")
            return GLib.SOURCE_REMOVE

        self.attach_attempts += 1
        if self.attach_attempts <= 6:
            try:
                allocation = window.get_allocation()
                _log(
                    "Inspector attach attempt "
                    f"{self.attach_attempts}: window={_type_name(window)} "
                    f"size={allocation.width}x{allocation.height}"
                )
            except Exception:
                _log(
                    "Inspector attach attempt "
                    f"{self.attach_attempts}: window={_type_name(window)}"
                )

        try:
            host = self._find_best_overlay(window)

            if host is not None and host is not self.host_overlay:
                self._detach_from_old_host()
                self.host_overlay = host
                self.host_box = None
                self.host_main_child = host.get_child()

                if self.host_main_child is None:
                    self.host_overlay = None
                    self.host_main_child = None
                    GLib.timeout_add(700, self.ensure_attached)
                    return GLib.SOURCE_REMOVE

                self.host_original_margin_end = (
                    self.host_main_child.get_margin_end()
                )

                # The inspector used to be an overlay child with a margin on
                # the file view sized to match it. That is two independent
                # numbers that have to agree, and they stop agreeing the moment
                # the window is too narrow for the view to give the margin back
                # - the view then keeps its minimum width and slides under the
                # panel. It also meant the location strip, which lives inside
                # the view, inherited a margin it did not need and stopped
                # short of the window edge.
                #
                # Packing both into a box makes GTK responsible for the
                # geometry instead. They cannot overlap, because a box does not
                # put its children on top of each other.
                view = self.host_main_child

                self.host_split = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL,
                    spacing=0,
                )

                host.remove(view)

                # Whatever the old margin mechanism last set, drop it. The box
                # decides the widths now, and a leftover margin here shows up
                # as a strip of dead space between the view and the inspector.
                view.set_margin_end(0)
                self.host_original_margin_end = 0

                # Set expansion on the widgets, not only as box packing
                # flags. GtkBox's expand flag alone left 424px of slack sitting
                # between the view and the inspector - the view kept its
                # natural width and the spare space went nowhere useful.
                view.set_hexpand(True)
                view.set_halign(Gtk.Align.FILL)

                self.panel.set_hexpand(False)
                self.panel.set_halign(Gtk.Align.FILL)

                self.host_split.pack_start(view, True, True, 0)
                self.host_split.pack_start(self.panel, False, False, 0)

                host.add(self.host_split)
                self.host_split.show_all()

                self.panel.set_visible(self.panel_visible)

                _log(
                    f"Inspector packed beside {_type_name(view)} "
                    f"inside {_type_name(host)}"
                )

            elif host is None and self.host_box is None:
                box = self._find_best_horizontal_box(window)

                if box is None:
                    _log("No suitable overlay/horizontal content box found yet; retrying.")
                    self._log_widget_tree(window)
                    GLib.timeout_add(700, self.ensure_attached)
                    return GLib.SOURCE_REMOVE

                self._detach_from_old_host()
                self.host_box = box
                self.host_overlay = None
                self.host_main_child = None

                box.pack_end(self.panel, False, False, 0)
                self.panel.show_all()
                self.panel.set_visible(self.panel_visible)

                _log(
                    "Inspector attached to horizontal box "
                    f"{_type_name(box)}"
                )

            return GLib.SOURCE_REMOVE

        except Exception:
            _log_exception("Failed while attaching inspector")
            GLib.timeout_add(1000, self.ensure_attached)
            return GLib.SOURCE_REMOVE

    def _find_best_overlay(self, root):
        candidates = []

        for widget in _walk(root):
            if not isinstance(widget, Gtk.Overlay):
                continue

            if widget is self.host_overlay:
                return widget

            try:
                if not widget.get_visible():
                    continue

                allocation = widget.get_allocation()
                width = allocation.width
                height = allocation.height
            except Exception:
                continue

            if width < 180 or height < 160:
                continue

            names = _ancestors(widget)
            joined = " ".join(names)

            score = (width * height) / 8000.0

            if width > 900 and height > 500:
                score += 180.0

            if any(
                token in joined
                for token in (
                    "NautilusFilesView",
                    "NautilusGridView",
                    "NautilusListView",
                    "NautilusViewIconController",
                    "NautilusWindowSlot",
                )
            ):
                score += 1000.0

            try:
                child = widget.get_child()
                child_name = _type_name(child) if child is not None else ""
                if "Nautilus" in child_name:
                    score += 300.0
                if isinstance(child, Gtk.ScrolledWindow):
                    score += 100.0
            except Exception:
                pass

            candidates.append((score, widget, width, height, joined))

        if not candidates:
            self._log_widget_tree(root)
            return None

        candidates.sort(key=lambda row: row[0], reverse=True)

        for score, widget, width, height, joined in candidates[:5]:
            _log(
                f"Overlay candidate score={score:.1f} size={width}x{height} "
                f"type={_type_name(widget)} ancestors={joined}"
            )

        return candidates[0][1]

    def _find_best_horizontal_box(self, root):
        candidates = []

        for widget in _walk(root):
            if not isinstance(widget, Gtk.Box):
                continue

            try:
                if widget.get_orientation() != Gtk.Orientation.HORIZONTAL:
                    continue
                if not widget.get_visible():
                    continue

                allocation = widget.get_allocation()
                width = allocation.width
                height = allocation.height
            except Exception:
                continue

            if width < 420 or height < 240:
                continue

            joined = " ".join(_ancestors(widget))
            score = (width * height) / 10000.0

            if "NautilusWindow" in joined:
                score += 300.0
            if "NautilusWindowSlot" in joined:
                score += 700.0
            if "HeaderBar" in joined:
                score -= 1000.0

            candidates.append((score, widget, width, height, joined))

        if not candidates:
            return None

        candidates.sort(key=lambda row: row[0], reverse=True)

        for score, widget, width, height, joined in candidates[:5]:
            _log(
                f"Box candidate score={score:.1f} size={width}x{height} "
                f"type={_type_name(widget)} ancestors={joined}"
            )

        return candidates[0][1]

    def _log_widget_tree(self, root):
        try:
            lines = []
            for widget in _walk(root):
                try:
                    allocation = widget.get_allocation()
                    size = f"{allocation.width}x{allocation.height}"
                except Exception:
                    size = "?"
                lines.append(f"{_type_name(widget)} {size}")
            _log("Widget tree:\n" + "\n".join(lines[:240]))
        except Exception:
            pass

    def _reserve_space(self):
        """Kept as the single place that re-checks the layout.

        There is no space to reserve any more: the inspector is a sibling of
        the file view, so hiding it hands its width back automatically and the
        location strip inside the view resizes with it. The name stays because
        several call sites mean "the layout may have changed, look at it".
        """
        # Deliberately empty of layout arithmetic. Before the split existed
        # this set a margin on the file view wide enough to clear the floating
        # inspector, and keeping both numbers in agreement is what kept
        # breaking. Nothing here may set a margin again.

        # Reserving space is not the same as it having worked. Check the
        # allocations once the layout settles and say so if the inspector is
        # sitting on top of the file view rather than beside it - that is the
        # bug this whole mechanism exists to prevent, and it is invisible from
        # the code alone.
        GLib.idle_add(self._check_geometry)

    def _check_geometry(self):
        try:
            if not self.panel_visible:
                return GLib.SOURCE_REMOVE

            if self.panel is None or self.host_main_child is None:
                return GLib.SOURCE_REMOVE

            panel = self.panel.get_allocation()
            base = self.host_main_child.get_allocation()

            if panel.width <= 1 or base.width <= 1:
                return GLib.SOURCE_REMOVE

            # get_allocation() is relative to each widget's own GdkWindow, so
            # two widgets in different windows both report x=0 and comparing
            # them directly says nothing. Translate both into the toplevel.
            top = self.panel.get_toplevel()

            panel_xy = self.panel.translate_coordinates(top, 0, 0)
            base_xy = self.host_main_child.translate_coordinates(top, 0, 0)

            if panel_xy is None or base_xy is None:
                return GLib.SOURCE_REMOVE

            panel.x = panel_xy[0]
            base.x = base_xy[0]

            overlap = (base.x + base.width) - panel.x

            if overlap > 1:
                _log(
                    f"GEOMETRY overlap={overlap}px "
                    f"panel=x{panel.x}+w{panel.width} "
                    f"base=x{base.x}+w{base.width} "
                    f"reserved={self.panel_width} "
                    f"base_type={_type_name(self.host_main_child)}"
                )

        except Exception:
            _log_exception("Geometry check failed")

        return GLib.SOURCE_REMOVE

    def _detach_from_old_host(self):
        if self.host_overlay is None:
            return

        # Give Nautilus its view back the way we found it, still parented to
        # the overlay and without our box in between.
        if self.host_split is not None:
            try:
                view = self.host_main_child

                if self.panel.get_parent() is self.host_split:
                    self.host_split.remove(self.panel)

                if view is not None and view.get_parent() is self.host_split:
                    self.host_split.remove(view)

                if self.host_split.get_parent() is self.host_overlay:
                    self.host_overlay.remove(self.host_split)

                if view is not None:
                    self.host_overlay.add(view)
            except Exception:
                _log_exception("Unable to unpick the inspector split")

            self.host_split = None

        try:
            parent = self.panel.get_parent()
            if parent is self.host_overlay:
                self.host_overlay.remove(self.panel)
        except Exception:
            pass

        try:
            if self.host_main_child is not None:
                self.host_main_child.set_margin_end(
                    self.host_original_margin_end
                )
        except Exception:
            pass

        self.host_overlay = None
        self.host_box = None
        self.host_main_child = None
        self.panel_visible = True

    # --------------------------------------------------------------
    # Selection / preview
    # --------------------------------------------------------------

    def set_location(self, uri):
        """The folder the window is showing; the Info tab describes it when
        nothing is selected."""
        if not uri or uri == self.location_uri:
            return
        self.location_uri = uri
        if not self.last_selection:
            # Deferred: Nautilus calls in here while it is building menus.
            self._selection_key = None
            GLib.idle_add(self.update_selection, [])

    def update_selection(self, selection):
        self.ensure_attached()

        selection = list(selection)
        key = (self.location_uri, tuple(item.get("uri") for item in selection))
        now = time.monotonic()

        # Nautilus rebuilds its menus - and so calls here - on focus and
        # hover changes too, not only when the selection moves. Re-measuring
        # an unchanged selection would only make the panel flicker.
        if key == self._selection_key and now - self._selection_at < 10.0:
            return GLib.SOURCE_REMOVE

        self._selection_key = key
        self._selection_at = now

        self.selection_generation += 1
        generation = self.selection_generation
        self.last_selection = selection
        self.active_metadata_box = None
        self._file_subtitle = None

        if not selection:
            self._render_empty_preview()
            return GLib.SOURCE_REMOVE

        if len(selection) > 1:
            self._render_multiple_selection(selection, generation)
            return GLib.SOURCE_REMOVE

        item = selection[0]
        uri = item.get("uri")

        if not uri:
            self._render_message(
                "Preview unavailable",
                "The selected item does not expose a usable address.",
            )
            return GLib.SOURCE_REMOVE

        self._current_name = item.get("name") or "Item"
        self._clear(self.preview_body)

        gfile = Gio.File.new_for_uri(uri)

        if item.get("is_dir"):
            self._render_folder_summary(gfile, item.get("name"), generation, selected=True)
        else:
            self._render_file_shell(item, gfile, generation)

        return GLib.SOURCE_REMOVE

    def _render_empty_preview(self):
        self._clear(self.preview_body)

        uri = self.location_uri
        if not uri:
            self._render_message(
                "Nothing selected",
                "Select a file or folder to see its preview and details.",
            )
            return

        gfile = Gio.File.new_for_uri(uri)
        self.selection_generation += 1
        self._render_folder_summary(
            gfile,
            None,
            self.selection_generation,
            selected=False,
        )

    # --------------------------------------------------------------
    # Folder summary - current location, or one selected folder
    # --------------------------------------------------------------

    def _render_folder_summary(self, gfile, name, generation, selected):
        body = self.preview_body
        path = gfile.get_path()

        if not name:
            try:
                info = gfile.query_info("standard::display-name", Gio.FileQueryInfoFlags.NONE, None)
                name = info.get_display_name()
            except Exception:
                name = gfile.get_basename() or gfile.get_uri()

        self._current_name = name or "Folder"

        hero, subtitle = self._hero(self._gicon_image(gfile, "folder", 64), self._current_name, "Folder")
        body.pack_start(hero, False, False, 0)

        project = self._project_for_path(path)
        if project is not None:
            body.pack_start(self._project_chip(project), False, False, 0)

        if path is None:
            body.pack_start(
                self._note(
                    "This location is not a local folder, so its contents "
                    "can't be measured here."
                ),
                False,
                False,
                0,
            )
            if selected:
                self._append_details_placeholder()
                self._query_metadata_async({"uri": gfile.get_uri()}, gfile, generation)
            body.show_all()
            return

        tiles = self._stat_tiles([("—", "Size"), ("—", "Files"), ("—", "Folders")])
        body.pack_start(tiles, False, False, 0)

        contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        contents.pack_start(self._note("Measuring…"), False, False, 0)
        body.pack_start(contents, False, False, 0)

        if selected:
            self._append_details_placeholder()
            self._query_metadata_async({"uri": gfile.get_uri()}, gfile, generation)

        self._append_actions(
            [
                ("document-open-symbolic", "Open", lambda *_: self._view_action("open-with-default-application")),
                ("edit-copy-symbolic", "Copy Path", lambda *_: self._copy_text(path)),
                ("utilities-terminal-symbolic", "Terminal", lambda *_: self._open_terminal(path)),
            ]
            if selected
            else [
                ("edit-copy-symbolic", "Copy Path", lambda *_: self._copy_text(path)),
                ("utilities-terminal-symbolic", "Terminal", lambda *_: self._open_terminal(path)),
                ("starred-symbolic", "Bookmark", lambda *_: self._bookmark_current_location()),
                ("document-properties-symbolic", "Properties", lambda *_: self._view_action("current-directory-properties")),
            ]
        )
        body.show_all()

        widgets = {"subtitle": subtitle, "tiles": tiles, "contents": contents}
        cached = self._scan_cache.get(path)
        if cached and time.monotonic() - cached[0] < 30.0:
            self._finish_folder_summary(generation, widgets, cached[1], None)
            return

        self._submit(
            _scan_folder,
            (path,),
            lambda payload, error: self._finish_folder_summary(
                generation, widgets, payload, error, cache_path=path
            ),
        )

    def _finish_folder_summary(self, generation, widgets, payload, error, cache_path=None):
        if generation != self.selection_generation:
            return GLib.SOURCE_REMOVE

        contents = widgets["contents"]
        self._clear(contents)

        if error:
            contents.pack_start(self._note(f"Can't read this folder: {error}"), False, False, 0)
            contents.show_all()
            return GLib.SOURCE_REMOVE

        if cache_path:
            self._scan_cache[cache_path] = (time.monotonic(), payload)
            if len(self._scan_cache) > 48:
                oldest = min(self._scan_cache, key=lambda key: self._scan_cache[key][0])
                self._scan_cache.pop(oldest, None)

        approx = "≈ " if payload["truncated"] else ""
        widgets["subtitle"].set_text(
            "Folder · " + _count_text(payload.get("visible_items", payload.get("items", 0)), "item")
        )
        self._set_stat_tiles(
            widgets["tiles"],
            [
                (approx + _human_size(payload["bytes"]), "Size"),
                (f"{payload['files']:,}", "Files"),
                (f"{payload['folders']:,}", "Folders"),
            ],
        )

        if payload["bytes"] <= 0 and payload["files"] == 0:
            contents.pack_start(self._note("This folder is empty."), False, False, 0)
            contents.show_all()
            return GLib.SOURCE_REMOVE

        contents.pack_start(self._kind_breakdown(payload), False, False, 0)
        contents.pack_start(self._largest_items(payload), False, False, 0)

        activity = self._activity(payload)
        if activity is not None:
            contents.pack_start(activity, False, False, 0)

        if payload["truncated"]:
            contents.pack_start(
                self._note(
                    "Large folder - figures cover the first "
                    f"{SCAN_MAX_ENTRIES:,} items and are lower bounds."
                ),
                False,
                False,
                0,
            )

        contents.show_all()
        return GLib.SOURCE_REMOVE

    def _kind_breakdown(self, payload):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self._section_label("Contents"), False, False, 0)

        group = self._group()
        total = payload["bytes"] or 1

        bar = SegmentBar(height=10).set_segments(
            [(payload["kinds"][kind] / total, KIND_COLORS[kind]) for kind in KINDS]
        )
        bar.set_margin_top(4)
        bar.set_margin_bottom(6)
        group.pack_start(bar, False, False, 0)

        rows = [
            (
                KIND_COLORS[kind],
                kind,
                _human_size(payload["kinds"][kind]),
                f"{payload['kind_counts'][kind]:,}",
            )
            for kind in KINDS
            if payload["kind_counts"][kind]
        ]
        group.pack_start(self._legend(rows), False, False, 0)

        box.pack_start(group, False, False, 0)
        return box

    def _largest_items(self, payload, title="Largest Items", limit=5):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self._section_label(title), False, False, 0)

        group = self._group()
        total = payload["bytes"] or 1
        children = [child for child in payload["children"] if child["bytes"] > 0][:limit]

        if not children:
            group.pack_start(self._note("Nothing here takes up space yet."), False, False, 0)

        for index, child in enumerate(children):
            color = ACCENT if index == 0 else SERIES_COLORS[3]
            group.pack_start(
                self._bar_row(
                    "folder" if child["is_dir"] else self._icon_name_for(child["name"]),
                    child["name"],
                    _human_size(child["bytes"]),
                    child["bytes"] / total,
                    color,
                    tooltip=_short_path(child["path"]),
                ),
                False,
                False,
                0,
            )

        box.pack_start(group, False, False, 0)
        return box

    def _activity(self, payload):
        days = payload.get("days") or []
        changed = sum(days)
        if not changed:
            return None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(
            self._section_label("Activity", trailing=f"{changed:,} changed · 14 days"),
            False,
            False,
            0,
        )

        group = self._group()
        chart = ActivityChart(height=44).set_values(days)
        chart.set_margin_top(4)
        group.pack_start(chart, False, False, 0)

        axis = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        start = Gtk.Label(label="2 weeks ago", xalign=0)
        end = Gtk.Label(label="Today", xalign=1)
        _css(start, "adaptive-axis-label")
        _css(end, "adaptive-axis-label")
        axis.pack_start(start, True, True, 0)
        axis.pack_end(end, False, False, 0)
        group.pack_start(axis, False, False, 0)

        box.pack_start(group, False, False, 0)
        return box

    # --------------------------------------------------------------
    # Multiple selection
    # --------------------------------------------------------------

    def _render_multiple_selection(self, selection, generation):
        self._clear(self.preview_body)
        body = self.preview_body

        folders = sum(1 for item in selection if item.get("is_dir"))
        files = len(selection) - folders
        parts = []
        if files:
            parts.append(_count_text(files, "file"))
        if folders:
            parts.append(_count_text(folders, "folder"))

        first = Gio.File.new_for_uri(selection[0].get("uri")) if selection[0].get("uri") else None
        icon = self._gicon_image(first, "edit-select-all-symbolic", 64) if first else None
        hero, subtitle = self._hero(icon, _count_text(len(selection), "item"), " · ".join(parts))
        body.pack_start(hero, False, False, 0)

        tiles = self._stat_tiles([("—", "Total Size"), ("—", "Files"), ("—", "Folders")])
        body.pack_start(tiles, False, False, 0)

        contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        contents.pack_start(self._note("Measuring…"), False, False, 0)
        body.pack_start(contents, False, False, 0)

        paths = [
            Gio.File.new_for_uri(item["uri"]).get_path()
            for item in selection
            if item.get("uri")
        ]
        paths = [path for path in paths if path]

        self._append_actions(
            [
                ("edit-copy-symbolic", "Copy Paths", lambda *_: self._copy_text("\n".join(paths))),
                ("package-x-generic-symbolic", "Compress", lambda *_: self._view_action("compress")),
                ("document-properties-symbolic", "Properties", lambda *_: self._view_action("properties")),
            ]
        )
        body.show_all()

        if not paths:
            self._clear(contents)
            contents.pack_start(self._note("These items are not on a local disk."), False, False, 0)
            contents.show_all()
            return

        def finish(payload, error):
            if generation != self.selection_generation:
                return
            self._clear(contents)
            if error:
                contents.pack_start(self._note(f"Can't measure the selection: {error}"), False, False, 0)
                contents.show_all()
                return

            approx = "≈ " if payload["truncated"] else ""
            self._set_stat_tiles(
                tiles,
                [
                    (approx + _human_size(payload["bytes"]), "Total Size"),
                    (f"{payload['files']:,}", "Files"),
                    (f"{payload['folders']:,}", "Folders"),
                ],
            )
            if payload["bytes"] > 0:
                contents.pack_start(self._kind_breakdown(payload), False, False, 0)
            contents.pack_start(
                self._largest_items(payload, title="By Size", limit=12),
                False,
                False,
                0,
            )
            hidden = len(payload["children"]) - 12
            if hidden > 0:
                contents.pack_start(self._note(f"+ {hidden:,} smaller items"), False, False, 0)
            contents.show_all()

        self._submit(_scan_paths, (paths,), finish)

    # --------------------------------------------------------------
    # Single file
    # --------------------------------------------------------------

    def _render_file_shell(self, item, gfile, generation):
        body = self.preview_body
        uri = item.get("uri") or ""
        local_path = gfile.get_path()
        mime = item.get("mime") or ""
        identity = _file_identity(item.get("name"), mime)

        preview_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _css(preview_card, "adaptive-preview-hero")
        media_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        media_box.set_halign(Gtk.Align.FILL)
        preview_card.pack_start(media_box, True, True, 0)
        body.pack_start(preview_card, False, False, 0)

        if identity.get("is_code") and local_path:
            self._render_source_preview(Path(local_path), mime, media_box)
        elif mime.startswith(IMAGE_MIME_PREFIX) or mime == PDF_MIME or mime.startswith("video/"):
            self._render_native_thumbnail_preview(uri, mime, media_box, generation)
        elif local_path and (
            Path(local_path).suffix.casefold() in TEXT_EXTENSIONS
            or mime.startswith("text/")
        ):
            self._render_source_preview(Path(local_path), mime, media_box)
        else:
            self._icon_preview(media_box, identity, mime, gfile)

        name = Gtk.Label(label=item.get("name") or "File")
        name.set_line_wrap(True)
        name.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        name.set_justify(Gtk.Justification.CENTER)
        name.set_selectable(True)
        name.set_margin_top(4)
        _css(name, "adaptive-hero-title")
        body.pack_start(name, False, False, 0)

        subtitle = Gtk.Label(label=identity.get("label") or "File")
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        _css(subtitle, "adaptive-hero-subtitle")
        body.pack_start(subtitle, False, False, 0)
        self._file_subtitle = subtitle

        self._append_details_placeholder()
        self._query_metadata_async(item, gfile, generation)

        self._append_actions(
            [
                ("document-open-symbolic", "Open", lambda *_: self._view_action("open-with-default-application")),
                ("view-more-symbolic", "Open With", lambda *_: self._view_action("open-with-other-application")),
                ("edit-copy-symbolic", "Copy Path", lambda *_: self._copy_text(local_path or uri)),
                ("document-properties-symbolic", "Properties", lambda *_: self._view_action("properties")),
            ]
        )
        body.show_all()

    def _icon_preview(self, box, identity, mime, gfile=None):
        icon = None
        if gfile is not None:
            icon = self._gicon_image(gfile, None, 96)
        if icon is None:
            icon = _theme_icon_for_identity(identity, mime)
            icon.set_pixel_size(96)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_margin_top(18)
        icon.set_margin_bottom(18)
        _css(icon, "adaptive-hero-icon")
        box.pack_start(icon, False, False, 0)

    def _render_native_thumbnail_preview(
        self,
        uri,
        mime,
        box,
        generation,
    ):
        loading = Gtk.Label(
            label="Loading preview…",
        )
        loading.set_halign(Gtk.Align.CENTER)
        _css(loading, "adaptive-note")
        loading.set_margin_top(40)
        loading.set_margin_bottom(40)
        box.pack_start(
            loading,
            False,
            False,
            0,
        )

        future = _EXECUTOR.submit(
            self._native_thumbnail_worker,
            uri,
            mime,
        )

        def done(fut):
            error = None
            thumb_path = None

            try:
                thumb_path = fut.result()
            except Exception as exc:
                error = str(exc)
                _log_exception(
                    f"Native thumbnail worker failed for {uri}"
                )

            GLib.idle_add(
                self._finish_native_thumbnail,
                generation,
                box,
                thumb_path,
                error,
                mime,
            )

        future.add_done_callback(done)

    def _native_thumbnail_worker(
        self,
        uri,
        mime,
    ):
        factory = self.thumbnail_factory

        if factory is None:
            raise RuntimeError(
                "GNOME Desktop thumbnail factory is unavailable"
            )

        gfile = Gio.File.new_for_uri(uri)
        info = gfile.query_info(
            "time::modified,standard::content-type",
            Gio.FileQueryInfoFlags.NONE,
            None,
        )

        try:
            mtime = int(
                info.get_attribute_uint64(
                    "time::modified"
                )
            )
        except Exception:
            mtime = 0

        actual_mime = (
            info.get_content_type()
            or mime
            or "application/octet-stream"
        )

        cached = factory.lookup(
            uri,
            mtime,
        )

        if cached and Path(cached).exists():
            _log(
                "Native thumbnail cache hit: "
                f"mime={actual_mime} path={cached}"
            )
            return cached

        if not factory.can_thumbnail(
            uri,
            actual_mime,
            mtime,
        ):
            raise RuntimeError(
                "System thumbnailer does not support "
                f"{actual_mime}"
            )

        try:
            pixbuf = factory.generate_thumbnail(
                uri,
                actual_mime,
                None,
            )
        except TypeError:
            pixbuf = factory.generate_thumbnail(
                uri,
                actual_mime,
            )

        if pixbuf is None:
            raise RuntimeError(
                "Native thumbnailer returned no preview "
                f"for {actual_mime}"
            )

        try:
            factory.save_thumbnail(
                pixbuf,
                uri,
                mtime,
                None,
            )
        except TypeError:
            factory.save_thumbnail(
                pixbuf,
                uri,
                mtime,
            )

        cached = factory.lookup(
            uri,
            mtime,
        )

        if cached and Path(cached).exists():
            _log(
                "Native thumbnail generated: "
                f"mime={actual_mime} path={cached}"
            )
            return cached

        # Still use the pixbuf produced by GNOME's native thumbnailer.
        CACHE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )
        digest = hashlib.sha1(
            f"{uri}:{mtime}:{actual_mime}".encode(
                "utf-8",
                errors="replace",
            )
        ).hexdigest()[:24]
        output = (
            CACHE_DIR
            / f"native-{digest}.png"
        )
        pixbuf.savev(
            str(output),
            "png",
            [],
            [],
        )
        return str(output)

    def _finish_native_thumbnail(
        self,
        generation,
        box,
        thumb_path,
        error,
        mime,
    ):
        if generation != self.selection_generation:
            return GLib.SOURCE_REMOVE

        self._clear(box)

        if error or not thumb_path:
            identity = _file_identity(self._current_name, mime)
            self._icon_preview(box, identity, mime)
            box.show_all()
            return GLib.SOURCE_REMOVE

        try:
            picture = RoundedPicture(GdkPixbuf.Pixbuf.new_from_file(str(thumb_path)), 270, 230)
            picture.set_halign(Gtk.Align.CENTER)
            box.pack_start(picture, False, False, 0)
        except Exception:
            _log_exception(
                "Unable to display native thumbnail "
                f"{thumb_path}"
            )
            self._fallback_media(
                box,
                "Preview could not be displayed",
            )

        box.show_all()
        return GLib.SOURCE_REMOVE

    def _render_source_preview(
        self,
        path,
        mime,
        box,
    ):
        try:
            size = path.stat().st_size

            if size > 4 * 1024 * 1024:
                self._fallback_media(
                    box,
                    "Source file is too large "
                    "for inline preview",
                )
                return

            with path.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                text = handle.read(24000)

            frame = Gtk.Frame()
            frame.set_shadow_type(
                Gtk.ShadowType.NONE
            )
            _css(
                frame,
                "adaptive-text-frame",
            )

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(
                Gtk.PolicyType.AUTOMATIC,
                Gtk.PolicyType.AUTOMATIC,
            )
            scroll.set_size_request(-1, 244)

            if HAS_GTKSOURCE:
                buffer = GtkSource.Buffer()
                buffer.set_highlight_syntax(True)
                buffer.set_highlight_matching_brackets(
                    True
                )

                manager = (
                    GtkSource.LanguageManager
                    .get_default()
                )

                language = None

                try:
                    language = manager.guess_language(
                        path.name,
                        mime or None,
                    )
                except Exception:
                    language = None

                if language is not None:
                    buffer.set_language(language)

                try:
                    schemes = (
                        GtkSource
                        .StyleSchemeManager
                        .get_default()
                    )
                    _add_scheme_path(schemes)
                    scheme = (
                        schemes.get_scheme("adaptive-dark")
                        or schemes.get_scheme("oblivion")
                        or schemes.get_scheme(
                            "solarized-dark"
                        )
                        or schemes.get_scheme("classic")
                    )
                    if scheme is not None:
                        buffer.set_style_scheme(scheme)
                except Exception:
                    pass

                buffer.set_text(text)

                view = GtkSource.View.new_with_buffer(
                    buffer
                )
                view.set_show_line_numbers(True)
                view.set_tab_width(4)
                view.set_insert_spaces_instead_of_tabs(
                    False
                )
                view.set_highlight_current_line(
                    False
                )
                view.set_monospace(True)
                view.set_editable(False)
                view.set_cursor_visible(False)
                view.set_wrap_mode(
                    Gtk.WrapMode.NONE
                )

                if language is not None:
                    _log(
                        "GtkSourceView language: "
                        f"{path.name} -> "
                        f"{language.get_name()} "
                        f"({language.get_id()})"
                    )
                else:
                    _log(
                        "GtkSourceView language: "
                        f"{path.name} -> not detected"
                    )

            else:
                view = Gtk.TextView()
                view.set_editable(False)
                view.set_cursor_visible(False)
                view.set_monospace(True)
                view.set_wrap_mode(
                    Gtk.WrapMode.NONE
                )
                view.get_buffer().set_text(text)

            _css(
                view,
                "adaptive-text-preview",
                "adaptive-code-preview",
            )

            scroll.add(view)
            frame.add(scroll)
            box.pack_start(
                frame,
                False,
                False,
                0,
            )

        except Exception:
            _log_exception(
                f"Source preview failed for {path}"
            )
            self._fallback_media(
                box,
                "Source preview unavailable",
            )

    def _fallback_media(self, box, text):
        icon = Gtk.Image.new_from_icon_name(
            "text-x-generic-symbolic",
            Gtk.IconSize.DIALOG,
        )
        icon.set_pixel_size(58)
        icon.set_halign(Gtk.Align.CENTER)
        box.pack_start(icon, False, False, 4)

        caption = Gtk.Label(label=text)
        caption.set_halign(Gtk.Align.CENTER)
        caption.set_line_wrap(True)
        _css(caption, "adaptive-note")
        box.pack_start(caption, False, False, 2)

    # --------------------------------------------------------------
    # Information list
    # --------------------------------------------------------------

    def _append_details_placeholder(self):
        self.preview_body.pack_start(self._section_label("Information"), False, False, 0)

        section = self._group()
        section.pack_start(self._note("Loading…"), False, False, 0)
        self.preview_body.pack_start(section, False, False, 0)

        self.active_metadata_box = section
        return section

    def _query_metadata_async(self, item, gfile, generation):
        attributes = ",".join(
            [
                "standard::size",
                "standard::allocated-size",
                "standard::display-name",
                "standard::content-type",
                "standard::type",
                "time::modified",
                "time::created",
                "unix::mode",
                "access::can-write",
                "owner::user",
            ]
        )

        try:
            gfile.query_info_async(
                attributes,
                Gio.FileQueryInfoFlags.NONE,
                GLib.PRIORITY_DEFAULT,
                None,
                self._metadata_ready,
                (generation, item),
            )
        except Exception:
            _log_exception("Unable to query preview metadata")

    def _metadata_ready(self, gfile, result, data):
        generation, item = data

        if generation != self.selection_generation:
            return

        section = self.active_metadata_box
        if section is None:
            return

        self._clear(section)

        try:
            info = gfile.query_info_finish(result)
        except Exception as error:
            _log(f"Metadata query failed: {error}")
            section.pack_start(self._note(f"Details unavailable · {error}"), False, False, 0)
            section.show_all()
            return

        is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
        content_type = info.get_content_type() or item.get("mime") or ""
        kind = "Folder" if is_dir else (
            Gio.content_type_get_description(content_type) or content_type or "File"
        )

        self._info_row(section, "Kind", kind)

        if not is_dir:
            size = info.get_size()
            self._info_row(section, "Size", f"{_human_size(size)}  ({size:,} bytes)")
            subtitle = getattr(self, "_file_subtitle", None)
            if subtitle is not None:
                subtitle.set_text(f"{kind} · {_human_size(size)}")

        # No "Opened" row: reading the file for this very preview updates its
        # access time, so it would always say "just now".
        for key, attribute in (
            ("Created", "time::created"),
            ("Modified", "time::modified"),
        ):
            try:
                value = info.get_attribute_uint64(attribute)
            except Exception:
                value = 0
            if value:
                self._info_row(section, key, f"{_format_timestamp(value)}", hint=_relative_time(value))

        dimensions_row = None
        path = gfile.get_path()
        if not is_dir and path and content_type.startswith("image/"):
            dimensions_row = self._info_row(section, "Dimensions", "…")

        parent = gfile.get_parent()
        if parent is not None:
            self._info_row(section, "Where", _short_path(parent.get_path() or parent.get_uri()), mono=True)

        try:
            mode = info.get_attribute_uint32("unix::mode")
            owner = info.get_attribute_string("owner::user") or ""
            writable = info.get_attribute_boolean("access::can-write")
            access = "Read & write" if writable else "Read only"
            if mode:
                self._info_row(
                    section,
                    "Access",
                    access,
                    hint=f"{_mode_text(mode)}{'  ' + owner if owner else ''}",
                )
        except Exception:
            pass

        section.show_all()

        if dimensions_row is not None:
            def dimensions(image_path=path):
                fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(image_path)
                if not width:
                    raise RuntimeError("unknown")
                megapixels = width * height / 1e6
                return f"{width:,} × {height:,}" + (f"  ·  {megapixels:.1f} MP" if megapixels >= 1 else "")

            def done(text, error, row=dimensions_row):
                if generation == self.selection_generation:
                    row.set_text("—" if error else text)

            self._submit(dimensions, (), done)

    def _append_actions(self, actions):
        """Quick actions as a row of glyph-over-label buttons, as in Finder's
        preview pane."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_homogeneous(True)
        bar.set_margin_top(10)
        _css(bar, "adaptive-action-bar")

        for icon_name, label, callback in actions:
            button = Gtk.Button()
            button.set_tooltip_text(label)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
            icon.set_pixel_size(16)
            text = Gtk.Label(label=label)
            text.set_ellipsize(Pango.EllipsizeMode.END)
            content.pack_start(icon, False, False, 0)
            content.pack_start(text, False, False, 0)
            button.add(content)
            button.connect("clicked", callback)
            _css(button, "adaptive-action")
            bar.pack_start(button, True, True, 0)

        self.preview_body.pack_start(bar, False, False, 0)

    # --------------------------------------------------------------
    # Storage
    # --------------------------------------------------------------

    def _render_storage(self):
        self._clear(self.storage_body)
        body = self.storage_body

        path = Gio.File.new_for_uri(self.location_uri).get_path() if self.location_uri else None
        path = path or str(Path.home())

        try:
            usage = shutil.disk_usage(path)
        except Exception:
            body.pack_start(self._note("Unable to read storage usage."), False, False, 0)
            body.show_all()
            return

        used = usage.total - usage.free
        fraction = used / usage.total if usage.total else 0.0
        volume = _volume_label(path)
        on_home_disk = self._same_filesystem(path, str(Path.home()))

        # Hero: ring + what is left, status in words as well as colour.
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        _css(hero, "adaptive-storage-hero")

        overlay = Gtk.Overlay()
        ring = UsageRing(size=84, line_width=9.0).set_fraction(fraction)
        overlay.add(ring)
        percent = Gtk.Label(label=f"{fraction * 100:.0f}%")
        percent.set_halign(Gtk.Align.CENTER)
        percent.set_valign(Gtk.Align.CENTER)
        _css(percent, "adaptive-ring-value")
        overlay.add_overlay(percent)
        hero.pack_start(overlay, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_valign(Gtk.Align.CENTER)

        name = Gtk.Label(
            label=volume["label"] or ("System Disk" if volume["target"] == "/" else _short_path(volume["target"])),
            xalign=0,
        )
        name.set_ellipsize(Pango.EllipsizeMode.END)
        _css(name, "adaptive-storage-name")
        text.pack_start(name, False, False, 0)

        free = Gtk.Label(label=f"{_human_size(usage.free)} available", xalign=0)
        _css(free, "adaptive-storage-free")
        text.pack_start(free, False, False, 0)

        of_total = Gtk.Label(label=f"of {_human_size(usage.total)}", xalign=0)
        _css(of_total, "adaptive-storage-caption")
        text.pack_start(of_total, False, False, 0)

        status = Gtk.Label(xalign=0)
        if fraction >= CAPACITY_CRIT:
            status.set_text("Almost full")
            _css(status, "adaptive-status", "critical")
        elif fraction >= CAPACITY_WARN:
            status.set_text("Getting full")
            _css(status, "adaptive-status", "warning")
        else:
            status.set_text("Plenty of space")
            _css(status, "adaptive-status", "good")
        status.set_halign(Gtk.Align.START)
        status.set_margin_top(5)
        text.pack_start(status, False, False, 0)

        hero.pack_start(text, True, True, 0)
        body.pack_start(hero, False, False, 0)

        # Composition: the biggest Home folders, the rest of Home, then
        # everything outside Home, against the free space as track.
        home_usage = self._home_usage or _cached_home_usage()
        self._home_usage = home_usage
        stale = (
            home_usage is None
            or time.time() - home_usage.get("measured_at", 0) > HOME_USAGE_MAX_AGE
        )

        composition = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        trailing = None
        if home_usage is not None:
            trailing = (
                "Measuring…"
                if self._home_measuring
                else "Measured " + _relative_time(home_usage.get("measured_at", 0))
            )
        composition.pack_start(self._section_label("Used Space", trailing=trailing), False, False, 0)
        group = self._group()

        if home_usage is None or not on_home_disk:
            bar = SegmentBar(height=12).set_segments([(fraction, _capacity_color(fraction))])
            group.pack_start(bar, False, False, 4)
            if on_home_disk:
                group.pack_start(
                    self._note("Measuring what Home holds - this runs once in the background."),
                    False,
                    False,
                    0,
                )
            else:
                group.pack_start(
                    self._legend([
                        (_capacity_color(fraction), "Used", _human_size(used), f"{fraction * 100:.0f}%"),
                        (_rgb("#48484A"), "Available", _human_size(usage.free), ""),
                    ]),
                    False,
                    False,
                    0,
                )
        else:
            total = usage.total or 1
            rows = home_usage.get("rows") or []
            top = rows[:4]
            home_total = home_usage.get("total") or sum(row["bytes"] for row in rows)
            rest = max(0, home_total - sum(row["bytes"] for row in top))
            system = max(0, used - home_total)

            series = [
                (row["bytes"], SERIES_COLORS[index], row["name"])
                for index, row in enumerate(top)
            ]
            series.append((rest, SERIES_COLORS[4], "Rest of Home"))
            series.append((system, SERIES_COLORS[5], "System & Apps"))

            bar = SegmentBar(height=12).set_segments(
                [(value / total, color) for value, color, _label in series]
            )
            group.pack_start(bar, False, False, 4)
            group.pack_start(
                self._legend(
                    [
                        (color, label, _human_size(value), f"{value / total * 100:.0f}%")
                        for value, color, label in series
                        if value > 0
                    ]
                    + [(_rgb("#3A3A3C"), "Available", _human_size(usage.free), f"{usage.free / total * 100:.0f}%")]
                ),
                False,
                False,
                0,
            )

        composition.pack_start(group, False, False, 0)
        body.pack_start(composition, False, False, 0)

        # When space is short, say where it can come from.
        if home_usage is not None and on_home_disk and fraction >= CAPACITY_WARN:
            body.pack_start(self._recommendations(home_usage), False, False, 0)

        if home_usage is not None and on_home_disk and home_usage.get("rows"):
            payload = {
                "bytes": home_usage.get("total") or 1,
                "children": [
                    {"name": row["name"], "path": row["path"], "is_dir": True, "bytes": row["bytes"]}
                    for row in home_usage["rows"]
                ],
            }
            body.pack_start(self._largest_items(payload, title="Largest in Home", limit=8), False, False, 0)

        volumes = self._other_volumes(path)
        if volumes:
            body.pack_start(volumes, False, False, 0)

        body.pack_start(self._section_label("Volume"), False, False, 0)
        details = self._group()
        self._info_row(details, "Device", volume["source"] or "—", mono=True)
        self._info_row(details, "Format", volume["fstype"] or "—")
        self._info_row(details, "Mounted at", volume["target"] or "—", mono=True)
        body.pack_start(details, False, False, 0)

        self._actions_row(
            self.storage_body,
            [
                ("view-refresh-symbolic", "Measure Again", lambda *_: self._measure_home(force=True)),
                ("user-home-symbolic", "Home", lambda *_: self._open_location(Path.home().as_uri())),
                ("drive-harddisk-symbolic", "Computer", lambda *_: self._open_location("file:///")),
            ],
        )

        body.show_all()

        if stale and on_home_disk:
            self._measure_home()

    def _measure_home(self, force=False):
        if self._home_measuring:
            return
        if not force and self._home_usage is not None:
            age = time.time() - self._home_usage.get("measured_at", 0)
            if age < HOME_USAGE_MAX_AGE:
                return

        self._home_measuring = True

        def done(data, error):
            self._home_measuring = False
            if error:
                _log(f"Home measurement failed: {error}")
            else:
                self._home_usage = data
            if self.stack is not None and self.stack.get_visible_child_name() == "storage":
                self._render_storage()

        self._submit(_measure_home, (), done, executor=_SLOW_EXECUTOR)
        if self.stack is not None and self.stack.get_visible_child_name() == "storage":
            self._render_storage()

    def _recommendations(self, home_usage):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self._section_label("Free Up Space"), False, False, 0)
        group = self._group()

        by_name = {row["name"]: row["bytes"] for row in home_usage.get("rows") or []}
        candidates = [
            ("user-trash-symbolic", "Trash", home_usage.get("trash", 0), "trash:///",
             "Deleted files still take space until the Trash is emptied."),
            ("folder-download-symbolic", "Downloads", by_name.get("Downloads", 0),
             (Path.home() / "Downloads").as_uri(), "Installers and archives tend to pile up here."),
            ("folder-symbolic", "Caches", by_name.get(".cache", 0),
             (Path.home() / ".cache").as_uri(), "Apps rebuild these when needed."),
        ]

        shown = 0
        for icon_name, title, size, uri, why in candidates:
            if size < 256 * 1024 * 1024:
                continue
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            _css(row, "adaptive-info-row")
            icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
            icon.set_pixel_size(18)
            _css(icon, "adaptive-accent-icon")
            row.pack_start(icon, False, False, 0)

            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            head = Gtk.Label(label=f"{title} · {_human_size(size)}", xalign=0)
            _css(head, "adaptive-row-title")
            detail = Gtk.Label(label=why, xalign=0)
            detail.set_line_wrap(True)
            _css(detail, "adaptive-row-subtitle")
            text.pack_start(head, False, False, 0)
            text.pack_start(detail, False, False, 0)
            row.pack_start(text, True, True, 0)

            review = Gtk.Button(label="Review")
            review.set_valign(Gtk.Align.CENTER)
            review.connect("clicked", lambda _b, target=uri: self._open_location(target))
            _css(review, "adaptive-pill-button")
            row.pack_end(review, False, False, 0)

            group.pack_start(row, False, False, 0)
            shown += 1

        if not shown:
            group.pack_start(
                self._note("Trash, Downloads and caches are small. See Largest in Home below."),
                False,
                False,
                0,
            )

        box.pack_start(group, False, False, 0)
        return box

    def _other_volumes(self, current_path):
        rows = []
        seen = set()

        try:
            current_target = _volume_label(current_path)["target"]
        except Exception:
            current_target = "/"
        seen.add(current_target)

        try:
            mounts = Gio.VolumeMonitor.get().get_mounts()
        except Exception:
            mounts = []

        for mount in mounts:
            try:
                root = mount.get_root()
                path = root.get_path()
            except Exception:
                continue
            # GVfs network shares are FUSE mounts under /run/user; statvfs on
            # one whose server went away blocks. They belong to Network.
            if not path or path in seen or "/gvfs/" in path:
                continue
            seen.add(path)
            try:
                usage = shutil.disk_usage(path)
            except Exception:
                continue
            rows.append((mount, path, usage))

        if not rows:
            return None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self._section_label("Other Volumes"), False, False, 0)
        group = self._group()

        for mount, path, usage in rows:
            fraction = (usage.total - usage.free) / usage.total if usage.total else 0.0
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            _css(row, "adaptive-info-row")

            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            icon = Gtk.Image.new_from_gicon(mount.get_symbolic_icon(), Gtk.IconSize.BUTTON)
            _css(icon, "adaptive-accent-icon")
            line.pack_start(icon, False, False, 0)

            name = Gtk.Label(label=mount.get_name() or _short_path(path), xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            _css(name, "adaptive-row-title")
            line.pack_start(name, True, True, 0)

            free = Gtk.Label(label=f"{_human_size(usage.free)} free", xalign=1)
            _css(free, "adaptive-row-value")
            line.pack_end(free, False, False, 0)

            if mount.can_eject() or mount.can_unmount():
                eject = Gtk.Button.new_from_icon_name("media-eject-symbolic", Gtk.IconSize.BUTTON)
                eject.set_tooltip_text("Eject")
                eject.connect("clicked", lambda _b, m=mount: self._eject(m))
                _css(eject, "adaptive-icon-button")
                line.pack_end(eject, False, False, 0)

            row.pack_start(line, False, False, 0)
            bar = SegmentBar(height=5).set_segments([(fraction, _capacity_color(fraction))])
            row.pack_start(bar, False, False, 0)

            open_button = Gtk.EventBox()
            open_button.add(row)
            open_button.connect(
                "button-release-event",
                lambda _w, _e, uri=Path(path).as_uri(): self._open_location(uri) or True,
            )
            group.pack_start(open_button, False, False, 0)

        box.pack_start(group, False, False, 0)
        return box

    def _eject(self, mount):
        operation = Gtk.MountOperation.new(self.window)

        def finished(source, result, _data=None):
            try:
                if mount.can_eject():
                    source.eject_with_operation_finish(result)
                else:
                    source.unmount_with_operation_finish(result)
            except Exception as error:
                self._show_error("Couldn't eject", str(error))
            GLib.idle_add(self._render_storage)

        try:
            if mount.can_eject():
                mount.eject_with_operation(Gio.MountUnmountFlags.NONE, operation, None, finished, None)
            else:
                mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, operation, None, finished, None)
        except Exception as error:
            self._show_error("Couldn't eject", str(error))

    @staticmethod
    def _same_filesystem(first, second):
        try:
            return os.stat(first).st_dev == os.stat(second).st_dev
        except OSError:
            return False

    # --------------------------------------------------------------
    # Network / native GVfs frontend
    # --------------------------------------------------------------

    def _render_network(self):
        self._clear(self.network_body)
        body = self.network_body

        icon = Gtk.Image.new_from_icon_name("network-server-symbolic", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(40)
        hero, _subtitle = self._hero(icon, "Network", "Servers and shared folders")
        body.pack_start(hero, False, False, 0)

        mounts = self._remote_mounts()
        body.pack_start(
            self._section_label("Connected", trailing=str(len(mounts)) if mounts else None),
            False,
            False,
            0,
        )
        connected = self._group()
        if not mounts:
            connected.pack_start(self._note("No servers connected."), False, False, 0)
        for mount in mounts:
            connected.pack_start(self._remote_row(mount), False, False, 0)
        body.pack_start(connected, False, False, 0)

        body.pack_start(self._section_label("Connect to Server"), False, False, 0)
        connect_card = self._group()

        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chips.set_homogeneous(True)
        entry = Gtk.Entry()
        entry.set_placeholder_text("smb://server/share")
        entry.set_hexpand(True)
        entry.connect("activate", lambda e: self._connect_remote(e.get_text()))
        _css(entry, "adaptive-network-entry")

        for label, scheme in (("SMB", "smb://"), ("SFTP", "sftp://"), ("FTP", "ftp://"), ("WebDAV", "davs://")):
            chip = Gtk.Button(label=label)
            _css(chip, "adaptive-chip")

            def use_scheme(_button, prefix=scheme):
                text = entry.get_text()
                rest = text.split("://", 1)[1] if "://" in text else text
                entry.set_text(prefix + rest)
                entry.grab_focus()
                entry.set_position(-1)

            chip.connect("clicked", use_scheme)
            chips.pack_start(chip, True, True, 0)

        connect_card.pack_start(chips, False, False, 0)
        connect_card.pack_start(entry, False, False, 2)

        connect = Gtk.Button(label="Connect")
        connect.connect("clicked", lambda *_: self._connect_remote(entry.get_text()))
        _css(connect, "adaptive-primary-button")
        connect_card.pack_start(connect, False, False, 0)
        body.pack_start(connect_card, False, False, 0)

        recent = self._recent_servers()
        if recent:
            body.pack_start(self._section_label("Recent Servers"), False, False, 0)
            group = self._group()
            for title, uri in recent:
                group.pack_start(
                    self._link_row("folder-remote-symbolic", title, uri, lambda target=uri: self._connect_remote(target)),
                    False,
                    False,
                    0,
                )
            body.pack_start(group, False, False, 0)

        self._actions_row(
            body,
            [
                ("network-workgroup-symbolic", "Browse", lambda *_: self._open_location("network:///")),
                ("go-jump-symbolic", "Go to Location", lambda *_: self._activate_window_action("enter-location")),
            ],
        )
        body.show_all()

    def _remote_row(self, mount):
        uri = mount.get_root().get_uri()
        row = self._link_row(
            None,
            mount.get_name() or uri,
            uri,
            lambda target=uri: self._open_location(target),
            gicon=mount.get_symbolic_icon(),
            status=True,
        )
        if mount.can_unmount():
            button = Gtk.Button.new_from_icon_name("media-eject-symbolic", Gtk.IconSize.BUTTON)
            button.set_tooltip_text("Disconnect")
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", lambda *_: self._disconnect(mount))
            _css(button, "adaptive-icon-button")
            row.get_child().pack_end(button, False, False, 0)
        return row

    def _disconnect(self, mount):
        def finished(source, result, _data=None):
            try:
                source.unmount_with_operation_finish(result)
            except Exception as error:
                self._show_error("Couldn't disconnect", str(error))
            GLib.idle_add(self._render_network)

        mount.unmount_with_operation(
            Gio.MountUnmountFlags.NONE,
            Gtk.MountOperation.new(self.window),
            None,
            finished,
            None,
        )

    def _recent_servers(self):
        """Servers GTK's "Connect to Server" remembers, newest first."""
        path = Path(GLib.get_user_config_dir()) / "gtk-3.0" / "servers"
        result = []
        try:
            bookmarks = GLib.BookmarkFile()
            bookmarks.load_from_file(str(path))
            uris = bookmarks.get_uris()
        except Exception:
            return result

        def modified(uri):
            try:
                return bookmarks.get_modified(uri)
            except Exception:
                return 0

        for uri in sorted(uris, key=modified, reverse=True)[:6]:
            try:
                title = bookmarks.get_title(uri)
            except Exception:
                title = None
            result.append((title or uri.split("://", 1)[-1].rstrip("/"), uri))
        return result

    def _connect_remote(self, text):
        uri = (text or "").strip()

        if not uri:
            return

        if "://" not in uri:
            uri = "smb://" + uri

        allowed = (
            "smb://",
            "sftp://",
            "ssh://",
            "ftp://",
            "dav://",
            "davs://",
            "nfs://",
            "afp://",
        )

        if not uri.casefold().startswith(allowed):
            self._show_error(
                "Unsupported address",
                (
                    "Use a GVfs address such as smb://server/share, "
                    "sftp://host/path, ftp://host/path, dav:// or davs://."
                ),
            )
            return

        self._open_location(uri)

    def _remote_mounts(self):
        result = []

        try:
            monitor = Gio.VolumeMonitor.get()
            for mount in monitor.get_mounts():
                if not mount.get_root().get_uri().startswith("file://"):
                    result.append(mount)
        except Exception:
            pass

        return result[:12]

    # --------------------------------------------------------------
    # Projects
    # --------------------------------------------------------------

    def _load_projects(self):
        """Project registry from the Project Context Service, one entry per
        path (the registry can hold duplicates), favourites first, then most
        recently active. Short timeouts: a stuck service must not stall the
        Files window."""
        if not self._dbus_proxy:
            return None, []

        active_id = None
        try:
            res = self._dbus_proxy.call_sync("GetActiveProject", None, Gio.DBusCallFlags.NONE, 1500, None)
            active_id = res.unpack()[0] or None
        except Exception:
            _log_exception("GetActiveProject failed")

        try:
            res = self._dbus_proxy.call_sync("ListProjects", None, Gio.DBusCallFlags.NONE, 1500, None)
            projects = json.loads(res.unpack()[0]) or {}
        except Exception:
            _log_exception("ListProjects failed")
            return active_id, []

        by_path = {}
        for pid, data in projects.items():
            path = data.get("path") or ""
            current = by_path.get(path)
            richer = bool((data.get("metadata") or {}).get("git"))
            if current is None or (richer and not (current.get("metadata") or {}).get("git")) or pid == active_id:
                entry = dict(data)
                entry["id"] = pid
                by_path[path] = entry

        def rank(entry):
            metadata = entry.get("metadata") or {}
            return (
                0 if entry["id"] == active_id else 1,
                0 if metadata.get("favorite") else 1,
                -(entry.get("last_active_at") or 0),
            )

        ordered = sorted(by_path.values(), key=rank)
        self._projects_cache = (active_id, ordered)
        return active_id, ordered

    def _project_for_path(self, path):
        if not path:
            return None
        _active, projects = self._projects_cache or (None, [])
        best = None
        for project in projects:
            root = project.get("path") or ""
            if root and (path == root or path.startswith(root.rstrip(os.sep) + os.sep)):
                if best is None or len(root) > len(best.get("path") or ""):
                    best = project
        return best

    def _project_chip(self, project):
        chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        _css(chip, "adaptive-project-chip")

        icon = Gtk.Image.new_from_icon_name("folder-templates-symbolic", Gtk.IconSize.BUTTON)
        _css(icon, "adaptive-accent-icon")
        chip.pack_start(icon, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name = Gtk.Label(label=project.get("name") or "Project", xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        _css(name, "adaptive-row-title")
        text.pack_start(name, False, False, 0)

        git = (project.get("metadata") or {}).get("git") or {}
        detail = Gtk.Label(label=self._git_summary(git) or "Project folder", xalign=0)
        detail.set_ellipsize(Pango.EllipsizeMode.END)
        _css(detail, "adaptive-row-subtitle")
        text.pack_start(detail, False, False, 0)
        chip.pack_start(text, True, True, 0)
        return chip

    @staticmethod
    def _git_summary(git):
        # The scanner records "-" as the branch of a folder that is not a
        # repository; such a project has nothing to summarise.
        branch = (git or {}).get("branch") or ""
        if not git or (branch in ("", "-") and not git.get("commits")):
            return ""
        parts = []
        if branch not in ("", "-"):
            parts.append(branch)
        dirty = git.get("dirty") or 0
        parts.append(_count_text(dirty, "change") if dirty else "clean")
        if git.get("last_commit_at"):
            parts.append("committed " + _relative_time(git["last_commit_at"]))
        return " · ".join(parts)

    def _render_project(self):
        self._clear(self.project_body)
        body = self.project_body

        if not self._dbus_proxy:
            body.pack_start(
                self._note("The Project Context Service isn't running, so projects can't be listed."),
                False,
                False,
                0,
            )
            body.show_all()
            return

        active_id, projects = self._load_projects()
        self._active_project_id = active_id
        active = next((p for p in projects if p["id"] == active_id), None)

        if active is not None:
            icon = Gtk.Image.new_from_icon_name("folder-templates", Gtk.IconSize.DIALOG)
            icon.set_pixel_size(56)
            hero, _subtitle = self._hero(icon, active.get("name") or "Project", _short_path(active.get("path")))
            body.pack_start(hero, False, False, 0)

            git = (active.get("metadata") or {}).get("git") or {}
            if git:
                tiles = self._stat_tiles(
                    [
                        (git.get("branch") or "—", "Branch"),
                        (f"{git.get('dirty') or 0:,}", "Changes"),
                        (f"{git.get('commits') or 0:,}", "Commits"),
                    ]
                )
                body.pack_start(tiles, False, False, 0)
                if git.get("last_commit_subject"):
                    body.pack_start(self._section_label("Last Commit"), False, False, 0)
                    group = self._group()
                    subject = Gtk.Label(label=git["last_commit_subject"], xalign=0)
                    subject.set_line_wrap(True)
                    _css(subject, "adaptive-row-title")
                    group.pack_start(subject, False, False, 0)
                    who = " · ".join(
                        part
                        for part in (
                            git.get("last_commit_author") or "",
                            _relative_time(git["last_commit_at"]) if git.get("last_commit_at") else "",
                        )
                        if part
                    )
                    if who:
                        meta = Gtk.Label(label=who, xalign=0)
                        _css(meta, "adaptive-row-subtitle")
                        group.pack_start(meta, False, False, 0)
                    body.pack_start(group, False, False, 0)

            self._actions_row(
                body,
                [
                    ("folder-open-symbolic", "Open Folder", lambda *_: self._open_location(Path(active["path"]).as_uri())),
                    ("utilities-terminal-symbolic", "Terminal", lambda *_: self._open_terminal(active["path"])),
                    ("edit-copy-symbolic", "Copy Path", lambda *_: self._copy_text(active["path"])),
                ],
            )
        else:
            body.pack_start(
                self._note("No active project. Pick one below to make it the context for Files and the shell."),
                False,
                False,
                0,
            )

        search = Gtk.SearchEntry()
        search.set_placeholder_text(f"Search {len(projects)} projects")
        search.set_margin_top(12)
        _css(search, "adaptive-search")
        body.pack_start(search, False, False, 0)

        group = self._group()
        rows = []
        for project in projects:
            row = self._project_row(project, project["id"] == active_id)
            rows.append((project, row))
            group.pack_start(row, False, False, 0)
        if not projects:
            group.pack_start(self._note("No projects found."), False, False, 0)
        body.pack_start(group, False, False, 0)

        def apply_filter(entry):
            needle = entry.get_text().casefold().strip()
            for project, row in rows:
                haystack = f"{project.get('name', '')} {project.get('path', '')}".casefold()
                row.set_visible(not needle or needle in haystack)

        search.connect("search-changed", apply_filter)
        body.show_all()

    def _project_row(self, project, is_active):
        git = (project.get("metadata") or {}).get("git") or {}
        subtitle = self._git_summary(git) or _short_path(project.get("path"))

        row = self._link_row(
            "emblem-default-symbolic" if is_active else (
                "starred-symbolic" if (project.get("metadata") or {}).get("favorite") else "folder-symbolic"
            ),
            project.get("name") or "Project",
            subtitle,
            lambda target=project["id"]: self._set_active_project(target),
            active=is_active,
        )
        row.set_tooltip_text(project.get("path") or "")
        return row

    def _set_active_project(self, project_id):
        try:
            self._dbus_proxy.call_sync(
                "SetActiveProject",
                GLib.Variant("(s)", (project_id,)),
                Gio.DBusCallFlags.NONE,
                1500,
                None,
            )
        except Exception:
            _log_exception("SetActiveProject failed")
        self._render_project()

    # --------------------------------------------------------------
    # Native actions / helpers
    # --------------------------------------------------------------

    def _bookmark_current_location(self):
        if not self._activate_window_action("bookmark-current-location"):
            self._show_error(
                "Bookmark unavailable",
                "Files can't bookmark this location.",
            )

    def _activate_window_action(self, action_name):
        window = self.window
        if window is None:
            return False

        try:
            actions = list(window.list_actions())
            if action_name not in actions:
                _log(
                    f"Window action not present: {action_name}; "
                    f"available={actions}"
                )
                return False

            window.activate_action(action_name, None)
            return True
        except Exception:
            _log_exception(f"Unable to activate action {action_name}")
            return False

    def _view_action(self, action_name):
        """Run one of the files view's own actions ("view.<name>") on the
        current selection, so Open, Open With and Properties behave exactly
        as the context menu does."""
        window = self.window
        if window is None:
            return False
        try:
            group = window.get_action_group("view")
            if group is None or not group.has_action(action_name):
                _log(f"View action not present: {action_name}")
                return False
            if not group.get_action_enabled(action_name):
                return False
            group.activate_action(action_name, None)
            return True
        except Exception:
            _log_exception(f"Unable to activate view action {action_name}")
            return False

    def _open_terminal(self, path):
        command = None
        try:
            settings = Gio.Settings.new("org.gnome.desktop.default-applications.terminal")
            command = settings.get_string("exec") or None
        except Exception:
            pass

        for candidate in (command, "x-terminal-emulator", "gnome-terminal"):
            if candidate and shutil.which(candidate):
                try:
                    subprocess.Popen(
                        [candidate],
                        cwd=path,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return
                except Exception:
                    continue
        self._show_error("No terminal found", "Set a default terminal in Settings.")

    def _open_location(self, uri):
        binary = os.environ.get("ADAPTIVE_FILES_BIN")

        try:
            if binary and Path(binary).exists():
                env = os.environ.copy()
                subprocess.Popen(
                    [binary, uri],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return

            Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception as error:
            self._show_error("Unable to open location", str(error))

    def _copy_text(self, text):
        try:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(str(text), -1)
            clipboard.store()
        except Exception:
            _log_exception("Clipboard copy failed")

    def _show_error(self, title, body):
        window = self.window

        dialog = Gtk.MessageDialog(
            transient_for=window,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(body)
        dialog.connect("response", lambda dialog, *_: dialog.destroy())
        dialog.show_all()

    def _submit(self, function, args, callback, executor=None):
        """Run function(*args) off the main loop and hand (result, error) to
        callback on it. Workers return plain data; GTK is only touched in the
        callback."""
        future = (executor or _EXECUTOR).submit(function, *args)

        def done(fut):
            try:
                payload, error = fut.result(), None
            except Exception as exc:
                payload, error = None, str(exc) or type(exc).__name__
                _log(f"Worker {getattr(function, '__name__', function)} failed: {error}")

            def deliver():
                try:
                    callback(payload, error)
                except Exception:
                    _log_exception("Worker callback failed")
                return GLib.SOURCE_REMOVE

            GLib.idle_add(deliver)

        future.add_done_callback(done)

    # --------------------------------------------------------------
    # UI building blocks
    # --------------------------------------------------------------

    def _clear(self, box):
        for child in list(box.get_children()):
            box.remove(child)

    def _group(self):
        """Grouped rows on a tile, hairline between rows (see preview.css)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _css(box, "adaptive-group")
        return box

    def _section_label(self, text, trailing=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        _css(row, "adaptive-section")
        label = Gtk.Label(label=text, xalign=0)
        _css(label, "adaptive-section-label")
        row.pack_start(label, True, True, 0)
        if trailing:
            extra = Gtk.Label(label=trailing, xalign=1)
            _css(extra, "adaptive-section-trailing")
            row.pack_end(extra, False, False, 0)
        return row

    def _note(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        _css(label, "adaptive-note")
        return label

    def _hero(self, icon, title, subtitle):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        _css(box, "adaptive-hero")

        if icon is not None:
            icon.set_halign(Gtk.Align.CENTER)
            icon.set_margin_bottom(6)
            _css(icon, "adaptive-hero-icon")
            box.pack_start(icon, False, False, 0)

        name = Gtk.Label(label=title or "")
        name.set_line_wrap(True)
        name.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        name.set_justify(Gtk.Justification.CENTER)
        name.set_max_width_chars(28)
        _css(name, "adaptive-hero-title")
        box.pack_start(name, False, False, 0)

        caption = Gtk.Label(label=subtitle or "")
        caption.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        _css(caption, "adaptive-hero-subtitle")
        box.pack_start(caption, False, False, 0)
        return box, caption

    def _gicon_image(self, gfile, fallback_name, size):
        """The icon Files itself shows for gfile (custom folder icons, the
        special Home/Downloads glyphs), else fallback_name."""
        gicon = None
        if gfile is not None:
            try:
                info = gfile.query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None)
                gicon = info.get_icon()
            except Exception:
                gicon = None
        if gicon is not None:
            image = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DIALOG)
        elif fallback_name:
            image = Gtk.Image.new_from_icon_name(fallback_name, Gtk.IconSize.DIALOG)
        else:
            return None
        image.set_pixel_size(size)
        return image

    def _icon_name_for(self, name):
        try:
            content_type, _uncertain = Gio.content_type_guess(name, None)
            icon = Gio.content_type_get_icon(content_type)
            names = icon.get_names() if hasattr(icon, "get_names") else []
            theme = Gtk.IconTheme.get_default()
            for candidate in names:
                if theme.has_icon(candidate):
                    return candidate
        except Exception:
            pass
        return "text-x-generic"

    def _stat_tiles(self, tiles):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_homogeneous(True)
        box.set_margin_top(8)
        _css(box, "adaptive-stats")
        for value, caption in tiles:
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            _css(tile, "adaptive-stat")
            number = Gtk.Label(label=value)
            number.set_ellipsize(Pango.EllipsizeMode.END)
            _css(number, "adaptive-stat-value")
            label = Gtk.Label(label=caption)
            _css(label, "adaptive-stat-caption")
            tile.pack_start(number, False, False, 0)
            tile.pack_start(label, False, False, 0)
            box.pack_start(tile, True, True, 0)
        return box

    def _set_stat_tiles(self, box, tiles):
        for tile, (value, caption) in zip(box.get_children(), tiles):
            number, label = tile.get_children()
            number.set_text(value)
            label.set_text(caption)

    def _legend(self, rows):
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(5)
        _css(grid, "adaptive-legend")
        for index, (color, label, value, share) in enumerate(rows):
            grid.attach(Swatch(color), 0, index, 1, 1)
            name = Gtk.Label(label=label, xalign=0)
            name.set_hexpand(True)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            _css(name, "adaptive-legend-label")
            grid.attach(name, 1, index, 1, 1)
            size = Gtk.Label(label=value, xalign=1)
            _css(size, "adaptive-legend-value")
            grid.attach(size, 2, index, 1, 1)
            extra = Gtk.Label(label=share, xalign=1)
            extra.set_width_chars(4)
            _css(extra, "adaptive-legend-share")
            grid.attach(extra, 3, index, 1, 1)
        return grid

    def _bar_row(self, icon_name, name, value, fraction, color, tooltip=None):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        _css(row, "adaptive-info-row", "adaptive-bar-row")
        if tooltip:
            row.set_tooltip_text(tooltip)

        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        icon.set_pixel_size(16)
        line.pack_start(icon, False, False, 0)
        label = Gtk.Label(label=name, xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        _css(label, "adaptive-row-title")
        line.pack_start(label, True, True, 0)
        size = Gtk.Label(label=value, xalign=1)
        _css(size, "adaptive-row-value")
        line.pack_end(size, False, False, 0)
        row.pack_start(line, False, False, 0)

        bar = SegmentBar(height=4).set_segments([(fraction, color)])
        bar.set_margin_start(24)
        row.pack_start(bar, False, False, 0)
        return row

    def _info_row(self, parent, key, value, mono=False, hint=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        _css(row, "adaptive-info-row")

        left = Gtk.Label(label=key, xalign=0)
        left.set_valign(Gtk.Align.START)
        _css(left, "adaptive-meta-key")
        row.pack_start(left, False, False, 0)

        values = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right = Gtk.Label(label=str(value), xalign=1)
        right.set_line_wrap(True)
        right.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        right.set_selectable(True)
        right.set_can_focus(False)
        _css(right, "adaptive-meta-value", *(("adaptive-mono",) if mono else ()))
        values.pack_start(right, False, False, 0)
        if hint:
            extra = Gtk.Label(label=hint, xalign=1)
            _css(extra, "adaptive-meta-hint")
            values.pack_start(extra, False, False, 0)
        row.pack_end(values, True, True, 0)

        parent.pack_start(row, False, False, 0)
        return right

    def _link_row(self, icon_name, title, subtitle, on_activate, gicon=None, active=False, status=False):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        _css(button, "adaptive-link-row", *(("active",) if active else ()))
        button.connect("clicked", lambda *_: on_activate())

        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        if gicon is not None:
            icon = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.BUTTON)
        else:
            icon = Gtk.Image.new_from_icon_name(icon_name or "folder-symbolic", Gtk.IconSize.BUTTON)
        icon.set_pixel_size(16)
        _css(icon, "adaptive-accent-icon")
        line.pack_start(icon, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        head = Gtk.Label(label=title, xalign=0)
        head.set_ellipsize(Pango.EllipsizeMode.END)
        _css(head, "adaptive-row-title")
        text.pack_start(head, False, False, 0)
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0)
            sub.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            _css(sub, "adaptive-row-subtitle")
            text.pack_start(sub, False, False, 0)
        line.pack_start(text, True, True, 0)

        if status:
            dot = Swatch(_rgb("#30D158"), size=7)
            dot.set_tooltip_text("Connected")
            line.pack_end(dot, False, False, 0)

        button.add(line)
        return button

    def _actions_row(self, body, actions):
        previous = self.preview_body
        self.preview_body = body
        try:
            self._append_actions(actions)
        finally:
            self.preview_body = previous

    def _render_message(self, title, body):
        self._clear(self.preview_body)

        icon = Gtk.Image.new_from_icon_name("document-open-recent-symbolic", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(40)
        hero, _subtitle = self._hero(icon, title, "")
        self.preview_body.pack_start(hero, False, False, 0)
        self.preview_body.pack_start(self._note(body), False, False, 0)
        self.preview_body.show_all()


class AdaptivePreviewExtension(GObject.GObject, Nautilus.MenuProvider, Nautilus.LocationWidgetProvider):
    """
    Nautilus 42's MenuProvider callback includes the window and the selected
    files. The selection callback is used as a notification source; the only
    context-menu item is the inspector toggle.
    """

    def __init__(self):
        global _MENU_OWNER

        super().__init__()

        if _MENU_OWNER is None:
            _MENU_OWNER = self

        _log("Adaptive Preview extension initialized.")

    def _window_from_args(self, args):
        for value in args:
            if isinstance(value, Gtk.Window):
                return value

        try:
            app = Gtk.Application.get_default()
            if app is not None:
                return app.get_active_window()
        except Exception:
            pass

        return None

    def _controller(self, window):
        if window is None:
            return None

        key = id(window)
        controller = _CONTROLLERS.get(key)

        if controller is None or controller.window is None:
            controller = PreviewController(window)
            _CONTROLLERS[key] = controller

            try:
                def _cleanup(*_args, k=key, c=controller):
                    _CONTROLLERS.pop(k, None)
                    c.release()

                window.connect("destroy", _cleanup)
            except Exception:
                pass

        return controller

    def get_widget(self, uri, window):
        """
        Nautilus 42 calls LocationWidgetProvider whenever the location/view
        changes. We use it as the deterministic window hook and return a
        compact Adaptive Files control strip.
        """
        try:
            controller = self._controller(window)

            if controller is None:
                return None

            controller.ensure_attached()
            GLib.idle_add(controller.ensure_attached)
            controller.set_location(uri)

            # No widget. This provider stays because it is the one callback
            # Nautilus makes on every location change, which is what gives the
            # inspector a deterministic hook to attach to - but it contributes
            # no UI of its own.
            #
            # It used to return an "ADAPTIVE FILES" strip carrying an Inspector
            # toggle and Storage/Network/Project buttons. The inspector already
            # has those as tabs and shows the path in its Location section, so
            # the strip was a second copy of the panel's own controls taking a
            # row off the top of every folder.
            controller._reserve_space()

            _log(
                f"Location hook for uri={uri}; "
                f"window={_type_name(window)}"
            )

            return None

        except Exception:
            _log_exception("get_widget failed")
            return None

    def get_file_items(self, *args):
        try:
            window = self._window_from_args(args)
            files = args[-1] if args else []

            controller = self._controller(window)
            if controller is None:
                return []

            snapshots = []
            try:
                for info in list(files or []):
                    snapshots.append(_snapshot_file(info))
            except Exception:
                _log_exception("Unable to snapshot Nautilus selection")

            GLib.idle_add(controller.update_selection, snapshots)

        except Exception:
            _log_exception("get_file_items failed")

        return []

    def get_background_items(self, *args):
        try:
            window = self._window_from_args(args)
            controller = self._controller(window)

            if controller is None:
                return []

            GLib.idle_add(controller.ensure_attached)

            # Nautilus passes the folder being shown; with nothing selected
            # the Info tab summarises it.
            folder = args[-1] if args else None
            if folder is not None and not isinstance(folder, Gtk.Window):
                try:
                    controller.set_location(folder.get_uri())
                except Exception:
                    pass

            if self is not _MENU_OWNER:
                return []

            # The only way to put the inspector away. It used to be a toggle on
            # the location strip; the strip is gone, and a right-click item
            # costs no screen space to offer.
            item = Nautilus.MenuItem(
                name="AdaptivePreview::toggle_inspector",
                label=(
                    "Hide Inspector"
                    if controller.panel_visible
                    else "Show Inspector"
                ),
                tip="Show or hide the Adaptive inspector panel",
            )
            item.connect(
                "activate",
                lambda _item: controller.toggle_panel(),
            )

            return [item]

        except Exception:
            _log_exception("get_background_items failed")

        return []
