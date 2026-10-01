#!/usr/bin/env python3
"""Adaptive Annotate - mark up a screenshot, then copy or save it.

    adaptive-annotate              select an area of the screen, then annotate it
    adaptive-annotate FILE.png     annotate an image you already have

Tools: Arrow (A), Box (R), Pen (P), Highlight (H), Redact (X), Text (T).
1-4 choose the colour. Ctrl+Z undoes, Ctrl+C copies the result, Ctrl+S saves
it to ~/Pictures/Screenshots, Esc closes.

Screen recording is GNOME's own (the screenshot shortcut, then the camera
toggle); this adds the one thing that screen lacks, drawing on the result.
The drawing itself is shapes.py, which has no GTK in it.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shapes as S  # noqa: E402

APP_ID = "com.karthi.AdaptiveAnnotate"
SAVE_DIR = Path.home() / "Pictures" / "Screenshots"

CSS = b"""
window.annotate { background-color: #1C1C1E; color: #F5F5F7; font-family: Inter, sans-serif; }
.an-bar { padding: 8px 10px; background-color: #2C2C2E; border-bottom: 1px solid #48484A; }
.an-bar button { min-height: 30px; padding: 0 10px; border-radius: 8px; background: none;
                 border: none; box-shadow: none; color: #F5F5F7; }
.an-bar button:hover { background-color: #3A3A3C; }
.an-bar button:checked { background-color: #0A84FF; color: white; }
.an-swatch { min-width: 22px; min-height: 22px; padding: 0; border-radius: 11px; }
.an-status { font-size: 12px; color: #98989D; }
.an-entry { min-height: 30px; border-radius: 8px; background-color: #141416; color: #F5F5F7; }
"""

TOOL_LABELS = (
    ("arrow", "Arrow", "a"), ("rect", "Box", "r"), ("pen", "Pen", "p"),
    ("highlight", "Highlight", "h"), ("redact", "Redact", "x"), ("text", "Text", "t"),
)


def capture_area():
    """Let the user drag an area; the PNG's path, or None if they cancelled."""
    if not shutil.which("gnome-screenshot"):
        return None
    handle, path = tempfile.mkstemp(prefix="adaptive-annotate-", suffix=".png")
    os.close(handle)
    subprocess.run(["gnome-screenshot", "--area", f"--file={path}"], check=False)
    if os.path.getsize(path) == 0:
        os.unlink(path)
        return None
    return path


def save_path(now=None, directory=None):
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(now))
    return (directory or SAVE_DIR) / f"Annotated {stamp}.png"


class Annotator(Gtk.ApplicationWindow):
    def __init__(self, app, image_path, temporary):
        super().__init__(application=app, title="Annotate")
        self.add_css_class("annotate")
        self.image = cairo.ImageSurface.create_from_png(image_path)
        self.temporary = image_path if temporary else None
        self.shapes = []
        self.current = None
        self.tool = "arrow"
        self.color = S.COLORS[S.DEFAULT_COLOR]
        self.view = (1.0, 0.0, 0.0)

        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        width, height = self.image.get_width(), self.image.get_height()
        self.set_default_size(min(max(width + 40, 720), 1500), min(max(height + 110, 420), 950))

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)
        root.append(self._toolbar())

        self.canvas = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.canvas.set_draw_func(self._draw)
        self.canvas.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        root.append(self.canvas)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.canvas.add_controller(drag)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", self._on_close)

    # ----------------------------------------------------------- toolbar

    def _toolbar(self):
        bar = Gtk.Box(spacing=4)
        bar.add_css_class("an-bar")
        self.tool_buttons = {}
        first = None
        for tool, label, key in TOOL_LABELS:
            button = Gtk.ToggleButton(label=label, tooltip_text=f"{label} ({key.upper()})")
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.connect("toggled", lambda b, t=tool: b.get_active() and self._set_tool(t))
            self.tool_buttons[tool] = button
            bar.append(button)
        first.set_active(True)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6))
        self.color_buttons = []
        group = None
        for index, (name, rgb) in enumerate(S.COLORS.items(), 1):
            swatch = Gtk.ToggleButton(tooltip_text=f"{name.capitalize()} ({index})")
            swatch.add_css_class("an-swatch")
            dot = Gtk.DrawingArea(content_width=14, content_height=14)
            dot.set_draw_func(lambda _a, ctx, w, h, c=rgb: (
                ctx.set_source_rgb(*c), ctx.arc(w / 2, h / 2, min(w, h) / 2, 0, 6.2832), ctx.fill()))
            swatch.set_child(dot)
            if group is None:
                group = swatch
            else:
                swatch.set_group(group)
            swatch.connect("toggled", lambda b, c=rgb: b.get_active() and self._set_color(c))
            self.color_buttons.append(swatch)
            bar.append(swatch)
        group.set_active(True)

        self.text_entry = Gtk.Entry(placeholder_text="Text, then click where it goes", visible=False,
                                    width_chars=26)
        self.text_entry.add_css_class("an-entry")
        bar.append(self.text_entry)

        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        self.status = Gtk.Label(label="")
        self.status.add_css_class("an-status")
        bar.append(self.status)
        for label, tip, handler in (("Undo", "Ctrl+Z", self.undo), ("Copy", "Ctrl+C", self.copy),
                                    ("Save", "Ctrl+S", self.save)):
            button = Gtk.Button(label=label, tooltip_text=tip)
            button.connect("clicked", lambda _b, h=handler: h())
            bar.append(button)
        return bar

    def _set_tool(self, tool):
        self.tool = tool
        self.text_entry.set_visible(tool == "text")
        if tool == "text":
            self.text_entry.grab_focus()

    def _set_color(self, color):
        self.color = color

    # ------------------------------------------------------------ drawing

    def _draw(self, _area, ctx, width, height):
        image_w, image_h = self.image.get_width(), self.image.get_height()
        self.view = S.fit(image_w, image_h, width, height)
        scale, x, y = self.view
        ctx.translate(x, y)
        ctx.scale(scale, scale)
        ctx.set_source_surface(self.image, 0, 0)
        ctx.paint()
        S.render(ctx, self.shapes + ([self.current] if self.current else []))

    def _point(self, x, y):
        scale, offset_x, offset_y = self.view
        return S.to_image((x, y), scale, offset_x, offset_y,
                          self.image.get_width(), self.image.get_height())

    def _drag_begin(self, _gesture, x, y):
        self.start = (x, y)
        if self.tool == "text":
            text = self.text_entry.get_text()
            shape = S.new_shape("text", self.color, self._point(x, y), text=text)
            if S.is_worth_keeping(shape):
                self.shapes.append(shape)
                self.text_entry.set_text("")
                self.canvas.queue_draw()
            else:
                self._say("Type the text first")
            return
        self.current = S.new_shape(self.tool, self.color, self._point(x, y))

    def _drag_update(self, _gesture, dx, dy):
        if self.current:
            S.extend(self.current, self._point(self.start[0] + dx, self.start[1] + dy))
            self.canvas.queue_draw()

    def _drag_end(self, _gesture, dx, dy):
        if self.current:
            S.extend(self.current, self._point(self.start[0] + dx, self.start[1] + dy))
            if S.is_worth_keeping(self.current):
                self.shapes.append(self.current)
            self.current = None
            self.canvas.queue_draw()

    # ------------------------------------------------------------ actions

    def _on_key(self, _controller, keyval, _keycode, state):
        control = state & Gdk.ModifierType.CONTROL_MASK
        name = (Gdk.keyval_name(keyval) or "").lower()
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if control and name == "z":
            self.undo()
            return True
        if control and name == "c":
            self.copy()
            return True
        if control and name == "s":
            self.save()
            return True
        # Letters and digits belong to the text field while it has focus.
        if self.text_entry.has_focus() or control:
            return False
        for tool, _label, key in TOOL_LABELS:
            if name == key:
                self.tool_buttons[tool].set_active(True)
                return True
        if name in ("1", "2", "3", "4"):
            self.color_buttons[int(name) - 1].set_active(True)
            return True
        return False

    def _say(self, text):
        self.status.set_text(text)
        GLib.timeout_add_seconds(3, lambda: self.status.set_text("") or GLib.SOURCE_REMOVE)

    def undo(self):
        if self.shapes:
            self.shapes.pop()
            self.canvas.queue_draw()

    def _png_bytes(self):
        surface = S.flatten(self.image, self.shapes)
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        try:
            surface.write_to_png(path)
            return Path(path).read_bytes()
        finally:
            os.unlink(path)

    def copy(self):
        # As PNG bytes: what every app that pastes pictures asks for, and what
        # the shell's clipboard history keeps.
        provider = Gdk.ContentProvider.new_for_bytes("image/png", GLib.Bytes.new(self._png_bytes()))
        Gdk.Display.get_default().get_clipboard().set_content(provider)
        self._say("Copied")

    def save(self):
        target = save_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self._png_bytes())
        self._say(f"Saved to {str(target).replace(str(Path.home()), '~')}")
        return target

    def _on_close(self, *_):
        if self.temporary:
            try:
                os.unlink(self.temporary)
            except OSError:
                pass
        return False


def main(argv):
    temporary = False
    if len(argv) > 1:
        image_path = argv[1]
        if not os.path.isfile(image_path):
            print(f"adaptive-annotate: no such image: {image_path}", file=sys.stderr)
            return 1
    else:
        image_path = capture_area()
        temporary = True
        if not image_path:
            return 0  # cancelled

    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", lambda a: Annotator(a, image_path, temporary).present())
    return app.run(None)


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    sys.exit(main(sys.argv))
