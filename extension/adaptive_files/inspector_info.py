"""Adaptive Files inspector - the information list (metadata, git, checksum, tags, share, project) and the actions under it.

Methods of the one PreviewController (adaptive_preview.py), kept in their own
file by subject. The class below is a mixin: PreviewController inherits from
it, so `self` here is the controller and everything on it is reachable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from .common import (
    cleanup, _count_text, _css, _EXECUTOR, filetags, _format_timestamp, Gdk,
    GdkPixbuf, Gio, gitinfo, GLib, Gtk, _human_size, _log, _log_exception,
    _mode_text, _notify, Pango, _refresh_file_badges, _relative_time, _rgb,
    _run_async, share, _short_path, TagDot,
)


class InfoMixin:
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

    def _share_popover(self, button, paths):
        """LocalSend and Slack as two large buttons on top - the everyday
        pair - then every other way to send, one row each."""
        paths = [p for p in paths if p]
        if not paths:
            return
        targets = share.available()
        popover = Gtk.Popover.new(button)
        popover.set_position(Gtk.PositionType.TOP)
        _css(popover, "adaptive-share")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        def icon_for(target, size):
            source = share.ICONS[target]
            if source.startswith("/") and os.path.exists(source):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(source, size, size)
                return Gtk.Image.new_from_pixbuf(pixbuf)
            image = Gtk.Image.new_from_icon_name(
                source if not source.startswith("/") else "emblem-shared-symbolic", Gtk.IconSize.BUTTON)
            image.set_pixel_size(size if size <= 20 else 24)
            return image

        def choose(_widget, target):
            popover.popdown()
            self._share(target, paths)

        top = [t for t in ("localsend", "slack") if t in targets]
        if top:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.set_homogeneous(True)
            for target in top:
                tile = Gtk.Button()
                _css(tile, "adaptive-share-tile")
                inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                inner.pack_start(icon_for(target, 32), False, False, 0)
                text = Gtk.Label(label=share.label(target))
                inner.pack_start(text, False, False, 0)
                tile.add(inner)
                tile.connect("clicked", choose, target)
                row.pack_start(tile, True, True, 0)
            box.pack_start(row, False, False, 0)

        for target in targets:
            if target in top:
                continue
            item = Gtk.Button()
            item.set_relief(Gtk.ReliefStyle.NONE)
            _css(item, "adaptive-share-row")
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            line.pack_start(icon_for(target, 16), False, False, 0)
            text = Gtk.Label(label=share.label(target), xalign=0)
            line.pack_start(text, True, True, 0)
            item.add(line)
            item.connect("clicked", choose, target)
            box.pack_start(item, False, False, 0)

        popover.add(box)
        box.show_all()
        popover.popup()

    def _share(self, target, paths):
        try:
            share.run(target, paths, _notify)
        except Exception as error:
            _log_exception(f"Share via {target} failed")
            self._show_error("Couldn't share", str(error))

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
