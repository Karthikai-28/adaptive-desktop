"""What Mario does when you tell it to: spoken sentences to commands, and the cheat sheet. Pure.

parse(text) gives {"intent": ..., "args": {...}} or None (then Mario answers as usual: Claude,
Gemini at Claude's limit, a plan you approve for code work). control.py carries commands out.

CHEATSHEET is what you can say, by section; scripts/verify-mario-commands.py checks that every
example on it parses to the command it promises, and docs/MARIO_COMMANDS.md is written from it
(`commands.py --markdown`). Mario Home shows it at /commands, and "what can I say" opens it.
"""

import re
import sys

NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
           "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
           "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
           "eighty": 80, "ninety": 90, "hundred": 100, "a hundred": 100, "first": 1, "second": 2,
           "third": 3, "fourth": 4, "fifth": 5}
LED_WORDS = {"green": "green", "red": "red", "yellow": "yellow", "orange": "yellow", "off": "off",
             "blinking green": "blink-green", "flashing green": "blink-green",
             "blinking red": "blink-red-yellow", "flashing red": "blink-red-yellow"}
SITES = {"youtube": "https://www.youtube.com/", "gmail": "https://mail.google.com/",
         "mail": "https://mail.google.com/", "calendar": "https://calendar.google.com/",
         "google": "https://www.google.com/", "github": "https://github.com/",
         "netflix": "https://www.netflix.com/", "maps": "https://maps.google.com/",
         "google maps": "https://maps.google.com/", "drive": "https://drive.google.com/",
         "google drive": "https://drive.google.com/", "photos": "https://photos.google.com/",
         "chatgpt": None, "whatsapp": "https://web.whatsapp.com/", "amazon": "https://www.amazon.in/"}

_POLITE = re.compile(r"^(?:(?:hey|hi|ok|okay)\s+)?(?:mario[,:]?\s+)?(?:(?:please|can you|could you|"
                     r"would you|will you|i want you to|i'd like you to|go ahead and)\s+)*", re.I)


def number(word):
    word = (word or "").strip().lower()
    if re.fullmatch(r"-?\d+", word):
        return int(word)
    if word.startswith("minus "):
        n = number(word[6:])
        return -n if n is not None else None
    return NUMBERS.get(word)


def normalise(text):
    t = str(text or "").strip()
    t = _POLITE.sub("", t)
    t = re.sub(r"\bplease\b", "", t, flags=re.I)
    t = re.sub(r"[.!?,]+$", "", t).strip().lower()
    t = re.sub(r"\s+", " ", t.replace("’", "'"))
    t = t.replace("work space", "workspace").replace("tele vision", "tv").replace("t.v.", "tv")
    t = re.sub(r"\b(?:television|telly)\b", "tv", t)
    # Speech recognition hears "Kinect" as kinnect, kinetic, or connect; "connect" is only taken
    # for the Kinect where nothing else makes sense, so "connect to my TV" stays the TV.
    t = re.sub(r"\b(?:kinnect|kinetic|kinect's|connects?)(?= (?:studio|light|led|webcam|camera|viewer))", "kinect", t)
    t = re.sub(r"\b(?:kinnect|kinetic)\b", "kinect", t)
    t = re.sub(r"\b(tilt|level|point|reset|straighten) the connect\b", r"\1 the kinect", t)
    return t


def _n(word, default=None):
    n = number(word) if word else None
    return default if n is None else n


