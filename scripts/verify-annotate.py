#!/usr/bin/env python3
"""Open the real Annotate window on a virtual display and draw on a picture.

The drawing model (apps/adaptive-annotate/shapes.py) is checked as functions
by verify-feature-logic.py. This drives the window itself: tools, colours,
drags, undo, copy and save, and reads the saved PNG back.

    scripts/verify-annotate.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import sandbox_display  # noqa: E402


def inner(sandbox, check):
    import cairo
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    sys.path.insert(0, str(REPO / "apps/adaptive-annotate"))
    import main as annotate

    # A plain grey 400x300 "screenshot".
    source = sandbox / "shot.png"
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 300)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.5, 0.5, 0.5)
    ctx.paint()
    surface.write_to_png(str(source))

    annotate.SAVE_DIR = sandbox / "saved"
    app = Gtk.Application(application_id="com.karthi.AdaptiveAnnotateCheck")
    state = {}

    def pump(ms=300):
        loop = GLib.MainLoop()
        GLib.timeout_add(ms, loop.quit)
        loop.run()

    def pixel(path, x, y):
        image = cairo.ImageSurface.create_from_png(str(path))
        data = image.get_data()
        offset = y * image.get_stride() + x * 4
        blue, green, red = data[offset], data[offset + 1], data[offset + 2]
        return red, green, blue

    def drag(window, start, end):
        """A drag in image coordinates, through the window's own handlers."""
        scale, ox, oy = window.view
        sx, sy = start[0] * scale + ox, start[1] * scale + oy
        dx, dy = (end[0] - start[0]) * scale, (end[1] - start[1]) * scale
        window._drag_begin(None, sx, sy)
        window._drag_update(None, dx / 2, dy / 2)
        window._drag_end(None, dx, dy)

    def checks():
        window = state["window"]
        pump(500)
        check(window.is_visible() and window.image.get_width() == 400, "the window opens on the picture")

        window.tool_buttons["rect"].set_active(True)
        check(window.tool == "rect", "choosing a tool switches to it")
        window.color_buttons[2].set_active(True)  # blue
        drag(window, (50, 50), (150, 120))
        check(len(window.shapes) == 1 and window.shapes[0]["tool"] == "rect", "a drag draws a box")

        drag(window, (200, 200), (201, 201))
        check(len(window.shapes) == 1, "a slip of the hand draws nothing")

        window.tool_buttons["redact"].set_active(True)
        drag(window, (300, 20), (380, 60))
        window.tool_buttons["text"].set_active(True)
        check(window.text_entry.get_visible(), "the text tool shows its field")
        drag(window, (20, 250), (20, 250))
        check(len(window.shapes) == 2, "text with nothing typed is not placed")
        window.text_entry.set_text("Look here")
        drag(window, (20, 250), (20, 250))
        check(len(window.shapes) == 3 and window.shapes[2]["text"] == "Look here", "typed text is placed where clicked")

        saved = window.save()
        check(saved.exists() and saved.parent == sandbox / "saved", "save writes into the screenshots folder")
        check(pixel(saved, 50, 85) == (10, 133, 255), f"the box is in the saved picture, in blue {pixel(saved, 50, 85)}")
        check(pixel(saved, 340, 40) == (0, 0, 0), "the redaction is solid black in the saved picture")
        check(pixel(saved, 250, 150) == (128, 128, 128), "the rest of the picture is untouched")

        window.undo()
        window.undo()
        check(len(window.shapes) == 1, "undo removes the last shape")
        window.copy()
        pump(300)
        formats = Gdk.Display.get_default().get_clipboard().get_formats().to_string()
        check("GdkTexture" in formats or "image/png" in formats, "copy puts the picture on the clipboard")

        window.close()
        app.quit()
        return GLib.SOURCE_REMOVE

    def guarded():
        try:
            return checks()
        except Exception as error:  # noqa: BLE001
            import traceback
            check(False, f"raised {error!r}: {traceback.format_exc(limit=3)}")
            app.quit()
            return GLib.SOURCE_REMOVE

    def on_activate(_app):
        state["window"] = annotate.Annotator(app, str(source), temporary=False)
        state["window"].present()
        GLib.timeout_add(400, guarded)

    app.connect("activate", on_activate)
    GLib.timeout_add_seconds(60, app.quit)
    app.run([])


if __name__ == "__main__":
    sys.exit(sandbox_display.run(__file__, inner, "Annotate window"))
