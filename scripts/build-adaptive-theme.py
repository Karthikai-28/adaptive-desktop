#!/usr/bin/env python3
"""Generate the session-wide Adaptive GTK3 theme from the design tokens.

One sheet skins every GTK3 window in the Adaptive session: Settings, Files,
Terminator, file choosers, dialogs. Files adds only what is specific to
Nautilus (extension/preview.css), never a second copy of the palette.

Base: Yaru-blue-dark, imported through its own GResource.

  /usr/share/themes/Yaru-blue-dark/gtk-3.0/gtk.css is a one-line stub that
  imports resource:///com/ubuntu/themes/Yaru-blue-dark/3.0/gtk.css. GTK only
  registers that resource when it loads a theme whose directory holds a
  gtk.gresource file - it looks in the directory of the theme being loaded,
  not in Yaru's. So this theme's gtk-3.0/ carries a gtk.gresource symlink to
  Yaru's bundle, and the import resolves.

  Earlier versions stood alone because the import failed without that link,
  and every widget with no rule here fell back to GTK's raw defaults. With
  Yaru underneath, an unstyled widget looks like Yaru-blue-dark - dark grey
  and blue - instead of unthemed, and the rules below only have to move the
  surfaces onto the Apple materials.

  Yaru inlines its colours, so @define-color alone cannot recolour it. Every
  surface the eye reads (window, header, sidebar, lists, menus, controls) gets
  an explicit rule below.

If the Yaru bundle is missing the symlink is skipped and the sheet still
loads; it just loses the base.

Colors, radii and spacing come from tokens/adaptive.tokens.json so no hex value
is duplicated per application. Regenerate after editing the tokens:

    ./scripts/build-adaptive-theme.py
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "tokens" / "adaptive.tokens.json"
THEME = REPO / "theme" / "Adaptive"

BASE_NAME = "Yaru-blue-dark"
BASE_RESOURCE = Path("/usr/share/themes") / BASE_NAME / "gtk-3.0" / "gtk.gresource"
BASE_IMPORT = f"resource:///com/ubuntu/themes/{BASE_NAME}/3.0/gtk.css"

# Token name -> GTK custom color name.
COLOR_NAMES = {
    "bg.canvas": "ad_bg",
    "bg.deep": "ad_bg_deep",
    "surface.1": "ad_surface",
    "surface.2": "ad_surface_2",
    "material.menu": "ad_menu",
    "material.sidebar": "ad_sidebar",
    "divider": "ad_divider",
    "text.primary": "ad_text",
    "text.muted": "ad_muted",
    "text.tertiary": "ad_tertiary",
    "text.quaternary": "ad_quaternary",
    "accent.primary": "ad_accent",
    "accent.hover": "ad_accent_hover",
    "accent.selection": "ad_selection",
    "accent.cyan": "ad_cyan",
    "accent.violet": "ad_violet",
    "state.warning": "ad_warning",
    "state.danger": "ad_danger",
    "state.success": "ad_success",
}


def load_tokens():
    return json.loads(TOKENS.read_text(encoding="utf-8"))


def color_block(tokens):
    lines = ["/* Design tokens - generated from tokens/adaptive.tokens.json */", ""]

    for token, name in COLOR_NAMES.items():
        value = tokens["color"][token]
        lines.append(f"@define-color {name:<16} {value};")

    lines += [
        "",
        "/* Materials from the palette table (shell stylesheet.css, end) */",
        "",
        "@define-color ad_fill          alpha(#FFFFFF, 0.08);",
        "@define-color ad_fill_strong   alpha(#FFFFFF, 0.12);",
        "@define-color ad_tile          alpha(#FFFFFF, 0.045);",
        "@define-color ad_hairline      alpha(#FFFFFF, 0.09);",
        "",
        "/* GTK's own named colors, so widgets Yaru draws from them follow */",
        "",
        "@define-color theme_bg_color            @ad_bg;",
        "@define-color theme_fg_color            @ad_text;",
        "@define-color theme_base_color          @ad_bg;",
        "@define-color theme_text_color          @ad_text;",
        "@define-color theme_selected_bg_color   @ad_selection;",
        "@define-color theme_selected_fg_color   #FFFFFF;",
        "@define-color theme_unfocused_bg_color  @ad_bg;",
        "@define-color theme_unfocused_fg_color  @ad_muted;",
        "@define-color theme_unfocused_base_color @ad_bg;",
        "@define-color theme_unfocused_text_color @ad_muted;",
        "@define-color theme_unfocused_selected_bg_color alpha(#FFFFFF, 0.14);",
        "@define-color theme_unfocused_selected_fg_color @ad_text;",
        "@define-color insensitive_bg_color      @ad_surface;",
        "@define-color insensitive_fg_color      @ad_quaternary;",
        "@define-color borders                   @ad_hairline;",
        "@define-color unfocused_borders         @ad_hairline;",
        "@define-color warning_color             @ad_warning;",
        "@define-color error_color               @ad_danger;",
        "@define-color success_color             @ad_success;",
        "",
        "/* Common named colors that stylesheets read for chrome */",
        "",
        "@define-color headerbar_bg_color        @ad_surface;",
        "@define-color headerbar_fg_color        @ad_text;",
        "@define-color sidebar_bg_color          @ad_sidebar;",
        "@define-color popover_bg_color          @ad_menu;",
        "@define-color content_view_bg           @ad_bg;",
    ]

    return "\n".join(lines)


def component_block(tokens):
    radius = tokens["radius"]

    return f"""
