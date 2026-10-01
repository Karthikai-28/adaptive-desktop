"""Adaptive Files inspector - a single file: models, video and audio, PDF pages, archives, photos and source.

Methods of the one PreviewController (adaptive_preview.py), kept in their own
file by subject. The class below is a mixin: PreviewController inherits from
it, so `self` here is the controller and everything on it is reachable.
"""

from __future__ import annotations

import hashlib
import io
import os

from .common import (
    ACCENT, _add_scheme_path, archives, CACHE_DIR, _count_text, _css, _EXECUTOR,
    _file_identity, GdkPixbuf, Gio, GLib, Gst, Gtk, GtkSource, HAS_GTKSOURCE,
    HAVE_PLAYER, _human_size, IMAGE_MIME_PREFIX, _log, _log_exception, media,
    models, Pango, Path, PDF_MIME, RoundedPicture, _run_async, SERIES_COLORS,
    TEXT_EXTENSIONS, _theme_icon_for_identity,
)


class FileMixin:
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
                ("emblem-shared-symbolic", "Share", lambda button: self._share_popover(button, [local_path]) if local_path else self._copy_text(uri)),
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
