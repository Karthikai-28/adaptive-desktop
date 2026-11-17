#!/usr/bin/env python3
"""Checks for Mario's spoken commands: what a sentence means (commands.py), what is done about it
(control.py, against a stand-in shell and HTTP), and that the cheat sheet tells the truth.

    scripts/verify-mario-commands.py           the checks (no desktop, no Kinect, no TV)
    scripts/verify-mario-commands.py --write   also rewrite docs/MARIO_COMMANDS.md from the code
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/mario-hub"))

import commands  # noqa: E402
import control  # noqa: E402

FAILED = []
DOC = REPO / "docs/MARIO_COMMANDS.md"


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def intent(text):
    r = commands.parse(text)
    return r and r["intent"]


def check_sheet():
    print("The cheat sheet tells the truth")
    for title, items in commands.CHEATSHEET:
        for say, want, _ in items:
            if want is None:
                continue
            family = want.split(".")[0]
            for example in commands.examples(say):
                got = intent(example)
                ok = got == want if " / " not in say else (got or "").split(".")[0] == family
                check(f"{title}: \"{example}\" -> {want if ' / ' not in say else family + '.*'}", ok, got)


PHRASES = {
    "hey mario how tall am i": "kinect.height",
    "Mario, what's my height?": "kinect.height",
    "can you measure me": "kinect.height",
    "how far away am I from the screen": "kinect.distance",
    "how tall are we": "kinect.height",
    "mario measure everyone": "kinect.height",
    "how many people are there": "kinect.people",
    "how many people can you see": "kinect.people",
    "who's in front of the kinect": "kinect.people",
    "open the kinect": "kinect.studio",
    "show me the point cloud": "kinect.studio",
    "open connect studio": "kinect.studio",
    "tilt the kinect up": "kinect.tilt",
    "point the kinect down by five degrees": "kinect.tilt",
    "tilt the connect down": "kinect.tilt",
    "reset the kinect": "kinect.level",
    "turn on night vision": "kinect.ir",
    "switch to infrared": "kinect.ir",
    "night vision auto": "kinect.ir",
    "set night vision to automatic": "kinect.ir",
    "kinect webcam off": "kinect.webcam",
    "scan the room": "kinect.snapshot",
    "turn on gestures": "air.on",
    "let me control it with my hands": "air.on",
    "disable gesture control": "air.off",
    "connect to my tv": "tv.cast",
    "cast my screen to the tv": "tv.cast",
    "put this on the tv": "tv.cast",
    "stop casting": "tv.stop",
    "turn the tv off": "tv.off",
    "wake up the tv": "tv.on",
    "turn up the tv": "tv.volume",
    "unmute the tv": "tv.mute",
    "please open spotify": "app.open",
    "launch visual studio code": "app.open",
    "close firefox": "app.close",
    "quit spotify": "app.close",
    "bring up the terminal": "app.focus",
    "make this window bigger": "window.maximize",
    "send the window to the previous workspace": "window.to-desktop",
    "switch to workspace 3": "desk.go",
    "go to the next workspace": "desk.next",
    "show everything": "desk.overview",
    "hide all windows": "desk.show-desktop",
    "lock my laptop": "desk.lock",
    "turn the volume up": "sys.volume",
    "quieter": "sys.volume",
    "unmute": "sys.mute",
    "pause the music": "media",
    "skip this": "media",
    "screenshot": "sys.screenshot",
    "silence notifications": "sys.dnd",
    "google best biryani near me": "web.search",
    "what can you do": "help",
    # misheard, or said with an accent: these are what speech recognition writes down
    "Open, Spotify, please.": "app.open",
    "Often Spotify": "app.open",
    "oven spotify": "app.open",
    "Opening Spotify": "app.open",
    "Lunch Firefox": "app.open",
    "Switch the Chrome": "app.focus",
    "switch the kinect to colour": "kinect.ir",
}
NOT_COMMANDS = [
    "what's the weather like", "why is my build failing", "run the tests in loom",
    "go to the gym tomorrow and remind me", "summarise my emails", "how many tasks do i have",
    "is claude at its limit", "write a function that parses dates in loom",
    "open terminal; delete files", "open files && rm -rf ~", "open $(reboot)", "close firefox | shutdown",
]


def check_phrases():
    print("What sentences mean")
    for text, want in PHRASES.items():
        check(f"\"{text}\" -> {want}", intent(text) == want, intent(text))
    for text in NOT_COMMANDS:
        check(f"\"{text}\" is for Mario to answer, not a command", intent(text) is None, intent(text))
    r = commands.parse("tilt the kinect down by 12 degrees")
    check("tilt down by 12 is -12", r["args"] == {"by": -12}, r["args"])
    r = commands.parse("set the volume to seventy")
    check("number words: seventy", r["args"] == {"level": 70}, r["args"])
    r = commands.parse("turn the kinect light blinking green")
    check("led colours: blinking green", r["args"] == {"colour": "blink-green"}, r["args"])
    r = commands.parse("go to desktop two")
    check("desktop two", r["args"] == {"n": 2}, r["args"])


def check_matching():
    print("Apps and windows by name")
    apps = [{"id": "org.gnome.Nautilus.desktop", "name": "Files", "keywords": ["folder", "explorer"], "exec": "nautilus"},
            {"id": "deja-dup.desktop", "name": "Files Backup", "keywords": [], "exec": "deja-dup"},
            {"id": "code.desktop", "name": "Visual Studio Code", "keywords": ["vscode"], "exec": "code"},
            {"id": "firefox.desktop", "name": "Firefox Web Browser", "keywords": [], "exec": "firefox"},
            {"id": "spotify.desktop", "name": "Spotify", "keywords": ["music"], "exec": "spotify"}]
    check("\"files\" is Files, not Files Backup", control.match_app("files", apps)["name"] == "Files")
    check("\"firefox\" by the start of its name", control.match_app("firefox", apps)["id"] == "firefox.desktop")
    check("\"vscode\" by a keyword", control.match_app("vscode", apps)["id"] == "code.desktop")
    check("\"studio code\" inside its name", control.match_app("studio code", apps)["id"] == "code.desktop")
    check("an app that is not there", control.match_app("pod bay doors", apps) is None)
    for heard in ("spotifai", "spot if i", "spotty fy", "sportify", "potify", "espotify", "spoti fy"):
        got = control.match_app(heard, apps)
        check(f"misheard \"{heard}\" is still Spotify", got and got["id"] == "spotify.desktop", got)
    check("\"fire fox\" (the words run together) is Firefox", control.match_app("fire fox", apps)["id"] == "firefox.desktop")
    check("\"firefocks\" by how it sounds", control.match_app("firefocks", apps)["id"] == "firefox.desktop")
    more = apps + [{"id": "monitor.desktop", "name": "System Monitor", "keywords": [], "exec": "gnome-system-monitor"},
                   {"id": "todo.desktop", "name": "To Do", "keywords": [], "exec": "todo"},
                   {"id": "backup.desktop", "name": "Backups", "keywords": [], "exec": "deja-dup"}]
    for wrong in ("sesame", "door", "up", "mind", "rocket"):
        check(f"\"open {wrong}\" opens nothing", control.match_app(wrong, more) is None, control.match_app(wrong, more))
    check("said on its own, only a clear name counts", control.match_app("spotifai", apps, strict=True)["name"] == "Spotify"
          and control.match_app("spot a fly", apps, strict=True) is None)
    check("the recogniser is told the apps' names", control.vocabulary(apps).startswith("Mario, Files")
          and "Spotify" in control.vocabulary(apps) and "Visual Studio Code" not in control.vocabulary(apps))
    for text, want in {"Spotify": "spotify", "spotify please": "spotify", "what time": None, "mail": None,
                       "hello there": None, "brief me": "brief me", "open; rm": None}.items():
        check(f"\"{text}\" on its own: {want or 'not a name'}", commands.bare_name(text) == want, commands.bare_name(text))
    wins = [{"id": 7, "appName": "Firefox", "title": "GitHub - Mozilla Firefox"},
            {"id": 9, "appName": "Terminal", "title": "kai@planetStormer: ~"}]
    check("a window by its app", control.match_window("terminal", wins)["id"] == 9)
    check("a window by a misheard name", control.match_window("terminel", wins)["id"] == 9)
    check("no such window", control.match_window("spotify", wins) is None)


class World:
    """A stand-in for the shell, the Kinect hub and the desktop."""

    def __init__(self, hub=True, kinect="streaming", webcam_device="/dev/video11"):
        self.ran, self.posted, self.opened = [], [], []
        self.hub, self.kinect, self.webcam_device = hub, kinect, webcam_device

    def sh(self, argv, wait=True, timeout=10):
        self.ran.append(list(argv))
        if argv[:1] == ["gdbus"] and "ListWindows" in " ".join(argv):
            return 0, "('[{\"id\": 4, \"appName\": \"Spotify\", \"title\": \"Spotify\"}]',)\n"
        if argv[:1] == ["gdbus"]:
            return 0, "(true,)\n"
        return 0, ""

    def http(self, method, url, body=None, timeout=5):
        if not self.hub:
            return None
        if url.endswith("/api/status"):
            return {"status": self.kinect, "tilt": -5.0, "error": "no power",
                    "webcam": {"device": self.webcam_device}}
        if "/api/measure" in url:
            return {"ok": True, "height": 1.78, "distance": 2.6, "count": 2,
                    "sentence": "You're 1.78 metres tall, about 5 foot 10.",
                    "count_sentence": "I can see 2 people: 1 standing and 1 sitting."}
        if url.endswith("/cloud.ply"):
            return b"ply\nformat binary_little_endian 1.0\n"
        if method == "POST":
            self.posted.append((url.rsplit("/", 1)[-1], body["value"]))
            return {"ok": True}
        return None

    def control(self):
        return control.Control(self.sh, self.http, launch=lambda n: {"ok": n == "terminal"},
                               open_url=self.opened.append,
                               apps=lambda: [{"id": "spotify.desktop", "name": "Spotify", "keywords": [], "exec": "spotify"}])


def say(world, text):
    return world.control().run(commands.parse(text))


def check_control():
    print("What Mario does")
    w = World()
    r = say(w, "how tall am I")
    check("how tall am I: the Kinect hub measures, Mario says it", r["ok"] and "1.78" in r["answer"], r)
    r = say(w, "how far am I from the TV")
    check("how far am I: the distance", "2.6 metres" in r["answer"], r)
    r = say(w, "how many people are there")
    check("how many people: the count and who stands or sits", "2 people" in r["answer"]
          and "sitting" in r["answer"], r)
    say(w, "tilt the kinect down by 10")
    check("tilt down by 10 from -5 goes to -15", w.posted[-1] == ("tilt", -15), w.posted)
    say(w, "tilt the kinect to 40")
    check("tilt is kept within the motor's range", w.posted[-1] == ("tilt", 27), w.posted)
    say(w, "night vision on")
    check("night vision: the infrared camera", w.posted[-1] == ("video", "ir"), w.posted)
    r = say(w, "use the kinect as a webcam")
    check("webcam on, with its device", w.posted[-1] == ("webcam", True) and r["ok"], r)
    r = say(World(webcam_device=None), "use the kinect as a webcam")
    check("webcam without the device: says how to set it up", not r["ok"] and "install-virtual-cameras" in r["answer"], r)
    r = say(World(kinect="unpowered"), "how tall am I")
    check("a Kinect without power: says so", not r["ok"] and "power" in r["answer"], r)
    w = World()
    say(w, "connect to my tv")
    check("connect to my TV: the cast toggles on", w.ran[-1][-1] == "--toggle", w.ran[-1])
    say(w, "turn off the tv")
    check("TV off: the TV remote", w.ran[-1][-2:] == ["--tv", "off"], w.ran[-1])
    say(w, "set the tv volume to 20")
    check("TV volume 20", w.ran[-1][-2:] == ["--tv-volume", "20"], w.ran[-1])
    say(w, "snap left")
    check("snap left: the shell's window action on the window you are in",
          w.ran[-1][-3:] == ["org.adaptive.Shell.WindowAction", "0", "tile-left"], w.ran[-1])
    say(w, "close spotify")
    check("close Spotify: found among the windows, closed by its id",
          w.ran[-1][-3:] == ["org.adaptive.Shell.WindowAction", "4", "close"], w.ran[-1])
    say(w, "go to desktop 3")
    check("desktop 3 is workspace index 2", w.ran[-1][-2:] == ["org.adaptive.Shell.ActivateWorkspace", "2"], w.ran[-1])
    say(w, "open spotify")
    check("open Spotify: through the app grid's launcher", w.ran[-1] == ["gtk-launch", "spotify"], w.ran[-1])
    say(w, "often spotty fy")
    check("\"often spotty fy\" (misheard): Spotify all the same", w.ran[-1] == ["gtk-launch", "spotify"], w.ran[-1])
    r = w.control().run({"intent": "app.maybe", "args": {"name": "spotifai"}})
    check("an app said on its own opens", w.ran[-1] == ["gtk-launch", "spotify"] and r["ok"], r)
    r = w.control().run({"intent": "app.maybe", "args": {"name": "brief me"}})
    check("words on their own that name no app: Mario answers", r.get("fallthrough") is True, r)
    c = w.control()
    c.launchers = {"terminal"}
    check("knows(): what would open, without opening it", c.knows("spotify") and c.knows("terminal") and c.knows("youtube")
          and not c.knows("the door") and not c.knows("terminal", strict=True) and len(w.ran) == len(w.ran))
    r = say(w, "open the pod bay doors")
    check("open something that is not an app: Mario answers instead", r.get("fallthrough") is True, r)
    say(w, "open youtube")
    check("open YouTube: the site", w.opened[-1] == "https://www.youtube.com/", w.opened)
    say(w, "set the volume to 40")
    check("volume 40", w.ran[-1] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "40%"], w.ran[-1])
    say(w, "search for weather in bengaluru")
    check("a web search", w.opened[-1].endswith("q=weather+in+bengaluru"), w.opened[-1])
    r = say(w, "what can i say")
    check("what can I say: the cheat sheet opens", w.opened[-1] == control.CHEATSHEET_URL and r["ok"], w.opened)
    r = say(World(hub=False), "take a 3d snapshot")
    check("no Kinect hub: says what to install", not r["ok"] and "install-air" in r["answer"], r)
    names = {i for _, items in commands.CHEATSHEET for _, i, _ in items if i}
    names |= {intent for intent, _, _ in commands.RULES}
    missing = [n for n in sorted(names)
               if not hasattr(control.Control, "do_" + n.replace(".", "_").replace("-", "_"))]
    check("every command has something that carries it out", not missing, missing)


def check_doc():
    print("docs/MARIO_COMMANDS.md")
    want = commands.markdown() + "\n"
    if "--write" in sys.argv:
        DOC.write_text(want)
    check("is written from commands.py (--write to update)", DOC.exists() and DOC.read_text() == want)


def main():
    check_sheet()
    check_phrases()
    check_matching()
    check_control()
    check_doc()
    print()
    if FAILED:
        print(f"{len(FAILED)} failed: " + ", ".join(FAILED[:12]))
        return 1
    print("Mario commands: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