/* ---------------------------------------------------------
 * Surfaces
 *
 * Opaque for information-heavy content. Translucency belongs to shell
 * chrome and temporary overlays, not to application windows.
 * --------------------------------------------------------- */

window,
window.background,
.background,
dialog.background,
messagedialog.background {{
    background-color: @ad_bg;
    background-image: none;
    color: @ad_text;
}}

window:backdrop,
window.background:backdrop {{
    background-color: @ad_bg;
    color: @ad_muted;
}}

* {{
    caret-color: @ad_accent;
    outline-color: alpha(@ad_accent, 0.55);
    -gtk-icon-shadow: none;
}}

decoration {{
    border-radius: {radius["medium"]}px {radius["medium"]}px 0 0;
    box-shadow: 0 12px 32px alpha(#000000, 0.45), 0 0 0 1px @ad_hairline;
}}

decoration:backdrop {{
    box-shadow: 0 6px 18px alpha(#000000, 0.35), 0 0 0 1px @ad_hairline;
}}

/* ---------------------------------------------------------
 * Header bars - one flat toolbar material, hairline below
 * --------------------------------------------------------- */

headerbar,
.titlebar,
.titlebar:not(headerbar),
window.csd > .titlebar,
headerbar.titlebar {{
    min-height: 44px;
    padding: 0 8px;
    border-width: 0 0 1px 0;
    border-style: solid;
    border-color: @ad_hairline;
    border-radius: 0;
    box-shadow: none;
    background-image: none;
    background-color: @ad_surface;
    color: @ad_text;
}}

window.csd > .titlebar,
window.csd > headerbar.titlebar {{
    border-radius: {radius["medium"]}px {radius["medium"]}px 0 0;
}}

window.maximized > .titlebar,
window.tiled > .titlebar {{
    border-radius: 0;
}}

headerbar:backdrop,
.titlebar:backdrop {{
    background-image: none;
    background-color: @ad_surface;
    color: @ad_tertiary;
}}

headerbar .title,
.titlebar .title {{
    font-weight: 600;
    color: @ad_text;
}}

headerbar .subtitle,
.titlebar .subtitle {{
    font-size: 10px;
    color: @ad_muted;
}}

headerbar separator {{
    background-color: transparent;
}}

/* Toolbar buttons are glyphs until pointed at, as in macOS. */
headerbar button,
.titlebar button {{
    min-height: 28px;
    min-width: 28px;
    padding: 0 6px;
    border: none;
    border-radius: {radius["small"] - 1}px;
    background-image: none;
    background-color: transparent;
    box-shadow: none;
    color: @ad_muted;
}}

headerbar button:hover,
.titlebar button:hover {{
    background-color: @ad_fill;
    color: @ad_text;
}}

headerbar button:active,
headerbar button:checked,
.titlebar button:active,
.titlebar button:checked {{
    background-color: @ad_fill_strong;
    color: @ad_text;
}}

headerbar button:disabled,
.titlebar button:disabled {{
    background-color: transparent;
    color: @ad_quaternary;
}}

headerbar button.titlebutton,
.titlebar button.titlebutton {{
    min-width: 24px;
    min-height: 24px;
    padding: 0;
    margin: 0 1px;
    border-radius: 99px;
    color: @ad_muted;
}}

headerbar button.titlebutton:hover,
.titlebar button.titlebutton:hover {{
    background-color: @ad_fill_strong;
    color: @ad_text;
}}

headerbar button.titlebutton.close:hover,
.titlebar button.titlebutton.close:hover {{
    background-color: @ad_danger;
    color: #FFFFFF;
}}

headerbar button.suggested-action,
.titlebar button.suggested-action {{
    background-color: @ad_accent;
    color: #FFFFFF;
}}

headerbar button.suggested-action:hover,
.titlebar button.suggested-action:hover {{
    background-color: @ad_accent_hover;
}}

headerbar entry,
.titlebar entry {{
    min-height: 28px;
}}

/* ---------------------------------------------------------
 * Sidebars - card material, accent glyphs, neutral selection
 * --------------------------------------------------------- */

.sidebar,
placessidebar,
placessidebar list,
placessidebar viewport,
stacksidebar,
stacksidebar list,
.navigation-sidebar {{
    background-color: @ad_sidebar;
    background-image: none;
    color: @ad_text;
    border: none;
}}

.sidebar:not(separator),
placessidebar,
stacksidebar {{
    border-right: 1px solid @ad_hairline;
}}

.sidebar row,
placessidebar row,
stacksidebar row,
.navigation-sidebar row {{
    min-height: 28px;
    margin: 1px 8px;
    padding: 0 8px;
    border-radius: {radius["small"] - 2}px;
    background-color: transparent;
    color: @ad_text;
}}

.sidebar row:hover,
placessidebar row:hover,
stacksidebar row:hover,
.navigation-sidebar row:hover {{
    background-color: @ad_tile;
}}

.sidebar row:selected,
.sidebar row:selected:focus,
placessidebar row:selected,
placessidebar row:selected:focus,
stacksidebar row:selected,
.navigation-sidebar row:selected {{
    background-color: @ad_fill_strong;
    color: @ad_text;
}}

.sidebar row:selected label,
placessidebar row:selected label,
stacksidebar row:selected label {{
    color: @ad_text;
}}

.sidebar row image,
placessidebar row image,
placessidebar .sidebar-icon {{
    margin-right: 8px;
    color: @ad_accent;
}}

.sidebar row:selected image,
placessidebar row:selected image {{
    color: @ad_accent;
}}

placessidebar row.sidebar-new-bookmark-row {{
    color: @ad_accent;
}}

placessidebar separator,
.sidebar separator {{
    margin: 6px 16px;
    min-height: 1px;
    background-color: @ad_hairline;
}}

/* Settings' panel list is a sidebar in all but name: a list inside a
 * scrolledwindow marked .view (gnome-control-center cc-window.ui). */
scrolledwindow.view list {{
    background-color: @ad_sidebar;
}}

scrolledwindow.view list row {{
    min-height: 30px;
    margin: 1px 8px;
    border-radius: {radius["small"] - 2}px;
}}

scrolledwindow.view list row:selected,
scrolledwindow.view list row:selected:focus {{
    background-color: @ad_selection;
    color: #FFFFFF;
}}

scrolledwindow.view list row image.sidebar-icon {{
    color: @ad_accent;
}}

scrolledwindow.view list row:selected image.sidebar-icon {{
    color: #FFFFFF;
}}

/* ---------------------------------------------------------
 * Content views
 * --------------------------------------------------------- */

view,
.view,
textview text,
iconview,
treeview.view,
flowbox {{
    background-color: @ad_bg;
    color: @ad_text;
}}

treeview.view,
.view {{
    border-color: @ad_hairline;
}}

treeview.view:selected,
treeview.view:selected:focus,
iconview:selected,
flowbox flowboxchild:selected,
.view:selected,
.view:selected:focus,
.view text selection,
textview text selection {{
    background-color: @ad_selection;
    color: #FFFFFF;
}}

treeview.view:selected:backdrop,
.view:selected:backdrop {{
    background-color: @ad_fill_strong;
    color: @ad_text;
}}

treeview.view:hover {{
    background-color: @ad_tile;
}}

treeview.view header button,
treeview.view header button:hover,
treeview.view header button:active {{
    min-height: 26px;
    padding: 0 8px;
    border-width: 0 1px 1px 0;
    border-style: solid;
    border-color: @ad_hairline;
    border-radius: 0;
    background-image: none;
    background-color: @ad_bg;
    box-shadow: none;
    color: @ad_muted;
    font-size: 11px;
    font-weight: 600;
}}

treeview.view header button:hover {{
    color: @ad_text;
}}

treeview.view.expander {{
    color: @ad_tertiary;
}}

rubberband,
.rubberband,
.view rubberband,
treeview.view rubberband,
flowbox rubberband {{
    border: 1px solid alpha(@ad_accent, 0.80);
    background-color: alpha(@ad_accent, 0.18);
}}

/* Grouped lists - Settings-style rows on a card, hairline between */

list {{
    background-color: @ad_surface;
    color: @ad_text;
    border-color: @ad_hairline;
}}

list row {{
    background-color: transparent;
}}

list row:hover {{
    background-color: @ad_tile;
}}

list row:selected,
list row:selected:focus {{
    background-color: @ad_selection;
    color: #FFFFFF;
}}

list row:selected:backdrop {{
    background-color: @ad_fill_strong;
    color: @ad_text;
}}

list separator,
list > separator {{
    background-color: @ad_hairline;
}}

frame > border,
.frame {{
    border: 1px solid @ad_hairline;
    border-radius: {radius["small"] + 2}px;
    box-shadow: none;
}}

/* ---------------------------------------------------------
 * Controls
 * --------------------------------------------------------- */

button {{
    min-height: 24px;
    padding: 3px 12px;
    border: 1px solid @ad_hairline;
    border-radius: {radius["small"] - 1}px;
    background-image: none;
    background-color: @ad_fill;
    box-shadow: none;
    text-shadow: none;
    color: @ad_text;
}}

button:hover {{
    background-color: @ad_fill_strong;
    border-color: @ad_hairline;
}}

button:active,
button:checked {{
    background-color: alpha(#FFFFFF, 0.18);
    border-color: @ad_hairline;
    color: @ad_text;
}}

button:disabled {{
    background-color: @ad_tile;
    border-color: transparent;
    color: @ad_quaternary;
}}

button:backdrop {{
    background-color: @ad_tile;
}}

button.flat,
button.image-button.flat,
.linked.flat button {{
    border-color: transparent;
    background-color: transparent;
}}

button.flat:hover {{
    background-color: @ad_fill;
}}

button.suggested-action,
button.default {{
    border-color: transparent;
    background-color: @ad_accent;
    color: #FFFFFF;
}}

button.suggested-action:hover,
button.default:hover {{
    background-color: @ad_accent_hover;
}}

button.suggested-action:disabled {{
    background-color: alpha(@ad_accent, 0.35);
    color: alpha(#FFFFFF, 0.55);
}}

button.destructive-action {{
    border-color: transparent;
    background-color: @ad_fill;
    color: @ad_danger;
}}

button.destructive-action:hover {{
    background-color: alpha(@ad_danger, 0.18);
}}

.linked > button,
.linked > entry {{
    border-radius: 0;
}}

.linked:not(.vertical) > button:first-child,
.linked:not(.vertical) > entry:first-child {{
    border-top-left-radius: {radius["small"] - 1}px;
    border-bottom-left-radius: {radius["small"] - 1}px;
}}

.linked:not(.vertical) > button:last-child,
.linked:not(.vertical) > entry:last-child {{
    border-top-right-radius: {radius["small"] - 1}px;
    border-bottom-right-radius: {radius["small"] - 1}px;
}}

entry,
spinbutton:not(.vertical),
spinbutton.vertical entry {{
    min-height: 26px;
    padding: 0 8px;
    border: 1px solid @ad_hairline;
    border-radius: {radius["small"] - 1}px;
    background-image: none;
    background-color: @ad_bg_deep;
    box-shadow: none;
    color: @ad_text;
}}

entry:focus,
spinbutton:focus {{
    border-color: @ad_accent;
    box-shadow: 0 0 0 2px alpha(@ad_accent, 0.35);
}}

entry:disabled {{
    color: @ad_quaternary;
}}

entry image {{
    color: @ad_tertiary;
}}

entry.search {{
    border-radius: 99px;
}}

switch {{
    min-width: 38px;
    min-height: 22px;
    border: none;
    border-radius: 99px;
    background-image: none;
    background-color: alpha(#FFFFFF, 0.16);
    color: transparent;
}}

switch:checked {{
    background-color: @ad_accent;
}}

switch slider {{
    min-width: 20px;
    min-height: 20px;
    margin: 1px;
    border: none;
    border-radius: 99px;
    background-image: none;
    background-color: #FFFFFF;
    box-shadow: 0 1px 3px alpha(#000000, 0.30);
}}

check,
radio {{
    min-width: 14px;
    min-height: 14px;
    border: 1px solid alpha(#FFFFFF, 0.22);
    background-image: none;
    background-color: @ad_fill;
    color: #FFFFFF;
}}

check {{
    border-radius: 4px;
}}

check:checked,
check:indeterminate,
radio:checked,
radio:indeterminate {{
    border-color: @ad_accent;
    background-color: @ad_accent;
}}

scale trough,
progressbar trough,
levelbar trough {{
    border: none;
    border-radius: 99px;
    background-image: none;
    background-color: alpha(#FFFFFF, 0.14);
}}

scale highlight,
progressbar progress {{
    border: none;
    border-radius: 99px;
    background-image: none;
    background-color: @ad_accent;
}}

scale slider {{
    min-width: 18px;
    min-height: 18px;
    border: none;
    border-radius: 99px;
    background-image: none;
    background-color: #FFFFFF;
    box-shadow: 0 1px 3px alpha(#000000, 0.35);
}}

levelbar block.filled,
levelbar block.high {{ background-color: @ad_accent; }}
levelbar block.low {{ background-color: @ad_warning; }}
levelbar block.full {{ background-color: @ad_danger; }}
levelbar block.empty {{ background-color: alpha(#FFFFFF, 0.14); }}

combobox button.combo,
button.combo {{
    padding: 3px 8px;
}}

/* ---------------------------------------------------------
 * Popovers and menus - menu material, accent hover
 * --------------------------------------------------------- */

popover,
popover.background,
menu,
.menu,
.context-menu {{
    padding: 5px;
    border-radius: {radius["medium"] - 2}px;
    border: 1px solid alpha(#FFFFFF, 0.12);
    background-image: none;
    background-color: @ad_menu;
    box-shadow: 0 10px 30px alpha(#000000, 0.50);
    color: @ad_text;
}}

popover modelbutton,
menu menuitem,
.menu menuitem,
menuitem {{
    min-height: 24px;
    padding: 0 10px;
    border-radius: {radius["small"] - 3}px;
    color: @ad_text;
    text-shadow: none;
}}

popover modelbutton:hover,
menu menuitem:hover,
.menu menuitem:hover,
menuitem:hover {{
    background-color: @ad_accent;
    color: #FFFFFF;
}}

menuitem accelerator,
popover modelbutton accelerator {{
    color: @ad_tertiary;
}}

menuitem:hover accelerator,
popover modelbutton:hover accelerator {{
    color: alpha(#FFFFFF, 0.75);
}}

menuitem:disabled,
popover modelbutton:disabled {{
    color: @ad_quaternary;
}}

popover separator,
menu separator,
.menu separator {{
    margin: 4px 10px;
    min-height: 1px;
    background-color: @ad_hairline;
}}

popover button,
popover list {{
    background-color: transparent;
}}

popover button:hover {{
    background-color: @ad_fill;
}}

/* ---------------------------------------------------------
 * Notebook, stack switchers
 * --------------------------------------------------------- */

notebook,
notebook > stack {{
    background-color: @ad_bg;
}}

notebook > header {{
    padding: 0;
    border-color: @ad_hairline;
    background-image: none;
    background-color: @ad_surface;
}}

notebook > header > tabs > tab {{
    min-height: 30px;
    padding: 0 12px;
    border: none;
    background-color: transparent;
    color: @ad_muted;
}}

notebook > header > tabs > tab:hover {{
    background-color: @ad_tile;
    color: @ad_text;
}}

notebook > header > tabs > tab:checked {{
    background-color: @ad_bg;
    box-shadow: inset 0 -2px 0 @ad_accent;
    color: @ad_text;
}}

stackswitcher > button,
.stack-switcher > button {{
    padding: 2px 14px;
}}

stackswitcher > button:checked,
.stack-switcher > button:checked {{
    background-color: alpha(#FFFFFF, 0.20);
}}

/* ---------------------------------------------------------
 * Scrollbars, separators, panes
 * --------------------------------------------------------- */

scrollbar,
scrollbar.overlay-indicator {{
    border: none;
    background-color: transparent;
    background-image: none;
}}

scrollbar slider {{
    min-width: 7px;
    min-height: 7px;
    margin: 2px;
    border: none;
    border-radius: 99px;
    background-color: alpha(#FFFFFF, 0.30);
}}

scrollbar slider:hover {{
    background-color: alpha(#FFFFFF, 0.46);
}}

scrollbar slider:active {{
    background-color: alpha(#FFFFFF, 0.58);
}}

separator {{
    background-color: @ad_hairline;
}}

paned > separator {{
    min-width: 1px;
    min-height: 1px;
    background-image: none;
    background-color: @ad_hairline;
}}

/* ---------------------------------------------------------
 * Dialogs, feedback, tooltips
 * --------------------------------------------------------- */

messagedialog .dialog-action-area button,
dialog .dialog-action-area button {{
    min-height: 28px;
}}

infobar,
infobar > revealer > box {{
    border: none;
    background-image: none;
    background-color: @ad_surface;
    color: @ad_text;
}}

infobar.info > revealer > box,
infobar.question > revealer > box {{ background-color: alpha(@ad_accent, 0.18); }}
infobar.warning > revealer > box {{ background-color: alpha(@ad_warning, 0.18); }}
infobar.error > revealer > box {{ background-color: alpha(@ad_danger, 0.18); }}

tooltip,
tooltip.background {{
    padding: 4px 8px;
    border: 1px solid alpha(#FFFFFF, 0.12);
    border-radius: {radius["small"] - 2}px;
    background-color: @ad_menu;
    box-shadow: none;
    color: @ad_text;
}}

tooltip label {{
    color: @ad_text;
}}

.dim-label,
label.dim-label {{
    color: @ad_muted;
    opacity: 1;
}}

selection,
label selection {{
    background-color: alpha(@ad_accent, 0.45);
    color: #FFFFFF;
}}

link,
*:link {{
    color: @ad_accent;
}}
"""


def render(tokens, with_base):
    header = [
        "/*",
        " * Adaptive - session-wide GTK 3 theme",
        " *",
        " * GENERATED by scripts/build-adaptive-theme.py - do not edit by hand.",
        " * Edit tokens/adaptive.tokens.json and regenerate.",
        " *",
        f" * Base: {BASE_NAME}, imported through the gtk.gresource symlink",
        " * beside this file. The rules below move its surfaces onto the",
        " * Apple dark materials.",
        " *",
        " * Scoped to the Adaptive session through its own dconf profile; the",
        " * normal Ubuntu session keeps Yaru.",
        " */",
        "",
    ]

    if with_base:
        header += [f'@import url("{BASE_IMPORT}");', ""]

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


def link_base(gtk3):
    """Point gtk-3.0/gtk.gresource at Yaru's bundle; see the module docstring."""
    link = gtk3 / "gtk.gresource"

    if not BASE_RESOURCE.exists():
        if link.is_symlink():
            link.unlink()
        return False

    if link.is_symlink() or link.exists():
        if link.is_symlink() and Path(link.readlink()) == BASE_RESOURCE:
            return True
        link.unlink()

    link.symlink_to(BASE_RESOURCE)
    return True


def main():
    tokens = load_tokens()
    gtk3 = THEME / "gtk-3.0"
    gtk3.mkdir(parents=True, exist_ok=True)

    with_base = link_base(gtk3)
    css = render(tokens, with_base)

    # GTK loads gtk.css for the theme and gtk-dark.css for its dark variant.
    # Adaptive is dark either way, so both get the same sheet.
    (gtk3 / "gtk.css").write_text(css, encoding="utf-8")
    (gtk3 / "gtk-dark.css").write_text(css, encoding="utf-8")
    (THEME / "index.theme").write_text(index_theme(), encoding="utf-8")

    print(f"Generated {THEME}")
    print(f"  gtk-3.0/gtk.css       {len(css.splitlines())} lines")
    print(f"  base                  {BASE_NAME if with_base else 'none (Yaru bundle missing)'}")
    print(f"  colors from           {TOKENS.relative_to(REPO)}")


if __name__ == "__main__":
    main()
