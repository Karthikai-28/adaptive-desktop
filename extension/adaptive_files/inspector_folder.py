"""Adaptive Files inspector - the folder summary and a selection of several items.

Methods of the one PreviewController (adaptive_preview.py), kept in their own
file by subject. The class below is a mixin: PreviewController inherits from
it, so `self` here is the controller and everything on it is reachable.
"""

from __future__ import annotations

import os
import shutil
import time

from .common import (
    ACCENT, ActivityChart, _capacity_color, CAPACITY_CRIT, CAPACITY_WARN, cleanup,
    _count_text, _css, Gio, gitinfo, GLib, Gtk, _human_size, KIND_COLORS, KINDS,
    Pango, _relative_time, _reveal, _scan_folder, SCAN_MAX_ENTRIES, _scan_paths,
    SegmentBar, SERIES_COLORS, _short_path,
)


class FolderMixin:
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
                ("emblem-shared-symbolic", "Share", lambda button: self._share_popover(button, [path])),
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
                ("emblem-shared-symbolic", "Share", lambda button: self._share_popover(button, paths)),
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
