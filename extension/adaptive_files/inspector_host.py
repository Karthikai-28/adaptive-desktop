"""Adaptive Files inspector - the panel itself: showing and hiding it, the toolbar buttons, the terminal drawer, and attaching it inside the Files window.

Methods of the one PreviewController (adaptive_preview.py), kept in their own
file by subject. The class below is a mixin: PreviewController inherits from
it, so `self` here is the controller and everything on it is reachable.
"""

from __future__ import annotations

import os
import shlex

from .common import (
    _ancestors, _css, Gdk, Gio, GLib, Gtk, _log, _log_exception, Pango, Path,
    _type_name, Vte, _walk,
)


class HostMixin:
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
