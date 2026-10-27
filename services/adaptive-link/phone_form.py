"""Phone form factor for desktop applications in a phone session.

A phone session used to be a small desktop: apps drew at desktop density on
a display a few hundred pixels wide, and the phone stretched the picture.
Here the display is made at the phone's own size in dp, times an integer
scale, and every toolkit is told that scale. GTK and libadwaita apps then lay
themselves out as they do on a Linux phone, websites see a phone-wide
browser (and a phone's user agent) and serve their mobile pages, and text is
the size of the phone's own.

What each kind of app is told:

- GTK 3/4, LibreOffice: GDK_SCALE (integer), dark, no window buttons.
- Qt: QT_SCALE_FACTOR, with Qt Quick's mobile Material style.
- Chromium, Chrome and Electron apps: --force-device-scale-factor, no
  smaller than their minimum window allows; browsers also a phone's UA.
- Firefox: the same through its profile's user.js, with meta viewport on.
- Java, Tk and plain X11: Xft.dpi, the screen DPI and Java's uiScale.

Each app has a layout (mode):

- phone: everything at the session's scale, the app's own phone layout.
- compact: widgets at 1x and text three quarters of the scale, for desktop
  apps whose smallest window is wider than a phone (Files, LibreOffice):
  readable, and the whole window fits. Learned on an app's first launch
  when its window does not fit (Choices.learn); browsers stay mobile.
- desktop: the desktop design as it is on the laptop, a little larger, and
  a desktop user agent.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

MODES = ("phone", "compact", "desktop")
# How much of the session's scale each layout draws text at.
RATIO = {"phone": 1.0, "compact": .75, "desktop": .6}
FRAMEBUFFER = 3840
# Narrowest window each kind of app accepts, in its own logical pixels.
MIN_WIDTH = {"browser": 520, "electron": 420, "firefox": 450}
BROWSERS = ("chrome", "chromium", "brave", "vivaldi", "msedge", "microsoft-edge", "opera")
ELECTRON_APPS = ("code", "code-insiders", "codium", "antigravity", "antigravity-ide", "cursor", "slack", "discord",
                 "obsidian", "signal-desktop", "teams", "spotify", "postman", "figma-linux", "notion-app")
MARK = "# Adaptive phone session: managed"


def plan(phone):
    """The display for a phone: {"dp": [w, h], "density": d, "sharpness": "auto" | 1-3}.

    Returns the integer scale apps are drawn at and the display's size in
    pixels. "auto" is 2: sharp on any phone and a quarter of the pixels of
    drawing at a phone's full density.
    """
    if not isinstance(phone, dict):
        raise ValueError("phone must describe its screen")
    dp = phone.get("dp")
    if not isinstance(dp, list) or len(dp) != 2:
        raise ValueError("phone dp must be [width, height]")
    width, height = (max(240, min(2000, int(v))) for v in dp)
    density = max(1.0, min(5.0, float(phone.get("density", 2))))
    sharpness = phone.get("sharpness", "auto")
    if sharpness == "auto":
        scale = 2 if density >= 1.75 else 1
    else:
        scale = max(1, min(3, int(sharpness), max(1, round(density))))
    while scale > 1 and max(width, height) * scale > FRAMEBUFFER:
        scale -= 1
    return {"scale": scale, "dp": [width, height], "density": density,
            "size": [min(FRAMEBUFFER, width * scale), min(FRAMEBUFFER, height * scale)]}


def kind(argv, app_id=""):
    """browser, electron, firefox or "" for what argv starts."""
    name = Path(argv[0]).name.lower() if argv else ""
    ident = app_id.lower().removesuffix(".desktop")
    if "firefox" in name or "firefox" in ident:
        return "firefox"
    if any(word in name or word in ident for word in BROWSERS):
        return "browser"
    if name in ELECTRON_APPS or any(ident == word or ident.startswith(word + "_") or ident.endswith("." + word) for word in ELECTRON_APPS):
        return "electron"
    found = shutil.which(argv[0]) if argv else None
    if found:
        real = Path(os.path.realpath(found))
        # Electron and Chromium ship this beside their executable; a wrapper
        # script one or two levels down (VS Code's bin/code) finds it above.
        for folder in (real.parent, real.parent.parent, real.parent.parent.parent):
            if (folder / "chrome_100_percent.pak").exists() or (folder / "resources" / "app.asar").exists():
                return "electron"
    return ""


def factor(scale, mode, short_side, minimum):
    """A fractional device scale no larger than the window can be drawn at."""
    wanted = scale * RATIO.get(mode, 1.0)
    fit = short_side / minimum if minimum else wanted
    return round(max(1.0, min(wanted, fit)), 2)


def environment(scale, mode="phone"):
    """Variables every app in the session is started with."""
    if mode not in MODES:
        mode = "phone"
    phone = mode == "phone"
    gdk = scale if phone else 1
    # GDK_SCALE is whole numbers only; the rest of the scale goes to text.
    text = 1 if phone else round(max(1.0, scale * RATIO[mode]), 2)
    qt = scale if phone else text
    env = {
        "GDK_SCALE": str(gdk), "GDK_DPI_SCALE": str(text),
        "QT_SCALE_FACTOR": str(qt), "QT_AUTO_SCREEN_SCALE_FACTOR": "0", "QT_ENABLE_HIGHDPI_SCALING": "0",
        "QT_QUICK_CONTROLS_STYLE": "Material", "QT_QUICK_CONTROLS_MATERIAL_THEME": "Dark",
        "QT_QUICK_CONTROLS_MOBILE": "1" if phone else "0",
        "XCURSOR_SIZE": str(24 * scale), "GTK_OVERLAY_SCROLLING": "1", "MOZ_USE_XINPUT2": "1",
        "ADAPTIVE_PHONE_SCALE": str(scale), "ADAPTIVE_PHONE_MODE": mode,
    }
    # Java draws at the scale it is given and ignores GDK_SCALE before 9.
    java = os.environ.get("_JAVA_OPTIONS", "")
    env["_JAVA_OPTIONS"] = (java + " " if java else "") + f"-Dsun.java2d.uiScale={qt}"
    return env


def user_agent(which, mode, version):
    if which == "firefox":
        return (f"Mozilla/5.0 (Android 14; Mobile; rv:{version}.0) Gecko/{version}.0 Firefox/{version}.0" if mode != "desktop"
                else f"Mozilla/5.0 (X11; Linux x86_64; rv:{version}.0) Gecko/20100101 Firefox/{version}.0")
    return f"Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Mobile Safari/537.36"


def browser_version(argv, fallback):
    """The major version the browser reports, so sites see a current one."""
    try:
        out = subprocess.run([argv[0], "--version"], capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return fallback
    found = re.search(r"(\d{2,4})\.\d+", out)
    return int(found.group(1)) if found else fallback


def firefox_version(profile, fallback=140):
    try:
        text = (Path(profile) / "compatibility.ini").read_text()
    except OSError:
        return fallback
    found = re.search(r"^LastVersion=(\d+)", text, re.M)
    return int(found.group(1)) if found else fallback


def firefox_prefs(profile, scale, mode, short_side):
    """Writes the managed user.js: Firefox reads it over its prefs at each start."""
    ratio = factor(scale, mode, short_side, MIN_WIDTH["firefox"])
    phone = mode != "desktop"
    prefs = {
        "layout.css.devPixelsPerPx": str(ratio),
        "general.useragent.override": user_agent("firefox", mode, firefox_version(profile)),
        # What makes Firefox for Android lay a page out at the device's width.
        "dom.meta-viewport.enabled": phone,
        "browser.uidensity": 2 if phone else 0,
        "dom.w3c_touch_events.enabled": 1 if phone else 2,
        "apz.allow_zooming": True,
        "browser.tabs.inTitlebar": 1,
        "ui.systemUsesDarkTheme": 1,
        "browser.aboutwelcome.enabled": False,
        "browser.shell.checkDefaultBrowser": False,
        "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
        # For userChrome.css below.
        "toolkit.legacyUserProfileCustomizations.stylesheets": True,
    }
    lines = [MARK] + [f"user_pref({json.dumps(k)}, {json.dumps(v)});" for k, v in prefs.items()]
    path = Path(profile) / "user.js"
    if path.exists() and not path.read_text().startswith(MARK):
        return False   # the owner's own user.js is left alone
    path.write_text("\n".join(lines) + "\n")
    style = Path(profile) / "chrome" / "userChrome.css"
    style.parent.mkdir(exist_ok=True)
    if not style.exists() or style.read_text().startswith("/* " + MARK):
        style.write_text(FIREFOX_CHROME if phone else "/* " + MARK + " */\n")
    return True


# Firefox's toolbars ask for a window wider than a phone; on a phone the
# address bar shares the row with the buttons and the bookmarks bar is gone.
FIREFOX_CHROME = """/* """ + MARK + """ */
:root, #main-window { min-width: 0 !important; }
#nav-bar, #TabsToolbar, #nav-bar-customization-target { min-width: 0 !important; }
#urlbar-container { min-width: 120px !important; width: auto !important; flex: 1 1 auto !important; }
#urlbar, #urlbar-input-container { min-width: 0 !important; }
#PersonalToolbar, #firefox-view-button, .titlebar-spacer, #alltabs-button, #fxa-toolbar-menu-button,
.titlebar-buttonbox-container { display: none !important; }
.tabbrowser-tab:not([pinned]) { min-width: 64px !important; }
"""


def adapt(argv, app_id, profile, env):
    """The launch arguments for this app's toolkit, at the session's scale."""
    scale = int(env.get("ADAPTIVE_PHONE_SCALE", "1"))
    mode = env.get("ADAPTIVE_PHONE_MODE", "phone")
    short_side = int(env.get("ADAPTIVE_PHONE_SHORT", "0")) or 800
    which = kind(argv, app_id)
    if which == "firefox":
        firefox_prefs(profile, scale, mode, short_side)
        # Firefox multiplies GTK's scale by its own: only its own counts.
        env.update(GDK_SCALE="1", GDK_DPI_SCALE="1")
    elif which in ("browser", "electron"):
        argv = argv + [f"--force-device-scale-factor={factor(scale, mode, short_side, MIN_WIDTH[which])}"]
        if which == "browser":
            argv += ["--hide-crash-restore-bubble", "--disable-features=Translate"]
            if mode != "desktop":
                argv.append("--user-agent=" + user_agent("browser", mode, browser_version(argv, 140)))
    return argv


GTK = """{mark}
[Settings]
gtk-application-prefer-dark-theme=1
gtk-decoration-layout={layout}
gtk-cursor-theme-size={cursor}
gtk-primary-button-warps-slider=false
gtk-enable-animations=true
"""


def prepare(config, scale):
    """GTK's own settings for the session (only files this module made)."""
    for version in ("gtk-3.0", "gtk-4.0"):
        path = Path(config) / version / "settings.ini"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not path.read_text().startswith(MARK):
            continue
        # The phone closes and switches apps itself: no window buttons.
        path.write_text(GTK.format(mark=MARK, layout="menu:", cursor=24 * scale))


