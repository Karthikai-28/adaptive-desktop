"""Command palette providers that need neither GTK nor the shell.

Kept apart from main.py so scripts/verify-command-providers.py can check them
in a plain Python process:

  calculate()   "12*(3+4)", "=2^10", "sqrt(2)" - a small, safe calculator.
                The expression is parsed, never eval()'d: only numbers,
                arithmetic and a fixed set of functions are accepted, and
                exponents are bounded so "9**9**9" cannot hang the palette.
  convert()     "5 km to mi", "72 f in c", "3 gib to mb"
  emoji()       ":rocket", ":thumbs up" - names from the Unicode database

shell_call() is the palette's way into the shell (org.adaptive.Shell, see
shell/adaptive-shell@local/shellActions.js) for windows, clipboard history and
project park/resume. It imports Gio lazily so this module loads without it.
"""

import ast
import json
import math
import operator
import re
import unicodedata

# ---------------------------------------------------------------- calculator

MAX_EXPONENT = 1000
MAX_LENGTH = 200

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_FUNCTIONS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "log": math.log10, "ln": math.log, "log2": math.log2, "exp": math.exp,
    "min": min, "max": max,
}
# Something to calculate: an operator between operands, or a function call.
_LOOKS_LIKE_MATH = re.compile(r"\d\s*[-+*/%^×÷]\s*[\d.(]|[a-z]+\s*\(|^\s*=")


class _Reject(ValueError):
    pass


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise _Reject("exponent too large")
        return _BINARY[type(node.op)](left, right)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS and not node.keywords):
        return _FUNCTIONS[node.func.id](*[_eval(arg) for arg in node.args])
    raise _Reject(type(node).__name__)


def format_number(value):
    if isinstance(value, bool):
        raise _Reject("bool")
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        raise _Reject("not finite")
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return format(value, ".12g")


def calculate(text):
    """The result as a string, or None when text is not a calculation."""
    text = (text or "").strip()
    if not text or len(text) > MAX_LENGTH or not _LOOKS_LIKE_MATH.search(text.lower()):
        return None
    expression = text.lstrip("=").strip().lower()
    expression = expression.replace("^", "**").replace("×", "*").replace("÷", "/")
    try:
        return format_number(_eval(ast.parse(expression, mode="eval")))
    except (_Reject, SyntaxError, ZeroDivisionError, OverflowError, ValueError, TypeError):
        return None


# ------------------------------------------------------------- unit converter

# Each dimension's units as factors of one base unit.
_UNITS = {
    "length": ({"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254, "inch": 0.0254,
                "inches": 0.0254, "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "yd": 0.9144,
                "mi": 1609.344, "mile": 1609.344, "miles": 1609.344, "nmi": 1852}, "m"),
    "mass": ({"mg": 1e-6, "g": 0.001, "kg": 1, "t": 1000, "oz": 0.028349523125,
              "lb": 0.45359237, "lbs": 0.45359237, "st": 6.35029318}, "kg"),
    "volume": ({"ml": 0.001, "l": 1, "cl": 0.01, "dl": 0.1, "gal": 3.785411784,
                "qt": 0.946352946, "pt": 0.473176473, "cup": 0.2365882365,
                "floz": 0.0295735295625, "tsp": 0.00492892159375, "tbsp": 0.01478676478125}, "l"),
    "data": ({"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "pb": 1e15,
              "kib": 2 ** 10, "mib": 2 ** 20, "gib": 2 ** 30, "tib": 2 ** 40, "pib": 2 ** 50}, "b"),
    "time": ({"ms": 0.001, "s": 1, "sec": 1, "min": 60, "h": 3600, "hr": 3600, "hour": 3600,
              "hours": 3600, "day": 86400, "days": 86400, "week": 604800, "weeks": 604800,
              "year": 31557600, "years": 31557600}, "s"),
    "speed": ({"m/s": 1, "kmh": 1 / 3.6, "km/h": 1 / 3.6, "kph": 1 / 3.6, "mph": 0.44704,
               "knot": 0.514444, "knots": 0.514444}, "m/s"),
    "area": ({"m2": 1, "km2": 1e6, "ha": 1e4, "acre": 4046.8564224, "acres": 4046.8564224,
              "ft2": 0.09290304, "sqft": 0.09290304}, "m2"),
}
_TEMPERATURE = {"c": "c", "°c": "c", "celsius": "c", "f": "f", "°f": "f",
                "fahrenheit": "f", "k": "k", "kelvin": "k"}
_CONVERT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([a-z°/0-9]+)\s+(?:to|in|->|as)\s+([a-z°/0-9]+)\s*$")


