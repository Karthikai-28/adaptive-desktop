#!/usr/bin/env python3
"""Show Mario Hub's pages on the desktop: Home as a layer you summon, the panel on a key.

    host.py --background   start Home loaded and hidden (the login entry does this, Adaptive session only)
    host.py                show Home, or hide it if it is showing (Super+H; --toggle is the same)
    host.py --show [TAB]   show Home, on Today or a tab from "tabs" in mario.json (mail, calendar, ...)
    host.py --hide         hide Home
    host.py --panel        the Mario panel: a window at the right edge, above the others; running it
                           again while it is open closes it (Super+J)

Home is not the desktop: the wallpaper is. Home is one window over the work area (the top bar
stays), above every other window while it is up and gone when it is not, so whatever you were doing
is untouched underneath. It hides when you press Escape, press its key again, or when another
window takes the keyboard (you opened something from it). scripts/adaptive-home.sh is the fast
way in for a key binding: it asks the running Home over D-Bus and only starts this file when there
is none.

Today is the hub's page. Every other tab is a site kept open in a view of its own with a profile
of its own (~/.local/share/adaptive-desktop/mario/web: signed in there once, it stays signed in),
laid over the rectangle the page reports. Signing in happens inside the tab; links that leave a
tab's site open in the browser (site_rules.py decides which is which).

GTK 3 + WebKitGTK (gir1.2-webkit2-4.1, or 4.0), as on Ubuntu 22.04; X11.
"""
import json
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
for _v in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", _v)
        break
    except ValueError:
        continue
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_rules  # noqa: E402

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "adaptive-desktop" / "mario.json"
PANEL_W = 760


def hub_url(path="/"):
    try:
        port = int(json.loads(CONFIG.read_text()).get("port", 8791))
    except (OSError, ValueError, TypeError):
        port = 8791
    return f"http://127.0.0.1:{port}{path}"


def make_view(path):
    settings = WebKit2.Settings(enable_developer_extras=bool(os.environ.get("MARIO_DEVTOOLS")),
                                enable_write_console_messages_to_stdout=True,
                                hardware_acceleration_policy=WebKit2.HardwareAccelerationPolicy.ON_DEMAND)
    view = WebKit2.WebView(settings=settings)
    view.set_background_color(Gdk.RGBA(0.078, 0.078, 0.086, 1))
    if not os.environ.get("MARIO_DEVTOOLS"):
        view.connect("context-menu", lambda *_: True)

    def retry(*_):
        GLib.timeout_add_seconds(2, lambda: (view.load_uri(hub_url(path)), False)[1])
        return True

    def stay_inside(_view, decision, kind):
        # links that leave the hub open in the browser, not inside the desktop
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith(hub_url("")):
                Gio.AppInfo.launch_default_for_uri(uri, None)
                decision.ignore()
                return True
        return False

    view.connect("load-failed", retry)
    # the page's web process can die (out of memory, a GPU reset after suspend); Home must not stay
    # blank until the next login, so it loads again
    view.connect("web-process-terminated", lambda *_: retry())
    view.connect("decide-policy", stay_inside)
    view.load_uri(hub_url(path))
    return view


def fade_in(win, ms=160):
    """Bring a window up from clear over a few frames (the compositor applies the opacity)."""
    started = GLib.get_monotonic_time()

    def step():
        t = min(1.0, (GLib.get_monotonic_time() - started) / (ms * 1000))
        win.set_opacity(1 - (1 - t) ** 3)       # ease out
        return t < 1

    GLib.timeout_add(16, step)


def workarea():
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    return monitor.get_workarea()


def now(win):
    """A timestamp the window manager accepts for giving a window the keyboard."""
    try:
        gi.require_version("GdkX11", "3.0")
        from gi.repository import GdkX11
        return GdkX11.x11_get_server_time(win.get_window())
    except (ValueError, ImportError, TypeError):
        return Gtk.get_current_event_time() or GLib.get_monotonic_time() // 1000


