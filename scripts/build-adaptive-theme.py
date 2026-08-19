#!/usr/bin/env python3
"""Generate the session-wide Adaptive GTK3 theme from the design tokens.

The theme is deliberately standalone. Two bases were tried and neither works:

* Yaru. /usr/share/themes/Yaru-dark/gtk-3.0/gtk.css is a one-line stub importing
  resource:///com/ubuntu/themes/Yaru-dark/3.0/gtk.css, and that GResource is
  only registered when GTK loads Yaru *by name*. Importing the file from another
  theme fails with "The resource does not exist" and silently leaves no base.
* Adwaita. Every variant GTK3 ships - gtk.css, gtk-dark.css - just imports
  gtk-contained[-dark].css, which is the precompiled sheet with colours inlined:
  zero @theme_bg_color references and #2d2d2d written out literally. Importing
  it puts hardcoded greys underneath that @define-color cannot reach, measured
  as 55% Adwaita grey against 34% Adaptive canvas in gnome-control-center.

Standing alone measured 90.8% Adaptive canvas in the same window, so that is
what this generates. The cost is that widgets with no rule here fall back to
GTK's built-in defaults, which makes component coverage below this comment the
thing to extend when something looks unfinished - not an import.

Colors, radii and spacing come from tokens/adaptive.tokens.json so no hex value
is duplicated per application. Regenerate after editing the tokens:

    ./scripts/build-adaptive-theme.py
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "tokens" / "adaptive.tokens.json"
THEME = REPO / "theme" / "Adaptive"

# Token name -> GTK custom color name.
COLOR_NAMES = {
    "bg.canvas": "ad_bg",
    "bg.deep": "ad_bg_deep",
    "surface.1": "ad_surface",
    "surface.2": "ad_surface_2",
    "divider": "ad_divider",
    "text.primary": "ad_text",
    "text.muted": "ad_muted",
    "accent.primary": "ad_accent",
    "accent.cyan": "ad_cyan",
    "accent.violet": "ad_violet",
    "state.warning": "ad_warning",
    "state.danger": "ad_danger",
    "state.success": "ad_success",
}

# Selection uses a desaturated accent so selected rows stay readable behind
# text rather than glowing.
SELECTION_BG = "#244E7A"


def load_tokens():
    return json.loads(TOKENS.read_text(encoding="utf-8"))


def color_block(tokens):
    lines = ["/* Design tokens - generated from tokens/adaptive.tokens.json */", ""]

    for token, name in COLOR_NAMES.items():
        value = tokens["color"][token]
        lines.append(f"@define-color {name:<16} {value};")

    lines += [
        "",
        "/* GTK's own named colors, so unstyled widgets follow the palette */",
        "",
        "@define-color theme_bg_color          @ad_bg;",
        "@define-color theme_fg_color          @ad_text;",
        "@define-color theme_base_color        @ad_bg_deep;",
        "@define-color theme_text_color        @ad_text;",
        f"@define-color theme_selected_bg_color {SELECTION_BG};",
        "@define-color theme_selected_fg_color @ad_text;",
        "@define-color insensitive_bg_color    @ad_surface;",
        "@define-color insensitive_fg_color    alpha(@ad_muted, 0.72);",
        "@define-color borders                 alpha(@ad_divider, 0.58);",
        "@define-color warning_color           @ad_warning;",
        "@define-color error_color             @ad_danger;",
        "@define-color success_color           @ad_success;",
        "",
        "/* Common named colors that stylesheets read for chrome */",
        "",
        "@define-color headerbar_bg_color      @ad_surface_2;",
        "@define-color headerbar_fg_color      @ad_text;",
        "@define-color sidebar_bg_color        @ad_bg_deep;",
        "@define-color popover_bg_color        @ad_surface;",
        "@define-color content_view_bg         @ad_bg_deep;",
    ]

    return "\n".join(lines)


def component_block(tokens):
    radius = tokens["radius"]
    space = tokens["spacing"]

    return f"""
