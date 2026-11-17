"""Mario's hands: carries out the commands commands.parse() finds. Each returns {"ok", "answer"}.

Everything goes through something that already exists and is already bounded: the shell's own
D-Bus bridge (org.adaptive.Shell: fixed action names), the Kinect hub's HTTP API (127.0.0.1),
the Cast command line, Air's start script, pactl, MPRIS, gsettings, the app grid's own launcher.
Nothing here runs a command line that was spoken: names are matched against what is installed.

The outside world comes in as two functions, so the checks can stand in for it:
    sh(argv, wait=True, timeout=10) -> (code, stdout)
    http(method, url, body=None, timeout=5) -> parsed JSON, bytes, or None
"""

import difflib
import json
import os
import re
import time
from pathlib import Path

import commands

REPO = Path(__file__).resolve().parents[2]
HUB = "http://127.0.0.1:8792"
SHELL = ["gdbus", "call", "--session", "-d", "org.gnome.Shell", "-o", "/org/adaptive/Shell"]
CAST = str(REPO / "scripts" / "adaptive-cast-launch.sh")
AIR = str(REPO / "scripts" / "adaptive-air.sh")
STUDIO = str(REPO / "apps" / "kinect-studio" / "studio.py")
CHEATSHEET_URL = "http://127.0.0.1:8791/commands"
SNAPSHOTS = Path.home() / "Pictures" / "Kinect"


def _words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def sounds(text):
    """A rough key for how a word sounds, so a name heard with a different accent (or spelled the
    way speech recognition heard it) still meets the app: spotifai, spotty fy -> spotify."""
    t = re.sub(r"[^a-z]", "", (text or "").lower())
    for a, b in (("ph", "f"), ("ck", "k"), ("ch", "k"), ("sh", "s"), ("th", "t"), ("q", "k"), ("x", "ks"),
                 ("z", "s"), ("w", "v"), ("ai", "i"), ("ay", "i"), ("ie", "i"), ("ee", "i"), ("ea", "i"),
                 ("oo", "u"), ("ou", "u")):
        t = t.replace(a, b)
    t = re.sub(r"c(?=[eiy])", "s", t).replace("c", "k")
    t = t.replace("y", "i")
    t = re.sub(r"(?<=.)h", "", t)              # a soft h after another sound
    t = re.sub(r"(.)\1+", r"\1", t)            # doubled letters
    return t[:1] + re.sub(r"[aeiou]+", "a", t[1:])   # vowels are where accents differ most


def _close(a, b):
    """How alike two spellings are, 0..1."""
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _names(app):
    """What an app can be called: its name, the first words of it, its command."""
    words = _words(app.get("name"))
    out = {"".join(words[:n]) for n in range(1, len(words) + 1)}
    out |= {w for w in _words(app.get("exec")) if len(w) > 3}
    return {n for n in out if len(n) >= 3}


def match_app(name, apps, strict=False):
    """The installed app a spoken name means, or None.

    apps: [{"id", "name", "keywords": [...], "exec"}]. Exact name first, then the name starting
    with what was said, then every spoken word in its name, keywords or command; then, for a name
    that was misheard or said with another accent, the closest name by spelling and by sound.
    strict: only an app the words clearly name (an app said on its own, with no "open").
    """
    said = " ".join(_words(name))
    joined = said.replace(" ", "")
    if len(joined) < 3:                  # "open up" names nothing
        return None
    best, best_score = None, 0
    for app in apps:
        title = " ".join(_words(app.get("name")))
        extra = " ".join(_words(" ".join(app.get("keywords") or []) + " " + (app.get("exec") or "") +
                                " " + (app.get("id") or "")))
        if title == said:
            score = 100
        elif title.replace(" ", "") == joined or joined in _names(app):
            score = 90                     # "fire fox", "spot ify": the words run together
        elif title.startswith(said) and not strict:
            score = 80
        elif said in title and not strict:
            score = 60
        elif all(w in (title + " " + extra).split() for w in said.split()) and not strict:
            score = 40
        else:
            # Misheard: the closest of its names, by spelling, or by sound when the spelling is not
            # far off either ("firefocks"). Short names must be very close: "open sesame" is not
            # System Monitor, "open the door" is not To Do.
            bar = 0.9 if strict else (0.86 if len(joined) <= 5 else 0.78)
            close = 0.0
            for n in _names(app):
                spelt, sound = _close(joined, n), _close(sounds(joined), sounds(n))
                if spelt >= bar or (sound >= (0.95 if strict else 0.9) and spelt >= 0.7):
                    close = max(close, spelt, sound - 0.04)
            if not close:
                continue
            score = 20 + close * 10
        score -= len(title) / 100          # the shorter of two matches: "Files" over "Files Backup"
        if score > best_score:
            best, best_score = app, score
    return best