# (intent, pattern, args from the match). The first that matches wins, so the specific come
# before the general ("open kinect studio" before "open <app>").
RULES = [
    # -- help
    ("help", r"(?:what can (?:i say|you do)|help(?: me)?|(?:show|open)(?: me)? (?:the )?(?:commands|cheat ?sheet)|"
             r"(?:list|what are) (?:the |your )?commands|mario commands)", lambda m: {}),

    # -- the Kinect
    ("kinect.height", r"(?:how tall am i|what(?:'s| is) my height|measure (?:my height|me|how tall i am)|"
                      r"how tall is (?:this|that|the) (?:person|guy|man|woman)|tell me my height)", lambda m: {}),
    ("kinect.distance", r"how far (?:away )?am i(?: from (?:the |my )?(?:tv|kinect|screen))?", lambda m: {}),
    ("kinect.studio", r"(?:open|show|launch|start)(?: me)? (?:the )?(?:kinect(?: studio| viewer| app| view)?|"
                      r"point cloud|depth (?:view|camera))", lambda m: {}),
    ("kinect.level", r"(?:level|straighten|reset) (?:the )?kinect|kinect (?:level|straight)", lambda m: {}),
    ("kinect.tilt", r"(?:tilt|point|move|turn) (?:the )?kinect (up|down)(?: by (\S+)(?: degrees?)?)?",
     lambda m: {"by": _n(m[2], 10) * (1 if m[1] == "up" else -1)}),
    ("kinect.tilt", r"(?:tilt|point|set) (?:the )?kinect(?: tilt)? to (\S+(?: \S+)??)(?: degrees?)?",
     lambda m: {"to": _n(m[1], 0)}),
    ("kinect.led", r"(?:turn |switch )?(?:the )?kinect(?:'s)? (?:light|led) (?:to )?(off|green|red|yellow|orange|"
                   r"blinking green|flashing green|blinking red|flashing red)", lambda m: {"colour": LED_WORDS[m[1]]}),
    ("kinect.led", r"turn (?:the )?kinect(?:'s)? (?:light|led) (off|green|red|yellow)", lambda m: {"colour": LED_WORDS[m[1]]}),
    ("kinect.led", r"turn off (?:the )?kinect(?:'s)? (?:light|led)", lambda m: {"colour": "off"}),
    ("kinect.ir", r"(?:turn |switch )?(?:the )?(?:night vision|infra ?red|ir)(?: mode| camera)? (on|off)",
     lambda m: {"on": m[1] == "on"}),
    ("kinect.ir", r"turn (on|off) (?:the )?(?:night vision|infra ?red|ir)(?: mode| camera)?", lambda m: {"on": m[1] == "on"}),
    ("kinect.ir", r"switch (?:the kinect )?to (night vision|infra ?red|colou?r)",
     lambda m: {"on": not m[1].startswith("colo")}),
    ("kinect.webcam", r"(?:use|start|turn on|switch on) (?:the )?kinect(?: as (?:a |the |my )?(?:webcam|camera)|"
                      r" (?:webcam|camera))", lambda m: {"on": True}),
    ("kinect.webcam", r"(?:stop|turn off|switch off) (?:the )?kinect (?:webcam|camera)", lambda m: {"on": False}),
    ("kinect.webcam", r"kinect (?:webcam|camera) (on|off)", lambda m: {"on": m[1] == "on"}),
    ("kinect.snapshot", r"(?:take|save|capture|grab) (?:a )?(?:3d|three d|point cloud|depth) (?:snapshot|scan|picture|photo|capture)|"
                        r"(?:save|export) (?:the )?point cloud|scan (?:the |this )?room", lambda m: {}),
    ("air.demo", r"(?:show|play|run|start) (?:me )?(?:the )?gestures? demo", lambda m: {}),
    ("air.on", r"(?:start|turn on|enable|switch on|activate) (?:the )?(?:hand )?(?:gestures?(?: control)?|air|hand control)|"
               r"gestures? on|(?:let me )?control (?:it|the computer|this) with my hands", lambda m: {}),
    ("air.off", r"(?:stop|turn off|disable|switch off|deactivate) (?:the )?(?:hand )?(?:gestures?(?: control)?|air|hand control)|"
                r"gestures? off", lambda m: {}),

    # -- the TV and casting
    ("tv.cast-window", r"(?:cast|put|show|send|mirror) (?:this|the) window (?:on|to) (?:the |my )?tv", lambda m: {}),
    ("tv.stop", r"(?:stop|end) (?:the )?(?:casting|mirroring|cast)|disconnect(?: from)?(?: (?:the |my )?tv)?|"
                r"stop (?:showing (?:it )?)?on (?:the )?tv|take (?:it|this) off (?:the )?tv", lambda m: {}),
    ("tv.on", r"turn on (?:the |my )?tv|(?:turn |switch )?(?:the |my )?tv on|switch on (?:the |my )?tv|wake (?:up )?(?:the |my )?tv",
     lambda m: {}),
    ("tv.off", r"turn off (?:the |my )?tv|(?:turn |switch )?(?:the |my )?tv off|switch off (?:the |my )?tv", lambda m: {}),
    ("tv.volume", r"set (?:the )?tv volume to (\S+)(?: percent)?", lambda m: {"level": _n(m[1], 20)}),
    ("tv.volume", r"(?:turn )?(?:the )?tv (?:volume )?(up|down)|tv volume (up|down)|(?:turn (up|down)|raise|lower) "
                  r"(?:the )?tv(?: volume)?", lambda m: {"step": "up" if "up" in (m[1], m[2], m[3]) or
                                                          m[0].startswith("raise") else "down"}),
    ("tv.mute", r"(mute|unmute) (?:the |my )?tv", lambda m: {"mute": m[1] == "mute"}),
    ("tv.wall", r"show (?:the )?(?:wall|clock|dashboard) on (?:the )?tv|tv (?:wall|clock)", lambda m: {}),
    ("tv.cast", r"(?:connect|cast|mirror|share|send)(?: (?:my|this|the))?(?: screen| laptop| desktop)? to (?:my |the )?tv|"
                r"connect (?:to )?(?:my |the )?tv|start (?:casting|mirroring)|put (?:this|my screen|it) on (?:the |my )?tv|"
                r"show (?:my screen|this) on (?:the |my )?tv", lambda m: {}),

    # -- windows
    ("window.to-desktop", r"(?:move|send|put) (?:this |the )?window to (?:the )?(next|previous|right|left|other) "
                          r"(?:desktop|workspace)", lambda m: {"way": "left" if m[1] in ("previous", "left") else "right"}),
    ("window.maximize", r"maximi[sz]e(?: (?:this|the))?(?: window)?|make (?:this|the|it) (?:window )?(?:bigger|full)",
     lambda m: {}),
    ("window.minimize", r"minimi[sz]e(?: (?:this|the))?(?: window)?|hide (?:this|the) window", lambda m: {}),
    ("window.fullscreen", r"(?:full ?screen|go full ?screen)(?: (?:this|the))?(?: window)?", lambda m: {}),
    ("window.tile", r"(?:snap|move|put|tile) (?:this |the )?(?:window )?(?:to )?(?:the )?(left|right)(?: half| side)?",
     lambda m: {"side": m[1]}),
    ("window.center", r"cent(?:er|re) (?:this |the )?window", lambda m: {}),
    ("app.close", r"close (?:this|the|that)(?: window| app)?|close (?:the )?window|close it", lambda m: {"name": None}),
    ("app.close", r"(?:close|quit|exit) (.+?)(?: window| app)?", lambda m: {"name": m[1]}),

    # -- desktops and the shell
    ("desk.go", r"(?:go|switch|move) to (?:desktop|workspace) (\S+)|(?:desktop|workspace) (\S+)",
     lambda m: {"n": _n(m[1] or m[2], 1)}),
    ("desk.next", r"(?:go |switch |move )?(?:to )?(?:the )?(?:next|right) (?:desktop|workspace)", lambda m: {}),
    ("desk.previous", r"(?:go |switch |move )?(?:to )?(?:the )?(?:previous|last|left) (?:desktop|workspace)", lambda m: {}),
    ("desk.overview", r"(?:show|open)(?: me)? (?:all )?(?:the |my )?(?:windows|overview|activities)|show everything|"
                      r"task view", lambda m: {}),
    ("desk.apps", r"(?:show|open)(?: me)? (?:all )?(?:the |my )?(?:apps|app grid|applications|app drawer)",
     lambda m: {}),
    ("desk.show-desktop", r"show (?:the |my )?desktop|hide (?:all )?(?:the |my )?windows|minimi[sz]e (?:everything|all)",
     lambda m: {}),
    ("desk.notifications", r"(?:show|open)(?: me)? (?:my |the )?notifications", lambda m: {}),
    ("desk.control-center", r"(?:open|show) (?:the )?(?:control cent(?:er|re)|quick settings)", lambda m: {}),
    ("desk.dropdown", r"(?:open|show|toggle) (?:the )?drop ?-?down(?: terminal)?", lambda m: {}),
    ("desk.palette", r"(?:open|show) (?:the )?(?:command )?palette", lambda m: {}),
    ("desk.lock", r"lock (?:the |my )?(?:screen|computer|laptop|pc)|lock it", lambda m: {}),

    # -- sound, media, the system
    ("sys.volume", r"set (?:the )?(?:volume|sound) to (\S+)(?: percent)?", lambda m: {"level": _n(m[1], 50)}),
    ("sys.volume", r"(?:turn )?(?:the )?(?:volume|sound) (up|down)|turn (up|down) (?:the )?(?:volume|sound)|(louder|quieter|softer)",
     lambda m: {"step": "up" if (m[1] or m[2] or "") == "up" or m[3] == "louder" else "down"}),
    ("sys.mute", r"(mute|unmute)(?: (?:the )?(?:sound|volume|audio|laptop|computer))?", lambda m: {"mute": m[1] == "mute"}),
    ("media", r"(pause|resume)(?: (?:the )?(?:music|song|video|track))?|play(?: (?:the )?(?:music|song|video))?",
     lambda m: {"what": {"pause": "Pause", "resume": "Play"}.get(m[1], "PlayPause")}),
    ("media", r"(?:next|skip)(?: (?:the )?(?:song|track|video))?|skip (?:this|it)", lambda m: {"what": "Next"}),
    ("media", r"previous(?: (?:song|track|video))?|go back a (?:song|track)", lambda m: {"what": "Previous"}),
    ("sys.screenshot", r"(?:take )?(?:a )?screen ?shot", lambda m: {}),
    ("sys.dnd", r"(?:turn (on|off) )?do not disturb(?: (on|off))?", lambda m: {"on": (m[1] or m[2] or "on") == "on"}),
    ("sys.dnd", r"(?:silence|mute) (?:my |the )?notifications", lambda m: {"on": True}),

    # -- the web
    ("web.search", r"(?:search|google|look up)(?: the web| google| online)?(?: for)? (.+)", lambda m: {"q": m[1]}),
    ("web.open", r"(?:go to|open|visit) ((?:[\w-]+\.)+(?:com|in|org|net|io|dev|ai|co))", lambda m: {"url": "https://" + m[1]}),

    # -- apps (last: anything else said as "open X" / "switch to X")
    # App names are a few words; a longer sentence is a request for Mario to answer or plan.
    ("app.focus", r"(?:switch|go|change) to (?!desktop|workspace)(\S+(?: \S+){0,2})|bring up (\S+(?: \S+){0,2})|"
                  r"show me (?:the )?(\S+(?: \S+){0,2}?) window",
     lambda m: {"name": m[1] or m[2] or m[3]}),
    ("app.open", r"(?:open|launch|start)(?: up)? (?:the |my )?(\S+(?: \S+){0,3}?)(?: app| application| program)?",
     lambda m: {"name": m[1]}),
]
_COMPILED = [(intent, re.compile(pattern), args) for intent, pattern, args in RULES]