/* ---------------------------------------------------------
 * Surfaces
 *
 * Opaque for information-heavy content. Translucency belongs to shell
 * chrome and temporary overlays, not to every application window.
 * --------------------------------------------------------- */

window,
window.background,
.background {{
    background-color: @ad_bg;
    color: @ad_text;
}}

window:backdrop,
window.background:backdrop {{
    background-color: @ad_bg_deep;
    color: @ad_muted;
}}

* {{
    caret-color: @ad_accent;
    outline-color: alpha(@ad_accent, 0.55);
}}

/* Keyboard focus must stay visible. */
*:focus-visible {{
    outline: 2px solid alpha(@ad_accent, 0.55);
    outline-offset: -2px;
}}

/* ---------------------------------------------------------
 * Header bars
 * --------------------------------------------------------- */

headerbar,
.titlebar {{
    border-width: 0 0 1px 0;
    border-style: solid;
    border-color: alpha(@ad_divider, 0.35);
    border-radius: 0;
    box-shadow: none;
    background-image: none;
    background-color: @ad_surface_2;
    color: @ad_text;
}}

headerbar:backdrop,
.titlebar:backdrop {{
    background-color: @ad_surface;
    color: @ad_muted;
}}

headerbar .title {{
    font-weight: 700;
    color: @ad_text;
}}

headerbar .subtitle {{
    font-size: {tokens["typography"]["metadata"]}px;
    color: @ad_muted;
}}

/* ---------------------------------------------------------
 * Sidebar and content views
 * --------------------------------------------------------- */

.sidebar,
placessidebar,
stacksidebar {{
    background-color: @ad_bg_deep;
    border-right: 1px solid alpha(@ad_divider, 0.32);
    color: @ad_text;
}}

.sidebar row,
placessidebar row {{
    min-height: 30px;
    padding: 0 {space["sm"]}px;
    border-radius: {radius["small"]}px;
    color: @ad_text;
}}

.sidebar row:hover,
placessidebar row:hover {{
    background-color: alpha(@ad_surface_2, 0.92);
}}

.sidebar row:selected,
placessidebar row:selected {{
    background-color: alpha(@ad_accent, 0.16);
    color: @ad_text;
}}

view,
textview,
iconview,
treeview.view {{
    background-color: @ad_bg_deep;
    color: @ad_text;
}}

treeview.view:selected,
iconview:selected,
flowbox flowboxchild:selected {{
    background-color: alpha(@ad_accent, 0.18);
    color: @ad_text;
}}

/* ---------------------------------------------------------
 * Controls
 * --------------------------------------------------------- */

button {{
    min-height: 26px;
    padding: {space["xs"]}px {space["md"]}px;
    border-radius: {radius["small"]}px;
    border: 1px solid alpha(@ad_divider, 0.42);
    background-image: none;
    background-color: @ad_surface;
    color: @ad_text;
}}

button:hover {{
    background-color: @ad_surface_2;
    border-color: alpha(@ad_accent, 0.36);
}}

button:active,
button:checked {{
    background-color: alpha(@ad_accent, 0.20);
    border-color: alpha(@ad_accent, 0.46);
}}

button:disabled {{
    background-color: @ad_surface;
    color: alpha(@ad_muted, 0.72);
}}

button.suggested-action {{
    background-color: alpha(@ad_accent, 0.24);
    border-color: alpha(@ad_accent, 0.52);
}}

button.destructive-action {{
    background-color: alpha(@ad_danger, 0.20);
    border-color: alpha(@ad_danger, 0.48);
}}

entry,
spinbutton {{
    min-height: 26px;
    padding: {space["xs"]}px {space["sm"]}px;
    border-radius: {radius["small"]}px;
    border: 1px solid alpha(@ad_divider, 0.48);
    background-color: @ad_bg_deep;
    color: @ad_text;
}}

entry:focus,
spinbutton:focus {{
    border-color: alpha(@ad_accent, 0.62);
}}

/* ---------------------------------------------------------
 * Popovers and menus
 * --------------------------------------------------------- */

