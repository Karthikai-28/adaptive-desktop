"""Adaptive Files inspector - the small building blocks every section is made of.

Methods of the one PreviewController (adaptive_preview.py), kept in their own
file by subject. The class below is a mixin: PreviewController inherits from
it, so `self` here is the controller and everything on it is reachable.
"""

from __future__ import annotations

from .common import (
    _css, Gio, Gtk, Pango, SegmentBar, Swatch,
)


class WidgetsMixin:
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
        for index, (color, label, value, portion) in enumerate(rows):
            grid.attach(Swatch(color), 0, index, 1, 1)
            name = Gtk.Label(label=label, xalign=0)
            name.set_hexpand(True)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            _css(name, "adaptive-legend-label")
            grid.attach(name, 1, index, 1, 1)
            size = Gtk.Label(label=value, xalign=1)
            _css(size, "adaptive-legend-value")
            grid.attach(size, 2, index, 1, 1)
            extra = Gtk.Label(label=portion, xalign=1)
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