_JOINED = re.compile(r"[;&|`$<>\n]")


def parse(text):
    # Something that reads like more than one instruction, or like a command line, is never a
    # command: Mario answers it instead ("open terminal; delete files" opens nothing).
    if _JOINED.search(str(text or "")):
        return None
    t = normalise(text)
    if not t:
        return None
    for intent, pattern, args in _COMPILED:
        m = pattern.fullmatch(t)
        if m:
            return {"intent": intent, "args": args(m), "text": t}
    return None


# What you can say. Every "say" parses to `intent` (scripts/verify-mario-commands.py).
CHEATSHEET = [
    ("Start", [
        ("Hey Mario …", None, "Wake Mario by voice (after training it once in Mario Home), or press Super+J."),
        ("What can I say?", "help", "This list."),
    ]),
    ("Kinect and you", [
        ("How tall am I?", "kinect.height", "Measures you with the Kinect: stand 2-4 m away, all of you in view."),
        ("How far am I from the TV?", "kinect.distance", "Your distance from the Kinect, across the floor."),
        ("Open Kinect Studio", "kinect.studio", "The camera, depth, 3D point cloud and sensors."),
        ("Tilt the Kinect down by 10", "kinect.tilt", "Up or down, by any number of degrees (10 if you don't say)."),
        ("Tilt the Kinect to minus 15", "kinect.tilt", "To an angle from level, -27 to 27."),
        ("Level the Kinect", "kinect.level", "Back to straight ahead."),
        ("Night vision on / Switch to colour", "kinect.ir", "The infrared camera: it sees in the dark."),
        ("Use the Kinect as a webcam / Stop the Kinect webcam", "kinect.webcam", "\"Kinect Camera\" for Meet, Zoom, OBS."),
        ("Take a 3D snapshot", "kinect.snapshot", "Saves the point cloud to Pictures/Kinect (PLY)."),
        ("Turn the Kinect light red / Turn off the Kinect light", "kinect.led", "Green, red, yellow, blinking, off."),
    ]),
    ("Hand gestures (Air)", [
        ("Start gestures / Stop gestures", "air.on", "Hand control on or off (Super+G does the same)."),
        ("Show the gesture demo", "air.demo", "Scripted hands play every gesture."),
    ]),
    ("TV", [
        ("Connect to my TV", "tv.cast", "Mirrors this screen on the TV (Miracast)."),
        ("Cast this window to the TV", "tv.cast-window", "Just the window you are in."),
        ("Stop casting / Disconnect", "tv.stop", "Back to the laptop alone."),
        ("Turn on the TV / Turn off the TV", "tv.on", "Wakes it over the network; off works too."),
        ("TV volume up / Set the TV volume to 20", "tv.volume", "Up, down, or a level 0-100."),
        ("Mute the TV / Unmute the TV", "tv.mute", ""),
        ("Show the clock on the TV", "tv.wall", "The wall page: clock, weather, vitals."),
    ]),
    ("Apps and windows", [
        ("Open Spotify / Open Files / Launch Firefox", "app.open", "Any app in the app grid, by its name."),
        ("Open YouTube / Open Gmail", "app.open", "Common sites open in the browser."),
        ("Switch to Chrome / Bring up Terminal", "app.focus", "Brings that app's window to the front."),
        ("Close this window / Close Spotify", "app.close", "The window you are in, or an app by name."),
        ("Maximise / Minimise", "window.maximize", "The window you are in."),
        ("Snap left / Put this window to the right", "window.tile", "That half of the screen."),
        ("Go full screen", "window.fullscreen", ""),
        ("Centre the window", "window.center", ""),
        ("Move this window to the next desktop", "window.to-desktop", "Next or previous."),
    ]),
    ("Desktops", [
        ("Next desktop / Previous desktop", "desk.next", ""),
        ("Go to desktop 2", "desk.go", "By number."),
        ("Show all windows", "desk.overview", "The overview."),
        ("Show all apps", "desk.apps", "The app grid."),
        ("Show the desktop", "desk.show-desktop", "Hides every window; again brings them back."),
        ("Show my notifications / Open control center", "desk.notifications", ""),
        ("Open the drop-down terminal / Open the palette", "desk.dropdown", ""),
        ("Lock the screen", "desk.lock", ""),
    ]),
    ("Sound and music", [
        ("Volume up / Turn the volume down / Louder", "sys.volume", "By 10%."),
        ("Set the volume to 40", "sys.volume", "A level, in percent."),
        ("Mute / Unmute", "sys.mute", ""),
        ("Play / Pause / Next song / Previous song", "media", "Whatever is playing (Spotify, the browser, …)."),
    ]),
    ("More", [
        ("Take a screenshot", "sys.screenshot", "Select an area, mark it up, copy or save it."),
        ("Do not disturb on / Turn off do not disturb", "sys.dnd", "Notification banners off or on."),
        ("Search for weather in Bengaluru", "web.search", "A web search in the browser."),
        ("Go to github.com", "web.open", "Any address."),
        ("Add a task: call the plumber / Take a note: …", None, "Into Mario's task list or notes."),
        ("Anything else", None, "Mario answers (Claude, Gemini at Claude's limit). Code work becomes a plan you start with Run."),
    ]),
]