popover,
popover.background,
menu,
.context-menu {{
    padding: {space["xs"]}px;
    border-radius: {radius["medium"]}px;
    border: 1px solid alpha(@ad_divider, 0.52);
    background-color: @ad_surface;
    color: @ad_text;
}}

popover modelbutton,
menuitem {{
    min-height: 26px;
    padding: 0 {space["sm"]}px;
    border-radius: {radius["small"]}px;
}}

popover modelbutton:hover,
menuitem:hover {{
    background-color: alpha(@ad_accent, 0.16);
    color: @ad_text;
}}

/* ---------------------------------------------------------
 * Notebook, scrollbars, separators
 * --------------------------------------------------------- */

notebook > header {{
    background-color: @ad_surface;
    border-color: alpha(@ad_divider, 0.35);
}}

notebook > header > tabs > tab:checked {{
    background-color: @ad_bg_deep;
    box-shadow: inset 0 -2px 0 @ad_accent;
    color: @ad_text;
}}

scrollbar {{
    background-color: transparent;
    border: none;
}}

scrollbar slider {{
    min-width: 7px;
    min-height: 7px;
    border-radius: {radius["small"]}px;
    background-color: alpha(@ad_muted, 0.42);
}}

scrollbar slider:hover {{
    background-color: alpha(@ad_accent, 0.62);
}}

separator {{
    background-color: alpha(@ad_divider, 0.42);
}}

/* ---------------------------------------------------------
 * Feedback
 * --------------------------------------------------------- */

progressbar progress {{
    background-color: @ad_accent;
    border-radius: {radius["small"]}px;
}}

levelbar block.high {{ background-color: @ad_success; }}
levelbar block.low {{ background-color: @ad_warning; }}
levelbar block.full {{ background-color: @ad_danger; }}

infobar.warning {{ background-color: alpha(@ad_warning, 0.20); }}
infobar.error {{ background-color: alpha(@ad_danger, 0.20); }}

tooltip {{
    border-radius: {radius["small"]}px;
    background-color: @ad_surface_2;
    color: @ad_text;
}}
"""


def render(tokens):
    header = [
        "/*",
        " * Adaptive - session-wide GTK 3 theme",
        " *",
        " * GENERATED by scripts/build-adaptive-theme.py - do not edit by hand.",
        " * Edit tokens/adaptive.tokens.json and regenerate.",
        " *",
        " * Standalone by necessity: GTK3 ships no themable base to import.",
        " * See scripts/build-adaptive-theme.py for what was tried.",
        " *",
        " * Scoped to the Adaptive session through its own dconf profile; the",
        " * normal Ubuntu session keeps Yaru.",
        " */",
        "",
    ]

    return "\n".join(header) + color_block(tokens) + "\n" + component_block(tokens)


def index_theme():
    return """[Desktop Entry]
Type=X-GNOME-Metatheme
Name=Adaptive
Comment=Adaptive Desktop visual system over Ubuntu's Yaru

[X-GNOME-Metatheme]
GtkTheme=Adaptive
MetacityTheme=Yaru-dark
IconTheme=AdaptiveFilesIcons
CursorTheme=Yaru
ButtonLayout=appmenu:minimize,maximize,close
"""


def main():
    tokens = load_tokens()
    gtk3 = THEME / "gtk-3.0"
    gtk3.mkdir(parents=True, exist_ok=True)

    css = render(tokens)

    # GTK loads gtk.css for the theme and gtk-dark.css for its dark variant.
    # Adaptive is dark either way, so both get the same sheet.
    (gtk3 / "gtk.css").write_text(css, encoding="utf-8")
    (gtk3 / "gtk-dark.css").write_text(css, encoding="utf-8")
    (THEME / "index.theme").write_text(index_theme(), encoding="utf-8")

    print(f"Generated {THEME}")
    print(f"  gtk-3.0/gtk.css       {len(css.splitlines())} lines")
    print(f"  colors from           {TOKENS.relative_to(REPO)}")


if __name__ == "__main__":
    main()
