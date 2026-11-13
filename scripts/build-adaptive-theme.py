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
is duplicated per application. The rules below name colours as $tokens (see
scripts/adaptive_tokens.py). Regenerate after editing the tokens, together
with every other stylesheet:

    ./scripts/build-tokens.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adaptive_tokens  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOKENS = adaptive_tokens.TOKENS
THEME = REPO / "theme" / "Adaptive"

BASE_NAME = "Yaru-blue-dark"
BASE_RESOURCE = Path("/usr/share/themes") / BASE_NAME / "gtk-3.0" / "gtk.gresource"
BASE_IMPORT = f"resource:///com/ubuntu/themes/{BASE_NAME}/3.0/gtk.css"

# Token name -> GTK custom color name.
COLOR_NAMES = (
    ("surface.window", "ad_bg"),
    ("surface.ground", "ad_bg_deep"),
    ("surface.card", "ad_surface"),
    ("surface.raised", "ad_surface_2"),
    ("surface.window", "ad_menu"),
    ("surface.pane", "ad_sidebar"),
    ("line.solid", "ad_divider"),
    ("text.primary", "ad_text"),
    ("text.secondary", "ad_secondary"),
    ("text.tertiary", "ad_muted"),
    ("text.quaternary", "ad_tertiary"),
    ("text.disabled", "ad_quaternary"),
    ("accent", "ad_accent"),
    ("accent.hover", "ad_accent_hover"),
    ("accent.pressed", "ad_selection"),
    ("cyan", "ad_cyan"),
    ("indigo", "ad_violet"),
    ("warn", "ad_warning"),
    ("danger", "ad_danger"),
    ("ok", "ad_success"),
)


def load_tokens():
    return adaptive_tokens.load()


def color_block(tokens):
    lines = ["/* Design tokens - generated from tokens/adaptive.tokens.json */", ""]

    for token, name in COLOR_NAMES:
        value = tokens.gtk(token)
        lines.append(f"@define-color {name:<16} {value};")

    lines += [
        "",
        "/* Materials from the palette table (shell stylesheet.css, end) */",
        "",
        "@define-color ad_fill          $white/8;",
        "@define-color ad_fill_strong   $white/12;",
        "@define-color ad_tile          $white/4;",
        "@define-color ad_hairline      $white/8;",
        "",
        "/* GTK's own named colors, so widgets Yaru draws from them follow */",
        "",
        "@define-color theme_bg_color            @ad_bg;",
        "@define-color theme_fg_color            @ad_text;",
        "@define-color theme_base_color          @ad_bg;",
        "@define-color theme_text_color          @ad_text;",
        "@define-color theme_selected_bg_color   @ad_selection;",
        "@define-color theme_selected_fg_color   $white;",
        "@define-color theme_unfocused_bg_color  @ad_bg;",
        "@define-color theme_unfocused_fg_color  @ad_muted;",
        "@define-color theme_unfocused_base_color @ad_bg;",
        "@define-color theme_unfocused_text_color @ad_muted;",
        "@define-color theme_unfocused_selected_bg_color $white/12;",
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
    radius = tokens.raw["radius"]

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
    outline-color: $accent/60;
    -gtk-icon-shadow: none;
}}

decoration {{
    border-radius: {radius["medium"]}px {radius["medium"]}px 0 0;
    box-shadow: 0 12px 32px $black/45, 0 0 0 1px @ad_hairline;
}}

decoration:backdrop {{
    box-shadow: 0 6px 18px $black/32, 0 0 0 1px @ad_hairline;
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
    color: $white;
}}

headerbar button.suggested-action,
.titlebar button.suggested-action {{
    background-color: @ad_accent;
    color: $white;
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
    color: $white;
}}

scrolledwindow.view list row image.sidebar-icon {{
    color: @ad_accent;
}}

scrolledwindow.view list row:selected image.sidebar-icon {{
    color: $white;
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
    color: $white;
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
    border: 1px solid $accent/80;
    background-color: $accent/16;
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
    color: $white;
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
    background-color: $white/16;
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
    color: $white;
}}

button.suggested-action:hover,
button.default:hover {{
    background-color: @ad_accent_hover;
}}

button.suggested-action:disabled {{
    background-color: $accent/32;
    color: $white/60;
}}

button.destructive-action {{
    border-color: transparent;
    background-color: @ad_fill;
    color: @ad_danger;
}}

button.destructive-action:hover {{
    background-color: $danger/16;
}}

/* Yaru paints these buttons with a background image (green for suggested)
 * in every state, which covers the colours above - Files' Rename button
 * came out green. */