def examples(say):
    """The separate sentences in a cheat-sheet entry ("A / B" is two)."""
    return [part.strip() for part in say.split(" / ") if "…" not in part]


def markdown():
    out = ["# Mario: what you can say", "",
           "Say \"Hey Mario\" (or press Super+J), then any of these. Words in a different order",
           "usually work too. This list is written from `services/mario-hub/commands.py`",
           "(`python3 services/mario-hub/commands.py --markdown`); Mario Home shows it at",
           "http://127.0.0.1:8791/commands, and \"What can I say?\" opens it.", ""]
    for title, items in CHEATSHEET:
        out += [f"## {title}", "", "| Say | What happens |", "| --- | --- |"]
        for say, _intent, what in items:
            out.append(f"| {say} | {what} |")
        out.append("")
    out += ["## Hand gestures (with Air on)", "",
            "See docs/AIR.md for the full list: raise an open palm to take control, pinch to",
            "click, wave up or down to scroll, an L (thumb and index) opened or closed to zoom,",
            "both hands pinching to zoom, a fist to grab a window (to the screen's edge: the next",
            "desktop), a fast sideways swipe for the next desktop, two open palms apart for every",
            "window.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    if "--markdown" in sys.argv:
        print(markdown())
    else:
        for line in sys.stdin:
            print(parse(line))
