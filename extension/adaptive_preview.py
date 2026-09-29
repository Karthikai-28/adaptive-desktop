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
import io
import math
import os
from pathlib import Path
import shlex
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

# Optional pieces: each feature that needs one switches itself off when it
# is missing, rather than taking the inspector down with it.
try:
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte
except (ValueError, ImportError):
    Vte = None

try:
    gi.require_version("Handy", "1")
    from gi.repository import Handy
except (ValueError, ImportError):
    Handy = None

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    HAVE_PLAYER = Gst.ElementFactory.find("gtksink") is not None
except (ValueError, ImportError):
    Gst = None
    HAVE_PLAYER = False

# Helper modules live in a package beside this file: nautilus-python loads
# every top-level .py in its extensions folder as an extension of its own.
import sys  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from adaptive_files import archives, cleanup, gitinfo, media, models  # noqa: E402
from adaptive_files import tags as filetags  # noqa: E402

# Finder's preview pane width. The panel is one inspector column, not a
# dashboard, so it gives the file grid back every pixel it can.
PANEL_WIDE = 260
PANEL_MEDIUM = 244
PANEL_NARROW = 228
# Windows narrower than this hide the inspector until widened again.
AUTO_HIDE_BELOW = 1000

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
# Thumbnails and git status for whole folders queue here, so they never hold
# up the selected item's own preview on _EXECUTOR.
_BACKGROUND = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_INFO_OWNER = None
# Git badges re-check a repository at least this often while it is on screen;
# commits and edits trigger a re-check sooner (index monitor, file mtimes).
GIT_STALE_SECONDS = 30

# nautilus-python starts Python and never releases the GIL: Files' main
# thread holds it even while it sits in its own C main loop. Worker threads
# therefore only advance while the main thread happens to be running Python,
# which showed up as previews stuck on "Loading…" until the next click.
# While any job is pending, a short timer on the main thread sleeps for a
# moment - sleeping releases the GIL - so the workers get to run. With no
# jobs pending the timer stops and costs nothing.
_PENDING = [0]
_PUMP = [0]


def _pump():
    if _PENDING[0] <= 0:
        _PUMP[0] = 0
        return GLib.SOURCE_REMOVE
    time.sleep(0.004)
    return GLib.SOURCE_CONTINUE


