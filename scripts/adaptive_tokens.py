"""Design tokens: read tokens/adaptive.tokens.json, resolve it, compile stylesheets from it.

The library behind scripts/build-tokens.py. Other generators (build-adaptive-theme.py,
build-adaptive-backgrounds.py) import it so no script parses the token file on its own.

A stylesheet source is a ``*.src.css`` file next to its output. In it a colour is never written
as a value; it is named:

    color: $text.primary;                 a role from "color"
    background-color: $white/8;           any role, hue or ramp step at an alpha from "alpha"
    border-radius: $radius.medium;        -> 12px
    transition: opacity $motion.state $motion.ease.standard;   -> 260ms cubic-bezier(...)
    background: $gradient.aurora;         -> linear-gradient(...)

``compile_css`` turns the names into plain values, which is what GNOME Shell's St, GTK 3 and the
TV's older browser all read (none of them can be relied on for CSS variables with alpha).
"""

import json
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "tokens" / "adaptive.tokens.json"
BASELINE = REPO / "tokens" / "handwritten-colours.json"
# written by build-tokens.py for the shell's JavaScript: generated, so its colours are not hand-written
SHELL_TOKENS = REPO / "shell" / "adaptive-shell@local" / "designTokens.js"
# the same for Python packages that are installed away from the checkout
PYTHON_TOKENS = (REPO / "extension" / "adaptive_files" / "design_tokens.py",)

SOURCE_SUFFIX = ".src.css"
SKIP_DIRS = {".git", ".local", "vendor", "build", "dist", "node_modules", "logs", "__pycache__",
             "theme", "icons", "design", "docs", ".gradle"}

_REF = re.compile(r"\$([a-z][a-z0-9]*(?:[.-][a-z0-9]+)*)(?:/(\d{1,2})(?!\d))?")
_ALIAS = re.compile(r"^\{([a-z0-9.-]+)\}(?:/(\d{1,2}))?$")


class TokenError(ValueError):
    pass


def oklch_to_hex(lightness, chroma, hue):
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
              -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
              -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def encode(x):
        x = min(1.0, max(0.0, x))
        x = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
        return round(x * 255)

    return "#%02X%02X%02X" % tuple(encode(x) for x in linear)


def rgb(hex_value):
    return tuple(int(hex_value[i:i + 2], 16) for i in (1, 3, 5))


class Tokens:
    """The resolved token file. ``colors`` maps every usable name to (hex, alpha or None)."""

    def __init__(self, raw):
        self.raw = raw
        ramp = raw["ramp"]
        self.ramp = [oklch_to_hex(lightness, ramp["chroma"], ramp["hue"]) for lightness in ramp["lightness"]]
        self.alphas = list(raw["alpha"])
        self.colors = {f"n{i}": (value, None) for i, value in enumerate(self.ramp)}
        for name, value in raw["hue"].items():
            self.colors[name] = (value.upper(), None)
        self.primitives = set(self.colors)
        pending = {k: v for k, v in raw["color"].items() if not k.startswith("_")}
        while pending:
            progressed = False
            for name, value in list(pending.items()):
                match = _ALIAS.match(value)
                if not match:
                    raise TokenError(f'color "{name}": "{value}" is not {{name}} or {{name}}/NN')
                target, alpha = match.group(1), match.group(2)
                if target not in self.colors:
                    continue
                base, base_alpha = self.colors[target]
                if alpha is not None:
                    if base_alpha is not None:
                        raise TokenError(f'color "{name}": {target} already carries an alpha')
                    base_alpha = self._alpha(alpha, f'color "{name}"')
                self.colors[name] = (base, base_alpha)
                del pending[name]
                progressed = True
            if not progressed:
                raise TokenError("unresolved colour names: " + ", ".join(sorted(pending)))
        self.exempt = {k: v for k, v in raw.get("exempt", {}).items() if not k.startswith("_")}

    def _alpha(self, text, where):
        alpha = int(text)
        if alpha not in self.alphas:
            raise TokenError(f"{where}: /{alpha} is not on the alpha scale {self.alphas}")
        return alpha

    # ---- values -----------------------------------------------------------------------------
    def hex(self, name):
        """An opaque colour as #RRGGBB."""
        value, alpha = self.colors[name]
        if alpha is not None:
            raise TokenError(f"{name} is translucent; use css()")
        return value

    def css(self, name, alpha=None, where=""):
        if name not in self.colors:
            raise TokenError(f"{where}: unknown colour ${name}")
        value, own = self.colors[name]
        if alpha is not None:
            if own is not None:
                raise TokenError(f"{where}: ${name} already carries an alpha; it cannot take /{alpha}")
            own = self._alpha(alpha, where)
        if own is None:
            return value
        r, g, b = rgb(value)
        return f"rgba({r}, {g}, {b}, {own / 100:.2f})"

    def gtk(self, name, alpha=None):
        """The same colour in GTK 3's own notation (for @define-color lines)."""
        value, own = self.colors[name]
        own = alpha if alpha is not None else own
        return value if own is None else f"alpha({value}, {own / 100:.2f})"

    def terminal(self):
        """The terminal scheme: background, foreground, cursor and the sixteen ANSI colours, as hex."""
        raw = self.raw["terminal"]
        resolve = lambda alias: self.hex(_ALIAS.match(alias).group(1))  # noqa: E731
        return {"background": resolve(raw["background"]), "foreground": resolve(raw["foreground"]),
                "cursor": resolve(raw["cursor"]),
                "ansi": [resolve(a) for a in raw["ansi"]] + [resolve(a) for a in raw["bright"]]}

    def value(self, name, where=""):
        """Any token a stylesheet can name, as CSS text."""
        raw = self.raw
        if name.startswith("radius.") and name[7:] in raw["radius"]:
            return f'{raw["radius"][name[7:]]}px'
        if name.startswith("space.") and name[6:] in raw["spacing"]:
            return f'{raw["spacing"][name[6:]]}px'
        if name.startswith("motion."):
            key = name[7:]
            if f"{key}.ms" in raw["motion"]:
                return f'{raw["motion"][key + ".ms"]}ms'
            if key in raw["motion"]:
                return str(raw["motion"][key])
        if name.startswith("gradient.") and name[9:] in raw["gradient"]:
            stops = [self.css(_ALIAS.match(stop).group(1)) for stop in raw["gradient"][name[9:]]]
            middle = ", ".join(f"{stop} 55%" if i == 1 and len(stops) == 3 else stop for i, stop in enumerate(stops))
            return f"linear-gradient(90deg, {middle})"
        return None

    # ---- stylesheets ------------------------------------------------------------------------
    def compile_css(self, text, where="stylesheet"):
        def replace(match):
            name, alpha = match.group(1), match.group(2)
            line = text.count("\n", 0, match.start()) + 1
            at = f"{where}:{line}"
            # "$text.primary." at the end of a sentence in a comment: try without the last part
            if name not in self.colors and alpha is None:
                other = self.value(name, at)
                if other is not None:
                    return other
            return self.css(name, alpha, at)

        return _REF.sub(replace, text)