class CachedApps:
    """installed_apps(), read again only when a minute has passed: launching waits for nothing."""

    def __init__(self, read=None, every=60):
        self.read, self.every = read or installed_apps, every
        self.apps, self.at = None, 0.0

    def __call__(self):
        if self.apps is None or time.monotonic() - self.at > self.every:
            try:
                self.apps, self.at = self.read(), time.monotonic()
            except Exception:  # noqa: BLE001  no app grid (no session): nothing to match
                self.apps, self.at = self.apps or [], time.monotonic()
        return self.apps


def vocabulary(apps, most=40):
    """App names for the recogniser to listen for (it then hears "Spotify", not "spot if I")."""
    names = []
    for app in apps:
        words = (app.get("name") or "").split()
        if 0 < len(words) <= 2 and len(app["name"]) <= 24 and app["name"] not in names:
            names.append(app["name"])
    return ", ".join(["Mario"] + names[:most])


def installed_apps():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    out = []
    for info in Gio.AppInfo.get_all():
        if not info.should_show():
            continue
        keywords = info.get_keywords() if hasattr(info, "get_keywords") else []
        out.append({"id": info.get_id() or "", "name": info.get_display_name() or info.get_name() or "",
                    "keywords": list(keywords or []), "exec": info.get_executable() or ""})
    return out


def match_window(name, windows):
    said = " ".join(_words(name))
    for w in windows:
        if said and (said in " ".join(_words(w.get("appName"))) or said in " ".join(_words(w.get("title")))):
            return w
    # a misheard name meets its window the way it meets its app
    app = match_app(said, [{"id": str(i), "name": w.get("appName") or ""} for i, w in enumerate(windows)])
    return windows[int(app["id"])] if app else None


