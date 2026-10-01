"""Adaptive Annotate - what is drawn over a screenshot, without GTK.

A drawing is a list of shapes in image coordinates. Each is a dict:

    {"tool": "arrow" | "rect" | "pen" | "highlight" | "redact" | "text",
     "color": (r, g, b), "width": px,
     "points": [(x, y), ...],        # start and end; every point for the pen
     "text": "..."}                  # text only

render() paints them onto any cairo context, so the window, the saved file
and scripts/verify-feature-logic.py all draw exactly the same thing.
"""

import math

TOOLS = ("arrow", "rect", "pen", "highlight", "redact", "text")

# The palette: one accent, and the three colours that read on any screenshot.
COLORS = {
    "red": (1.0, 0.27, 0.23),
    "yellow": (1.0, 0.84, 0.04),
    "blue": (0.04, 0.52, 1.0),
    "white": (1.0, 1.0, 1.0),
}
DEFAULT_COLOR = "red"
DEFAULT_WIDTH = 4
TEXT_SIZE = 22
# A drag shorter than this is a slip of the hand, not a shape.
MIN_DRAG = 4


def new_shape(tool, color, start, width=DEFAULT_WIDTH, text=""):
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    return {"tool": tool, "color": tuple(color), "width": width,
            "points": [tuple(start), tuple(start)], "text": text}


def extend(shape, point):
    """Follow the pointer: the pen grows a path, everything else moves its end."""
    if shape["tool"] == "pen":
        shape["points"].append(tuple(point))
    else:
        shape["points"][-1] = tuple(point)
    return shape


def is_worth_keeping(shape):
    """Whether a finished drag made anything. Text is kept if it says something."""
    if shape["tool"] == "text":
        return bool(shape["text"].strip())
    (x0, y0), (x1, y1) = shape["points"][0], shape["points"][-1]
    if shape["tool"] == "pen":
        return len(shape["points"]) > 2
    return math.hypot(x1 - x0, y1 - y0) >= MIN_DRAG


def bounds(shape):
    """(x, y, width, height) of a two-point shape, whichever way it was dragged."""
    (x0, y0), (x1, y1) = shape["points"][0], shape["points"][-1]
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


def _arrow(ctx, shape):
    (x0, y0), (x1, y1) = shape["points"][0], shape["points"][-1]
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return
    angle = math.atan2(y1 - y0, x1 - x0)
    head = min(max(shape["width"] * 4.5, 14), length * 0.6)
    # The shaft stops inside the head, so its square end never pokes through.
    ctx.move_to(x0, y0)
    ctx.line_to(x1 - math.cos(angle) * head * 0.7, y1 - math.sin(angle) * head * 0.7)
    ctx.stroke()
    ctx.move_to(x1, y1)
    for side in (-1, 1):
        ctx.line_to(x1 - head * math.cos(angle + side * 0.42), y1 - head * math.sin(angle + side * 0.42))
    ctx.close_path()
    ctx.fill()


def render_shape(ctx, shape):
    r, g, b = shape["color"]
    tool = shape["tool"]
    ctx.save()
    ctx.set_line_width(shape["width"])
    ctx.set_line_cap(1)   # round
    ctx.set_line_join(1)  # round
    ctx.set_source_rgba(r, g, b, 1)

    if tool == "arrow":
        _arrow(ctx, shape)
    elif tool == "rect":
        ctx.rectangle(*bounds(shape))
        ctx.stroke()
    elif tool == "pen":
        ctx.move_to(*shape["points"][0])
        for point in shape["points"][1:]:
            ctx.line_to(*point)
        ctx.stroke()
    elif tool == "highlight":
        ctx.set_source_rgba(r, g, b, 0.35)
        ctx.rectangle(*bounds(shape))
        ctx.fill()
    elif tool == "redact":
        # Solid, not blurred: a blur can be undone, a black box cannot.
        ctx.set_source_rgba(0, 0, 0, 1)
        ctx.rectangle(*bounds(shape))
        ctx.fill()
    elif tool == "text" and shape["text"]:
        ctx.select_font_face("Inter", 0, 1)
        ctx.set_font_size(TEXT_SIZE)
        x, y = shape["points"][0]
        # A dark edge under the letters keeps them readable on any background.
        ctx.move_to(x, y + TEXT_SIZE)
        ctx.text_path(shape["text"])
        ctx.set_source_rgba(0, 0, 0, 0.7)
        ctx.set_line_width(3)
        ctx.stroke_preserve()
        ctx.set_source_rgba(r, g, b, 1)
        ctx.fill()
    ctx.restore()


def render(ctx, shapes):
    for shape in shapes:
        render_shape(ctx, shape)


def flatten(image_surface, shapes):
    """A new cairo ImageSurface: the screenshot with the shapes painted on."""
    import cairo
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, image_surface.get_width(), image_surface.get_height())
    ctx = cairo.Context(out)
    ctx.set_source_surface(image_surface, 0, 0)
    ctx.paint()
    render(ctx, shapes)
    out.flush()
    return out


def fit(image_width, image_height, area_width, area_height):
    """(scale, x, y) to show the image centred in the area, never enlarged."""
    if image_width <= 0 or image_height <= 0 or area_width <= 0 or area_height <= 0:
        return 1.0, 0.0, 0.0
    scale = min(area_width / image_width, area_height / image_height, 1.0)
    return scale, (area_width - image_width * scale) / 2, (area_height - image_height * scale) / 2


def to_image(point, scale, offset_x, offset_y, image_width, image_height):
    """A point in the widget -> the same point on the image, kept inside it."""
    x = (point[0] - offset_x) / scale
    y = (point[1] - offset_y) / scale
    return min(max(x, 0), image_width), min(max(y, 0), image_height)
