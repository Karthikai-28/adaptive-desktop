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
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)


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
    try:
        number = float(value)
    except Exception:
        return "—"

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(number)} {unit}"
            return f"{number:.1f} {unit}"
        number /= 1024.0

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


class UsageRing(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self._fraction = 0.0
        self.set_size_request(116, 116)

    def set_fraction(self, fraction):
        self._fraction = max(0.0, min(1.0, float(fraction)))
        self.queue_draw()

    def do_draw(self, cr):
        allocation = self.get_allocation()
        width = allocation.width
        height = allocation.height

        cx = width / 2.0
        cy = height / 2.0
        radius = min(width, height) * 0.32
        line_width = 9.0

        cr.set_line_width(line_width)
        cr.set_line_cap(1)

        cr.set_source_rgba(0.18, 0.25, 0.35, 0.76)
        cr.arc(cx, cy, radius, 0.0, math.tau)
        cr.stroke()

        cr.set_source_rgba(0.47, 0.66, 1.0, 0.98)
        cr.arc(
            cx,
            cy,
            radius,
            -math.pi / 2.0,
            -math.pi / 2.0 + math.tau * self._fraction,
        )
        cr.stroke()

        return False


class PreviewController:
    def __init__(self, window):
        self._window = window
        self.panel = None
        self.stack = None

        self.preview_body = None
        self.preview_title = None
        self.preview_subtitle = None

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

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        header.set_margin_start(12)
        header.set_margin_end(12)
        header.set_margin_top(10)
        header.set_margin_bottom(7)
        _css(header, "adaptive-preview-header")

        glyph = Gtk.Image.new_from_icon_name("adaptive-inspector-symbolic", Gtk.IconSize.BUTTON)
        glyph.set_pixel_size(22)
        _css(glyph, "adaptive-preview-glyph")
        header.pack_start(glyph, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.set_hexpand(True)

        title = Gtk.Label(label="Inspector", xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        _css(title, "adaptive-preview-title")

        subtitle = Gtk.Label(label="Select an item", xalign=0)
        subtitle.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        _css(subtitle, "adaptive-preview-subtitle")

        title_box.pack_start(title, False, False, 0)
        title_box.pack_start(subtitle, False, False, 0)

        header.pack_start(title_box, True, True, 0)
        panel.pack_start(header, False, False, 0)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(120)
        stack.set_hexpand(True)
        stack.set_vexpand(True)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(stack)
        switcher.set_halign(Gtk.Align.FILL)
        switcher.set_hexpand(True)
        switcher.set_margin_start(10)
        switcher.set_margin_end(10)
        switcher.set_margin_bottom(8)
        _css(switcher, "adaptive-inspector-switcher")
        panel.pack_start(switcher, False, False, 0)

        preview_scroll, preview_body = self._make_scroll_body()
        storage_scroll, storage_body = self._make_scroll_body()
        network_scroll, network_body = self._make_scroll_body()
        project_scroll, project_body = self._make_scroll_body()

        stack.add_titled(preview_scroll, "preview", "Preview")
        stack.add_titled(storage_scroll, "storage", "Storage")
        stack.add_titled(network_scroll, "network", "Network")
        stack.add_titled(project_scroll, "project", "Project")

        panel.pack_start(stack, True, True, 0)

        self.panel = panel
        self.stack = stack
        self.preview_title = title
        self.preview_subtitle = subtitle

        self.preview_body = preview_body
        self.storage_body = storage_body
        self.network_body = network_body
        self.project_body = project_body

        stack.connect("notify::visible-child-name", self._on_stack_changed)

        self._render_empty_preview()
        self._render_storage()
        self._render_network()
        self._render_project()

    def _make_scroll_body(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.set_margin_top(4)
        body.set_margin_bottom(16)

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

                host.add_overlay(self.panel)

                try:
                    host.set_overlay_pass_through(self.panel, False)
                except Exception:
                    pass

                self._reserve_space()
                self.panel.show_all()
                self.panel.set_visible(self.panel_visible)

                _log(
                    "Inspector attached to overlay "
                    f"{_type_name(host)}; base={_type_name(self.host_main_child)}"
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
        if self.host_main_child is None:
            return

        try:
            extra = self.panel_width + 1 if self.panel_visible else 0
            self.host_main_child.set_margin_end(
                self.host_original_margin_end + extra
            )
        except Exception:
            _log_exception("Unable to reserve space for inspector")

    def _detach_from_old_host(self):
        if self.host_overlay is None:
            return

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

    def update_selection(self, selection):
        self.ensure_attached()

        self.selection_generation += 1
        generation = self.selection_generation
        self.last_selection = list(selection)
        self.active_metadata_box = None

        if not selection:
            self._render_empty_preview()
            return GLib.SOURCE_REMOVE

        if len(selection) > 1:
            self._render_multiple_selection(selection)
            return GLib.SOURCE_REMOVE

        item = selection[0]
        uri = item.get("uri")

        if not uri:
            self._render_message(
                "Preview unavailable",
                "The selected item does not expose a usable URI.",
            )
            return GLib.SOURCE_REMOVE

        self.preview_title.set_text(item.get("name") or "Item")

        if item.get("is_dir"):
            subtitle = "Folder"
        else:
            identity = _file_identity(
                item.get("name"),
                item.get("mime"),
            )
            subtitle = (
                identity.get("label")
                or item.get("mime")
                or "File"
            )

        self.preview_subtitle.set_text(subtitle)

        self._clear(self.preview_body)

        gfile = Gio.File.new_for_uri(uri)

        if item.get("is_dir"):
            self._render_folder_shell(item, gfile, generation)
        else:
            self._render_file_shell(item, gfile, generation)

        self._query_metadata_async(item, gfile, generation)
        return GLib.SOURCE_REMOVE

    def _render_empty_preview(self):
        self.preview_title.set_text("Inspector")
        self.preview_subtitle.set_text("Single click an item")
        self._clear(self.preview_body)

        card = self._card()
        card.set_halign(Gtk.Align.FILL)

        glyph = Gtk.Label(label="◇")
        glyph.set_halign(Gtk.Align.CENTER)
        _css(glyph, "adaptive-empty-glyph")
        card.pack_start(glyph, False, False, 4)

        title = Gtk.Label(label="Nothing selected")
        title.set_halign(Gtk.Align.CENTER)
        _css(title, "adaptive-empty-title")
        card.pack_start(title, False, False, 0)

        text = Gtk.Label(
            label=(
                "Single click a file or folder to inspect it here. "
                "Double click remains the normal Nautilus open action."
            ),
            xalign=0.5,
        )
        text.set_line_wrap(True)
        text.set_justify(Gtk.Justification.CENTER)
        _css(text, "adaptive-empty-copy")
        card.pack_start(text, False, False, 4)

        self.preview_body.pack_start(card, False, False, 0)

        self.preview_body.pack_start(
            self._section_label("QUICK ACTIONS"),
            False,
            False,
            0,
        )

        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        actions.pack_start(
            self._button(
                "Bookmark Current Location",
                lambda *_: self._bookmark_current_location(),
            ),
            False,
            False,
            0,
        )
        actions.pack_start(
            self._button(
                "Copy Current Path",
                lambda *_: self._copy_current_path(),
            ),
            False,
            False,
            0,
        )
        self.preview_body.pack_start(actions, False, False, 0)

        self.preview_body.show_all()

    def _render_multiple_selection(self, selection):
        self.preview_title.set_text(f"{len(selection)} items")
        self.preview_subtitle.set_text("Multiple selection")
        self._clear(self.preview_body)

        card = self._card()

        count = Gtk.Label(label=str(len(selection)))
        count.set_halign(Gtk.Align.CENTER)
        _css(count, "adaptive-selection-count")
        card.pack_start(count, False, False, 2)

        caption = Gtk.Label(label="selected items")
        caption.set_halign(Gtk.Align.CENTER)
        _css(caption, "adaptive-empty-copy")
        card.pack_start(caption, False, False, 0)

        self.preview_body.pack_start(card, False, False, 0)

        self.preview_body.pack_start(
            self._section_label("SELECTION"),
            False,
            False,
            0,
        )

        for item in selection[:10]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
            _css(row, "adaptive-content-row")
            icon = Gtk.Image.new_from_icon_name(
                "folder-symbolic" if item.get("is_dir") else "text-x-generic-symbolic",
                Gtk.IconSize.MENU,
            )
            label = Gtk.Label(label=item.get("name") or "Item", xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_hexpand(True)

            row.pack_start(icon, False, False, 0)
            row.pack_start(label, True, True, 0)
            self.preview_body.pack_start(row, False, False, 0)

        if len(selection) > 10:
            extra = Gtk.Label(
                label=f"+ {len(selection) - 10} more",
                xalign=0,
            )
            _css(extra, "adaptive-muted")
            self.preview_body.pack_start(extra, False, False, 0)

        self.preview_body.show_all()

    def _render_folder_shell(self, item, gfile, generation):
        hero = self._card()
        _css(hero, "adaptive-preview-hero")

        icon = Gtk.Image.new_from_icon_name(
            "folder",
            Gtk.IconSize.DIALOG,
        )
        icon.set_pixel_size(66)
        icon.set_halign(Gtk.Align.CENTER)
        _css(icon, "adaptive-icon-tile")
        hero.pack_start(icon, False, False, 4)

        name = Gtk.Label(label=item.get("name") or "Folder")
        name.set_halign(Gtk.Align.CENTER)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        _css(name, "adaptive-hero-name")
        hero.pack_start(name, False, False, 2)

        self.preview_body.pack_start(hero, False, False, 0)

        self.preview_body.pack_start(
            self._section_label("CONTENTS"),
            False,
            False,
            0,
        )

        contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        _css(contents, "adaptive-contents-card")

        loading = Gtk.Label(label="Loading folder contents…", xalign=0)
        _css(loading, "adaptive-muted")
        contents.pack_start(loading, False, False, 7)

        self.preview_body.pack_start(contents, False, False, 0)

        self._enumerate_folder_async(
            gfile,
            generation,
            contents,
        )

        self._append_details_placeholder()
        self._append_path_and_actions(item)

    def _render_file_shell(self, item, gfile, generation):
        preview_card = self._card()
        _css(preview_card, "adaptive-preview-hero")

        media_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
        )
        media_box.set_halign(Gtk.Align.FILL)
        preview_card.pack_start(
            media_box,
            False,
            False,
            0,
        )

        self.preview_body.pack_start(
            preview_card,
            False,
            False,
            0,
        )

        uri = item.get("uri") or ""
        local_path = gfile.get_path()
        mime = item.get("mime") or ""
        identity = _file_identity(
            item.get("name"),
            mime,
        )

        self._render_file_identity(
            item,
            mime,
            identity,
            media_box,
        )

        if identity.get("is_code") and local_path:
            self._render_source_preview(
                Path(local_path),
                mime,
                media_box,
            )
        elif (
            mime.startswith(IMAGE_MIME_PREFIX)
            or mime == PDF_MIME
        ):
            self._render_native_thumbnail_preview(
                uri,
                mime,
                media_box,
                generation,
            )
        elif local_path and (
            Path(local_path).suffix.casefold() in TEXT_EXTENSIONS
            or mime.startswith("text/")
        ):
            self._render_source_preview(
                Path(local_path),
                mime,
                media_box,
            )
        else:
            icon = _theme_icon_for_identity(
                identity,
                mime,
            )
            icon.set_pixel_size(72)
            icon.set_halign(Gtk.Align.CENTER)
            _css(icon, "adaptive-icon-tile")
            media_box.pack_start(
                icon,
                False,
                False,
                10,
            )

            caption = Gtk.Label(
                label=identity.get("label") or "File",
            )
            caption.set_halign(Gtk.Align.CENTER)
            _css(caption, "adaptive-muted")
            media_box.pack_start(
                caption,
                False,
                False,
                0,
            )

        self._append_details_placeholder()
        self._append_path_and_actions(item)

    def _render_file_identity(
        self,
        item,
        mime,
        identity,
        box,
    ):
        row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        _css(row, "adaptive-file-identity")

        icon = _theme_icon_for_identity(
            identity,
            mime,
        )
        icon.set_pixel_size(26)
        _css(icon, "adaptive-file-type-icon")
        row.pack_start(icon, False, False, 0)

        labels = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=0,
        )
        labels.set_hexpand(True)

        primary = Gtk.Label(
            label=identity.get("label") or "File",
            xalign=0,
        )
        primary.set_ellipsize(
            Pango.EllipsizeMode.END
        )
        _css(
            primary,
            "adaptive-file-type-title",
        )

        secondary_parts = []
        suffix = identity.get("suffix")

        if suffix:
            secondary_parts.append(
                suffix.lstrip(".").upper()
            )

        if mime:
            secondary_parts.append(mime)

        secondary = Gtk.Label(
            label=" · ".join(secondary_parts),
            xalign=0,
        )
        secondary.set_ellipsize(
            Pango.EllipsizeMode.END
        )
        _css(
            secondary,
            "adaptive-file-type-subtitle",
        )

        labels.pack_start(
            primary,
            False,
            False,
            0,
        )
        labels.pack_start(
            secondary,
            False,
            False,
            0,
        )

        row.pack_start(
            labels,
            True,
            True,
            0,
        )
        box.pack_start(row, False, False, 0)

    def _render_native_thumbnail_preview(
        self,
        uri,
        mime,
        box,
        generation,
    ):
        loading = Gtk.Label(
            label="Loading native Ubuntu preview…",
        )
        loading.set_halign(Gtk.Align.CENTER)
        _css(loading, "adaptive-muted")
        box.pack_start(
            loading,
            False,
            False,
            14,
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

        for child in list(box.get_children()):
            try:
                classes = (
                    child
                    .get_style_context()
                    .list_classes()
                )
            except Exception:
                classes = []

            if "adaptive-file-identity" in classes:
                continue

            box.remove(child)

        if error or not thumb_path:
            identity = _file_identity(
                self.preview_title.get_text(),
                mime,
            )

            icon = _theme_icon_for_identity(
                identity,
                mime,
            )
            icon.set_pixel_size(72)
            icon.set_halign(Gtk.Align.CENTER)
            _css(icon, "adaptive-icon-tile")
            box.pack_start(
                icon,
                False,
                False,
                8,
            )

            message = Gtk.Label(
                label=(
                    error
                    or "Native preview unavailable"
                ),
            )
            message.set_halign(Gtk.Align.CENTER)
            message.set_line_wrap(True)
            _css(message, "adaptive-muted")
            box.pack_start(
                message,
                False,
                False,
                2,
            )
            box.show_all()
            return GLib.SOURCE_REMOVE

        try:
            pixbuf = (
                GdkPixbuf.Pixbuf
                .new_from_file_at_scale(
                    str(thumb_path),
                    282,
                    246,
                    True,
                )
            )

            image = Gtk.Image.new_from_pixbuf(
                pixbuf
            )
            image.set_halign(Gtk.Align.CENTER)
            _css(
                image,
                "adaptive-media-preview",
            )
            box.pack_start(
                image,
                False,
                False,
                2,
            )

            source = Gtk.Label(
                label="Ubuntu native thumbnail pipeline",
            )
            source.set_halign(Gtk.Align.CENTER)
            _css(
                source,
                "adaptive-native-preview-caption",
            )
            box.pack_start(
                source,
                False,
                False,
                0,
            )

        except Exception:
            _log_exception(
                "Unable to display native thumbnail "
                f"{thumb_path}"
            )
            self._fallback_media(
                box,
                "Native preview could not be displayed",
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
                    scheme = (
                        schemes.get_scheme("oblivion")
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
        _css(caption, "adaptive-muted")
        box.pack_start(caption, False, False, 2)

    def _enumerate_folder_async(self, gfile, generation, box):
        """
        Enumerate in a worker thread and return plain Python data to GTK.

        The previous implementation kept Gtk/PyGObject wrappers only through
        weak refs while chaining enumerate_children_async() and
        next_files_async(). On Ubuntu 22.04 this could leave the card forever
        at "Loading folder contents…".

        GIO still performs the actual native enumeration; only the orchestration
        is changed.
        """
        uri = gfile.get_uri()

        _log(f"Folder preview start: generation={generation} uri={uri}")

        future = _EXECUTOR.submit(
            self._folder_contents_worker,
            uri,
        )

        def done(fut):
            error = None
            payload = None

            try:
                payload = fut.result()
            except Exception as exc:
                error = str(exc)
                _log_exception(f"Folder preview worker failed for {uri}")

            GLib.idle_add(
                self._finish_folder_contents,
                generation,
                box,
                payload,
                error,
            )

        future.add_done_callback(done)

    @staticmethod
    def _folder_contents_worker(uri):
        attributes = ",".join(
            [
                "standard::name",
                "standard::display-name",
                "standard::type",
                "standard::size",
                "standard::content-type",
                "standard::is-hidden",
            ]
        )

        gfile = Gio.File.new_for_uri(uri)
        enumerator = None
        rows = []
        has_more = False

        try:
            enumerator = gfile.enumerate_children(
                attributes,
                Gio.FileQueryInfoFlags.NONE,
                None,
            )

            while True:
                info = enumerator.next_file(None)

                if info is None:
                    break

                try:
                    if info.get_is_hidden():
                        continue
                except Exception:
                    pass

                if len(rows) >= 12:
                    has_more = True
                    break

                is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
                content_type = info.get_content_type() or ""

                display_name = (
                    info.get_display_name()
                    or info.get_name()
                    or "Item"
                )

                if is_dir:
                    icon_name = "folder-symbolic"
                    type_label = "Folder"
                else:
                    identity = _file_identity(
                        display_name,
                        content_type,
                    )
                    icon_name = (
                        identity.get("icon_name")
                        or "text-x-generic"
                    )
                    type_label = (
                        identity.get("label")
                        or "File"
                    )

                rows.append(
                    {
                        "name": display_name,
                        "type_label": type_label,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else info.get_size(),
                        "icon_name": icon_name,
                    }
                )

        finally:
            if enumerator is not None:
                try:
                    enumerator.close(None)
                except Exception:
                    pass

        return {
            "rows": rows,
            "has_more": has_more,
        }

    def _finish_folder_contents(
        self,
        generation,
        box,
        payload,
        error,
    ):
        if generation != self.selection_generation:
            return GLib.SOURCE_REMOVE

        if box is None:
            return GLib.SOURCE_REMOVE

        self._clear(box)

        if error:
            label = Gtk.Label(
                label=f"Unable to preview folder · {error}",
                xalign=0,
            )
            label.set_line_wrap(True)
            _css(label, "adaptive-muted")
            box.pack_start(label, False, False, 7)
            box.show_all()
            return GLib.SOURCE_REMOVE

        payload = payload or {}
        rows = payload.get("rows") or []

        if not rows:
            empty = Gtk.Label(
                label="No visible contents",
                xalign=0,
            )
            _css(empty, "adaptive-muted")
            box.pack_start(empty, False, False, 7)

        for row_data in rows:
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=7,
            )
            _css(row, "adaptive-content-row")

            icon = Gtk.Image.new_from_icon_name(
                row_data.get("icon_name") or "text-x-generic",
                Gtk.IconSize.MENU,
            )
            icon.set_pixel_size(16)

            name = Gtk.Label(
                label=row_data.get("name") or "Item",
                xalign=0,
            )
            name.set_hexpand(True)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_tooltip_text(
                row_data.get("type_label")
                or row_data.get("name")
                or ""
            )

            row.pack_start(icon, False, False, 0)
            row.pack_start(name, True, True, 0)

            if not row_data.get("is_dir"):
                size = Gtk.Label(
                    label=_human_size(row_data.get("size", 0)),
                    xalign=1,
                )
                _css(size, "adaptive-row-size")
                row.pack_end(size, False, False, 0)

            box.pack_start(row, False, False, 0)

        if payload.get("has_more"):
            more = Gtk.Label(
                label="+ more items",
                xalign=0,
            )
            _css(more, "adaptive-muted")
            box.pack_start(more, False, False, 5)

        _log(
            "Folder preview complete: "
            f"generation={generation} rows={len(rows)} "
            f"has_more={bool(payload.get('has_more'))}"
        )

        box.show_all()
        return GLib.SOURCE_REMOVE

    def _append_details_placeholder(self):
        self.preview_body.pack_start(
            self._section_label("DETAILS"),
            False,
            False,
            0,
        )

        section = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
        )
        _css(section, "adaptive-metadata-card")

        loading = Gtk.Label(
            label="Loading details…",
            xalign=0,
        )
        _css(loading, "adaptive-muted")
        section.pack_start(loading, False, False, 0)

        self.preview_body.pack_start(
            section,
            False,
            False,
            0,
        )

        self.active_metadata_box = section
        return section

    def _query_metadata_async(self, item, gfile, generation):
        attributes = ",".join(
            [
                "standard::size",
                "standard::display-name",
                "standard::content-type",
                "standard::type",
                "time::modified",
                "time::created",
                "unix::mode",
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

            label = Gtk.Label(
                label=f"Details unavailable · {error}",
                xalign=0,
            )
            label.set_line_wrap(True)
            _css(label, "adaptive-muted")
            section.pack_start(label, False, False, 0)
            section.show_all()
            return

        content_type = info.get_content_type() or item.get("mime") or "—"
        display_type = (
            Gio.content_type_get_description(content_type)
            or content_type
        )

        self._metadata_row(section, "Type", display_type)

        if info.get_file_type() != Gio.FileType.DIRECTORY:
            self._metadata_row(
                section,
                "Size",
                _human_size(info.get_size()),
            )

        modified = 0
        created = 0

        try:
            modified = info.get_attribute_uint64("time::modified")
        except Exception:
            pass

        try:
            created = info.get_attribute_uint64("time::created")
        except Exception:
            pass

        if modified:
            self._metadata_row(
                section,
                "Modified",
                _format_timestamp(modified),
            )

        if created:
            self._metadata_row(
                section,
                "Created",
                _format_timestamp(created),
            )

        try:
            mode = info.get_attribute_uint32("unix::mode")
            if mode:
                self._metadata_row(
                    section,
                    "Permissions",
                    _mode_text(mode),
                )
        except Exception:
            pass

        section.show_all()

    def _append_path_and_actions(self, item):
        uri = item.get("uri") or ""
        gfile = Gio.File.new_for_uri(uri)
        path = gfile.get_path() or uri

        self.preview_body.pack_start(
            self._section_label("LOCATION"),
            False,
            False,
            0,
        )

        path_card = self._card()
        path_label = Gtk.Label(label=path, xalign=0)
        path_label.set_selectable(True)
        path_label.set_line_wrap(True)
        path_label.set_line_wrap_mode(Pango.WrapMode.CHAR)
        _css(path_label, "adaptive-path-value")
        path_card.pack_start(path_label, False, False, 0)
        self.preview_body.pack_start(path_card, False, False, 0)

        self.preview_body.pack_start(
            self._section_label("ACTIONS"),
            False,
            False,
            0,
        )

        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        actions.pack_start(
            self._button(
                "Copy Path",
                lambda *_: self._copy_text(path),
            ),
            False,
            False,
            0,
        )

        actions.pack_start(
            self._button(
                "Bookmark Current Location",
                lambda *_: self._bookmark_current_location(),
            ),
            False,
            False,
            0,
        )

        self.preview_body.pack_start(actions, False, False, 0)
        self.preview_body.show_all()

    # --------------------------------------------------------------
    # Storage
    # --------------------------------------------------------------

    def _render_storage(self):
        self._clear(self.storage_body)

        try:
            usage = shutil.disk_usage(str(Path.home()))
            used = usage.total - usage.free
            fraction = used / usage.total if usage.total else 0.0
        except Exception:
            self._render_storage_error("Unable to read storage usage.")
            return

        overview = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        _css(overview, "adaptive-storage-overview")

        overlay = Gtk.Overlay()
        overlay.set_size_request(116, 116)

        ring = UsageRing()
        ring.set_fraction(fraction)
        overlay.add(ring)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)

        percent = Gtk.Label(label=f"{fraction * 100:.0f}%")
        _css(percent, "adaptive-storage-percent")
        center.pack_start(percent, False, False, 0)

        caption = Gtk.Label(label="USED")
        _css(caption, "adaptive-storage-used-caption")
        center.pack_start(caption, False, False, 0)

        overlay.add_overlay(center)
        overview.pack_start(overlay, False, False, 0)

        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        summary.set_valign(Gtk.Align.CENTER)
        summary.set_hexpand(True)

        free = Gtk.Label(label=_human_size(usage.free), xalign=0)
        _css(free, "adaptive-storage-free")
        summary.pack_start(free, False, False, 0)

        free_caption = Gtk.Label(label="Available", xalign=0)
        _css(free_caption, "adaptive-storage-label")
        summary.pack_start(free_caption, False, False, 0)

        used_value = Gtk.Label(label=_human_size(used), xalign=0)
        _css(used_value, "adaptive-storage-used-value")
        summary.pack_start(used_value, False, False, 8)

        used_caption = Gtk.Label(label="Used", xalign=0)
        _css(used_caption, "adaptive-storage-label")
        summary.pack_start(used_caption, False, False, 0)

        overview.pack_start(summary, True, True, 0)
        self.storage_body.pack_start(overview, False, False, 0)

        self.storage_body.pack_start(
            self._section_label("CAPACITY"),
            False,
            False,
            0,
        )

        capacity = self._card()

        values = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        total = Gtk.Label(
            label=f"Total  {_human_size(usage.total)}",
            xalign=0,
        )
        total.set_hexpand(True)
        _css(total, "adaptive-capacity-label")

        free_value = Gtk.Label(
            label=f"{_human_size(usage.free)} free",
            xalign=1,
        )
        _css(free_value, "adaptive-capacity-label")

        values.pack_start(total, True, True, 0)
        values.pack_end(free_value, False, False, 0)
        capacity.pack_start(values, False, False, 0)

        bar = Gtk.ProgressBar()
        bar.set_fraction(fraction)
        _css(bar, "adaptive-storage-bar")
        capacity.pack_start(bar, False, False, 7)

        self.storage_body.pack_start(capacity, False, False, 0)

        volume = self._volume_details()

        self.storage_body.pack_start(
            self._section_label("VOLUME"),
            False,
            False,
            0,
        )

        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        _css(details, "adaptive-metadata-card")

        self._metadata_row(details, "Device", volume["source"])
        self._metadata_row(details, "Filesystem", volume["fstype"])
        self._metadata_row(details, "Mounted at", volume["target"])
        self._metadata_row(details, "Home", str(Path.home()))

        self.storage_body.pack_start(details, False, False, 0)

        self.storage_body.pack_start(
            self._section_label("OPEN"),
            False,
            False,
            0,
        )

        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        actions.pack_start(
            self._button(
                "Home",
                lambda *_: self._open_location(Path.home().as_uri()),
            ),
            False,
            False,
            0,
        )
        actions.pack_start(
            self._button(
                "Filesystem",
                lambda *_: self._open_location("file:///"),
            ),
            False,
            False,
            0,
        )
        actions.pack_start(
            self._button(
                "Refresh Storage",
                lambda *_: self._render_storage(),
            ),
            False,
            False,
            0,
        )

        self.storage_body.pack_start(actions, False, False, 0)
        self.storage_body.show_all()

    def _render_storage_error(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        _css(label, "adaptive-muted")
        self.storage_body.pack_start(label, False, False, 0)
        self.storage_body.show_all()

    def _volume_details(self):
        values = {
            "source": "Unknown",
            "fstype": "Linux filesystem",
            "target": "/",
        }

        try:
            proc = subprocess.run(
                [
                    "findmnt",
                    "-n",
                    "-o",
                    "SOURCE,FSTYPE,TARGET",
                    "--target",
                    str(Path.home()),
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )

            line = proc.stdout.strip().splitlines()[0]
            parts = line.split()

            if len(parts) >= 3:
                values["source"] = parts[0]
                values["fstype"] = parts[1]
                values["target"] = " ".join(parts[2:])
        except Exception:
            pass

        return values

    # --------------------------------------------------------------
    # Network / native GVfs frontend
    # --------------------------------------------------------------

    def _render_network(self):
        self._clear(self.network_body)

        intro = self._card()

        title = Gtk.Label(label="Remote Locations", xalign=0)
        _css(title, "adaptive-network-title")
        intro.pack_start(title, False, False, 0)

        copy = Gtk.Label(
            label=(
                "Connections are handled by Ubuntu's native GIO/GVfs stack. "
                "This panel only provides the Adaptive Files interface."
            ),
            xalign=0,
        )
        copy.set_line_wrap(True)
        _css(copy, "adaptive-network-copy")
        intro.pack_start(copy, False, False, 4)

        self.network_body.pack_start(intro, False, False, 0)

        self.network_body.pack_start(
            self._section_label("CONNECT TO SERVER"),
            False,
            False,
            0,
        )

        connect_card = self._card()

        entry = Gtk.Entry()
        entry.set_text("smb://")
        entry.set_placeholder_text("smb://server/share")
        entry.set_hexpand(True)
        _css(entry, "adaptive-network-entry")
        connect_card.pack_start(entry, False, False, 0)

        connect = self._button(
            "Connect",
            lambda *_: self._connect_remote(entry.get_text()),
        )
        connect_card.pack_start(connect, False, False, 7)

        self.network_body.pack_start(connect_card, False, False, 0)

        self.network_body.pack_start(
            self._section_label("NATIVE NETWORK"),
            False,
            False,
            0,
        )

        native_actions = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=5,
        )

        native_actions.pack_start(
            self._button(
                "Browse Network",
                lambda *_: self._open_location("network:///"),
            ),
            False,
            False,
            0,
        )

        native_actions.pack_start(
            self._button(
                "Enter Location",
                lambda *_: self._activate_window_action("enter-location"),
            ),
            False,
            False,
            0,
        )

        self.network_body.pack_start(native_actions, False, False, 0)

        mounts = self._remote_mounts()

        if mounts:
            self.network_body.pack_start(
                self._section_label("CONNECTED"),
                False,
                False,
                0,
            )

            mounted = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=4,
            )

            for name, uri in mounts:
                mounted.pack_start(
                    self._button(
                        name,
                        lambda _button, target=uri: self._open_location(target),
                    ),
                    False,
                    False,
                    0,
                )

            self.network_body.pack_start(mounted, False, False, 0)

        self.network_body.show_all()

    def _connect_remote(self, text):
        uri = (text or "").strip()

        if not uri:
            return

        if "://" not in uri:
            uri = "smb://" + uri

        allowed = (
            "smb://",
            "sftp://",
            "ftp://",
            "dav://",
            "davs://",
            "nfs://",
        )

        if not uri.casefold().startswith(allowed):
            self._show_error(
                "Unsupported address",
                (
                    "Use a native GVfs URI such as smb://server/share, "
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
                root = mount.get_root()
                uri = root.get_uri()

                if uri.startswith("file://"):
                    continue

                result.append((mount.get_name() or uri, uri))
        except Exception:
            pass

        return result[:12]

    # --------------------------------------------------------------
    # Native actions / helpers
    # --------------------------------------------------------------

    def _bookmark_current_location(self):
        if not self._activate_window_action("bookmark-current-location"):
            self._show_error(
                "Bookmark unavailable",
                (
                    "The native Nautilus bookmark action is not available "
                    "for this location."
                ),
            )

    def _copy_current_path(self):
        text = None

        if self.last_selection:
            uri = self.last_selection[0].get("uri")
            if uri:
                gfile = Gio.File.new_for_uri(uri)
                text = gfile.get_parent().get_path() if gfile.get_parent() else None

        if not text:
            text = str(Path.home())

        self._copy_text(text)

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

    # --------------------------------------------------------------
    # UI helpers
    # --------------------------------------------------------------

    def _clear(self, box):
        for child in list(box.get_children()):
            box.remove(child)

    def _card(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(1)
        box.set_margin_bottom(1)
        box.set_margin_start(0)
        box.set_margin_end(0)
        _css(box, "adaptive-card")
        return box

    def _section_label(self, text):
        label = Gtk.Label(label=text, xalign=0)
        _css(label, "adaptive-section-label")
        return label

    def _button(self, label, callback):
        button = Gtk.Button(label=label)
        button.set_halign(Gtk.Align.FILL)
        button.set_hexpand(True)
        _css(button, "adaptive-inspector-button")
        button.connect("clicked", callback)
        return button

    def _metadata_row(self, parent, key, value):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        left = Gtk.Label(label=key, xalign=0)
        left.set_hexpand(True)
        _css(left, "adaptive-meta-key")

        right = Gtk.Label(label=str(value), xalign=1)
        right.set_line_wrap(True)
        right.set_selectable(True)
        _css(right, "adaptive-meta-value")

        row.pack_start(left, True, True, 0)
        row.pack_end(right, False, False, 0)

        parent.pack_start(row, False, False, 0)

    def _render_message(self, title, body):
        self.preview_title.set_text(title)
        self.preview_subtitle.set_text("")
        self._clear(self.preview_body)

        card = self._card()

        headline = Gtk.Label(label=title, xalign=0)
        _css(headline, "adaptive-empty-title")
        card.pack_start(headline, False, False, 0)

        copy = Gtk.Label(label=body, xalign=0)
        copy.set_line_wrap(True)
        _css(copy, "adaptive-empty-copy")
        card.pack_start(copy, False, False, 0)

        self.preview_body.pack_start(card, False, False, 0)
        self.preview_body.show_all()

    def _render_project(self):
        self._clear(self.project_body)
        
        card = self._card()
        _css(card, "adaptive-project-card")
        
        headline = Gtk.Label(label="PROJECT CONTEXT", xalign=0)
        _css(headline, "adaptive-metadata-key")
        card.pack_start(headline, False, False, 0)
        
        if not self._dbus_proxy:
            err = Gtk.Label(label="Project Context Service offline", xalign=0)
            _css(err, "adaptive-muted")
            card.pack_start(err, False, False, 8)
            self.project_body.pack_start(card, False, False, 0)
            self.project_body.show_all()
            return
            
        try:
            res = self._dbus_proxy.call_sync(
                "GetActiveProject",
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            pid, name, path = res.unpack()
            self._active_project_id = pid or None
            
            if pid:
                title = Gtk.Label(label=name, xalign=0)
                _css(title, "adaptive-empty-title", "adaptive-project-active-badge")
                card.pack_start(title, False, False, 4)
                
                path_label = Gtk.Label(label=path, xalign=0)
                path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                _css(path_label, "adaptive-muted")
                card.pack_start(path_label, False, False, 0)
            else:
                title = Gtk.Label(label="No active project", xalign=0)
                _css(title, "adaptive-muted")
                card.pack_start(title, False, False, 4)
                
        except Exception as e:
            _log_exception("GetActiveProject failed")
            
        self.project_body.pack_start(card, False, False, 0)
        
        try:
            res = self._dbus_proxy.call_sync(
                "ListProjects",
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            projects = json.loads(res.unpack()[0])
            
            list_card = self._card()
            _css(list_card, "adaptive-project-card")
            
            list_head = Gtk.Label(label="AVAILABLE PROJECTS", xalign=0)
            _css(list_head, "adaptive-metadata-key")
            list_card.pack_start(list_head, False, False, 8)
            
            if not projects:
                empty = Gtk.Label(label="No projects found", xalign=0)
                _css(empty, "adaptive-muted")
                list_card.pack_start(empty, False, False, 0)
            else:
                for pid, pdata in projects.items():
                    is_active = (pid == self._active_project_id)
                    btn = Gtk.Button(label="★ " + pdata["name"] if is_active else pdata["name"])
                    btn.set_halign(Gtk.Align.FILL)
                    _css(btn, "adaptive-project-list-row")
                    if is_active:
                        _css(btn, "adaptive-project-active-badge")
                    
                    def set_active(button, target_id=pid):
                        try:
                            self._dbus_proxy.call_sync(
                                "SetActiveProject",
                                GLib.Variant.new("(s)", [target_id]),
                                Gio.DBusCallFlags.NONE,
                                -1,
                                None
                            )
                        except Exception as e:
                            _log_exception("SetActiveProject failed")
                            
                    btn.connect("clicked", set_active)
                    list_card.pack_start(btn, False, False, 2)
            
            self.project_body.pack_start(list_card, False, False, 0)
        except Exception as e:
            _log_exception("ListProjects failed")
            
        self.project_body.show_all()


class AdaptivePreviewExtension(GObject.GObject, Nautilus.MenuProvider, Nautilus.LocationWidgetProvider):
    """
    Nautilus 42's MenuProvider callback includes the window and the selected
    files. We use the selection callback only as a notification source; the
    extension returns no extra context-menu items.
    """

    def __init__(self):
        super().__init__()
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

            strip = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=5,
            )
            _css(strip, "adaptive-location-strip")

            brand = Gtk.Label(label="ADAPTIVE FILES")
            brand.set_margin_start(3)
            brand.set_margin_end(5)
            _css(brand, "adaptive-location-brand")
            strip.pack_start(brand, False, False, 0)

            inspector = Gtk.ToggleButton(label="Inspector")
            inspector.set_active(controller.panel_visible)
            _css(inspector, "adaptive-location-button")

            def toggle(button):
                controller.set_panel_visible(button.get_active())

            inspector.connect("toggled", toggle)
            strip.pack_start(inspector, False, False, 0)

            storage = Gtk.Button(label="Storage")
            _css(storage, "adaptive-location-button")
            storage.connect(
                "clicked",
                lambda *_: controller.show_tab("storage"),
            )
            strip.pack_start(storage, False, False, 0)

            network = Gtk.Button(label="Network")
            _css(network, "adaptive-location-button")
            network.connect(
                "clicked",
                lambda *_: controller.show_tab("network"),
            )
            strip.pack_start(network, False, False, 0)

            project = Gtk.Button(label="Project")
            _css(project, "adaptive-location-button")
            project.connect(
                "clicked",
                lambda *_: controller.show_tab("project"),
            )
            strip.pack_start(project, False, False, 0)

            path = Gtk.Label(label=uri or "", xalign=1)
            path.set_hexpand(True)
            path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            _css(path, "adaptive-muted")
            strip.pack_end(path, True, True, 6)

            strip.show_all()

            _log(
                f"LocationWidgetProvider active for uri={uri}; "
                f"window={_type_name(window)}"
            )

            return strip

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

            if controller is not None:
                GLib.idle_add(controller.ensure_attached)

        except Exception:
            _log_exception("get_background_items failed")

        return []