def settings_commands(scale):
    """Commands run once in the session: its own dconf and X resources."""
    return [
        ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", "prefer-dark"],
        ["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(24 * scale)],
        ["gsettings", "set", "org.gnome.desktop.wm.preferences", "button-layout", "appmenu:"],
    ]


def resources(scale):
    return f"Xft.dpi: {96 * scale}\nXcursor.size: {24 * scale}\nXft.antialias: 1\nXft.hinting: 1\nXft.hintstyle: hintslight\nXft.rgba: none\n"


class Choices:
    """The layout of each app on one phone, kept with its sessions.

    chosen is what the owner picked and always wins; learned is what a
    launch found (an app too wide for the phone layout)."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        clean = lambda part: {k: v for k, v in (part if isinstance(part, dict) else {}).items() if isinstance(k, str) and v in MODES}
        return {"chosen": clean(data.get("chosen")), "learned": clean(data.get("learned"))}

    def mode(self, app_id):
        data = self.load()
        return data["chosen"].get(app_id) or data["learned"].get(app_id) or "phone"

    def chosen(self, app_id):
        return app_id in self.load()["chosen"]

    def effective(self):
        data = self.load()
        return {**data["learned"], **data["chosen"]}

    def set(self, app_id, mode):
        if mode not in MODES:
            raise ValueError("layout must be phone, compact or desktop")
        return self.save(app_id, mode, "chosen")

    def learn(self, app_id, mode):
        return self.save(app_id, mode, "learned")

    def save(self, app_id, mode, part):
        data = self.load()
        data[part][app_id] = mode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        os.replace(tmp, self.path)
        return data