def _run_async(executor, function, *args):
    """executor.submit, plus keeping the GIL pump running until it is done."""
    _PENDING[0] += 1
    if not _PUMP[0]:
        _PUMP[0] = GLib.timeout_add(10, _pump)
    future = executor.submit(function, *args)

    def settled(_future):
        # Runs on the worker thread; the counter is only read by _pump.
        _PENDING[0] -= 1

    future.add_done_callback(settled)
    return future


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
        # (size, path) of files big enough to be worth de-duplicating.
        "records": [],
    }

    def spent():
        if remaining[0] <= 0 or time.monotonic() - started > max_seconds:
            result["truncated"] = True
            return True
        return False

    def account_file(name, st, path):
        size = st.st_size
        if size >= 64 * 1024 and len(result["records"]) < 30000:
            result["records"].append((size, path))
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
                            total += account_file(entry.name, st, entry.path)
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
            size = account_file(name, st, path) if stat.S_ISREG(st.st_mode) else 0
            result["children"].append(
                {
                    "name": name,
                    "path": path,
                    "is_dir": False,
                    "bytes": size,
                    "kind": _kind_for_name(name),
                    "mtime": st.st_mtime,
                    "atime": st.st_atime,
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


class TagDot(Gtk.Button):
    """A tag colour as a small round toggle: filled when applied, a ring
    when not."""

    def __init__(self, color):
        super().__init__()
        self._color = color
        self._filled = False
        self.set_relief(Gtk.ReliefStyle.NONE)
        _css(self, "adaptive-tag-dot")
        area = Gtk.DrawingArea()
        area.set_size_request(16, 16)
        area.connect("draw", self._draw)
        self.add(area)
        self._area = area

    def set_filled(self, filled):
        self._filled = bool(filled)
        self._area.queue_draw()

    def _draw(self, area, cr):
        width = area.get_allocated_width()
        height = area.get_allocated_height()
        radius = min(width, height) / 2.0 - 1.5
        cr.arc(width / 2.0, height / 2.0, radius, 0, math.tau)
        if self._filled:
            cr.set_source_rgb(*self._color)
            cr.fill_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.85)
            cr.set_line_width(1.5)
            cr.stroke()
        else:
            cr.set_source_rgba(self._color[0], self._color[1], self._color[2], 0.9)
            cr.set_line_width(1.5)
            cr.stroke()
        return False


# NautilusFileInfo objects the info provider has seen, by URI, so a tag or
# git change can ask Files to redraw exactly those icons. Bounded; losing an
# old entry only means that icon updates on the next directory refresh.
_KNOWN_FILES = {}
_KNOWN_LIMIT = 6000


def _remember_file(file_info):
    try:
        uri = file_info.get_uri()
    except Exception:
        return
    _KNOWN_FILES.pop(uri, None)
    _KNOWN_FILES[uri] = file_info
    while len(_KNOWN_FILES) > _KNOWN_LIMIT:
        _KNOWN_FILES.pop(next(iter(_KNOWN_FILES)))


def _refresh_file_badges(uris=None, prefix=None):
    """Re-run the info provider for these files (or everything under a
    folder URI prefix), which redraws their emblems."""
    targets = []
    if uris:
        targets = [_KNOWN_FILES[uri] for uri in uris if uri in _KNOWN_FILES]
    elif prefix:
        targets = [info for uri, info in _KNOWN_FILES.items() if uri.startswith(prefix)]
    for info in targets:
        try:
            info.invalidate_extension_info()
        except Exception:
            pass


def _reveal(paths):
    """Open each file's folder in Files with the file selected. Asynchronous
    on purpose: this process is the FileManager1 service, so a synchronous
    call to it from here would wait on itself."""
    uris = [Gio.File.new_for_path(path).get_uri() for path in paths]
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call(
            "org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1",
            "ShowItems",
            GLib.Variant("(ass)", (uris, "")),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            None,
            None,
        )
    except Exception:
        _log_exception("Reveal failed")


class PreviewController:
    def __init__(self, window):
        self._window = window
        self.panel = None
        # One reusable location strip per window; see get_widget().
        self.host_split = None

        self.preview_body = None


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
        self._narrow = False
        self._override = None
        self._controls_installed = False
        self._header_buttons = {}
        self._player = None
        self.host_column = None
        self.terminal_slot = None
        self.terminal = None
        self._terminal_pid = None
        self._terminal_cwd = None
        self._selection_key = None
        self._selection_at = 0.0
        self._current_name = ""
        self._file_subtitle = None
        self._scan_cache = {}
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
        # Projects only feed the chip on a folder summary; keep the list
        # current so the chip is right the next time a folder is shown.
        if signal_name in ("ActiveProjectChanged", "ProjectListChanged"):
            GLib.idle_add(self._load_projects)

    def _configure_process_theme(self):
        try:
            settings = Gtk.Settings.get_default()
            if settings is not None:
                settings.set_property("gtk-icon-theme-name", "AdaptiveFilesIcons")
                # No gtk-application-prefer-dark-theme: the Adaptive theme is
                # dark in both variants, and libhandy warns when it is set.
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
        # One column: what is selected, or the folder when nothing is. Disk
        # space and the owning project appear inside the folder summary, where
        # they answer a question about that folder; network places are
        # already in the sidebar's Other Locations.
        scroll, body = self._make_scroll_body()
        scroll.set_size_request(PANEL_WIDE, -1)
        scroll.set_halign(Gtk.Align.END)
        scroll.set_valign(Gtk.Align.FILL)
        scroll.set_vexpand(True)
        _css(scroll, "adaptive-preview-panel")

        self.panel = scroll
        self.preview_body = body

        self._load_projects()
        self._render_empty_preview()

    def _make_scroll_body(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.set_margin_top(4)
        body.set_margin_bottom(16)

        scroll.add(body)
        return scroll, body


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

        # Below this width the grid needs the room more than the inspector
        # does. Crossing the line either way forgets a manual override, so
        # the panel comes back on its own when the window is widened.
        narrow = width < AUTO_HIDE_BELOW
        if narrow != self._narrow:
            self._narrow = narrow
            self._override = None
            GLib.idle_add(self._apply_panel_visibility)

    # --------------------------------------------------------------
    # Panel controls
    # --------------------------------------------------------------

    def _panel_shown(self):
        if self._override is not None:
            return self._override
        return self.panel_visible and not self._narrow

    def _apply_panel_visibility(self):
        if self.panel is not None:
            shown = self._panel_shown()
            self.panel.set_visible(shown)
            if shown:
                self.panel.show_all()
            button = self._header_buttons.get("inspector")
            if button is not None:
                button.handler_block_by_func(self._on_inspector_button)
                button.set_active(shown)
                button.handler_unblock_by_func(self._on_inspector_button)
        self._reserve_space()
        return GLib.SOURCE_REMOVE

    def set_panel_visible(self, visible):
        visible = bool(visible)
        if self._narrow:
            # Showing it in a narrow window is a one-off, not a preference.
            self._override = visible
        else:
            self.panel_visible = visible
            self._override = None
        self._apply_panel_visibility()
        return visible

    def toggle_panel(self):
        return self.set_panel_visible(not self._panel_shown())

    def _on_inspector_button(self, button):
        self.set_panel_visible(button.get_active())

    # --------------------------------------------------------------
    # Toolbar buttons and shortcuts
    # --------------------------------------------------------------

    def _install_window_controls(self):
        window = self.window
        if window is None or self._controls_installed:
            return GLib.SOURCE_REMOVE
        self._controls_installed = True

        try:
            app = window.get_application()
            for name, callback, accels in (
                ("adaptive-inspector", lambda *_: self.toggle_panel(), ["<Control><Shift>p"]),
                ("adaptive-terminal", lambda *_: self.toggle_terminal(), ["<Control>grave", "F4"]),
            ):
                if window.lookup_action(name) is None:
                    action = Gio.SimpleAction.new(name, None)
                    action.connect("activate", callback)
                    window.add_action(action)
                if app is not None:
                    app.set_accels_for_action(f"win.{name}", accels)
        except Exception:
            _log_exception("Unable to add inspector shortcuts")

        header = None
        for widget in _walk(window):
            if _type_name(widget) == "NautilusToolbar":
                header = widget
                break
        if header is None or not hasattr(header, "pack_end"):
            _log("Toolbar not found; inspector buttons skipped (shortcuts still work).")
            return GLib.SOURCE_REMOVE

        inspector = Gtk.ToggleButton()
        inspector.add(Gtk.Image.new_from_icon_name("sidebar-show-right-symbolic", Gtk.IconSize.BUTTON))
        inspector.set_tooltip_text("Inspector  (Ctrl+Shift+P)")
        inspector.set_active(self._panel_shown())
        inspector.connect("toggled", self._on_inspector_button)
        _css(inspector, "image-button", "adaptive-toolbar-toggle")

        terminal = Gtk.ToggleButton()
        terminal.add(Gtk.Image.new_from_icon_name("utilities-terminal-symbolic", Gtk.IconSize.BUTTON))
        terminal.set_tooltip_text("Terminal  (Ctrl+`)")
        terminal.set_sensitive(Vte is not None)
        terminal.connect("toggled", self._on_terminal_button)
        _css(terminal, "image-button", "adaptive-toolbar-toggle")

        # pack_end stacks leftwards: the inspector toggle ends up nearest the
        # window's edge, where Finder keeps its preview button.
        header.pack_end(inspector)
        header.pack_end(terminal)
        inspector.show_all()
        terminal.show_all()
        self._header_buttons = {"inspector": inspector, "terminal": terminal}
        return GLib.SOURCE_REMOVE

    # --------------------------------------------------------------
    # Terminal drawer
    # --------------------------------------------------------------

    def _on_terminal_button(self, button):
        if button.get_active() != self._terminal_open():
            self.toggle_terminal()

    def _terminal_open(self):
        slot = getattr(self, "terminal_slot", None)
        return slot is not None and slot.get_visible()

    def toggle_terminal(self):
        slot = getattr(self, "terminal_slot", None)
        if slot is None or Vte is None:
            return
        if self._terminal_open():
            slot.hide()
            view = self.host_main_child
            if view is not None:
                view.grab_focus()
        else:
            if self.terminal is None:
                self._spawn_terminal()
            slot.set_no_show_all(False)
            slot.show_all()
            column = self.host_column
            height = column.get_allocated_height()
            if height > 0:
                column.set_position(max(160, height - 260))
            self.terminal.grab_focus()
            self._terminal_follow()

        button = self._header_buttons.get("terminal")
        if button is not None:
            button.handler_block_by_func(self._on_terminal_button)
            button.set_active(self._terminal_open())
            button.handler_unblock_by_func(self._on_terminal_button)

    def _spawn_terminal(self):
        terminal = Vte.Terminal()
        terminal.set_scrollback_lines(5000)
        terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.OFF)
        terminal.set_audible_bell(False)
        try:
            interface = Gio.Settings.new("org.gnome.desktop.interface")
            terminal.set_font(Pango.FontDescription.from_string(interface.get_string("monospace-font-name")))
        except Exception:
            pass

        def rgba(value):
            color = Gdk.RGBA()
            color.parse(value)
            return color

        # Graphite canvas and label white from the palette; ANSI colours are
        # left to VTE so command output keeps its usual meaning.
        terminal.set_color_background(rgba("#141416"))
        terminal.set_color_foreground(rgba("#F5F5F7"))
        terminal.set_color_cursor(rgba("#0A84FF"))
        terminal.set_color_highlight(rgba("#0058D0"))
        terminal.set_color_highlight_foreground(rgba("#FFFFFF"))
        terminal.set_hexpand(True)
        terminal.set_vexpand(True)
        terminal.connect("child-exited", self._on_terminal_exited)

        shell = os.environ.get("SHELL") or "/bin/bash"
        directory = self._location_path() or str(Path.home())
        terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            directory,
            [shell],
            None,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            self._on_terminal_spawned,
        )

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(terminal)
        self.terminal_slot.pack_start(scroll, True, True, 0)
        self.terminal = terminal
        self._terminal_cwd = directory

    def _on_terminal_spawned(self, _terminal, pid, error, *_args):
        if error is not None:
            _log(f"Terminal failed to start: {error}")
            return
        self._terminal_pid = pid

    def _on_terminal_exited(self, _terminal, _status):
        # "exit" closes the drawer; the next toggle starts a fresh shell.
        self._close_terminal()
        button = self._header_buttons.get("terminal")
        if button is not None:
            button.handler_block_by_func(self._on_terminal_button)
            button.set_active(False)
            button.handler_unblock_by_func(self._on_terminal_button)

    def _close_terminal(self):
        slot = getattr(self, "terminal_slot", None)
        if slot is not None:
            for child in slot.get_children():
                slot.remove(child)
            slot.hide()
        self.terminal = None
        self._terminal_pid = None

    def _location_path(self):
        if not self.location_uri:
            return None
        return Gio.File.new_for_uri(self.location_uri).get_path()

    def _terminal_follow(self):
        """cd the drawer's shell to the folder Files is showing - only when
        the shell is sitting at its prompt, never into a running program."""
        if self.terminal is None or not self._terminal_pid or not self._terminal_open():
            return
        path = self._location_path()
        if not path or path == self._terminal_cwd:
            return
        try:
            pty = self.terminal.get_pty()
            foreground = os.tcgetpgrp(pty.get_fd())
        except Exception:
            return
        if foreground != self._terminal_pid:
            return
        self._terminal_cwd = path
        # Ctrl-U clears a half-typed line first so the cd runs clean; the
        # leading space keeps it out of history where the shell allows.
        command = "\x15 cd -- " + shlex.quote(path) + "\n"
        self.terminal.feed_child(command.encode("utf-8"))

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

                # The view sits over a terminal slot that stays hidden until
                # asked for; a paned so the terminal's height can be dragged.
                self.host_column = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
                self.host_column.set_hexpand(True)
                self.host_column.set_wide_handle(False)
                self.terminal_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                _css(self.terminal_slot, "adaptive-terminal-slot")
                self.terminal_slot.set_no_show_all(True)
                self.host_column.pack1(view, True, False)
                self.host_column.pack2(self.terminal_slot, False, False)

                self.host_split.pack_start(self.host_column, True, True, 0)
                self.host_split.pack_start(self.panel, False, False, 0)

                host.add(self.host_split)
                self.host_split.show_all()

                self._apply_panel_visibility()
                GLib.idle_add(self._install_window_controls)

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
                self._apply_panel_visibility()

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

                column = getattr(self, "host_column", None)
                if view is not None and column is not None and view.get_parent() is column:
                    column.remove(view)
                if column is not None and column.get_parent() is self.host_split:
                    self.host_split.remove(column)
                self.host_column = None
                self._close_terminal()

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
        GLib.idle_add(self._terminal_follow)
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
        self._stop_player()

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

        hero, subtitle = self._hero(self._gicon_image(gfile, "folder", 56), self._current_name, "Folder")
        body.pack_start(hero, False, False, 0)

        project = self._project_for_path(path)
        repo = gitinfo.repo_root(path) if path else None
        if repo is not None:
            # A repository gets a live card (branch, changes, upstream); the
            # registered project, if any, only lends it a name.
            body.pack_start(self._repo_card(repo, project, generation), False, False, 0)
        elif project is not None:
            body.pack_start(self._project_chip(project), False, False, 0)

        if path is not None and selected:
            body.pack_start(self._tag_picker([gfile]), False, False, 0)

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

        if not selected:
            disk = self._disk_line(path)
            if disk is not None:
                body.pack_start(disk, False, False, 0)

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

        old = cleanup.old_installers(payload["children"])
        if old:
            contents.pack_start(self._old_installers(old), False, False, 0)

        # Duplicates need hashing, so they arrive after everything else and
        # only take space when there is something to show.
        duplicates = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        contents.pack_start(duplicates, False, False, 0)
        if len(payload.get("records") or []) > 1:
            self._submit(
                cleanup.find_duplicates,
                (payload["records"],),
                lambda result, failure: self._show_duplicates(generation, duplicates, result, failure),
            )

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

    def _repo_card(self, root, project, generation):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self._section_label("Repository"), False, False, 0)
        group = self._group()
        _css(group, "adaptive-repo")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.set_margin_top(6)
        icon = Gtk.Image.new_from_icon_name("folder-templates-symbolic", Gtk.IconSize.BUTTON)
        _css(icon, "adaptive-accent-icon")
        head.pack_start(icon, False, False, 0)
        name = Gtk.Label(
            label=(project or {}).get("name") or os.path.basename(root) or root,
            xalign=0,
        )
        name.set_ellipsize(Pango.EllipsizeMode.END)
        _css(name, "adaptive-row-title")
        head.pack_start(name, True, True, 0)
        branch = Gtk.Label(label="…", xalign=1)
        branch.set_ellipsize(Pango.EllipsizeMode.START)
        branch.set_max_width_chars(16)
        _css(branch, "adaptive-branch")
        head.pack_end(branch, False, False, 0)
        group.pack_start(head, False, False, 0)

        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        group.pack_start(rows, False, False, 0)
        box.pack_start(group, False, False, 0)

        def done(info, error):
            if generation != self.selection_generation:
                return
            if error or not info:
                branch.set_text("")
                rows.pack_start(self._note("Couldn't read the repository."), False, False, 0)
                rows.show_all()
                return

            branch.set_text(info.get("branch") or "—")
            changes = []
            if info["conflicts"]:
                changes.append(_count_text(info["conflicts"], "conflict"))
            if info["modified"]:
                changes.append(f"{info['modified']:,} modified")
            if info["staged"]:
                changes.append(f"{info['staged']:,} staged")
            if info["untracked"]:
                changes.append(f"{info['untracked']:,} new")
            value = self._info_row(rows, "Changes", " · ".join(changes) or "Clean")
            if info["conflicts"]:
                _css(value, "git-conflict")
            elif changes:
                _css(value, "git-modified")

            if info.get("upstream"):
                sync = []
                if info["ahead"]:
                    sync.append(f"↑ {info['ahead']} to push")
                if info["behind"]:
                    sync.append(f"↓ {info['behind']} to pull")
                self._info_row(
                    rows,
                    "Upstream",
                    " · ".join(sync) or "Up to date",
                    hint=info["upstream"],
                )
            else:
                self._info_row(rows, "Upstream", "None")

            if info.get("last_subject"):
                # A commit subject is prose, not a value: it gets the full
                # width, wrapped, with who and when underneath.
                commit = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                _css(commit, "adaptive-info-row")
                key = Gtk.Label(label="Last commit", xalign=0)
                _css(key, "adaptive-meta-key")
                subject = Gtk.Label(label=info["last_subject"], xalign=0)
                subject.set_line_wrap(True)
                subject.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                subject.set_max_width_chars(30)
                _css(subject, "adaptive-row-title")
                who = Gtk.Label(
                    label=f"{info.get('last_author', '')} · {_relative_time(info.get('last_at', 0))}",
                    xalign=0,
                )
                _css(who, "adaptive-meta-hint")
                commit.pack_start(key, False, False, 0)
                commit.pack_start(subject, False, False, 0)
                commit.pack_start(who, False, False, 0)
                rows.pack_start(commit, False, False, 0)
            rows.show_all()

        self._submit(gitinfo.summary, (root,), done)
        return box

    def _old_installers(self, items):
        total = sum(item["bytes"] for item in items)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(
            self._section_label("Old Installers", trailing=_human_size(total)),
            False,
            False,
            0,
        )
        group = self._group()
        group.pack_start(
            self._note(
                f"Not opened or changed in {cleanup.OLD_DAYS} days. "
                "Moving them to the Trash can be undone."
            ),
            False,
            False,
            0,
        )
        for item in items[:5]:
            last = max(item.get("mtime", 0), item.get("atime", 0))
            row = self._bar_row(
                self._icon_name_for(item["name"]),
                item["name"],
                _human_size(item["bytes"]),
                item["bytes"] / (total or 1),
                SERIES_COLORS[3],
                tooltip=f"Last used {_relative_time(last)}",
            )
            group.pack_start(row, False, False, 0)
        if len(items) > 5:
            group.pack_start(self._note(f"+ {len(items) - 5} more"), False, False, 0)

        button = Gtk.Button(label=f"Move {len(items)} to Trash…")
        button.set_margin_top(4)
        button.set_margin_bottom(8)
        _css(button, "adaptive-quiet-button")
        button.connect("clicked", lambda *_: self._trash_confirmed(items, total))
        group.pack_start(button, False, False, 0)

        box.pack_start(group, False, False, 0)
        return box

    def _trash_confirmed(self, items, total):
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Move {_count_text(len(items), 'item')} to the Trash?",
        )
        dialog.format_secondary_text(
            f"{_human_size(total)} of installers and archives unused for "
            f"{cleanup.OLD_DAYS} days. You can restore them from the Trash."
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        trash = dialog.add_button("Move to Trash", Gtk.ResponseType.OK)
        _css(trash, "destructive-action")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)

        def answered(dialog, response):
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return

            def work():
                failed = []
                for item in items:
                    try:
                        Gio.File.new_for_path(item["path"]).trash(None)
                    except GLib.Error as error:
                        failed.append(f"{item['name']}: {error.message}")
                return failed

            def done(failed, error):
                if error or failed:
                    self._show_error("Some items stayed", error or "\n".join(failed[:6]))
                self._selection_key = None
                self._scan_cache.clear()
                self.update_selection(self.last_selection)

            self._submit(work, (), done)

        dialog.connect("response", answered)
        dialog.show_all()

    def _show_duplicates(self, generation, box, result, error):
        if generation != self.selection_generation or error or not result:
            return
        groups, complete = result
        groups = [group for group in groups if group["reclaimable"] >= 512 * 1024]
        if not groups:
            return

        reclaimable = sum(group["reclaimable"] for group in groups)
        box.pack_start(
            self._section_label(
                "Duplicates",
                trailing=f"{_human_size(reclaimable)} reclaimable" + ("" if complete else "+"),
            ),
            False,
            False,
            0,
        )
        group_box = self._group()
        group_box.pack_start(
            self._note(
                f"{_count_text(len(groups), 'file')} stored more than once in this "
                "folder, matched by content."
            ),
            False,
            False,
            0,
        )

        for group in groups[:5]:
            first = group["paths"][0]
            expander = Gtk.Expander()
            _css(expander, "adaptive-info-row", "adaptive-duplicate")
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            icon = Gtk.Image.new_from_icon_name(self._icon_name_for(os.path.basename(first)), Gtk.IconSize.MENU)
            icon.set_pixel_size(16)
            header.pack_start(icon, False, False, 0)
            label = Gtk.Label(label=os.path.basename(first), xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            _css(label, "adaptive-row-title")
            header.pack_start(label, True, True, 0)
            count = Gtk.Label(label=f"×{len(group['paths'])}  {_human_size(group['bytes'])}", xalign=1)
            _css(count, "adaptive-row-value")
            header.pack_end(count, False, False, 0)
            expander.set_label_widget(header)
            expander.set_label_fill(True)

            copies = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            copies.set_margin_start(18)
            here = self.location_uri and Gio.File.new_for_uri(self.location_uri).get_path()
            for copy in group["paths"]:
                shown = os.path.relpath(copy, here) if here and copy.startswith(here + os.sep) else _short_path(copy)
                link = Gtk.Button(label=shown)
                link.set_relief(Gtk.ReliefStyle.NONE)
                link.set_tooltip_text("Show in Files")
                link.get_child().set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                link.get_child().set_xalign(0)
                _css(link, "adaptive-path-link")
                link.connect("clicked", lambda _b, target=copy: _reveal([target]))
                copies.pack_start(link, False, False, 0)
            expander.add(copies)
            group_box.pack_start(expander, False, False, 0)

        if len(groups) > 5:
            group_box.pack_start(self._note(f"+ {len(groups) - 5} more sets"), False, False, 0)
        box.pack_start(group_box, False, False, 0)
        box.show_all()

    def _disk_line(self, path):
        """Free space on the disk holding this folder: one line and a thin
        bar, coloured only when space is running short."""
        # GVfs shares are FUSE mounts; statvfs on one whose server went away
        # blocks the window.
        if "/gvfs/" in path:
            return None
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            return None
        if not usage.total:
            return None

        fraction = (usage.total - usage.free) / usage.total

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        header = self._section_label("Disk")
        if fraction >= CAPACITY_WARN:
            state = Gtk.Label(
                label="Almost full" if fraction >= CAPACITY_CRIT else "Getting full",
                xalign=1,
            )
            _css(
                state,
                "adaptive-section-trailing",
                "critical" if fraction >= CAPACITY_CRIT else "warning",
            )
            header.pack_end(state, False, False, 0)
        box.pack_start(header, False, False, 0)

        group = self._group()
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        line.set_margin_top(6)
        free = Gtk.Label(label=f"{_human_size(usage.free)} available", xalign=0)
        _css(free, "adaptive-row-title")
        line.pack_start(free, True, True, 0)
        total = Gtk.Label(label=f"of {_human_size(usage.total)}", xalign=1)
        _css(total, "adaptive-row-value")
        line.pack_end(total, False, False, 0)
        group.pack_start(line, False, False, 0)

        bar = SegmentBar(height=6).set_segments([(fraction, _capacity_color(fraction))])
        bar.set_margin_top(6)
        bar.set_margin_bottom(8)
        group.pack_start(bar, False, False, 0)

        box.pack_start(group, False, False, 0)
        return box

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
        icon = self._gicon_image(first, "edit-select-all-symbolic", 56) if first else None
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
        name = item.get("name") or "File"
        local_path = gfile.get_path()
        mime = item.get("mime") or ""
        identity = _file_identity(name, mime)

        preview_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        _css(preview_card, "adaptive-preview-hero")
        media_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        media_box.set_halign(Gtk.Align.FILL)
        preview_card.pack_start(media_box, True, True, 0)
        body.pack_start(preview_card, False, False, 0)

        # Sections that depend on the file type fill this box once their
        # worker returns; it sits between Information and the actions.
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        if local_path and models.handles(name):
            self._render_model_preview(local_path, uri, media_box, extra, generation)
        elif local_path and HAVE_PLAYER and mime.startswith(("video/", "audio/")):
            self._render_player(uri, mime, media_box, gfile)
        elif local_path and mime == PDF_MIME:
            self._render_pdf_pager(local_path, media_box, generation)
        elif identity.get("is_code") and local_path:
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

        title = Gtk.Label(label=name)
        title.set_line_wrap(True)
        title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_justify(Gtk.Justification.CENTER)
        title.set_selectable(True)
        title.set_margin_top(4)
        _css(title, "adaptive-hero-title")
        body.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label=identity.get("label") or "File")
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        _css(subtitle, "adaptive-hero-subtitle")
        body.pack_start(subtitle, False, False, 0)
        self._file_subtitle = subtitle

        if local_path:
            body.pack_start(self._tag_picker([gfile]), False, False, 0)

        self._append_details_placeholder()
        self._query_metadata_async(item, gfile, generation)

        body.pack_start(extra, False, False, 0)
        if local_path and archives.handles(name):
            self._render_archive_section(local_path, extra, generation)
        elif local_path and mime.startswith(IMAGE_MIME_PREFIX):
            self._render_photo_section(local_path, extra, generation)

        self._append_actions(
            [
                ("document-open-symbolic", "Open", lambda *_: self._view_action("open-with-default-application")),
                ("view-more-symbolic", "Open With", lambda *_: self._view_action("open-with-other-application")),
                ("edit-copy-symbolic", "Copy Path", lambda *_: self._copy_text(local_path or uri)),
            ]
        )
        body.show_all()

    # --------------------------------------------------------------
    # 3D models and print files
    # --------------------------------------------------------------

    def _render_model_preview(self, path, uri, box, extra, generation):
        loading = self._note("Rendering…")
        loading.set_halign(Gtk.Align.CENTER)
        loading.set_margin_top(40)
        loading.set_margin_bottom(40)
        box.pack_start(loading, False, False, 0)

        def work():
            suffix = Path(path).suffix.casefold()
            data = {"kind": "gcode" if suffix in models.GCODE_SUFFIXES else "mesh"}
            if data["kind"] == "gcode":
                info = models.gcode_info(path)
                data["fields"] = info["fields"]
                data["slicer"] = info["slicer"]
            else:
                try:
                    data["stats"] = models.mesh_stats(models.load_mesh(path))
                except Exception as error:
                    data["stats_error"] = str(error)

            image = models.preview_image(path)
            if image is not None:
                buffer = io.BytesIO()
                image.save(buffer, "PNG")
                data["png"] = buffer.getvalue()
                # Give the grid the same picture.
                try:
                    mtime = os.stat(path).st_mtime
                    if models.cached_thumbnail(uri, mtime) is None:
                        models.write_thumbnail(uri, path, image)
                except Exception:
                    pass
            return data

        def done(data, error):
            if generation != self.selection_generation:
                return
            self._clear(box)
            if error or not data or not data.get("png"):
                self._fallback_media(box, f"No preview · {error}" if error else "No preview")
            else:
                loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                loader.write(data["png"])
                loader.close()
                picture = RoundedPicture(loader.get_pixbuf(), 214, 200)
                picture.set_halign(Gtk.Align.CENTER)
                box.pack_start(picture, False, False, 0)
            box.show_all()
            if data:
                self._fill_model_section(extra, data)

        self._submit(work, (), done)

    def _fill_model_section(self, extra, data):
        rows = []
        if data["kind"] == "gcode":
            fields = data.get("fields") or {}
            title = "Print"
            time_text = fields.get("time")
            if not time_text and fields.get("seconds"):
                try:
                    total = int(float(fields["seconds"]))
                    time_text = f"{total // 3600}h {total % 3600 // 60}m"
                except ValueError:
                    pass
            if time_text:
                rows.append(("Print time", time_text))
            used = []
            if fields.get("grams"):
                used.append(f"{float(fields['grams']):.1f} g")
            if fields.get("millimetres"):
                used.append(f"{float(fields['millimetres']) / 1000:.2f} m")
            elif fields.get("metres"):
                used.append(fields["metres"].replace("m", " m"))
            if used:
                rows.append(("Filament", "  ·  ".join(used)))
            material = fields.get("material")
            profile = (fields.get("filament") or "").strip('"')
            if material or profile:
                rows.append(("Material", " — ".join(p for p in (material, profile) if p)))
            layer = []
            if fields.get("layer_height"):
                layer.append(f"{fields['layer_height']} mm layers")
            if fields.get("nozzle"):
                layer.append(f"{fields['nozzle']} mm nozzle")
            if layer:
                rows.append(("Settings", "  ·  ".join(layer)))
            if fields.get("profile"):
                rows.append(("Profile", fields["profile"].strip('"')))
            if fields.get("printer"):
                rows.append(("Printer", fields["printer"]))
            if data.get("slicer"):
                rows.append(("Sliced with", data["slicer"]))
        else:
            title = "Model"
            stats = data.get("stats")
            if stats:
                x, y, z = stats["size"]
                rows.append(("Dimensions", f"{x:.1f} × {y:.1f} × {z:.1f} mm"))
                rows.append(("Volume", f"{stats['volume'] / 1000:.1f} cm³"))
                rows.append(("Triangles", f"{stats['triangles']:,}"))
            elif data.get("stats_error"):
                rows.append(("Mesh", data["stats_error"]))

        if not rows:
            return
        extra.pack_start(self._section_label(title), False, False, 0)
        group = self._group()
        for key, value in rows:
            self._info_row(group, key, value)
        extra.pack_start(group, False, False, 0)
        extra.show_all()

    # --------------------------------------------------------------
    # Video and audio
    # --------------------------------------------------------------

    def _render_player(self, uri, mime, box, gfile):
        self._stop_player()
        is_video = mime.startswith("video/")

        pipeline = Gst.ElementFactory.make("playbin", None)
        if pipeline is None:
            self._render_native_thumbnail_preview(uri, mime, box, self.selection_generation)
            return
        pipeline.set_property("uri", uri)

        frame = None
        if is_video:
            sink = Gst.ElementFactory.make("gtksink", None)
            pipeline.set_property("video-sink", sink)
            video = sink.props.widget
            video.set_halign(Gtk.Align.FILL)
            video.set_valign(Gtk.Align.FILL)
            # gtksink asks for the video's own size (1080 px tall for a 1080p
            # clip). As an overlay child it gets exactly the placeholder's
            # size instead; the placeholder is resized to the clip's aspect
            # once the first frame is decoded.
            frame = Gtk.DrawingArea()
            frame.set_size_request(214, 120)
            holder = Gtk.Overlay()
            holder.add(frame)
            holder.add_overlay(video)
            _css(holder, "adaptive-video")
            box.pack_start(holder, False, False, 0)
        else:
            self._icon_preview(box, _file_identity(self._current_name, mime), mime, gfile)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_margin_top(4)
        play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        play.set_tooltip_text("Play")
        _css(play, "adaptive-round-button")
        controls.pack_start(play, False, False, 0)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.001)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        _css(scale, "adaptive-scrubber")
        controls.pack_start(scale, True, True, 0)

        clock = Gtk.Label(label="0:00")
        _css(clock, "adaptive-row-value")
        controls.pack_end(clock, False, False, 0)
        box.pack_start(controls, False, False, 0)

        state = {"pipeline": pipeline, "playing": False, "duration": 0, "timer": 0, "bus": None}
        self._player = state

        def stamp(nanoseconds):
            seconds = max(0, int(nanoseconds / Gst.SECOND))
            return f"{seconds // 60}:{seconds % 60:02d}" if seconds < 3600 else \
                f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

        def tick():
            if self._player is not state:
                return GLib.SOURCE_REMOVE
            ok, position = pipeline.query_position(Gst.Format.TIME)
            if not state["duration"]:
                found, duration = pipeline.query_duration(Gst.Format.TIME)
                if found and duration > 0:
                    state["duration"] = duration
            if frame is not None and not state.get("sized"):
                pad = pipeline.emit("get-video-pad", 0)
                caps = pad.get_current_caps() if pad is not None else None
                if caps is not None and caps.get_size() > 0:
                    structure = caps.get_structure(0)
                    ok_w, width = structure.get_int("width")
                    ok_h, height = structure.get_int("height")
                    if ok_w and ok_h and width > 0:
                        frame.set_size_request(214, max(80, min(260, int(214 * height / width))))
                        state["sized"] = True
            if ok and state["duration"]:
                scale.handler_block_by_func(on_seek)
                scale.set_value(position / state["duration"])
                scale.handler_unblock_by_func(on_seek)
                clock.set_text(f"{stamp(position)} / {stamp(state['duration'])}")
            return GLib.SOURCE_CONTINUE

        def set_playing(playing):
            state["playing"] = playing
            pipeline.set_state(Gst.State.PLAYING if playing else Gst.State.PAUSED)
            play.get_image().set_from_icon_name(
                "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic",
                Gtk.IconSize.BUTTON,
            )
            play.set_tooltip_text("Pause" if playing else "Play")

        def on_seek(_scale):
            if state["duration"]:
                pipeline.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    int(scale.get_value() * state["duration"]),
                )

        def on_message(_bus, message):
            if self._player is not state:
                return
            if message.type == Gst.MessageType.EOS:
                set_playing(False)
                pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH, 0)
            elif message.type == Gst.MessageType.ERROR:
                error, _debug = message.parse_error()
                _log(f"Player error: {error.message}")
                clock.set_text("Can't play")
                play.set_sensitive(False)

        play.connect("clicked", lambda *_: set_playing(not state["playing"]))
        scale.connect("value-changed", on_seek)

        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message)
        state["bus"] = bus
        state["timer"] = GLib.timeout_add(250, tick)

        # Paused shows the first frame and learns the duration without
        # making a sound.
        pipeline.set_state(Gst.State.PAUSED)

    def _stop_player(self):
        state = getattr(self, "_player", None)
        self._player = None
        if not state:
            return
        try:
            state["pipeline"].set_state(Gst.State.NULL)
            if state.get("bus") is not None:
                state["bus"].remove_signal_watch()
            if state.get("timer"):
                GLib.source_remove(state["timer"])
        except Exception:
            _log_exception("Stopping the player failed")

    # --------------------------------------------------------------
    # PDF pages
    # --------------------------------------------------------------

    def _render_pdf_pager(self, path, box, generation):
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        holder.pack_start(self._note("Loading…"), False, False, 40)
        box.pack_start(holder, False, False, 0)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        nav.set_margin_top(4)
        back = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        forward = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        for button in (back, forward):
            _css(button, "adaptive-round-button")
        where = Gtk.Label(label="")
        _css(where, "adaptive-row-value")
        nav.pack_start(back, False, False, 0)
        nav.pack_start(where, True, True, 0)
        nav.pack_end(forward, False, False, 0)
        box.pack_start(nav, False, False, 0)
        nav.set_no_show_all(True)

        state = {"page": 1, "count": 0}

        def show(page):
            state["page"] = page
            back.set_sensitive(page > 1)
            forward.set_sensitive(page < state["count"])
            if state["count"]:
                where.set_text(f"Page {page} of {state['count']}")

            def done(png, error, wanted=page):
                if generation != self.selection_generation or state["page"] != wanted:
                    return
                self._clear(holder)
                if error:
                    holder.pack_start(self._note(f"Can't show this page · {error}"), False, False, 20)
                else:
                    picture = RoundedPicture(GdkPixbuf.Pixbuf.new_from_file(png), 214, 290)
                    picture.set_halign(Gtk.Align.CENTER)
                    holder.pack_start(picture, False, False, 0)
                holder.show_all()

            self._submit(media.pdf_page, (path, page, 428), done)

        def counted(count, error):
            if generation != self.selection_generation:
                return
            state["count"] = count or 0
            if state["count"] > 1:
                nav.set_no_show_all(False)
                nav.show_all()
            show(1)

        def step(delta):
            try:
                show(max(1, min(state["count"], state["page"] + delta)))
            except Exception:
                _log_exception("PDF paging failed")

        back.connect("clicked", lambda *_: step(-1))
        forward.connect("clicked", lambda *_: step(1))
        self._submit(media.pdf_page_count, (path,), counted)

    # --------------------------------------------------------------
    # Archives
    # --------------------------------------------------------------

    def _render_archive_section(self, path, extra, generation):
        def done(data, error):
            if generation != self.selection_generation:
                return
            trailing = "partial" if data and data.get("partial") else None
            extra.pack_start(self._section_label("Contents", trailing=trailing), False, False, 0)
            group = self._group()
            if error:
                group.pack_start(self._note(f"Can't read this archive · {error}"), False, False, 0)
                extra.pack_start(group, False, False, 0)
                extra.show_all()
                return

            details = data.get("details") or {}
            if details.get("Application"):
                self._info_row(group, "Application", details["Application"])
            for key in ("Package", "Version", "Architecture"):
                if details.get(key):
                    self._info_row(group, key, details[key])

            self._info_row(
                group,
                "Holds",
                f"{_count_text(data['files'], 'file')} · {_count_text(data['folders'], 'folder')}",
            )
            ratio = data["unpacked"] / data["packed"] if data["packed"] else 0
            self._info_row(
                group,
                "Unpacked",
                _human_size(data["unpacked"]),
                hint=f"{ratio:.1f}× the archive" if ratio >= 1.05 else None,
            )

            if "executable" in details:
                if details["executable"]:
                    self._info_row(group, "Runs as app", "Yes")
                else:
                    button = Gtk.Button(label="Make Executable")
                    _css(button, "adaptive-pill-button")

                    def allow(_button):
                        try:
                            archives.make_executable(path)
                            button.set_label("Done")
                            button.set_sensitive(False)
                        except OSError as failure:
                            self._show_error("Couldn't change permissions", str(failure))

                    button.connect("clicked", allow)
                    self._widget_row(group, "Runs as app", button)

            top = [entry for entry in data.get("top") or [] if entry["bytes"] > 0][:6]
            total = data["unpacked"] or 1
            for index, entry in enumerate(top):
                group.pack_start(
                    self._bar_row(
                        "folder" if entry["is_dir"] else self._icon_name_for(entry["name"]),
                        entry["name"],
                        _human_size(entry["bytes"]),
                        entry["bytes"] / total,
                        ACCENT if index == 0 else SERIES_COLORS[3],
                    ),
                    False,
                    False,
                    0,
                )

            if details.get("Description"):
                note = self._note(details["Description"])
                group.pack_start(note, False, False, 0)

            extra.pack_start(group, False, False, 0)
            extra.show_all()

        self._submit(archives.inspect, (path,), done)

    # --------------------------------------------------------------
    # Photos
    # --------------------------------------------------------------

    def _render_photo_section(self, path, extra, generation):
        def done(details, error):
            if generation != self.selection_generation or error or not details:
                return
            gps = details.pop("_gps", None)
            if not details and not gps:
                return
            extra.pack_start(self._section_label("Camera"), False, False, 0)
            group = self._group()
            for key, value in details.items():
                self._info_row(group, key, value)
            if gps:
                latitude, longitude = gps
                where = (
                    f"{abs(latitude):.4f}° {'N' if latitude >= 0 else 'S'}, "
                    f"{abs(longitude):.4f}° {'E' if longitude >= 0 else 'W'}"
                )
                button = Gtk.Button(label="Open Map")
                _css(button, "adaptive-pill-button")
                url = (
                    "https://www.openstreetmap.org/"
                    f"?mlat={latitude:.6f}&mlon={longitude:.6f}#map=15/{latitude:.6f}/{longitude:.6f}"
                )
                button.connect("clicked", lambda *_: Gio.AppInfo.launch_default_for_uri(url, None))
                button.set_tooltip_text("Opens OpenStreetMap in the browser")
                self._widget_row(group, "Location", button, hint=where)
            extra.pack_start(group, False, False, 0)
            extra.show_all()

        self._submit(media.photo_details, (path,), done)

    def _icon_preview(self, box, identity, mime, gfile=None):
        icon = None
        if gfile is not None:
            icon = self._gicon_image(gfile, None, 80)
        if icon is None:
            icon = _theme_icon_for_identity(identity, mime)
            icon.set_pixel_size(80)
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

        future = _run_async(
            _EXECUTOR,
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
            picture = RoundedPicture(GdkPixbuf.Pixbuf.new_from_file(str(thumb_path)), 214, 200)
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

        if path:
            self._append_git_row(section, path, generation)
            if not is_dir:
                self._append_checksum_row(section, path, generation)

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

    def _append_git_row(self, section, path, generation):
        root = gitinfo.repo_root(path)
        if root is None:
            return
        value = self._info_row(section, "Git", "…")

        def work():
            return gitinfo.badge(path), gitinfo.last_change(path)

        words = {
            "modified": "Modified",
            "added": "Staged",
            "untracked": "Not tracked",
            "conflict": "Conflict",
        }

        def done(result, error):
            if generation != self.selection_generation:
                return
            if error or result is None:
                value.set_text("—")
                return
            state, last = result
            text = words.get(state, "Committed" if last else "—")
            value.set_text(text)
            context = value.get_style_context()
            for kind in words:
                context.remove_class(f"git-{kind}")
            if state:
                context.add_class(f"git-{state}")
            if last:
                author, when, subject = last
                hint = Gtk.Label(
                    label=f"{subject}\n{author} · {_relative_time(when)}" if subject else author,
                    xalign=1,
                )
                hint.set_line_wrap(True)
                hint.set_justify(Gtk.Justification.RIGHT)
                hint.set_max_width_chars(26)
                _css(hint, "adaptive-meta-hint")
                value.get_parent().pack_start(hint, False, False, 0)
                hint.show()

        self._submit(work, (), done)

    def _append_checksum_row(self, section, path, generation):
        button = Gtk.Button(label="Compute")
        button.set_tooltip_text("SHA-256 of the whole file; the result is copied")
        _css(button, "adaptive-pill-button")
        holder = self._widget_row(section, "SHA-256", button)

        def start(_button):
            button.set_sensitive(False)
            button.set_label("0%")

            def progress(fraction):
                GLib.idle_add(
                    lambda: button.set_label(f"{fraction * 100:.0f}%")
                    if generation == self.selection_generation else None
                )

            def cancelled():
                return generation != self.selection_generation

            def done(digest, error):
                if generation != self.selection_generation or digest is None:
                    return
                holder.remove(button)
                if error:
                    label = Gtk.Label(label="Couldn't read the file", xalign=1)
                    _css(label, "adaptive-meta-hint")
                else:
                    label = Gtk.Label(label=f"{digest[:10]}…{digest[-10:]}", xalign=1)
                    label.set_tooltip_text(f"{digest}\nCopied to the clipboard")
                    label.set_selectable(True)
                    _css(label, "adaptive-meta-value", "adaptive-mono")
                    self._copy_text(digest)
                holder.pack_end(label, False, False, 0)
                holder.show_all()

            self._submit(cleanup.sha256, (path, progress, cancelled), done)

        button.connect("clicked", start)

    def _widget_row(self, parent, key, widget, hint=None):
        """An Information row whose value is a control."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        _css(row, "adaptive-info-row")
        left = Gtk.Label(label=key, xalign=0)
        left.set_valign(Gtk.Align.CENTER)
        _css(left, "adaptive-meta-key")
        row.pack_start(left, False, False, 0)
        widget.set_valign(Gtk.Align.CENTER)
        row.pack_end(widget, False, False, 0)
        if hint:
            extra = Gtk.Label(label=hint, xalign=1)
            extra.set_hexpand(True)
            _css(extra, "adaptive-meta-hint")
            row.pack_end(extra, True, True, 0)
        parent.pack_start(row, False, False, 0)
        return row

    def _tag_picker(self, gfiles):
        """Seven tag dots under the title; a filled dot is applied. Clicking
        toggles that tag on the selection, as the Tags menu does."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_halign(Gtk.Align.CENTER)
        row.set_margin_top(6)
        _css(row, "adaptive-tag-picker")

        applied = set(filetags.get(gfiles[0])) if len(gfiles) == 1 else set()
        dots = {}

        def refresh():
            for tag, dot in dots.items():
                dot.set_filled(tag in applied)

        for tag in filetags.TAG_IDS:
            dot = TagDot(_rgb(filetags.COLORS[tag]))
            dot.set_tooltip_text(filetags.LABELS[tag])

            def toggle(_button, which=tag):
                try:
                    now_on = filetags.toggle(gfiles, which)
                except Exception as error:
                    self._show_error("Couldn't change tags", str(error))
                    return
                if now_on:
                    applied.add(which)
                else:
                    applied.discard(which)
                refresh()
                _refresh_file_badges([gfile.get_uri() for gfile in gfiles])

            dot.connect("clicked", toggle)
            dots[tag] = dot
            row.pack_start(dot, False, False, 0)

        refresh()
        return row

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
        future = _run_async(executor or _EXECUTOR, function, *args)

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
        name.set_max_width_chars(22)
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
        right.set_max_width_chars(24)
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

            if self is _MENU_OWNER and files:
                local = [info for info in files if info.get_uri_scheme() == "file"]
                if local:
                    return [self._tags_menu(controller, local)]

        except Exception:
            _log_exception("get_file_items failed")

        return []

    def _tags_menu(self, controller, files):
        """Tags ▸ one item per colour. A colour every selected item already
        has is marked, and choosing it takes it off; otherwise it is added."""
        locations = [info.get_location() for info in files]
        # Reading tags is a metadata lookup per file; past a few hundred the
        # menu would lag, so large selections just skip the marks.
        current = [set(filetags.get(loc)) for loc in locations] if len(locations) <= 300 else []

        top = Nautilus.MenuItem(name="AdaptiveTags::menu", label="Tags", tip="Colour tags")
        submenu = Nautilus.Menu()
        top.set_submenu(submenu)

        def apply(_item, tag=None):
            try:
                if tag is None:
                    filetags.clear(locations)
                else:
                    filetags.toggle(locations, tag)
            except Exception as error:
                _log(f"Tagging failed: {error}")
            _refresh_file_badges([info.get_uri() for info in files])
            controller._selection_key = None
            GLib.idle_add(controller.update_selection, list(controller.last_selection))

        for tag in filetags.TAG_IDS:
            marked = bool(current) and all(tag in tags for tags in current)
            item = Nautilus.MenuItem(
                name=f"AdaptiveTags::{tag}",
                label=filetags.LABELS[tag] + ("  ✓" if marked else ""),
            )
            item.connect("activate", apply, tag)
            submenu.append_item(item)

        if any(current):
            item = Nautilus.MenuItem(name="AdaptiveTags::clear", label="Remove Tags")
            item.connect("activate", apply, None)
            submenu.append_item(item)
        return top

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
                    if controller._panel_shown()
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


class AdaptiveFilesBadges(GObject.GObject, Nautilus.InfoProvider):
    """Icon emblems for git state and colour tags, and previews for 3D and
    print files that Ubuntu has no thumbnailer for."""

    def __init__(self):
        global _INFO_OWNER

        super().__init__()
        # Same duplicate-instance guard as the menu: one instance does the work.
        if _INFO_OWNER is None:
            _INFO_OWNER = self
        self._watches = {}
        self._debounce = {}
        self._thumbs_busy = set()
        self._refreshing = set()
        self._thumbs_failed = set()

    def update_file_info_full(self, provider, handle, closure, file):
        done = Nautilus.OperationResult.COMPLETE
        if self is not _INFO_OWNER:
            return done
        try:
            if file.get_uri_scheme() != "file":
                return done
            location = file.get_location()
            path = location.get_path()
            if not path:
                return done

            _remember_file(file)

            for tag in filetags.get(location):
                file.add_emblem(f"adaptive-tag-{tag}")

            self._maybe_thumbnail(file.get_uri(), path)

            root = gitinfo.repo_root(path)
            if root is None or path == root:
                return done
            self._watch_repo(root)

            # Emblems are added here, synchronously, from the cached status.
            # nautilus-python's asynchronous completion path did not apply
            # emblems added after IN_PROGRESS, and Nautilus fetches extension
            # info one file at a time anyway, so async bought nothing. A
            # stale or missing cache is refreshed in the background, and the
            # refresh redraws this repository's icons when it lands.
            cached = gitinfo.peek(root)
            try:
                mtime = os.lstat(path).st_mtime
            except OSError:
                mtime = 0
            if cached is None or time.time() - cached[0] > GIT_STALE_SECONDS or mtime > cached[0]:
                self._refresh_repo(root)
            if cached is not None:
                state = gitinfo.badge(path, cached[1])
                if state:
                    file.add_emblem(f"adaptive-git-{state}")
            return done
        except Exception:
            _log_exception("update_file_info_full failed")
            return done

    def _refresh_repo(self, root):
        if root in self._refreshing:
            return
        self._refreshing.add(root)
        prefix = Gio.File.new_for_path(root).get_uri() + "/"

        def report(_future):
            def redraw():
                self._refreshing.discard(root)
                _refresh_file_badges(prefix=prefix)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(redraw)

        _run_async(_BACKGROUND, gitinfo.refresh, root).add_done_callback(report)

    def cancel_update(self, provider, handle):
        # The worker finishes regardless; Nautilus drops a completion for a
        # handle it has already cancelled.
        pass

    def _maybe_thumbnail(self, uri, path):
        if not models.HAVE_RENDERER or not models.handles(path):
            return
        try:
            st = os.stat(path)
        except OSError:
            return
        if st.st_size > 150 * 1024 * 1024:
            return
        key = (path, int(st.st_mtime))
        if key in self._thumbs_busy or key in self._thumbs_failed:
            return
        if models.cached_thumbnail(uri, st.st_mtime) is not None:
            return

        self._thumbs_busy.add(key)

        def work():
            image = models.preview_image(path)
            if image is None:
                raise RuntimeError("no preview")
            models.write_thumbnail(uri, path, image)

        def report(future):
            self._thumbs_busy.discard(key)
            try:
                future.result()
            except Exception as error:
                self._thumbs_failed.add(key)
                _log(f"Model preview failed for {path}: {error}")

        _run_async(_BACKGROUND, work).add_done_callback(report)

    def _watch_repo(self, root):
        """Refresh a repository's badges when its index changes - a commit,
        an add or a checkout in a terminal - which Files would not notice."""
        if root in self._watches:
            return
        index = Gio.File.new_for_path(os.path.join(root, ".git", "index"))
        try:
            monitor = index.monitor_file(Gio.FileMonitorFlags.NONE, None)
        except GLib.Error:
            self._watches[root] = None
            return

        def fire():
            self._debounce.pop(root, None)
            self._refresh_repo(root)
            return GLib.SOURCE_REMOVE

        def changed(*_args):
            if root not in self._debounce:
                self._debounce[root] = GLib.timeout_add(700, fire)

        monitor.connect("changed", changed)
        self._watches[root] = monitor