def load():
    return Tokens(json.loads(TOKENS.read_text(encoding="utf-8")))


# ---- sources and outputs ---------------------------------------------------------------------

def walk(root=REPO):
    for path in sorted(root.iterdir()):
        if path.name in SKIP_DIRS:
            continue
        if path.is_dir() and not path.is_symlink():
            yield from walk(path)
        elif path.is_file():
            yield path


def sources():
    return [path for path in walk() if path.name.endswith(SOURCE_SUFFIX)]


def output_for(source):
    return source.with_name(source.name[:-len(SOURCE_SUFFIX)] + ".css")


def check_braces(text, where):
    """A stray or missing brace does not fail anywhere: the browser just drops the next rule."""
    depth = 0
    plain = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    for number, line in enumerate(plain.splitlines(), 1):
        for char in line:
            depth += (char == "{") - (char == "}")
            if depth < 0:
                raise TokenError(f"{where}:{number}: a closing brace with nothing to close")
    if depth:
        raise TokenError(f"{where}: {depth} opening brace(s) never closed")


def render(tokens, source):
    relative = source.relative_to(REPO)
    check_braces(source.read_text(encoding="utf-8"), str(relative))
    banner = (f"/* GENERATED from {relative.name} by scripts/build-tokens.py. Edit {relative.name}, "
              f"then run the script.\n   Colours come from tokens/adaptive.tokens.json. */\n")
    return banner + tokens.compile_css(source.read_text(encoding="utf-8"), str(relative))


# ---- colours written by hand -----------------------------------------------------------------

LINTED = {".css", ".js", ".py", ".html", ".sh", ".kt"}
_HEX = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})(?![0-9a-fA-F\w])")
_HEX3 = re.compile(r"(?<=[:\s,(])#[0-9a-fA-F]{3}(?![-\w])")
_FUNC = re.compile(r"\b(?:rgba?|hsla?)\(\s*[\d.]")
_KOTLIN = re.compile(r"\b0x[0-9A-Fa-f]{8}\b")


def count_colours(path):
    """How many colour values a file spells out itself."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    total = len(_HEX.findall(text)) + len(_FUNC.findall(text))
    if path.suffix == ".kt":
        total += len(_KOTLIN.findall(text))
    if path.name.endswith(SOURCE_SUFFIX):
        for line in text.splitlines():
            stripped = line.rstrip()
            if stripped.endswith(("{", ",")) and ":" not in stripped:
                continue          # a selector line: "#feed" there is an id, not a colour
            total += len(_HEX3.findall(line))
    return total


def handwritten(tokens):
    """{repo-relative path: count} for every file that still spells out colours."""
    generated = {output_for(source) for source in sources()} | {SHELL_TOKENS, *PYTHON_TOKENS}
    found = {}
    for path in walk():
        relative = str(path.relative_to(REPO))
        if path.suffix not in LINTED or path in generated or relative in tokens.exempt:
            continue
        if path.name.startswith(("verify-", "test-")) or "/test/" in relative or "/androidTest/" in relative:
            continue              # checks may name the colours they expect
        count = count_colours(path)
        if count:
            found[relative] = count
    return found
