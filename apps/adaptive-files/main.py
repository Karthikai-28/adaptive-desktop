#!/usr/bin/env python3
import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk, Gdk

APP_ID = "com.karthi.AdaptiveFiles"
BASE_DIR = Path(__file__).resolve().parent
ASSETS = BASE_DIR / "assets"

CONFIG_DIR = Path.home() / ".config" / "adaptive-desktop"
PROJECT_REGISTRY = CONFIG_DIR / "projects.json"
PINNED_REGISTRY = CONFIG_DIR / "bookmarks.json"
REMOTE_REGISTRY = CONFIG_DIR / "remotes.json"

PREVIEW_CACHE = Path.home() / ".cache" / "adaptive-files" / "previews"


@dataclass
class Item:
    file: Gio.File
    name: str
    is_dir: bool
    size: int
    modified: str
    created: str
    permissions: str


def fmt_time(dt):
    if not dt:
        return "—"
    try:
        return datetime.fromtimestamp(dt.to_unix()).strftime("%b %d, %Y · %I:%M %p")
    except Exception:
        return "—"


def fmt_size(n):
    n = int(n or 0)
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def fmt_mode(mode):
    try:
        return stat.filemode(mode)
    except Exception:
        return "—"


def file_display(file_obj):
    if file_obj is None:
        return "—"
    return file_obj.get_parse_name() or file_obj.get_uri() or "Unknown"


def pic(name, size=18):
    image = Gtk.Picture.new_for_filename(str(ASSETS / name))
    image.set_size_request(size, size)
    image.set_can_shrink(True)
    return image


def folder_asset(name):
    key = name.casefold()
    if any(x in key for x in ("src", "bin", "env", "code", "include")):
        return "folder-code.svg"
    if "download" in key:
        return "folder-download.svg"
    if any(x in key for x in ("doc", "note", "paper")):
        return "folder-docs.svg"
    if any(x in key for x in ("config", "system", "settings", "intel")):
        return "folder-system.svg"
    return "folder-generic.svg"


def is_image(path):
    return path.suffix.casefold() in {
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"
    }


def is_text(path):
    return path.suffix.casefold() in {
        ".txt", ".md", ".rst", ".log", ".py", ".js", ".ts", ".tsx", ".jsx",
        ".c", ".h", ".cpp", ".hpp", ".cc", ".java", ".rs", ".go", ".sh",
        ".bash", ".zsh", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".conf", ".xml", ".html", ".css", ".csv", ".sql"
    }