class Home(Gtk.Application):
    """One instance per session; later launches hand it their arguments."""

    def __init__(self):
        super().__init__(application_id="com.karthi.MarioHome", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = self.page = self.overlay = None
        self.sites = {}          # tab id -> its view
        self.signing_in = {}     # tab id -> its view is on a sign-in page
        self.sent_to_sign_in = set()
        self.site_context = None
        self.shown_at = 0
        self.hiding = False
        self.had_keyboard = False     # since it was last shown
        for name, param, call in (("toggle", None, lambda *_: self.toggle()),
                                  ("show", GLib.VariantType.new("s"), lambda _a, v: self.show_home(v.get_string())),
                                  ("hide", None, lambda *_: self.hide_home())):
            action = Gio.SimpleAction.new(name, param)
            action.connect("activate", call)
            self.add_action(action)

    # ---- the command line: the first launch and every later one ---------------------------
    def do_command_line(self, line):
        args = line.get_arguments()[1:]
        fresh = self.win is None
        if fresh:
            self.build()
        if "--background" in args:
            pass                                  # loaded, waiting for its key
        elif "--hide" in args:
            self.hide_home()
        elif "--show" in args:
            rest = args[args.index("--show") + 1:]
            self.show_home(rest[0] if rest and not rest[0].startswith("-") else "")
        else:
            self.toggle()
        return 0

    def build(self):
        win = Gtk.ApplicationWindow(application=self, title="Mario Home")
        # A dock-type window sits above ordinary windows, is on every workspace, stays out of the
        # taskbar and the window switcher, and the shell does not animate it: the fade is ours.
        win.set_type_hint(Gdk.WindowTypeHint.DOCK)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_accept_focus(True)
        win.stick()
        self.page = make_view("/")
        manager = self.page.get_user_content_manager()
        manager.register_script_message_handler("home")
        manager.connect("script-message-received::home", self.from_page)
        self.overlay = Gtk.Overlay()
        self.overlay.add(self.page)
        win.add(self.overlay)
        win.connect("delete-event", lambda *_: (self.hide_home(), True)[1])
        win.connect("key-press-event", self.key)
        win.connect("notify::is-active", self.focus_moved)
        Gdk.Screen.get_default().connect("monitors-changed", lambda *_: self.place())
        self.win = win
        self.place()
        self.overlay.show()
        self.page.show()
        self.hold()                               # no window on screen, still running

    def place(self):
        area = workarea()
        self.win.move(area.x, area.y)
        self.win.resize(area.width, area.height)

    # ---- show and hide ---------------------------------------------------------------------
    def toggle(self):
        if self.win.get_visible() and not self.hiding:
            self.hide_home()
        else:
            self.show_home("")

    def show_home(self, tab=""):
        self.hiding = False
        self.place()
        if not self.win.get_visible():
            self.had_keyboard = False
            self.win.set_opacity(0)
            self.win.show()
            fade_in(self.win)
        self.shown_at = GLib.get_monotonic_time()
        self.win.present_with_time(now(self.win))
        self.js(f"window.homeSpace && homeSpace.open({json.dumps(tab or '')})")

    def hide_home(self):
        if not self.win.get_visible() or self.hiding:
            return
        self.hiding = True
        started = GLib.get_monotonic_time()

        def step():
            if not self.hiding:                   # shown again while fading out
                return False
            t = min(1.0, (GLib.get_monotonic_time() - started) / 120000)
            self.win.set_opacity(1 - t)
            if t < 1:
                return True
            self.win.hide()
            self.win.set_opacity(1)
            self.hiding = False
            self.js("window.homeSpace && homeSpace.closed()")
            return False

        GLib.timeout_add(16, step)

    def focus_moved(self, *_):
        """Another window has the keyboard: something was opened from Home, so Home steps aside.
        Not at once: a menu or a moment without focus while Home is still arriving is not that."""
        def check():
            settled = GLib.get_monotonic_time() - self.shown_at > 600000
            # only once Home has had the keyboard: if the window manager never gave it, hiding
            # here would make Home flash up and vanish
            if self.win.get_visible() and not self.win.is_active() and settled and self.had_keyboard:
                self.hide_home()
            return False
        if self.win.is_active():
            self.had_keyboard = True
        else:
            GLib.timeout_add(250, check)

    def key(self, _win, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK and not event.state & Gdk.ModifierType.MOD1_MASK
        digit = event.keyval - Gdk.KEY_0
        if ctrl and 1 <= digit <= 9:              # also while a site has the keyboard
            self.js(f"homeSpace.select({digit})")
            return True
        return False

    def js(self, script):
        self.page.run_javascript(script, None, None, None)

    # ---- tabs --------------------------------------------------------------------------------
    def from_page(self, _manager, result):
        try:
            msg = json.loads(result.get_js_value().to_string())
        except (ValueError, AttributeError, GLib.Error):
            return
        kind = msg.get("type")
        if kind == "close":
            self.hide_home()
        elif kind == "tab":
            self.select(msg.get("id"), msg.get("url"), msg.get("rect"))
        elif kind == "rect" and msg.get("rect"):
            for view in self.sites.values():
                self.fit(view, msg["rect"])

    def select(self, tab, url, rect):
        for name, view in self.sites.items():
            view.set_visible(name == tab)
        if tab == "today" or not url or not url.startswith("https://") or not rect:
            self.page.grab_focus()
            return
        view = self.sites.get(tab)
        if not view:
            view = self.sites[tab] = self.site_view(tab, url)
            self.overlay.add_overlay(view)
        self.fit(view, rect)
        view.show()
        view.grab_focus()

    @staticmethod
    def fit(view, rect):
        x, y, width, height = (int(v) for v in rect)
        view.set_halign(Gtk.Align.START)
        view.set_valign(Gtk.Align.START)
        view.set_margin_start(x)
        view.set_margin_top(y)
        view.set_size_request(width, height)

    def site_view(self, tab, url):
        """A site's own view. All sites share one profile, kept apart from every other browser."""
        if not self.site_context:
            data = Path(GLib.get_user_data_dir()) / "adaptive-desktop" / "mario" / "web"
            cache = Path(GLib.get_user_cache_dir()) / "adaptive-desktop" / "mario-web"
            data.mkdir(parents=True, exist_ok=True)
            manager = WebKit2.WebsiteDataManager(base_data_directory=str(data), base_cache_directory=str(cache))
            self.site_context = WebKit2.WebContext.new_with_website_data_manager(manager)
            self.site_context.get_cookie_manager().set_persistent_storage(
                str(data / "cookies.sqlite"), WebKit2.CookiePersistentStorage.SQLITE)
        view = WebKit2.WebView.new_with_context(self.site_context)
        view.set_background_color(Gdk.RGBA(0.11, 0.11, 0.118, 1))

        def send(uri, new_window=False, clicked=False):
            """True when the view must not go there itself."""
            where = site_rules.route(uri, url, new_window=new_window, clicked=clicked)
            if where == site_rules.BROWSER:
                Gio.AppInfo.launch_default_for_uri(uri, None)
            elif where == site_rules.HERE:
                view.load_uri(uri)
            return where != site_rules.STAY

        def policy(_view, decision, kind):
            # signing in stays here (a sign-in page in the browser signs the browser in, not Home);
            # a link that leaves the site (a link in a mail) belongs in the browser
            if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
                action = decision.get_navigation_action()
                if send(action.get_request().get_uri(),
                        new_window=kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION,
                        clicked=action.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED):
                    decision.ignore()
                    return True
            return False

        def popup(_view, action):
            # window.open(): there is one view per tab, so the page it asks for is routed, not opened
            send(action.get_request().get_uri(), new_window=True)
            return None

        def loaded(_view, event):
            if event != WebKit2.LoadEvent.COMMITTED:
                return
            uri = view.get_uri() or ""
            sign_in = site_rules.signed_out_landing(uri, url)
            if sign_in and tab not in self.sent_to_sign_in:     # once, so it cannot go round
                self.sent_to_sign_in.add(tab)
                view.load_uri(sign_in)
                return
            was = self.signing_in.get(tab, False)
            self.signing_in[tab] = bool(sign_in) or site_rules.is_sign_in(uri, url)
            if site_rules.host(uri) == site_rules.host(url):
                self.sent_to_sign_in.discard(tab)
                if was:
                    self.signed_in(tab)

        view.connect("decide-policy", policy)
        view.connect("create", popup)
        view.connect("load-changed", loaded)
        view.connect("web-process-terminated", lambda v, *_: v.load_uri(url))
        view.tab_url = url
        view.load_uri(url)
        return view

    def signed_in(self, tab):
        """The sites share one profile: signed in on one tab, the others still showing a sign-in
        page are signed in too and only have to load again."""
        for name, view in self.sites.items():
            if name != tab and self.signing_in.get(name):
                self.sent_to_sign_in.discard(name)
                view.load_uri(view.tab_url)


class Panel(Gtk.Application):
    """Unique per session: a second launch reaches the first, which toggles."""

    def __init__(self):
        super().__init__(application_id="com.karthi.MarioPanel", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win and self.win.get_visible():
            self.win.hide()
            return
        if not self.win:
            win = Gtk.ApplicationWindow(application=self, title="Mario")
            win.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            win.set_keep_above(True)
            win.set_skip_taskbar_hint(True)
            win.connect("delete-event", lambda w, _e: (w.hide(), True)[1])
            win.connect("key-press-event", lambda w, e: (w.hide(), True)[1] if e.keyval == Gdk.KEY_Escape else False)
            win.add(make_view("/panel"))
            self.win = win
        area = workarea()
        self.win.resize(PANEL_W, area.height - 32)
        self.win.move(area.x + area.width - PANEL_W - 16, area.y + 16)
        self.win.set_opacity(0)
        self.win.show_all()
        self.win.present_with_time(Gtk.get_current_event_time() or GLib.get_monotonic_time() // 1000)
        fade_in(self.win)
        # the page slides its content in and puts the keyboard on Talk to Mario
        self.win.get_child().run_javascript("window.marioShown && window.marioShown()", None, None, None)


def main():
    args = sys.argv[1:]
    if "--panel" in args:
        return Panel().run([sys.argv[0]])
    # The autostart entry is seen by the normal Ubuntu session too, which must stay as it was:
    # Home only exists inside the Adaptive session (its wrapper sets this profile).
    if os.environ.get("DCONF_PROFILE") != "adaptive" and not os.environ.get("MARIO_ANY_SESSION"):
        print("Mario Home runs in the Adaptive Desktop session only (MARIO_ANY_SESSION=1 overrides).")
        return 0
    return Home().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
