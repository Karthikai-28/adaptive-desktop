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

import os
import sys

# Helper modules live in a package beside this file: nautilus-python loads
# every top-level .py in its extensions folder as an extension of its own.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# common requires the GObject library versions; it comes first.
import time

from adaptive_files.common import (  # noqa: E402
    AUTO_HIDE_BELOW, _BACKGROUND, _CONTROLLERS, _css, filetags, Gdk, Gio,
    GIT_STALE_SECONDS, gitinfo, GLib, GnomeDesktop, GObject, Gtk, _log,
    _log_exception, models, Nautilus, PANEL_MEDIUM, PANEL_NARROW, PANEL_WIDE, Path,
    _refresh_file_badges, _remember_file, _run_async, share, _snapshot_file,
    _type_name,
)
from adaptive_files.inspector_host import HostMixin  # noqa: E402
from adaptive_files.inspector_folder import FolderMixin  # noqa: E402
from adaptive_files.inspector_file import FileMixin  # noqa: E402
from adaptive_files.inspector_info import InfoMixin  # noqa: E402
from adaptive_files.inspector_widgets import WidgetsMixin  # noqa: E402

# Nautilus instantiates this extension once per provider interface it
# implements, so every instance is asked to contribute context-menu items and
# the same entry appeared three times. One instance owns the menu.
_MENU_OWNER = None
_INFO_OWNER = None


# The controller's methods are kept by subject in adaptive_files/inspector_*.py;
# what is here is its life cycle and how a selection becomes a preview.
class PreviewController(HostMixin, FolderMixin, FileMixin, InfoMixin, WidgetsMixin):
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
                    return [self._share_menu(controller, local), self._tags_menu(controller, local)]

        except Exception:
            _log_exception("get_file_items failed")

        return []

    def _share_menu(self, controller, files):
        """Share ▸ LocalSend and Slack first, then the other ways out."""
        paths = [info.get_location().get_path() for info in files]
        top = Nautilus.MenuItem(name="AdaptiveShare::menu", label="Share", tip="Send these files")
        submenu = Nautilus.Menu()
        top.set_submenu(submenu)

        def send(_item, target):
            controller._share(target, paths)

        for target in share.available():
            item = Nautilus.MenuItem(name=f"AdaptiveShare::{target}", label=share.label(target))
            item.connect("activate", send, target)
            submenu.append_item(item)
        return top

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