def _to_kelvin(value, unit):
    return {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[unit]


def _from_kelvin(value, unit):
    return {"c": value - 273.15, "f": (value - 273.15) * 9 / 5 + 32, "k": value}[unit]


def convert(text):
    """"5 km = 3.10686 mi", or None when text is not a conversion."""
    match = _CONVERT.match((text or "").lower())
    if not match:
        return None
    amount, source, target = float(match.group(1)), match.group(2), match.group(3)

    if source in _TEMPERATURE and target in _TEMPERATURE:
        result = _from_kelvin(_to_kelvin(amount, _TEMPERATURE[source]), _TEMPERATURE[target])
    else:
        for units, _base in _UNITS.values():
            if source in units and target in units:
                result = amount * units[source] / units[target]
                break
        else:
            return None

    shown = format(result, ".6g")
    return f"{format_number(amount)} {source} = {shown} {target}"


# ------------------------------------------------------------------- emoji

_EMOJI_RANGES = (
    (0x1F300, 0x1F5FF), (0x1F600, 0x1F64F), (0x1F680, 0x1F6FF), (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF), (0x2600, 0x26FF), (0x2700, 0x27BF), (0x1F1E6, 0x1F1FF),
)
_emoji_index = None


def _emoji_table():
    global _emoji_index
    if _emoji_index is None:
        table = []
        for start, end in _EMOJI_RANGES:
            for codepoint in range(start, end + 1):
                char = chr(codepoint)
                name = unicodedata.name(char, "")
                if name:
                    table.append((char, name.lower()))
        _emoji_index = table
    return _emoji_index


def emoji(text, limit=12):
    """[(char, name)] for ":word word", best matches first; [] otherwise."""
    text = (text or "").strip().lower()
    if not text.startswith(":") or len(text) < 3:
        return []
    terms = text[1:].split()
    hits = []
    for char, name in _emoji_table():
        if all(term in name for term in terms):
            words = name.split()
            rank = (0 if words and words[0].startswith(terms[0]) else
                    1 if any(w.startswith(terms[0]) for w in words) else 2, len(name))
            hits.append((rank, char, name))
    hits.sort()
    return [(char, name.title()) for _rank, char, name in hits[:limit]]


# ------------------------------------------------------------ shell bridge

SHELL_NAME = "org.gnome.Shell"
SHELL_PATH = "/org/adaptive/Shell"
SHELL_INTERFACE = "org.adaptive.Shell"


def shell_call(method, signature=None, args=None, timeout_ms=1500):
    """Call org.adaptive.Shell; the first return value, or None if unreachable."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        params = GLib.Variant(signature, args) if signature else None
        reply = bus.call_sync(SHELL_NAME, SHELL_PATH, SHELL_INTERFACE, method, params,
                              None, Gio.DBusCallFlags.NO_AUTO_START, timeout_ms, None)
        values = reply.unpack() if reply is not None else ()
        return values[0] if values else None
    except Exception:
        return None


def shell_json(method, signature=None, args=None, default=None, timeout_ms=1500):
    raw = shell_call(method, signature, args, timeout_ms)
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def match_windows(windows, query):
    """Open windows matching query by title or app, focused one last."""
    folded = (query or "").casefold()
    if len(folded) < 2:
        return []
    hits = []
    for window in windows or []:
        title = window.get("title", "")
        app = window.get("appName", "")
        haystack = f"{title} {app}".casefold()
        if folded in haystack:
            starts = title.casefold().startswith(folded) or app.casefold().startswith(folded)
            hits.append((window.get("focused", False), not starts, title.casefold(), window))
    hits.sort(key=lambda h: h[:3])
    return [h[3] for h in hits]


def clipboard_query(query):
    """The filter text for "clip ..." / "clipboard ...", or None."""
    match = re.match(r"^\s*(clip|clipboard|cb)(?:\s+(.*))?$", query or "", re.I)
    return (match.group(2) or "").strip() if match else None


def format_bytes(size):
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{round(size / 1024)} KB"
    return f"{size} B"


def clipboard_entries(history, wanted, limit=10):
    """The history as the palette lists it: pinned first, then newest first.

    Each entry is the shell's item plus "title" (one line to show) and
    "detail". Images have no text to match, so a filter keeps only the ones
    asked for by the word "image".
    """
    folded = (wanted or "").casefold()
    entries = []
    for item in history or []:
        if item.get("kind") == "image":
            if folded and folded not in "image picture screenshot png":
                continue
            width, height = item.get("width", 0), item.get("height", 0)
            shape = f"{width}×{height}  ·  " if width and height else ""
            entry = dict(item, title="Image", detail=f"{shape}{format_bytes(item.get('size', 0))}")
        else:
            text = item.get("text", "")
            if folded not in text.casefold():
                continue
            line = " ".join(text.split())
            entry = dict(item, title=line[:120] + ("…" if len(line) > 120 else ""),
                         detail=f"{len(text)} characters" if len(text) > 120 else "")
        entries.append(entry)
    # Stable: the shell already has them newest first.
    entries.sort(key=lambda e: not e.get("pinned"))
    return entries[:limit]


# ------------------------------------------------------------- the computer

def _link():
    """The link daemon's own socket (services/adaptive-link/control.py)."""
    import sys
    from pathlib import Path
    folder = str(Path(__file__).resolve().parent.parent.parent / "services" / "adaptive-link")
    if folder not in sys.path:
        sys.path.append(folder)
    import control
    return control


def ask_link(text, timeout=2):
    """What `text` could mean as something for the computer to do: the
    link's one way in (services/adaptive-link/actions.py), asked for here in
    ordinary words. [{"id", "args", "say", "risk", "sure"}], or [] if the
    link is not running or the words mean nothing to it."""
    if len(text.split()) < 1 or len(text) < 3:
        return []
    try:
        answer = _link().call("POST", "/ask", {"text": text}, timeout)
    except Exception:  # noqa: BLE001 - the palette works without the link
        return []
    matches = answer.get("matches") if isinstance(answer, dict) else None
    return [match for match in matches if isinstance(match, dict) and "say" in match] if isinstance(matches, list) else []


def do_link(ident, args, timeout=120):
    """Do one of those. (done, what it said)."""
    try:
        answer = _link().call("POST", "/ask", {"id": ident, "args": args}, timeout)
    except Exception as error:  # noqa: BLE001
        return False, str(error) or "Adaptive Link is not running"
    return bool(answer.get("ok")), str(answer.get("text") or "")