class Control:
    def __init__(self, sh, http, launch=None, open_url=None, apps=installed_apps, launchers=()):
        self.sh, self.http = sh, http
        self.launch = launch or (lambda name: {"ok": False})
        self.launchers = set(launchers)    # the names launch() knows, for knows()
        self.open_url = open_url or (lambda url: self.sh(["xdg-open", url], wait=False))
        self.apps = apps

    def knows(self, name, strict=False):
        """Would "open <name>" open something? Pure: nothing is launched (the voice asks this to
        stop listening as soon as a command is complete)."""
        key = " ".join(_words(name))
        if not key:
            return False
        if not strict and (key in self.launchers or key in ("kinect", "kinect studio")):
            return True
        return bool(commands.SITES.get(key)) or match_app(key, self.apps(), strict=strict) is not None

    def run(self, cmd):
        intent = cmd["intent"]
        handler = getattr(self, "do_" + intent.replace(".", "_").replace("-", "_"), None)
        if handler is None:
            return {"ok": False, "answer": "I don't know how to do that yet."}
        try:
            return handler(**cmd.get("args", {}))
        except Exception as err:          # one failing command never takes Mario down
            return {"ok": False, "answer": f"That didn't work: {err}"}

    @staticmethod
    def said(answer, ok=True):
        return {"ok": ok, "answer": answer}

    # ---------------------------------------------------------------- help
    def do_help(self):
        self.open_url(CHEATSHEET_URL)
        groups = ", ".join(title.lower() for title, _ in commands.CHEATSHEET[1:])
        return self.said(f"Here's everything you can say. In short: {groups}. Try \"how tall am I\", "
                         "\"connect to my TV\", or \"open Spotify\".")

    # ---------------------------------------------------------------- the Kinect
    def _hub(self):
        """Make sure the Kinect hub is running; the status, or None."""
        status = self.http("GET", HUB + "/api/status", timeout=1)
        if isinstance(status, dict):
            return status
        self.sh(["systemctl", "--user", "start", "adaptive-kinect.service"])
        for _ in range(40):
            status = self.http("GET", HUB + "/api/status", timeout=1)
            if isinstance(status, dict):
                return status
            time.sleep(0.15)
        return None

    def _kinect_ready(self):
        status = self._hub()
        if status is None:
            return None, self.said("The Kinect hub isn't installed. Run scripts/install-air.sh.", False)
        if status.get("status") in ("unpowered", "no-kinect"):
            return None, self.said(status.get("error") or "The Kinect isn't connected.", False)
        return status, None

    def do_kinect_height(self):
        _, problem = self._kinect_ready()
        if problem:
            return problem
        r = self.http("GET", HUB + "/api/measure", timeout=20)
        if not isinstance(r, dict):
            return self.said("The Kinect didn't answer.", False)
        return self.said(r.get("sentence") or r.get("error") or "I couldn't measure you.", bool(r.get("ok")))

    def do_kinect_distance(self):
        _, problem = self._kinect_ready()
        if problem:
            return problem
        r = self.http("GET", HUB + "/api/measure?seconds=2", timeout=20)
        if not isinstance(r, dict) or r.get("distance") is None:
            return self.said((r or {}).get("error") or "I can't see you.", False)
        return self.said(f"You're {r['distance']:.1f} metres from the Kinect.")

    def do_kinect_people(self):
        _, problem = self._kinect_ready()
        if problem:
            return problem
        r = self.http("GET", HUB + "/api/measure?seconds=2", timeout=20)
        if not isinstance(r, dict):
            return self.said("The Kinect didn't answer.", False)
        return self.said(r.get("count_sentence") or r.get("error") or "I can't see anyone.", True)

    def do_kinect_studio(self):
        self.sh(["python3", STUDIO], wait=False)
        return self.said("Opening Kinect Studio.")

    def _post(self, name, value):
        return self.http("POST", f"{HUB}/api/{name}", {"value": value}, timeout=3)

    def do_kinect_tilt(self, to=None, by=None):
        status, problem = self._kinect_ready()
        if problem:
            return problem
        if to is None:
            to = (status.get("tilt") or 0) + (by or 0)
        to = max(-27, min(27, int(round(to))))
        self._post("tilt", to)
        return self.said(f"Tilting the Kinect to {to} degrees." if to else "Levelling the Kinect.")

    def do_kinect_level(self):
        return self.do_kinect_tilt(to=0)

    def do_kinect_led(self, colour):
        _, problem = self._kinect_ready()
        if problem:
            return problem
        self._post("led", colour)
        return self.said("Kinect light off." if colour == "off" else f"Kinect light {colour.replace('-', ' ')}.")

    def do_kinect_ir(self, on):
        _, problem = self._kinect_ready()
        if problem:
            return problem
        if on is None:
            self._post("video", "auto")
            return self.said("Night vision on its own: colour while the room is lit, infrared in the dark.")
        self._post("video", "ir" if on else "rgb")
        return self.said("Night vision on: the infrared camera." if on else "Back to the colour camera.")

    def do_kinect_webcam(self, on):
        _, problem = self._kinect_ready()
        if problem:
            return problem
        self._post("webcam", bool(on))
        if not on:
            return self.said("The Kinect webcam is off.")
        status = self.http("GET", HUB + "/api/status", timeout=2) or {}
        if not (status.get("webcam") or {}).get("device"):
            return self.said("The Kinect webcam needs a one-time setup: run scripts/install-virtual-cameras.sh "
                             "in a terminal (it asks for your password).", False)
        return self.said("The Kinect is your webcam now: pick Kinect Camera in your call.")

    def do_kinect_snapshot(self):
        _, problem = self._kinect_ready()
        if problem:
            return problem
        data = self.http("GET", HUB + "/cloud.ply", timeout=10)
        if not isinstance(data, (bytes, bytearray)) or not data.startswith(b"ply"):
            return self.said("I couldn't get a 3D picture from the Kinect.", False)
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOTS / time.strftime("kinect-%Y%m%d-%H%M%S.ply")
        path.write_bytes(data)
        return self.said(f"Saved a 3D scan to Pictures/Kinect, {path.name}.")

    def do_air_on(self):
        code, _ = self.sh([AIR, "--start"])
        return self.said("Gestures on. Raise an open palm to take control." if code == 0
                         else "Air isn't installed. Run scripts/install-air.sh.", code == 0)

    def do_air_off(self):
        self.sh([AIR, "--stop"])
        return self.said("Gestures off.")

    def do_air_demo(self):
        self.sh([AIR, "--demo"], wait=False)
        return self.said("Playing the gesture demo.")

    # ---------------------------------------------------------------- TV
    def _casting(self):
        state = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "adaptive-cast.json"
        try:
            return json.loads(state.read_text()).get("state") in (
                "preparing", "connecting", "negotiating", "streaming", "reconnecting")
        except (OSError, ValueError):
            return False

    def do_tv_cast(self):
        if self._casting():
            return self.said("You're already on the TV.")
        self.sh([CAST, "--toggle"], wait=False)
        return self.said("Connecting to your TV.")

    def do_tv_cast_window(self):
        self.sh([CAST, "--show", "window"] + ([] if self._casting() else ["--toggle"]), wait=False)
        return self.said("Putting this window on the TV.")

    def do_tv_stop(self):
        self.sh([CAST, "--stop"], wait=False)
        return self.said("Stopped casting.")

    def do_tv_on(self):
        self.sh([CAST, "--tv", "on"], wait=False)
        return self.said("Turning on the TV.")

    def do_tv_off(self):
        self.sh([CAST, "--tv", "off"], wait=False)
        return self.said("Turning off the TV.")

    def do_tv_volume(self, step=None, level=None):
        if level is not None:
            self.sh([CAST, "--tv-volume", str(max(0, min(100, int(level))))], wait=False)
            return self.said(f"TV volume {level}.")
        self.sh([CAST, "--tv", "volume-up" if step == "up" else "volume-down"], wait=False)
        return self.said("TV volume up." if step == "up" else "TV volume down.")

    def do_tv_mute(self, mute):
        self.sh([CAST, "--tv", "mute" if mute else "unmute"], wait=False)
        return self.said("TV muted." if mute else "TV unmuted.")

    def do_tv_wall(self):
        self.sh([CAST, "--wall"], wait=False)
        return self.said("Showing the clock on the TV.")

    # ---------------------------------------------------------------- windows and apps
    def _window(self, action, wid=0):
        code, out = self.sh(SHELL + ["-m", "org.adaptive.Shell.WindowAction", str(int(wid)), action])
        return code == 0 and "true" in out

    def _windows(self):
        code, out = self.sh(SHELL + ["-m", "org.adaptive.Shell.ListWindows"])
        m = re.match(r"\('(.*)',\)\s*$", out.strip(), re.S)
        try:
            return json.loads(m[1].replace("\\'", "'")) if code == 0 and m else []
        except ValueError:
            return []

    def _window_command(self, action, done):
        return self.said(done) if self._window(action) else self.said("There's no window to do that to.", False)

    def do_window_maximize(self):
        return self._window_command("maximize", "Maximised.")

    def do_window_minimize(self):
        return self._window_command("minimize", "Minimised.")

    def do_window_fullscreen(self):
        return self._window_command("fullscreen", "Full screen.")

    def do_window_tile(self, side):
        return self._window_command("tile-" + side, f"To the {side}.")

    def do_window_center(self):
        return self._window_command("center", "Centred.")

    def do_window_to_desktop(self, way):
        return self._window_command("to-workspace-" + way,
                                    "Moved it to the next desktop." if way == "right" else "Moved it to the previous desktop.")

    def do_app_close(self, name=None):
        if not name:
            return self._window_command("close", "Closed.")
        w = match_window(name, self._windows())
        if not w:
            return self.said(f"{name.capitalize()} isn't open.", False)
        self._window("close", w["id"])
        return self.said(f"Closed {w.get('appName') or name}.")

    def do_app_focus(self, name):
        w = match_window(name, self._windows())
        if w:
            self._window("focus", w["id"])
            return self.said(f"Here's {w.get('appName') or name}.")
        return self.do_app_open(name)        # not open yet: open it (or answer as usual)

    def do_app_maybe(self, name):
        """A few words that might be an app said on its own ("Spotify"): open it only when the words
        clearly name one; anything else is answered as usual."""
        key = " ".join(_words(name))
        if commands.SITES.get(key):
            self.open_url(commands.SITES[key])
            return self.said(f"Opening {name}.")
        app = match_app(key, self.apps(), strict=True)
        if not app:
            return {"ok": False, "answer": "", "fallthrough": True}
        self.sh(["gtk-launch", re.sub(r"\.desktop$", "", app["id"])], wait=False)
        return self.said(f"Opening {app['name']}.")

    def do_app_open(self, name):
        key = " ".join(_words(name))
        if key in ("kinect", "kinect studio"):
            return self.do_kinect_studio()
        result = self.launch(key)
        if result.get("ok"):
            return self.said(f"Opening {name}.")
        if key in commands.SITES and commands.SITES[key]:
            self.open_url(commands.SITES[key])
            return self.said(f"Opening {name}.")
        app = match_app(key, self.apps())
        if not app:
            # Not an app: let Mario answer the sentence as usual.
            return {"ok": False, "answer": f"I couldn't find an app called {name}.", "fallthrough": True}
        self.sh(["gtk-launch", re.sub(r"\.desktop$", "", app["id"])], wait=False)
        return self.said(f"Opening {app['name']}.")

    # ---------------------------------------------------------------- desktops
    def _shell_run(self, action):
        code, out = self.sh(SHELL + ["-m", "org.adaptive.Shell.Run", action])
        return code == 0 and "true" in out

    def do_desk_next(self):
        self._shell_run("workspace-right")
        return self.said("Next desktop.")

    def do_desk_previous(self):
        self._shell_run("workspace-left")
        return self.said("Previous desktop.")

    def do_desk_go(self, n):
        code, out = self.sh(SHELL + ["-m", "org.adaptive.Shell.ActivateWorkspace", str(int(n) - 1)])
        ok = code == 0 and "true" in out
        return self.said(f"Desktop {n}." if ok else f"There's no desktop {n}.", ok)

    def do_desk_overview(self):
        self._shell_run("overview")
        return self.said("Here are all your windows.")

    def do_desk_apps(self):
        self._shell_run("app-grid")
        return self.said("All your apps.")

    def do_desk_show_desktop(self):
        _, out = self.sh(["wmctrl", "-m"])
        showing = "showing the desktop\" mode: ON" in out
        self.sh(["wmctrl", "-k", "off" if showing else "on"])
        return self.said("Windows back." if showing else "Here's the desktop.")

    def do_desk_notifications(self):
        self._shell_run("notifications")
        return self.said("Your notifications.")

    def do_desk_control_center(self):
        self._shell_run("control-center")
        return self.said("Control center.")

    def do_desk_dropdown(self):
        self._shell_run("dropdown-terminal")
        return self.said("Terminal.")

    def do_desk_palette(self):
        self.sh([str(REPO / "scripts" / "adaptive-command-launch.sh")], wait=False)
        return self.said("The palette.")

    def do_desk_lock(self):
        self.sh(["loginctl", "lock-session"])
        return self.said("Locked.")

    # ---------------------------------------------------------------- sound and media
    def do_sys_volume(self, step=None, level=None):
        if level is not None:
            level = max(0, min(150, int(level)))
            self.sh(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
            return self.said(f"Volume {level}.")
        self.sh(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        self.sh(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%" if step == "up" else "-10%"])
        return self.said("Louder." if step == "up" else "Quieter.")

    def do_sys_mute(self, mute):
        self.sh(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0"])
        return self.said("Muted." if mute else "Sound on.")

    def _players(self):
        code, out = self.sh(["gdbus", "call", "--session", "-d", "org.freedesktop.DBus", "-o", "/org/freedesktop/DBus",
                             "-m", "org.freedesktop.DBus.ListNames"])
        return re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", out) if code == 0 else []

    def do_media(self, what):
        players = self._players()
        if not players:
            return self.said("Nothing is playing.", False)
        playing = [p for p in players if "Playing" in self.sh(
            ["gdbus", "call", "--session", "-d", p, "-o", "/org/mpris/MediaPlayer2", "-m",
             "org.freedesktop.DBus.Properties.Get", "org.mpris.MediaPlayer2.Player", "PlaybackStatus"])[1]]
        target = (playing or players)[0]
        self.sh(["gdbus", "call", "--session", "-d", target, "-o", "/org/mpris/MediaPlayer2", "-m",
                 f"org.mpris.MediaPlayer2.Player.{what}"])
        return self.said({"Pause": "Paused.", "Play": "Playing.", "PlayPause": "OK.", "Next": "Next.",
                          "Previous": "Previous."}[what])

    def do_sys_screenshot(self):
        self.launch("screenshot")
        return self.said("Select what to capture.")

    def do_sys_dnd(self, on):
        self.sh(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "false" if on else "true"])
        return self.said("Do not disturb is on." if on else "Notifications are back on.")

    # ---------------------------------------------------------------- the web
    def do_web_search(self, q):
        from urllib.parse import quote_plus
        self.open_url("https://www.google.com/search?q=" + quote_plus(q))
        return self.said(f"Searching for {q}.")

    def do_web_open(self, url):
        self.open_url(url)
        return self.said(f"Opening {url.split('//', 1)[-1]}.")