button.suggested-action,
button.suggested-action:hover,
button.suggested-action:active,
button.suggested-action:checked,
button.suggested-action:backdrop,
button.suggested-action:disabled,
button.suggested-action:backdrop:disabled,
button.destructive-action,
button.destructive-action:hover,
button.destructive-action:active,
button.destructive-action:checked,
button.destructive-action:backdrop,
button.destructive-action:disabled,
button.destructive-action:backdrop:disabled {{
    background-image: none;
    text-shadow: none;
    -gtk-icon-shadow: none;
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
    box-shadow: 0 0 0 2px $accent/32;
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
    background-color: $white/16;
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
    background-color: $white;
    box-shadow: 0 1px 3px $black/32;
}}

check,
radio {{
    min-width: 14px;
    min-height: 14px;
    border: 1px solid $white/24;
    background-image: none;
    background-color: @ad_fill;
    color: $white;
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
    background-color: $white/12;
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
    background-color: $white;
    box-shadow: 0 1px 3px $black/32;
}}

levelbar block.filled,
levelbar block.high {{ background-color: @ad_accent; }}
levelbar block.low {{ background-color: @ad_warning; }}
levelbar block.full {{ background-color: @ad_danger; }}
levelbar block.empty {{ background-color: $white/12; }}

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
    border: 1px solid $white/12;
    background-image: none;
    background-color: @ad_menu;
    box-shadow: 0 10px 30px $black/45;
    color: @ad_text;
}}

/* A menu is its own popup window, sized to the menu plus its decoration's
 * shadow. A shadow on the menu itself was cut off at the window's edge and
 * showed as a dark box around every right-click menu, so the decoration
 * carries it, shaped like the menu. */
menu,
.menu,
.context-menu {{
    box-shadow: none;
}}

.csd.popup decoration {{
    border-radius: {radius["medium"] - 2}px;
    box-shadow: 0 8px 24px $black/45;
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
    color: $white;
}}

menuitem accelerator,
popover modelbutton accelerator {{
    color: @ad_tertiary;
}}

menuitem:hover accelerator,
popover modelbutton:hover accelerator {{
    color: $white/80;
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
    background-color: $white/16;
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
    background-color: $white/32;
}}

scrollbar slider:hover {{
    background-color: $white/45;
}}

scrollbar slider:active {{
    background-color: $white/60;
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

/* Yaru fills a dialog's destructive and suggested buttons itself, which
 * left the generic red-text rule above on a red fill. In a dialog they are
 * solid, white-labelled buttons, as in macOS alerts. */
messagedialog .dialog-action-area button.destructive-action,
dialog .dialog-action-area button.destructive-action {{
    background-image: none;
    background-color: @ad_danger;
    color: $white;
}}

messagedialog .dialog-action-area button.suggested-action,
dialog .dialog-action-area button.suggested-action {{
    background-image: none;
    background-color: @ad_accent;
    color: $white;
}}

messagedialog .dialog-action-area button:not(.destructive-action):not(.suggested-action),
dialog .dialog-action-area button:not(.destructive-action):not(.suggested-action) {{
    background-image: none;
    background-color: @ad_fill;
    color: @ad_text;
}}

infobar,
infobar > revealer > box {{
    border: none;
    background-image: none;
    background-color: @ad_surface;
    color: @ad_text;
}}

infobar.info > revealer > box,
infobar.question > revealer > box {{ background-color: $accent/16; }}
infobar.warning > revealer > box {{ background-color: $warn/16; }}
infobar.error > revealer > box {{ background-color: $danger/16; }}

tooltip,
tooltip.background {{
    padding: 4px 8px;
    border: 1px solid $white/12;
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
    background-color: $accent/45;
    color: $white;
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

    body = color_block(tokens) + "\n" + component_block(tokens)
    return "\n".join(header) + tokens.compile_css(body, "scripts/build-adaptive-theme.py")


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


def has_base():
    """Whether the committed sheet imports Yaru: the form every machine with Yaru produces."""
    return BASE_RESOURCE.exists() or not (THEME / "gtk-3.0" / "gtk.css").exists()


def outputs(tokens):
    """{path: text}, for scripts/build-tokens.py (which writes and checks them)."""
    css = render(tokens, has_base())
    gtk3 = THEME / "gtk-3.0"
    # GTK loads gtk.css for the theme and gtk-dark.css for its dark variant.
    # Adaptive is dark either way, so both get the same sheet.
    return {gtk3 / "gtk.css": css, gtk3 / "gtk-dark.css": css, THEME / "index.theme": index_theme()}


def link(verbose=True):
    gtk3 = THEME / "gtk-3.0"
    gtk3.mkdir(parents=True, exist_ok=True)
    with_base = link_base(gtk3)
    if verbose:
        print(f"  base                  {BASE_NAME if with_base else 'none (Yaru bundle missing)'}")
    return with_base


def main():
    tokens = load_tokens()
    link(verbose=False)
    for path, text in outputs(tokens).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"Generated {THEME}")
    link()
    print(f"  colors from           {TOKENS.relative_to(REPO)}")


if __name__ == "__main__":
    main()
