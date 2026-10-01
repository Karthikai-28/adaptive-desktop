"""Adaptive Files inspector - what its parts share.

The GTK and GNOME imports, the constants, the logging and async helpers, the
small drawing widgets and the folder scan used across the inspector:
adaptive_preview.py (the extension Nautilus loads) and the inspector_*.py
modules beside this one, which hold the PreviewController's methods by subject.

This module is where the versions of the GObject libraries are required, so
it has to be imported before anything else that uses them.
"""

from __future__ import annotations

import concurrent.futures
import datetime as _dt
import math
import os
from pathlib import Path
import stat
import time
import traceback

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

from gi.repository import (  # noqa: F401 - used here and handed on to the parts
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

# The inspector's own helper modules, handed on to its parts from here.
from . import archives, cleanup, gitinfo, media, models  # noqa: E402,F401
from . import share  # noqa: E402,F401
from . import tags as filetags  # noqa: E402,F401

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

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
# Thumbnails and git status for whole folders queue here, so they never hold
# up the selected item's own preview on _EXECUTOR.
_BACKGROUND = concurrent.futures.ThreadPoolExecutor(max_workers=2)
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


def _notify(title, body):
    """A desktop notification from Files, e.g. "Copied for Slack"."""
    try:
        app = Gtk.Application.get_default()
        note = Gio.Notification.new(title)
        note.set_body(body)
        app.send_notification("adaptive-share", note)
    except Exception:
        _log_exception("Notification failed")


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