class AdaptiveFilesWindow(Gtk.ApplicationWindow):
    SIDEBAR_WIDE = 174
    SIDEBAR_COMPACT = 54
    PREVIEW_WIDE = 298
    PREVIEW_NARROW = 244
    GRID_ITEM_WIDTH = 108

    def __init__(self, app, start=None):
        super().__init__(application=app)

        self.set_title("Files")
        self.set_default_size(1240, 770)
        self.set_size_request(840, 550)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PREVIEW_CACHE.mkdir(parents=True, exist_ok=True)

        self.current = start or Gio.File.new_for_path(str(Path.home()))
        self.back_stack = []
        self.forward_stack = []

        self.items = []
        self.visible_items = []
        self.selected = None
        self.selected_button = None
        self.selected_items = {}
        self.selected_buttons = {}

        self.show_hidden = False
        self.query = ""
        self.view_mode = "grid"
        self.split_enabled = False
        self.secondary_current = Gio.File.new_for_path(str(Path.home()))
        self.secondary_items = []
        self.transfer_log = []

        self.sidebar_labels = []
        self._last_width = -1
        self._last_content_width = -1
        self._responsive_source = None
        self._storage_anim_source = None
        self._storage_anim_value = 0.0
        self._storage_target = 0.0
        self._mount_operation = None

        self._load_css()
        self._build_ui()
        self._install_keyboard_shortcuts()
        self.populate()

        self._responsive_source = GLib.timeout_add(180, self._responsive_check)
        self.connect("close-request", self._on_close_request)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(BASE_DIR / "style.css"))
        display = Gdk.Display.get_default()

        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build_ui(self):
        self.set_titlebar(self._build_titlebar())

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("root")
        self.set_child(root)

        root.append(self._build_toolbar())

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_hexpand(True)
        body.set_vexpand(True)
        body.add_css_class("body")
        root.append(body)

        self.sidebar = self._build_sidebar()
        body.append(self.sidebar)

        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_paned.set_hexpand(True)
        self.main_paned.set_vexpand(True)
        self.main_paned.set_wide_handle(False)
        self.main_paned.add_css_class("content-paned")
        body.append(self.main_paned)

        self.browser = self._build_browser()
        self.main_paned.set_start_child(self.browser)
        self.main_paned.set_resize_start_child(True)
        self.main_paned.set_shrink_start_child(False)

        self.preview_panel = self._build_preview_panel()
        self.main_paned.set_end_child(self.preview_panel)
        self.main_paned.set_resize_end_child(False)
        self.main_paned.set_shrink_end_child(False)

        root.append(self._build_statusbar())

    def _build_titlebar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("titlebar")

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        brand.set_hexpand(True)
        brand.append(pic("app-logo.svg", 18))

        title = Gtk.Label(label="Files", xalign=0)
        title.add_css_class("title")
        brand.append(title)
        bar.append(brand)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        controls.append(self._window_button("minimize.svg", self.minimize, "Minimize"))
        controls.append(self._window_button("maximize.svg", self._toggle_maximize, "Maximize"))
        controls.append(self._window_button("close.svg", self.close, "Close"))
        bar.append(controls)

        return bar

    def _build_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.add_css_class("toolbar")

        self.back_btn = self._icon_button("back.svg", "Back", self.go_back)
        self.forward_btn = self._icon_button("forward.svg", "Forward", self.go_forward)
        self.up_btn = self._icon_button("up.svg", "Up", self.go_up)

        bar.append(self.back_btn)
        bar.append(self.forward_btn)
        bar.append(self.up_btn)

        self.path_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.path_box.add_css_class("path-box")
        self.path_box.set_size_request(252, -1)
        self.path_box.append(pic("home.svg", 13))

        self.path_entry = Gtk.Entry()
        self.path_entry.set_editable(False)
        self.path_entry.set_hexpand(True)
        self.path_entry.add_css_class("path-entry")
        self.path_entry.set_tooltip_text("Selectable/copyable path")
        self.path_box.append(self.path_entry)

        bar.append(self.path_box)

        self.pin_btn = Gtk.ToggleButton()
        self.pin_btn.add_css_class("tool-button")
        self.pin_btn.set_child(pic("pin.svg", 14))
        self.pin_btn.set_tooltip_text("Pin or unpin this location")
        self.pin_btn.connect("clicked", self._toggle_pin_current)
        bar.append(self.pin_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        self.search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.search_box.add_css_class("search-box")
        self.search_box.set_size_request(164, -1)
        self.search_box.append(pic("search.svg", 13))

        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search")
        self.search_entry.set_hexpand(True)
        self.search_entry.add_css_class("search-entry")
        self.search_entry.connect("changed", self._search_changed)
        self.search_box.append(self.search_entry)

        bar.append(self.search_box)

        self.grid_btn = self._toggle_icon_button(
            "grid.svg", "Grid", lambda *_: self.set_view("grid")
        )
        self.list_btn = self._toggle_icon_button(
            "list.svg", "List", lambda *_: self.set_view("list")
        )
        self.grid_btn.set_active(True)

        bar.append(self.grid_btn)
        bar.append(self.list_btn)

        self.split_btn = Gtk.ToggleButton()
        self.split_btn.add_css_class("tool-button")
        self.split_btn.set_child(pic("split.svg", 14))
        self.split_btn.set_tooltip_text("Split view")
        self.split_btn.connect("toggled", self._split_changed)
        bar.append(self.split_btn)

        self.hidden_btn = Gtk.ToggleButton()
        self.hidden_btn.add_css_class("tool-button")
        self.hidden_btn.set_child(pic("eye.svg", 14))
        self.hidden_btn.set_tooltip_text("Show hidden files")
        self.hidden_btn.connect("toggled", self._hidden_changed)
        bar.append(self.hidden_btn)

        refresh = self._icon_button("more.svg", "Refresh", self.reload)
        bar.append(refresh)

        return bar

    def _build_sidebar(self):
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        side.set_size_request(self.SIDEBAR_WIDE, -1)
        side.set_hexpand(False)
        side.set_vexpand(True)
        side.add_css_class("sidebar")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        side.append(scroll)

        self.sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.sidebar_box.set_margin_top(8)
        self.sidebar_box.set_margin_start(6)
        self.sidebar_box.set_margin_end(6)
        scroll.set_child(self.sidebar_box)

        self._side_heading(self.sidebar_box, "PLACES")
        self._side_item(
            self.sidebar_box,
            "Home",
            "home.svg",
            lambda: self.navigate(Gio.File.new_for_path(str(Path.home()))),
        )
        self._side_item(
            self.sidebar_box,
            "Recent",
            "star.svg",
            lambda: self.navigate(Gio.File.new_for_uri("recent:///")),
        )

        for label, asset, path in (
            ("Documents", "documents.svg", Path.home() / "Documents"),
            ("Downloads", "downloads.svg", Path.home() / "Downloads"),
            ("Pictures", "pictures.svg", Path.home() / "Pictures"),
            ("Music", "music.svg", Path.home() / "Music"),
            ("Videos", "videos.svg", Path.home() / "Videos"),
        ):
            if path.exists():
                target = Gio.File.new_for_path(str(path))
                self._side_item(
                    self.sidebar_box,
                    label,
                    asset,
                    lambda t=target: self.navigate(t),
                )

        self._side_item(
            self.sidebar_box,
            "Trash",
            "trash.svg",
            lambda: self.navigate(Gio.File.new_for_uri("trash:///")),
        )

        self._side_heading(self.sidebar_box, "PINNED")
        self.pinned_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.sidebar_box.append(self.pinned_box)
        self._reload_pinned_sidebar()

        projects = self._projects()
        if projects:
            self._side_heading(self.sidebar_box, "PROJECTS")
            for project in projects:
                name = project.get("name")
                root = project.get("root") or project.get("path")
                if not name or not root:
                    continue

                path = Path(root).expanduser()

                if path.exists():
                    target = Gio.File.new_for_path(str(path))
                    self._side_item(
                        self.sidebar_box,
                        name,
                        "folder-nav.svg",
                        lambda t=target: self.navigate(t),
                    )

        self._side_heading(self.sidebar_box, "NETWORK")
        self._side_action_item(
            self.sidebar_box,
            "Connect to Server…",
            "network.svg",
            self._show_connect_dialog,
        )
        self.remote_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.sidebar_box.append(self.remote_box)
        self._reload_remote_sidebar()

        self._side_heading(self.sidebar_box, "LOCATIONS")
        self._side_item(
            self.sidebar_box,
            "Filesystem",
            "filesystem.svg",
            lambda: self.navigate(Gio.File.new_for_path("/")),
        )

        self.storage_button = Gtk.Button()
        self.storage_button.add_css_class("storage-button")
        self.storage_button.set_margin_start(7)
        self.storage_button.set_margin_end(7)
        self.storage_button.set_margin_bottom(7)
        self.storage_button.set_tooltip_text("Open storage overview")
        self.storage_button.connect("clicked", lambda *_: self._show_storage_preview())

        storage_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        storage_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        storage_top.append(pic("storage.svg", 14))

        self.storage_primary = Gtk.Label(xalign=0)
        self.storage_primary.set_hexpand(True)
        self.storage_primary.add_css_class("storage-primary")
        storage_top.append(self.storage_primary)
        storage_box.append(storage_top)

        self.storage_secondary = Gtk.Label(xalign=0)
        self.storage_secondary.add_css_class("storage-secondary")
        storage_box.append(self.storage_secondary)

        self.storage_mini = Gtk.ProgressBar()
        self.storage_mini.add_css_class("storage-mini")
        storage_box.append(self.storage_mini)

        self.storage_button.set_child(storage_box)
        side.append(self.storage_button)

        self._refresh_storage()
        return side

    def _build_browser(self):
        browser = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        browser.set_hexpand(True)
        browser.set_vexpand(True)
        browser.add_css_class("browser")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("browser-header")

        self.folder_title = Gtk.Label(label="Home", xalign=0)
        self.folder_title.set_hexpand(True)
        self.folder_title.add_css_class("folder-title")

        self.folder_summary = Gtk.Label(label="", xalign=1)
        self.folder_summary.add_css_class("folder-summary")

        header.append(self.folder_title)
        header.append(self.folder_summary)
        browser.append(header)

        self.browser_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.browser_paned.set_wide_handle(False)
        self.browser_paned.set_hexpand(True)
        self.browser_paned.set_vexpand(True)
        self.browser_paned.add_css_class("browser-paned")
        browser.append(self.browser_paned)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_hexpand(True)
        self.scroll.set_vexpand(True)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_row_spacing(5)
        self.flow.set_column_spacing(5)
        self.flow.set_margin_top(10)
        self.flow.set_margin_bottom(10)
        self.flow.set_margin_start(10)
        self.flow.set_margin_end(10)
        self.flow.set_min_children_per_line(1)
        self.flow.set_max_children_per_line(20)
        self.flow.set_hexpand(True)
        self.flow.set_halign(Gtk.Align.FILL)
        self.flow.set_valign(Gtk.Align.START)
        self.scroll.set_child(self.flow)

        self.browser_paned.set_start_child(self.scroll)
        self.browser_paned.set_resize_start_child(True)
        self.browser_paned.set_shrink_start_child(False)

        self.secondary_browser = self._build_secondary_browser()
        self.secondary_browser.set_visible(False)
        self.browser_paned.set_end_child(self.secondary_browser)
        self.browser_paned.set_resize_end_child(True)
        self.browser_paned.set_shrink_end_child(False)

        return browser

    def _build_secondary_browser(self):
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        pane.add_css_class("secondary-browser")
        pane.set_hexpand(True)
        pane.set_vexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        header.add_css_class("secondary-header")

        header.append(pic("folder-generic.svg", 14))

        self.secondary_title = Gtk.Label(label="Home", xalign=0)
        self.secondary_title.set_hexpand(True)
        self.secondary_title.set_ellipsize(3)
        self.secondary_title.add_css_class("folder-title")
        header.append(self.secondary_title)

        self.secondary_path = Gtk.Label(label=str(Path.home()), xalign=1)
        self.secondary_path.set_ellipsize(3)
        self.secondary_path.add_css_class("folder-summary")
        header.append(self.secondary_path)

        pane.append(header)

        self.secondary_scroll = Gtk.ScrolledWindow()
        self.secondary_scroll.set_hexpand(True)
        self.secondary_scroll.set_vexpand(True)
        pane.append(self.secondary_scroll)

        self.secondary_flow = Gtk.FlowBox()
        self.secondary_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.secondary_flow.set_row_spacing(5)
        self.secondary_flow.set_column_spacing(5)
        self.secondary_flow.set_margin_top(10)
        self.secondary_flow.set_margin_bottom(10)
        self.secondary_flow.set_margin_start(10)
        self.secondary_flow.set_margin_end(10)
        self.secondary_flow.set_min_children_per_line(1)
        self.secondary_flow.set_max_children_per_line(12)
        self.secondary_flow.set_hexpand(True)
        self.secondary_flow.set_halign(Gtk.Align.FILL)
        self.secondary_flow.set_valign(Gtk.Align.START)
        self.secondary_scroll.set_child(self.secondary_flow)

        return pane

    def _build_preview_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.set_size_request(self.PREVIEW_WIDE, -1)
        panel.set_hexpand(False)
        panel.set_vexpand(True)
        panel.add_css_class("preview-panel")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("preview-header")

        self.preview_header_icon = Gtk.Box()
        self.preview_header_icon.add_css_class("preview-header-icon")
        self.preview_header_icon.append(pic("folder-generic.svg", 19))
        header.append(self.preview_header_icon)

        title_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_stack.set_hexpand(True)

        self.preview_title = Gtk.Label(label="Preview", xalign=0)
        self.preview_title.set_ellipsize(3)
        self.preview_title.add_css_class("preview-title")

        self.preview_subtitle = Gtk.Label(label="", xalign=0)
        self.preview_subtitle.set_ellipsize(3)
        self.preview_subtitle.add_css_class("preview-subtitle")

        title_stack.append(self.preview_title)
        title_stack.append(self.preview_subtitle)
        header.append(title_stack)

        panel.append(header)

        self.preview_scroll = Gtk.ScrolledWindow()
        self.preview_scroll.set_hexpand(True)
        self.preview_scroll.set_vexpand(True)
        self.preview_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.preview_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        self.preview_content.set_margin_top(12)
        self.preview_content.set_margin_bottom(12)
        self.preview_content.set_margin_start(12)
        self.preview_content.set_margin_end(12)

        self.preview_scroll.set_child(self.preview_content)
        panel.append(self.preview_scroll)

        self.preview_actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.preview_actions.add_css_class("preview-actions")
        self.preview_actions.set_margin_top(8)
        self.preview_actions.set_margin_bottom(10)
        self.preview_actions.set_margin_start(10)
        self.preview_actions.set_margin_end(10)
        panel.append(self.preview_actions)

        return panel

    def _build_statusbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("statusbar")

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("status-text")

        self.selection_label = Gtk.Label(label="", xalign=1)
        self.selection_label.add_css_class("status-text")

        bar.append(self.status_label)
        bar.append(self.selection_label)
        return bar

    # ------------------------------------------------------------------
    # Component factories
    # ------------------------------------------------------------------

    def _window_button(self, icon, callback, tooltip):
        button = Gtk.Button()
        button.add_css_class("window-button")
        button.set_child(pic(icon, 10))
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_: callback())
        return button

    def _icon_button(self, icon, tooltip, callback):
        button = Gtk.Button()
        button.add_css_class("tool-button")
        button.set_child(pic(icon, 14))
        button.set_tooltip_text(tooltip)
        button.connect("clicked", callback)
        return button

    def _toggle_icon_button(self, icon, tooltip, callback):
        button = Gtk.ToggleButton()
        button.add_css_class("tool-button")
        button.set_child(pic(icon, 14))
        button.set_tooltip_text(tooltip)
        button.connect("clicked", callback)
        return button

    def _side_heading(self, box, text):
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("side-heading")
        label.set_margin_top(7)
        label.set_margin_bottom(3)
        box.append(label)

    def _side_item(self, box, text, icon, callback):
        button = Gtk.Button()
        button.add_css_class("side-item")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        row.append(pic(icon, 15))

        label = Gtk.Label(label=text, xalign=0)
        label.set_hexpand(True)
        label.set_ellipsize(3)
        label.add_css_class("side-label")
        self.sidebar_labels.append(label)

        row.append(label)
        button.set_child(row)
        button.connect("clicked", lambda *_: callback())
        box.append(button)

    def _side_action_item(self, box, text, icon, callback):
        self._side_item(box, text, icon, callback)

    def _action_button(self, icon, text, callback, css_class="preview-action"):
        button = Gtk.Button()
        button.add_css_class(css_class)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        row.append(pic(icon, 13))

        label = Gtk.Label(label=text, xalign=0)
        label.set_hexpand(True)
        row.append(label)

        button.set_child(row)
        button.connect("clicked", callback)
        return button

    def _section_label(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("preview-section-label")
        return label

    def _metadata_row(self, label_text, value_text):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        label = Gtk.Label(label=label_text, xalign=0)
        label.set_hexpand(True)
        label.add_css_class("preview-meta-key")

        value = Gtk.Label(label=value_text, xalign=1)
        value.set_wrap(True)
        value.add_css_class("preview-meta-value")

        row.append(label)
        row.append(value)
        return row

    def _clear_box(self, box):
        child = box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            box.remove(child)
            child = next_child

    def _replace_header_icon(self, asset_name):
        self._clear_box(self.preview_header_icon)
        self.preview_header_icon.append(pic(asset_name, 19))

    # ------------------------------------------------------------------
    # Keyboard + responsive layout
    # ------------------------------------------------------------------

    def _install_keyboard_shortcuts(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        focus = self.get_focus()

        if keyval == Gdk.KEY_BackSpace:
            if focus is self.search_entry:
                return False
            self.go_back()
            return True

        if keyval == Gdk.KEY_Left and state & Gdk.ModifierType.ALT_MASK:
            self.go_back()
            return True

        if keyval == Gdk.KEY_Right and state & Gdk.ModifierType.ALT_MASK:
            self.go_forward()
            return True

        if keyval == Gdk.KEY_Up and state & Gdk.ModifierType.ALT_MASK:
            self.go_up()
            return True

        if keyval in (Gdk.KEY_f, Gdk.KEY_F) and state & Gdk.ModifierType.CONTROL_MASK:
            self.search_entry.grab_focus()
            return True

        if keyval in (Gdk.KEY_l, Gdk.KEY_L) and state & Gdk.ModifierType.CONTROL_MASK:
            self.path_entry.grab_focus()
            self.path_entry.select_region(0, -1)
            return True

        if keyval == Gdk.KEY_Escape and self.search_entry.get_text():
            self.search_entry.set_text("")
            return True

        return False

    def _responsive_check(self):
        width = self.get_width()
        content_width = self.browser.get_width()

        if width == self._last_width and content_width == self._last_content_width:
            return GLib.SOURCE_CONTINUE

        self._last_width = width
        self._last_content_width = content_width

        compact = width < 960

        self.sidebar.set_size_request(
            self.SIDEBAR_COMPACT if compact else self.SIDEBAR_WIDE,
            -1,
        )

        for label in self.sidebar_labels:
            label.set_visible(not compact)

        self.search_box.set_visible(not compact)
        self.storage_primary.set_visible(not compact)
        self.storage_secondary.set_visible(not compact)
        self.storage_mini.set_visible(not compact)

        self.preview_panel.set_size_request(
            self.PREVIEW_NARROW if width < 1140 else self.PREVIEW_WIDE,
            -1,
        )

        self.path_box.set_size_request(208 if compact else 252, -1)

        if self.view_mode == "grid":
            available = max(120, content_width - 22)
            columns = max(1, available // self.GRID_ITEM_WIDTH)
            self.flow.set_max_children_per_line(int(columns))
        else:
            self.flow.set_max_children_per_line(1)

        return GLib.SOURCE_CONTINUE

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate(self, target, record=True):
        if record and self.current and not self.current.equal(target):
            self.back_stack.append(self.current)
            self.forward_stack.clear()

        self.current = target
        self.selected = None
        self.selected_button = None
        self.selected_items = {}
        self.selected_buttons = {}
        self.populate()

    def go_back(self, *_):
        if not self.back_stack:
            return

        self.forward_stack.append(self.current)
        self.current = self.back_stack.pop()
        self.selected = None
        self.selected_button = None
        self.selected_items = {}
        self.selected_buttons = {}
        self.populate()

    def go_forward(self, *_):
        if not self.forward_stack:
            return

        self.back_stack.append(self.current)
        self.current = self.forward_stack.pop()
        self.selected = None
        self.selected_button = None
        self.selected_items = {}
        self.selected_buttons = {}
        self.populate()

    def go_up(self, *_):
        parent = self.current.get_parent()
        if parent:
            self.navigate(parent)

    def reload(self, *_):
        self.populate()

    def _hidden_changed(self, button):
        self.show_hidden = button.get_active()
        self.populate()

    def _search_changed(self, entry):
        self.query = entry.get_text().strip().casefold()
        self._render_items()

    def set_view(self, mode):
        self.view_mode = mode
        self.grid_btn.set_active(mode == "grid")
        self.list_btn.set_active(mode == "list")
        self._render_items()
        self._render_secondary_items()
        self._last_content_width = -1

    def _split_changed(self, button):
        self.split_enabled = button.get_active()
        self.secondary_browser.set_visible(self.split_enabled)

        if self.split_enabled:
            self.secondary_current = self.current
            self.populate_secondary()
            self._message("Split View", "Second pane opened for file transfers.")
        else:
            self._message("Split View", "Second pane hidden.")

        self._show_location_preview()

    # ------------------------------------------------------------------
    # Filesystem
    # ------------------------------------------------------------------

    def populate(self):
        self.back_btn.set_sensitive(bool(self.back_stack))
        self.forward_btn.set_sensitive(bool(self.forward_stack))
        self.up_btn.set_sensitive(self.current.get_parent() is not None)

        self.path_entry.set_text(self._raw_path(self.current))
        self._update_pin_button()

        title = self.current.get_basename() or "Files"
        if self.current.get_path() == str(Path.home()):
            title = "Home"

        self.folder_title.set_text(title)

        try:
            self.items = self._read_items(self.current)

        except GLib.Error as error:
            self._render_error(error.message)
            return

        self._render_items()
        self._show_location_preview()

        if self.split_enabled and self.secondary_current.equal(self.current):
            self.populate_secondary()

    def _read_items(self, location):
        items = []
        attributes = ",".join(
            [
                "standard::name",
                "standard::display-name",
                "standard::type",
                "standard::size",
                "standard::is-hidden",
                "time::modified",
                "time::created",
                "unix::mode",
            ]
        )

        enumerator = location.enumerate_children(
            attributes,
            Gio.FileQueryInfoFlags.NONE,
            None,
        )

        try:
            while True:
                info = enumerator.next_file(None)
                if info is None:
                    break

                if info.get_is_hidden() and not self.show_hidden:
                    continue

                child_name = info.get_name()
                if not child_name:
                    continue

                child = location.get_child(child_name)

                items.append(
                    Item(
                        file=child,
                        name=info.get_display_name() or child_name,
                        is_dir=(info.get_file_type() == Gio.FileType.DIRECTORY),
                        size=info.get_size(),
                        modified=fmt_time(info.get_modification_date_time()),
                        created=fmt_time(info.get_creation_date_time()),
                        permissions=fmt_mode(info.get_attribute_uint32("unix::mode")),
                    )
                )
        finally:
            enumerator.close(None)

        items.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
        return items

    def _render_items(self):
        self._clear_box(self.flow)

        self.visible_items = [
            item
            for item in self.items
            if not self.query or self.query in item.name.casefold()
        ]

        if self.view_mode == "grid":
            self.flow.set_max_children_per_line(
                max(
                    1,
                    int(
                        max(120, self.browser.get_width() - 22)
                        // self.GRID_ITEM_WIDTH
                    ),
                )
            )
        else:
            self.flow.set_max_children_per_line(1)

        if not self.visible_items:
            empty = Gtk.Label(
                label="No matching files" if self.query else "This folder is empty",
                xalign=0.5,
            )
            empty.add_css_class("browser-empty")
            empty.set_margin_top(42)
            empty.set_margin_bottom(42)
            empty.set_margin_start(18)
            empty.set_margin_end(18)
            self.flow.append(empty)

        for item in self.visible_items:
            self.flow.append(self._item_widget(item))

        folders = sum(1 for item in self.visible_items if item.is_dir)
        files = len(self.visible_items) - folders

        self.folder_summary.set_text(f"{folders} folders · {files} files")
        self.status_label.set_text(f"{len(self.visible_items)} items")
        if len(self.selected_items) > 1:
            self.selection_label.set_text(f"{len(self.selected_items)} selected")
        else:
            self.selection_label.set_text(self.selected.name if self.selected else "")

    def populate_secondary(self):
        if not self.split_enabled:
            return

        try:
            self.secondary_items = self._read_items(self.secondary_current)
            self._render_secondary_items()
        except GLib.Error as error:
            self.secondary_items = []
            self._render_secondary_error(error.message)

    def _render_secondary_items(self):
        if not hasattr(self, "secondary_flow"):
            return

        self._clear_box(self.secondary_flow)

        title = self.secondary_current.get_basename() or "Files"
        if self.secondary_current.get_path() == str(Path.home()):
            title = "Home"

        self.secondary_title.set_text(title)
        self.secondary_path.set_text(self._raw_path(self.secondary_current))

        if self.view_mode == "grid":
            self.secondary_flow.set_max_children_per_line(12)
        else:
            self.secondary_flow.set_max_children_per_line(1)

        if not self.secondary_items:
            empty = Gtk.Label(label="This folder is empty", xalign=0.5)
            empty.add_css_class("browser-empty")
            empty.set_margin_top(42)
            empty.set_margin_bottom(42)
            self.secondary_flow.append(empty)
            return

        for item in self.secondary_items:
            self.secondary_flow.append(self._secondary_item_widget(item))

    def _render_secondary_error(self, text):
        self._clear_box(self.secondary_flow)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(80)

        title = Gtk.Label(label="Unable to open this location")
        title.add_css_class("error-title")

        detail = Gtk.Label(label=text)
        detail.set_wrap(True)
        detail.set_max_width_chars(36)
        detail.add_css_class("error-detail")

        box.append(title)
        box.append(detail)
        self.secondary_flow.append(box)

    def _secondary_item_widget(self, item):
        button = Gtk.Button()
        button.add_css_class("item")

        if self.view_mode == "list":
            button.add_css_class("item-list")
            button.set_size_request(-1, 44)
        else:
            button.set_size_request(104, 88)

        horizontal = self.view_mode == "list"
        row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL,
            spacing=4,
        )
        row.set_halign(Gtk.Align.FILL)
        row.set_valign(Gtk.Align.CENTER)

        asset = folder_asset(item.name) if item.is_dir else "file-generic.svg"
        row.append(pic(asset, 38 if horizontal else 44))

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text_box.set_hexpand(True)

        name = Gtk.Label(label=item.name, xalign=0 if horizontal else 0.5)
        name.set_ellipsize(3)
        name.set_max_width_chars(16)
        name.add_css_class("item-name")
        text_box.append(name)

        if not item.is_dir:
            secondary = Gtk.Label(
                label=fmt_size(item.size),
                xalign=0 if horizontal else 0.5,
            )
            secondary.add_css_class("item-secondary")
            text_box.append(secondary)

        row.append(text_box)
        button.set_child(row)

        gesture = Gtk.GestureClick.new()
        gesture.set_button(0)
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect("pressed", self._secondary_item_pressed, item)
        button.add_controller(gesture)

        return button

    def _secondary_item_pressed(self, _gesture, n_press, _x, _y, item):
        if n_press == 1:
            self.preview_title.set_text(item.name)
            self.preview_subtitle.set_text("Split pane target")
            return

        if n_press == 2:
            if item.is_dir:
                self.secondary_current = item.file
                self.populate_secondary()
            else:
                self._open_file(item)

    def _item_widget(self, item):
        button = Gtk.Button()
        button.add_css_class("item")

        if self.view_mode == "list":
            button.add_css_class("item-list")
            button.set_size_request(-1, 44)
        else:
            button.set_size_request(104, 88)

        if (
            item.file is not None
            and item.file.get_uri() in self.selected_items
        ):
            button.add_css_class("selected")
            self.selected_buttons[item.file.get_uri()] = button

        horizontal = self.view_mode == "list"

        row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL,
            spacing=4,
        )
        row.set_halign(Gtk.Align.FILL)
        row.set_valign(Gtk.Align.CENTER)

        asset = folder_asset(item.name) if item.is_dir else "file-generic.svg"
        row.append(pic(asset, 38 if horizontal else 44))

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text_box.set_hexpand(True)

        name = Gtk.Label(label=item.name, xalign=0 if horizontal else 0.5)
        name.set_ellipsize(3)
        name.set_max_width_chars(16)
        name.add_css_class("item-name")
        text_box.append(name)

        if not item.is_dir:
            secondary = Gtk.Label(
                label=fmt_size(item.size),
                xalign=0 if horizontal else 0.5,
            )
            secondary.add_css_class("item-secondary")
            text_box.append(secondary)

        row.append(text_box)
        button.set_child(row)

        # Capture clicks before Gtk.Button consumes the sequence.
        # Single click previews; n_press == 2 opens/navigates.
        gesture = Gtk.GestureClick.new()
        gesture.set_button(0)
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect("pressed", self._item_pressed, item, button)
        button.add_controller(gesture)

        return button

    def _item_pressed(self, gesture, n_press, _x, _y, item, button):
        state = gesture.get_current_event_state()
        if isinstance(state, tuple):
            state = state[-1]
        additive = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if n_press == 1:
            self._select_item(item, button, additive=additive)
            return

        if n_press == 2:
            if item.is_dir:
                self.navigate(item.file)
            else:
                self._open_file(item)

    def _select_item(self, item, button, additive=False):
        uri = item.file.get_uri()

        if additive:
            if uri in self.selected_items:
                button.remove_css_class("selected")
                self.selected_items.pop(uri, None)
                self.selected_buttons.pop(uri, None)
            else:
                self.selected_items[uri] = item
                self.selected_buttons[uri] = button
                button.add_css_class("selected")
        else:
            for selected_button in self.selected_buttons.values():
                selected_button.remove_css_class("selected")
            self.selected_items = {uri: item}
            self.selected_buttons = {uri: button}
            button.add_css_class("selected")

        if self.selected_items:
            self.selected = list(self.selected_items.values())[-1]
            self.selected_button = self.selected_buttons.get(self.selected.file.get_uri())
        else:
            self.selected = None
            self.selected_button = None

        if len(self.selected_items) > 1:
            self.selection_label.set_text(f"{len(self.selected_items)} selected")
            self._show_multi_preview()
        elif self.selected:
            self.selection_label.set_text(self.selected.name)
            self._show_item_preview(self.selected)
        else:
            self.selection_label.set_text("")
            self._show_location_preview()

    def _show_multi_preview(self):
        self._clear_box(self.preview_content)
        self._clear_box(self.preview_actions)

        count = len(self.selected_items)
        self._replace_header_icon("folder-generic.svg")
        self.preview_title.set_text(f"{count} selected")
        self.preview_subtitle.set_text("Multiple selection")

        self.preview_content.append(self._section_label("SELECTION"))
        self.preview_content.append(self._metadata_row("Items", str(count)))

        self.preview_actions.append(
            self._action_button("copy.svg", "Copy Paths", self._action_copy_paths)
        )
        if self.split_enabled:
            self.preview_actions.append(
                self._action_button("copy.svg", "Copy to Other Pane", self._action_copy_to_split)
            )
            self.preview_actions.append(
                self._action_button("open.svg", "Move to Other Pane", self._action_move_to_split)
            )
        self.preview_actions.append(
            self._action_button("delete.svg", "Move Selection to Trash", self._action_trash_selection)
        )

    def _open_file(self, item):
        try:
            Gio.AppInfo.launch_default_for_uri(item.file.get_uri(), None)
        except GLib.Error as error:
            self._message("Open failed", error.message)

    def _render_error(self, text):
        self._clear_box(self.flow)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(80)

        title = Gtk.Label(label="Unable to open this location")
        title.add_css_class("error-title")

        detail = Gtk.Label(label=text)
        detail.set_wrap(True)
        detail.set_max_width_chars(55)
        detail.add_css_class("error-detail")

        box.append(title)
        box.append(detail)
        self.flow.append(box)

        self.status_label.set_text("Location unavailable")
        self.selection_label.set_text("")

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _show_location_preview(self):
        self._clear_box(self.preview_content)
        self._clear_box(self.preview_actions)

        self._replace_header_icon("folder-generic.svg")
        self.preview_title.set_text(self.folder_title.get_text())
        self.preview_subtitle.set_text(self._raw_path(self.current))

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hero.add_css_class("preview-hero")
        hero.set_halign(Gtk.Align.FILL)

        icon = pic("folder-generic.svg", 64)
        icon.set_halign(Gtk.Align.CENTER)
        hero.append(icon)

        summary = Gtk.Label(
            label=f"{len(self.items)} visible items",
            xalign=0.5,
        )
        summary.add_css_class("preview-large-caption")
        hero.append(summary)
        self.preview_content.append(hero)

        self.preview_content.append(self._section_label("LOCATION"))
        self.preview_content.append(
            self._metadata_row("Path", self._raw_path(self.current))
        )

        pin_label = "Unpin Current Folder" if self._is_current_pinned() else "Pin Current Folder"
        self.preview_actions.append(
            self._action_button("pin.svg", pin_label, self._toggle_pin_current)
        )
        if self.transfer_log:
            self.preview_actions.append(
                self._action_button("info.svg", "Transfer Center", self._show_transfer_center)
            )

    def _show_item_preview(self, item):
        self._clear_box(self.preview_content)
        self._clear_box(self.preview_actions)

        self._replace_header_icon(
            folder_asset(item.name) if item.is_dir else "file-generic.svg"
        )
        self.preview_title.set_text(item.name)
        self.preview_subtitle.set_text(
            "Folder preview" if item.is_dir else "File preview"
        )

        if item.is_dir:
            self._render_folder_preview(item)
        else:
            self._render_file_preview(item)

        self.preview_content.append(self._section_label("DETAILS"))
        self.preview_content.append(
            self._metadata_row("Type", "Folder" if item.is_dir else "File")
        )
        self.preview_content.append(
            self._metadata_row("Location", file_display(item.file.get_parent()))
        )
        self.preview_content.append(
            self._metadata_row(
                "Size",
                self._folder_count_text(item) if item.is_dir else fmt_size(item.size),
            )
        )
        self.preview_content.append(self._metadata_row("Modified", item.modified))
        self.preview_content.append(self._metadata_row("Permissions", item.permissions))

        self.preview_actions.append(
            self._action_button("open.svg", "Open", self._action_open)
        )
        self.preview_actions.append(
            self._action_button("rename.svg", "Rename", self._action_rename)
        )
        self.preview_actions.append(
            self._action_button("archive.svg", "Compress", self._action_compress)
        )
        self.preview_actions.append(
            self._action_button("copy.svg", "Copy Path", self._action_copy)
        )
        if self.split_enabled:
            self.preview_actions.append(
                self._action_button("copy.svg", "Copy to Other Pane", self._action_copy_to_split)
            )
            self.preview_actions.append(
                self._action_button("open.svg", "Move to Other Pane", self._action_move_to_split)
            )
        self.preview_actions.append(
            self._action_button("delete.svg", "Move to Trash", self._action_trash)
        )

    def _render_folder_preview(self, item):
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hero.add_css_class("preview-hero")

        icon = pic(folder_asset(item.name), 62)
        icon.set_halign(Gtk.Align.CENTER)
        hero.append(icon)

        children = self._folder_children(item.file, limit=12)

        caption = Gtk.Label(
            label=f"{len(children)} shown" if children else "No visible contents",
            xalign=0.5,
        )
        caption.add_css_class("preview-large-caption")
        hero.append(caption)

        self.preview_content.append(hero)

        if children:
            self.preview_content.append(self._section_label("CONTENTS"))

            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            list_box.add_css_class("folder-preview-list")

            for child_name, child_is_dir, child_size in children:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
                row.add_css_class("folder-preview-row")

                row.append(
                    pic(
                        folder_asset(child_name)
                        if child_is_dir
                        else "file-generic.svg",
                        18,
                    )
                )

                name = Gtk.Label(label=child_name, xalign=0)
                name.set_hexpand(True)
                name.set_ellipsize(3)
                name.add_css_class("folder-preview-name")
                row.append(name)

                if not child_is_dir:
                    size = Gtk.Label(label=fmt_size(child_size), xalign=1)
                    size.add_css_class("folder-preview-size")
                    row.append(size)

                list_box.append(row)

            self.preview_content.append(list_box)

    def _render_file_preview(self, item):
        local = item.file.get_path()
        path = Path(local) if local else None

        if path and is_image(path):
            image = Gtk.Picture.new_for_filename(str(path))
            image.set_can_shrink(True)
            image.set_size_request(230, 188)
            image.set_halign(Gtk.Align.CENTER)
            image.add_css_class("actual-preview")
            self.preview_content.append(image)
            return

        if path and path.suffix.casefold() == ".pdf":
            pdf_preview = self._pdf_preview(path)

            if pdf_preview:
                image = Gtk.Picture.new_for_filename(str(pdf_preview))
                image.set_can_shrink(True)
                image.set_size_request(230, 205)
                image.set_halign(Gtk.Align.CENTER)
                image.add_css_class("actual-preview")
                self.preview_content.append(image)
                return

        if path and is_text(path):
            text_view = Gtk.TextView()
            text_view.set_editable(False)
            text_view.set_cursor_visible(False)
            text_view.set_monospace(True)
            text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            text_view.add_css_class("text-preview")
            text_view.set_size_request(230, 188)

            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:12000]
            except Exception as error:
                text = f"Unable to preview text:\n{error}"

            text_view.get_buffer().set_text(text)
            self.preview_content.append(text_view)
            return

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hero.add_css_class("preview-hero")

        icon = pic("file-generic.svg", 66)
        icon.set_halign(Gtk.Align.CENTER)
        hero.append(icon)

        label = Gtk.Label(label="Preview unavailable", xalign=0.5)
        label.add_css_class("preview-large-caption")
        hero.append(label)

        self.preview_content.append(hero)

    # ------------------------------------------------------------------
    # Storage redesign
    # ------------------------------------------------------------------

    def _refresh_storage(self):
        usage = shutil.disk_usage(str(Path.home()))
        used = usage.total - usage.free
        fraction = used / usage.total if usage.total else 0

        self.storage_primary.set_text("Storage")
        self.storage_secondary.set_text(f"{fmt_size(usage.free)} available")
        self.storage_mini.set_fraction(fraction)

    def _show_storage_preview(self):
        self.selected = None
        self.selected_items = {}
        self.selected_buttons = {}

        if self.selected_button:
            self.selected_button.remove_css_class("selected")
            self.selected_button = None

        self.selection_label.set_text("Storage")
        self._clear_box(self.preview_content)
        self._clear_box(self.preview_actions)

        usage = shutil.disk_usage(str(Path.home()))
        used = usage.total - usage.free
        fraction = used / usage.total if usage.total else 0

        volume = self._volume_details()

        self._replace_header_icon("storage.svg")
        self.preview_title.set_text("Storage")
        self.preview_subtitle.set_text(
            f"{volume['target']} · {volume['fstype']}"
        )

        overview = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        overview.add_css_class("storage-overview-card")

        ring_wrap = Gtk.Overlay()
        ring_wrap.set_size_request(116, 116)

        self.storage_drawing = Gtk.DrawingArea()
        self.storage_drawing.set_size_request(116, 116)
        self.storage_drawing.set_draw_func(self._draw_storage_ring)
        ring_wrap.set_child(self.storage_drawing)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)

        percent = Gtk.Label(label=f"{fraction * 100:.0f}%")
        percent.add_css_class("storage-percent")
        center.append(percent)

        used_label = Gtk.Label(label="used")
        used_label.add_css_class("storage-percent-label")
        center.append(used_label)

        ring_wrap.add_overlay(center)
        overview.append(ring_wrap)

        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        summary.set_hexpand(True)
        summary.set_valign(Gtk.Align.CENTER)

        available_value = Gtk.Label(label=fmt_size(usage.free), xalign=0)
        available_value.add_css_class("storage-feature-value")
        available_label = Gtk.Label(label="Available", xalign=0)
        available_label.add_css_class("storage-feature-label")

        summary.append(available_value)
        summary.append(available_label)

        used_value = Gtk.Label(label=fmt_size(used), xalign=0)
        used_value.add_css_class("storage-feature-value-small")
        used_label2 = Gtk.Label(label="Used", xalign=0)
        used_label2.add_css_class("storage-feature-label")

        summary.append(used_value)
        summary.append(used_label2)

        overview.append(summary)
        self.preview_content.append(overview)

        self.preview_content.append(self._section_label("CAPACITY"))

        capacity_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        capacity_card.add_css_class("storage-capacity-card")

        labels = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        total_label = Gtk.Label(label=f"Total {fmt_size(usage.total)}", xalign=0)
        total_label.set_hexpand(True)
        total_label.add_css_class("storage-capacity-label")

        free_label = Gtk.Label(label=f"{fmt_size(usage.free)} free", xalign=1)
        free_label.add_css_class("storage-capacity-label")

        labels.append(total_label)
        labels.append(free_label)
        capacity_card.append(labels)

        bar = Gtk.ProgressBar()
        bar.set_fraction(fraction)
        bar.add_css_class("storage-capacity-bar")
        capacity_card.append(bar)

        self.preview_content.append(capacity_card)

        self.preview_content.append(self._section_label("VOLUME"))

        volume_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        volume_card.add_css_class("storage-detail-card")
        volume_card.append(self._metadata_row("Device", volume["source"]))
        volume_card.append(self._metadata_row("Filesystem", volume["fstype"]))
        volume_card.append(self._metadata_row("Mounted at", volume["target"]))
        volume_card.append(self._metadata_row("Home", str(Path.home())))
        self.preview_content.append(volume_card)

        self.preview_actions.append(
            self._action_button(
                "home.svg",
                "Open Home",
                lambda *_: self.navigate(Gio.File.new_for_path(str(Path.home()))),
            )
        )
        self.preview_actions.append(
            self._action_button(
                "filesystem.svg",
                "Open Filesystem",
                lambda *_: self.navigate(Gio.File.new_for_path("/")),
            )
        )
        self.preview_actions.append(
            self._action_button(
                "more.svg",
                "Refresh Storage",
                lambda *_: self._show_storage_preview(),
            )
        )

        self._start_storage_animation(fraction)

    def _volume_details(self):
        details = {
            "source": "Unknown",
            "fstype": "Linux filesystem",
            "target": "/",
        }

        try:
            result = subprocess.run(
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

            line = result.stdout.strip().splitlines()[0]
            parts = line.split()

            if len(parts) >= 3:
                details["source"] = parts[0]
                details["fstype"] = parts[1]
                details["target"] = " ".join(parts[2:])

        except Exception:
            pass

        return details

    def _start_storage_animation(self, target):
        if self._storage_anim_source:
            GLib.source_remove(self._storage_anim_source)
            self._storage_anim_source = None

        self._storage_target = max(0.0, min(1.0, target))

        if not self._animations_enabled():
            self._storage_anim_value = self._storage_target
            if hasattr(self, "storage_drawing"):
                self.storage_drawing.queue_draw()
            return

        self._storage_anim_value = 0.0
        self._storage_anim_source = GLib.timeout_add(
            16,
            self._storage_animation_tick,
        )

    def _animations_enabled(self):
        result = subprocess.run(
            [
                "gsettings",
                "get",
                "org.gnome.desktop.interface",
                "enable-animations",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.returncode != 0 or result.stdout.strip() != "false"

    def _storage_animation_tick(self):
        distance = self._storage_target - self._storage_anim_value

        if abs(distance) < 0.005:
            self._storage_anim_value = self._storage_target

            if hasattr(self, "storage_drawing"):
                self.storage_drawing.queue_draw()

            self._storage_anim_source = None
            return GLib.SOURCE_REMOVE

        self._storage_anim_value += distance * 0.14

        if hasattr(self, "storage_drawing"):
            self.storage_drawing.queue_draw()

        return GLib.SOURCE_CONTINUE

    def _draw_storage_ring(self, _area, cr, width, height):
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) * 0.32
        line_width = 9

        cr.set_line_width(line_width)
        cr.set_line_cap(1)

        cr.set_source_rgba(0.17, 0.23, 0.33, 0.72)
        cr.arc(center_x, center_y, radius, 0, math.tau)
        cr.stroke()

        cr.set_source_rgba(0.42, 0.66, 1.0, 0.95)
        cr.arc(
            center_x,
            center_y,
            radius,
            -math.pi / 2,
            -math.pi / 2 + math.tau * self._storage_anim_value,
        )
        cr.stroke()

    # ------------------------------------------------------------------
    # Pins / bookmarks
    # ------------------------------------------------------------------

    def _load_list(self, path):
        if not path.exists():
            return []

        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _save_list(self, path, items):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(items, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _current_uri(self):
        return self.current.get_uri()

    def _is_current_pinned(self):
        uri = self._current_uri()
        return any(item.get("uri") == uri for item in self._load_list(PINNED_REGISTRY))

    def _update_pin_button(self):
        self.pin_btn.set_active(self._is_current_pinned())

    def _toggle_pin_current(self, *_):
        uri = self._current_uri()
        pins = self._load_list(PINNED_REGISTRY)
        existing = next((item for item in pins if item.get("uri") == uri), None)

        if existing:
            pins = [item for item in pins if item.get("uri") != uri]
        else:
            name = self.current.get_basename()
            if not name or name == "/":
                name = self._raw_path(self.current)

            pins.append(
                {
                    "name": name,
                    "uri": uri,
                }
            )

        self._save_list(PINNED_REGISTRY, pins)
        self._reload_pinned_sidebar()
        self._update_pin_button()
        self._show_location_preview()

    def _reload_pinned_sidebar(self):
        if not hasattr(self, "pinned_box"):
            return

        self._clear_box(self.pinned_box)
        pins = self._load_list(PINNED_REGISTRY)

        if not pins:
            empty = Gtk.Label(label="No pinned folders", xalign=0)
            empty.add_css_class("side-empty")
            empty.set_margin_start(8)
            self.pinned_box.append(empty)
            return

        for item in pins:
            uri = item.get("uri")
            name = item.get("name") or "Pinned"

            if not uri:
                continue

            if uri.startswith("smb://"):
                callback = lambda u=uri: self._connect_remote_uri(u, save=False)
                icon = "network.svg"
            else:
                target = Gio.File.new_for_uri(uri)
                callback = lambda t=target: self.navigate(t)
                icon = "pin.svg"

            self._side_item(self.pinned_box, name, icon, callback)

    # ------------------------------------------------------------------
    # Samba / remote locations
    # ------------------------------------------------------------------

    def _reload_remote_sidebar(self):
        if not hasattr(self, "remote_box"):
            return

        self._clear_box(self.remote_box)

        for item in self._load_list(REMOTE_REGISTRY):
            uri = item.get("uri")
            name = item.get("name")

            if not uri:
                continue

            self._side_item(
                self.remote_box,
                name or self._remote_label(uri),
                "server.svg",
                lambda u=uri: self._connect_remote_uri(u, save=False),
            )

    def _show_connect_dialog(self):
        dialog = Gtk.Dialog(
            title="Connect to Server",
            transient_for=self,
            modal=True,
        )

        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Connect", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_spacing(10)

        title = Gtk.Label(label="Remote Location", xalign=0)
        title.add_css_class("dialog-title")
        content.append(title)

        help_text = Gtk.Label(
            label="Enter a Samba address such as smb://server/share",
            xalign=0,
        )
        help_text.set_wrap(True)
        help_text.add_css_class("dialog-help")
        content.append(help_text)

        entry = Gtk.Entry()
        entry.set_text("smb://")
        entry.set_activates_default(True)
        entry.set_hexpand(True)
        content.append(entry)

        def response(dlg, response_id):
            if response_id == Gtk.ResponseType.OK:
                uri = entry.get_text().strip()
                dlg.destroy()
                self._connect_remote_uri(uri, save=True)
                return

            dlg.destroy()

        dialog.connect("response", response)
        dialog.present()
        entry.grab_focus()
        entry.set_position(-1)

    def _connect_remote_uri(self, uri, save=True):
        uri = uri.strip()

        if not uri:
            return

        if "://" not in uri:
            uri = f"smb://{uri}"

        parsed = urllib.parse.urlparse(uri)

        if parsed.scheme.casefold() != "smb":
            self._message(
                "Unsupported remote",
                "This milestone currently enables Samba locations using smb://server/share.",
            )
            return

        target = Gio.File.new_for_uri(uri)

        try:
            # Gtk.MountOperation provides the authentication/question UI
            # needed by GIO remote mounts.
            self._mount_operation = Gtk.MountOperation.new(self)

            target.mount_enclosing_volume(
                Gio.MountMountFlags.NONE,
                self._mount_operation,
                None,
                self._remote_mount_done,
                (target, uri, save),
            )

            self._show_remote_connecting(uri)

        except GLib.Error as error:
            self._message("Connection failed", error.message)
        except Exception as error:
            self._message("Connection failed", str(error))

    def _remote_mount_done(self, source, result, payload):
        target, uri, save = payload

        try:
            source.mount_enclosing_volume_finish(result)
        except GLib.Error as error:
            # Backends may report "already mounted"; in that case an
            # enumeration attempt is still useful and will decide whether
            # the remote is accessible.
            if "already mounted" not in error.message.casefold():
                self._message("Connection failed", error.message)
                return

        self._mount_operation = None

        if save:
            remotes = self._load_list(REMOTE_REGISTRY)

            if not any(item.get("uri") == uri for item in remotes):
                remotes.append(
                    {
                        "name": self._remote_label(uri),
                        "uri": uri,
                    }
                )
                self._save_list(REMOTE_REGISTRY, remotes)

            self._reload_remote_sidebar()

        self.navigate(target)

    def _show_remote_connecting(self, uri):
        self._clear_box(self.preview_content)
        self._clear_box(self.preview_actions)

        self._replace_header_icon("network.svg")
        self.preview_title.set_text("Connecting")
        self.preview_subtitle.set_text(uri)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("remote-connect-card")

        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_halign(Gtk.Align.CENTER)
        card.append(spinner)

        label = Gtk.Label(label="Opening Samba location…", xalign=0.5)
        label.add_css_class("preview-large-caption")
        card.append(label)

        self.preview_content.append(card)

    def _remote_label(self, uri):
        try:
            parsed = urllib.parse.urlparse(uri)
            pieces = [piece for piece in parsed.path.split("/") if piece]

            if pieces:
                return f"{parsed.hostname or 'Server'} / {pieces[0]}"

            return parsed.hostname or uri
        except Exception:
            return uri

    # ------------------------------------------------------------------
    # Previews / actions
    # ------------------------------------------------------------------

    def _folder_children(self, file_obj, limit=12):
        children = []

        try:
            enum = file_obj.enumerate_children(
                "standard::name,standard::display-name,standard::type,standard::size,standard::is-hidden",
                Gio.FileQueryInfoFlags.NONE,
                None,
            )

            while len(children) < limit:
                info = enum.next_file(None)
                if info is None:
                    break

                if info.get_is_hidden() and not self.show_hidden:
                    continue

                children.append(
                    (
                        info.get_display_name() or info.get_name() or "Unknown",
                        info.get_file_type() == Gio.FileType.DIRECTORY,
                        info.get_size(),
                    )
                )

            enum.close(None)

        except Exception:
            pass

        children.sort(key=lambda row: (not row[1], row[0].casefold()))
        return children

    def _pdf_preview(self, path):
        if shutil.which("pdftoppm") is None:
            return None

        try:
            signature = f"{path}:{path.stat().st_mtime_ns}".encode()
            digest = hashlib.sha1(signature).hexdigest()[:20]
            output_base = PREVIEW_CACHE / f"pdf-{digest}"
            output_png = output_base.with_suffix(".png")

            if output_png.exists():
                return output_png

            subprocess.run(
                [
                    "pdftoppm",
                    "-f", "1",
                    "-singlefile",
                    "-scale-to", "700",
                    "-png",
                    str(path),
                    str(output_base),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=12,
                check=False,
            )

            return output_png if output_png.exists() else None

        except Exception:
            return None

    def _folder_count_text(self, item):
        try:
            enum = item.file.enumerate_children(
                "standard::name,standard::is-hidden",
                Gio.FileQueryInfoFlags.NONE,
                None,
            )

            count = 0

            while True:
                info = enum.next_file(None)
                if info is None:
                    break

                if info.get_is_hidden() and not self.show_hidden:
                    continue

                count += 1

            enum.close(None)
            return f"{count} items"

        except Exception:
            return "Folder"

    def _action_open(self, *_):
        if not self.selected:
            return

        if self.selected.is_dir:
            self.navigate(self.selected.file)
        else:
            self._open_file(self.selected)

    def _action_copy(self, *_):
        if not self.selected:
            return

        self.get_display().get_clipboard().set(file_display(self.selected.file))
        self._message("Copied", "Path copied to clipboard.")

    def _action_copy_paths(self, *_):
        if not self.selected_items:
            return

        paths = [
            file_display(item.file)
            for item in self.selected_items.values()
        ]
        self.get_display().get_clipboard().set("\n".join(paths))
        self._message("Copied", f"{len(paths)} paths copied to clipboard.")

    def _action_trash(self, *_):
        if not self.selected:
            return

        name = self.selected.name

        try:
            self.selected.file.trash(None)
            self.selected = None
            self.selected_button = None
            self.selected_items = {}
            self.selected_buttons = {}
            self.populate()
            self._message("Moved to Trash", name)

        except GLib.Error as error:
            self._message("Trash failed", error.message)

    def _action_trash_selection(self, *_):
        if not self.selected_items:
            return

        count = 0
        failures = []

        for item in list(self.selected_items.values()):
            try:
                item.file.trash(None)
                count += 1
            except GLib.Error as error:
                failures.append(f"{item.name}: {error.message}")

        self.selected = None
        self.selected_button = None
        self.selected_items = {}
        self.selected_buttons = {}
        self.populate()

        if failures:
            self._message("Some items were not moved", "\n".join(failures[:4]))
        else:
            self._message("Moved to Trash", f"{count} items")

    def _action_rename(self, *_):
        if not self.selected:
            return

        dialog = Gtk.Dialog(title="Rename", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Rename", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        entry = Gtk.Entry(text=self.selected.name)
        entry.set_activates_default(True)
        content.append(entry)
        dialog.set_default_response(Gtk.ResponseType.OK)

        def done(dlg, response):
            if response == Gtk.ResponseType.OK:
                new_name = entry.get_text().strip()

                if new_name and new_name != self.selected.name:
                    try:
                        self.selected.file.set_display_name(new_name, None)
                        self.selected = None
                        self.selected_button = None
                        self.selected_items = {}
                        self.selected_buttons = {}
                        self.populate()

                    except GLib.Error as error:
                        self._message("Rename failed", error.message)

            dlg.destroy()

        dialog.connect("response", done)
        dialog.present()

    def _action_compress(self, *_):
        if not self.selected:
            return

        local_path = self.selected.file.get_path()

        if not local_path:
            self._message(
                "Compress",
                "Compression currently supports local filesystem items only.",
            )
            return

        path = Path(local_path)
        archive = path.parent / f"{path.name}.zip"

        try:
            if path.is_dir():
                shutil.make_archive(
                    str(path.parent / path.name),
                    "zip",
                    root_dir=str(path.parent),
                    base_dir=path.name,
                )
            else:
                with zipfile.ZipFile(
                    archive,
                    "w",
                    zipfile.ZIP_DEFLATED,
                ) as zf:
                    zf.write(path, arcname=path.name)

            self.populate()
            self._message("Archive created", str(archive))

        except Exception as error:
            self._message("Compress failed", str(error))

    def _action_copy_to_split(self, *_):
        self._start_transfer(move=False)

    def _action_move_to_split(self, *_):
        self._start_transfer(move=True)

    def _selected_for_transfer(self):
        if self.selected_items:
            return list(self.selected_items.values())
        if self.selected:
            return [self.selected]
        return []

    def _start_transfer(self, move=False):
        if not self.split_enabled:
            self._message("Split view", "Open split view to choose a destination pane.")
            return

        items = self._selected_for_transfer()
        if not items:
            self._message("Transfer", "Select files or folders first.")
            return

        destination_root = self.secondary_current.get_path()
        if not destination_root:
            self._message(
                "Transfer unavailable",
                "Copy and move currently support local filesystem destinations.",
            )
            return

        local_items = []
        for item in items:
            path = item.file.get_path()
            if not path:
                self._message(
                    "Transfer unavailable",
                    "Remote-to-local transfers are not enabled in this build.",
                )
                return
            local_items.append((item, Path(path)))

        destination = Path(destination_root)
        conflicts = [
            path.name
            for _item, path in local_items
            if (destination / path.name).exists()
        ]

        if conflicts:
            self._show_conflict_dialog(
                conflicts,
                lambda policy: self._perform_transfer(local_items, destination, move, policy),
            )
            return

        self._perform_transfer(local_items, destination, move, "replace")

    def _show_conflict_dialog(self, conflicts, callback):
        dialog = Gtk.Dialog(
            title="Name Conflict",
            transient_for=self,
            modal=True,
        )
        dialog.add_button("Skip", 1)
        dialog.add_button("Keep Both", 2)
        dialog.add_button("Replace", 3)
        dialog.set_default_response(2)

        content = dialog.get_content_area()
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)
        content.set_spacing(8)

        title = Gtk.Label(label="Some names already exist", xalign=0)
        title.add_css_class("dialog-title")
        content.append(title)

        preview = ", ".join(conflicts[:4])
        if len(conflicts) > 4:
            preview = f"{preview}, and {len(conflicts) - 4} more"

        detail = Gtk.Label(
            label=f"Choose how to handle: {preview}",
            xalign=0,
        )
        detail.set_wrap(True)
        detail.add_css_class("dialog-help")
        content.append(detail)

        def response(dlg, response_id):
            dlg.destroy()
            policy = {
                1: "skip",
                2: "keep",
                3: "replace",
            }.get(response_id, "skip")
            callback(policy)

        dialog.connect("response", response)
        dialog.present()

    def _perform_transfer(self, local_items, destination, move, conflict_policy):
        action = "Moved" if move else "Copied"
        count = 0
        failures = []

        for item, source in local_items:
            try:
                target = destination / source.name

                same_target = False
                try:
                    same_target = source.resolve() == target.resolve()
                except Exception:
                    same_target = source == target

                if same_target and move:
                    continue

                if same_target:
                    target = self._unique_destination(target)
                elif target.exists():
                    if conflict_policy == "skip":
                        continue
                    if conflict_policy == "keep":
                        target = self._unique_destination(target)
                    elif conflict_policy == "replace":
                        self._remove_existing_target(target)

                if move:
                    shutil.move(str(source), str(target))
                elif source.is_dir():
                    shutil.copytree(str(source), str(target))
                else:
                    shutil.copy2(str(source), str(target))

                count += 1
                self.transfer_log.insert(
                    0,
                    {
                        "action": action,
                        "name": item.name,
                        "destination": str(destination),
                        "time": datetime.now().strftime("%I:%M %p"),
                    },
                )

            except Exception as error:
                failures.append(f"{item.name}: {error}")

        self.transfer_log = self.transfer_log[:12]
        self.selected = None
        self.selected_button = None
        self.selected_items = {}
        self.selected_buttons = {}
        self.populate()
        self.populate_secondary()

        if failures:
            self._message("Transfer incomplete", "\n".join(failures[:4]))
        else:
            self._message(action, f"{count} item{'s' if count != 1 else ''} to {destination}")

    def _unique_destination(self, target):
        if not target.exists():
            return target

        stem = target.stem
        suffix = target.suffix
        parent = target.parent

        for index in range(1, 1000):
            candidate = parent / f"{stem} copy {index}{suffix}"
            if not candidate.exists():
                return candidate

        raise RuntimeError(f"Unable to choose a unique name for {target.name}")

    def _remove_existing_target(self, target):
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    def _show_transfer_center(self, *_):
        self._clear_box(self.preview_content)
        self._clear_box(self.preview_actions)

        self._replace_header_icon("copy.svg")
        self.preview_title.set_text("Transfer Center")
        self.preview_subtitle.set_text("Recent local copy and move actions")

        if not self.transfer_log:
            self.preview_content.append(
                Gtk.Label(label="No transfers yet", xalign=0)
            )
            return

        self.preview_content.append(self._section_label("RECENT TRANSFERS"))
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        list_box.add_css_class("folder-preview-list")

        for entry in self.transfer_log:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            row.add_css_class("folder-preview-row")

            label = Gtk.Label(
                label=f"{entry['action']} {entry['name']}",
                xalign=0,
            )
            label.set_ellipsize(3)
            label.add_css_class("folder-preview-name")

            detail = Gtk.Label(
                label=f"{entry['time']} · {entry['destination']}",
                xalign=0,
            )
            detail.set_ellipsize(3)
            detail.add_css_class("folder-preview-size")

            row.append(label)
            row.append(detail)
            list_box.append(row)

        self.preview_content.append(list_box)

    # ------------------------------------------------------------------
    # Config / misc
    # ------------------------------------------------------------------

    def _load_list(self, path):
        if not path.exists():
            return []

        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _save_list(self, path, items):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(items, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _projects(self):
        if not PROJECT_REGISTRY.exists():
            return []

        try:
            data = json.loads(PROJECT_REGISTRY.read_text())

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                projects = data.get("projects")
                if isinstance(projects, list):
                    return projects
                elif isinstance(projects, dict):
                    return list(projects.values())

        except Exception:
            pass

        return []

    def _raw_path(self, file_obj):
        path = file_obj.get_path()
        return path if path else file_display(file_obj)

    def _toggle_maximize(self):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def _message(self, title, body):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            buttons=Gtk.ButtonsType.OK,
            text=title,
            secondary_text=body,
        )
        dialog.connect("response", lambda dlg, *_: dlg.destroy())
        dialog.present()

    def _on_close_request(self, *_):
        if self._responsive_source:
            GLib.source_remove(self._responsive_source)
            self._responsive_source = None

        if self._storage_anim_source:
            GLib.source_remove(self._storage_anim_source)
            self._storage_anim_source = None

        return False


class AdaptiveFilesApp(Gtk.Application):
    def __init__(self, target=None):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.target = target

    def do_activate(self):
        if not self.props.active_window:
            AdaptiveFilesWindow(self, self.target).present()
        else:
            self.props.active_window.present()

    def do_open(self, files, _n_files, _hint):
        for file_obj in files:
            target = file_obj
            path = file_obj.get_path()

            if path and Path(path).is_file():
                target = file_obj.get_parent()

            AdaptiveFilesWindow(self, target).present()


def parse_target():
    if len(sys.argv) < 2:
        return None

    return Gio.File.new_for_commandline_arg(sys.argv[1])


def main():
    app = AdaptiveFilesApp(parse_target())
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
