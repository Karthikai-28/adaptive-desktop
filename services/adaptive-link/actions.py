"""Adaptive Link - one way in to everything the computer can do.

The link has many doors: a screen on the phone for each thing, a command for
each on the computer. This is the one door. Every thing that can be done is
an *action* with a name, the words people use for it, what it needs, and how
much it risks. "turn off bluetooth", "put the sound on the headset",
"what's using the memory" are matched against those words - here, on the
computer, with no service asked - and the best matches are offered, each as
a sentence saying exactly what it will do.

    ask("turn the wifi off")   ->   [{"id": "wifi", "args": {"state": "off"},
                                      "say": "Turn Wi-Fi off", "risk": "cuts"}, ...]
    run(link, "wifi", {"state": "off"})

Nothing here does the work. Each action calls what already does it
(desktop.py, system.py, machine.py), under the same switches of the owner's
as the screen it replaces. What an action risks decides whether it is done
at once or asked about first:

    safe      nothing lost by doing it by mistake (mute, lock, what's using memory)
    changes   changes something, and can be put back (a sound output, a profile)
    cuts      may cut the phone off from the computer (Wi-Fi off)
    destroys  cannot be undone (ending a process, shutting down)

Three things are built on that:

    chains    several actions under one name ("start the meeting")
    undo      what puts the last action back, kept as it is done
    plug-ins  actions other programs add, as small files in
              ~/.config/adaptive-desktop/actions.d/
"""

import difflib
import json
import re
import subprocess
import time
from pathlib import Path

import desktop
import machine
import system

RISKS = ("safe", "changes", "cuts", "destroys")
PLUGIN_DIR = Path.home() / ".config" / "adaptive-desktop" / "actions.d"
MATCHES = 6
JOURNAL = 30

# Said differently, meant the same. Applied to what is asked before matching.
SAME = (
    (r"\bwi-?fi\b|\bwireless\b", "wifi"), (r"\bswitch(ed)?\b|\bput\b", "turn"), (r"\bdisable\b", "turn off"),
    (r"\benable\b", "turn on"), (r"\bstop\b", "stop"), (r"\bquieter\b|\bvolume down\b|\bturn (it )?down\b", "quieter"),
    (r"\blouder\b|\bvolume up\b|\bturn (it )?up\b", "louder"), (r"\bmonitor\b|\bscreen\b", "display"),
    (r"\bspeakers?\b|\bheadphones?\b|\bheadset\b", "sound output"), (r"\bplease\b|\bcould you\b|\bcan you\b|\bthe\b|\bmy\b|\ba\b", " "),
)


def tidy(text):
    """What was asked, in the plainest words: lower case, no punctuation,
    the common other ways of saying a thing turned into one."""
    text = re.sub(r"[^\w\s%+-]", " ", str(text or "").lower())
    for pattern, plain in SAME:
        text = re.sub(pattern, plain, text)
    return " ".join(text.split())


def _plain(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower()).split())


def closeness(asked, name):
    """How well what was asked names this thing, 0 to 1. A name said in full
    inside the request scores highest; a near miss still scores."""
    # A name is taken as it is written: the other-ways-of-saying that are
    # folded together in a request ("speakers" for "sound output") would
    # make one device's name match another's.
    name = _plain(name)
    said = set(_plain(asked).split()) | set(tidy(asked).split())
    if not said or not name:
        return 0.0
    if name in _plain(asked):
        return 1.0
    words = name.split()
    hits = sum(1 for word in words if _said(word, said))
    # Things are asked for by part of their name ("the emberton" for
    # "EMBERTON II"): one word of it said is already a fair match.
    return 0.5 + 0.4 * hits / len(words) if hits else 0.0


def _said(word, said):
    """Whether a word is among those said, allowing a slip of the finger in
    a long one - a short word is only itself ("buy" is not "busy")."""
    return word in said or (len(word) >= 5 and bool(difflib.get_close_matches(word, said, n=1, cutoff=0.84)))


def number_in(asked):
    found = re.search(r"(\d{1,3})\s*%?", asked)
    return int(found.group(1)) if found else None


def on_or_off(asked):
    """"on", "off" or "" - which the request says, if either."""
    words = tidy(asked).split()
    if "off" in words or "disconnect" in words:
        return "off"
    if "on" in words or "connect" in words:
        return "on"
    return ""


class Action:
    """One thing that can be done.

    words     what a request for it tends to contain; each is worth a point
    switch    the owner's switch it goes with (allow_input, ...), or None
    risk      one of RISKS
    choices   for an action about one of several things (a network, a
              window): returns [(value, name)] to pick from by what was said
    args      (asked, chosen) -> {args} for the request, or None if it does
              not say enough to do this
    say       (args) -> the sentence shown before doing it
    do        (args) -> (done, what to say); may also return a third value,
              the (id, args) that would put it back
    """

    def __init__(self, ident, words, do, say, risk="safe", switch=None, choices=None, args=None, needs=()):
        self.id, self.words, self.do, self._say = ident, [tidy(word) for word in words], do, say
        self.risk, self.switch, self.choices, self._args, self.needs = risk, switch, choices, args, needs

    def say(self, args):
        return self._say(args) if callable(self._say) else self._say

    def score(self, asked):
        plain = tidy(asked)
        said = plain.split()
        best = 0.0
        for phrase in self.words:
            parts = phrase.split()
            hits = sum(1 for part in parts if _said(part, said))
            # Every word of a phrase said is worth more than most words of a longer one.
            best = max(best, hits / len(parts) * (0.6 + 0.4 * min(1, len(parts) / 2)) if parts else 0)
        return best

    def resolve(self, asked):
        """(score, args) for this request, or None if this action is not it."""
        score = self.score(asked)
        if score < 0.55:
            return None
        chosen = None
        if self.choices:
            ranked = sorted(((closeness(asked, name), value, name) for value, name in self.choices()), reverse=True)
            if not ranked or ranked[0][0] < 0.5:
                return None
            chosen = (ranked[0][1], ranked[0][2])
            score = 0.5 * score + 0.5 * ranked[0][0]
        args = self._args(asked, chosen) if self._args else {}
        return None if args is None else (score, args)


# ------------------------------------------------------------ the actions

def _ok(done, text=""):
    return (bool(done), text)


def _switchable(ident, words, name, now, change, risk="changes", switch="allow_input"):
    """An action that turns one thing on or off, and can be undone."""
    def args(asked, _chosen):
        state = on_or_off(asked)
        return {"state": state} if state else None

    def do(args):
        before = now()
        done, text = change(args["state"])
        back = (ident, {"state": "on" if before else "off"}) if done and before is not None else None
        return done, text, back

    return Action(ident, words, do, lambda a: f"Turn {name} {a['state']}", risk, switch, args=args)


def _wifi(state):
    done, text, _undo = system.network_action("wifi", state)
    return done, text


def _volume(args):
    before = desktop.volume()["percent"]
    done = desktop.set_volume(args["to"])
    return done, f"Volume {desktop.volume()['percent']}%", ("volume", {"to": before}) if done and before is not None else None


def _mute(_args):
    return desktop.set_volume("mute"), "Muted" if desktop.volume()["muted"] else "Sound on", ("mute", {})


def _brightness(args):
    before = machine.display()["brightness"]
    done, text = machine.display_action("brightness", "", str(args["to"]))
    return done, text or f"Brightness {args['to']}%", ("brightness", {"to": before}) if done and before else None


def _sound_output(args):
    before = next((d["name"] for d in machine.sound()["outputs"] if d["default"]), "")
    done, text = machine.sound_action("output-use", args["device"])
    return done, text, ("sound-output", {"device": before, "name": "what it was"}) if done and before else None


def _profile(args):
    before = machine.health()["profile"]
    done, text = machine.health_action("profile", args["profile"])
    return done, text, ("profile", {"profile": before}) if done and before else None


def _busiest(sort):
    def do(_args):
        found = system.processes(sort)[:5]
        if sort == "memory":
            return True, "\n".join(f"{p['name']}  {p['rss'] // (1 << 20)} MB" for p in found)
        return True, "\n".join(f"{p['name']}  {p['cpu']}%" for p in found)
    return do


def _disk(_args):
    return True, "\n".join(f"{d['mount']}  {d['free'] // (1 << 30)} GB free of {d['total'] // (1 << 30)} GB"
                           for d in system.summary()["disks"])


def _battery(_args):
    battery = machine.battery()
    if battery is None:
        return True, "This computer has no battery"
    left = f", {battery['minutes'] // 60} h {battery['minutes'] % 60} min" if battery.get("minutes") else ""
    return True, f"{battery['percent']}% {battery['state'].lower()}{left}"


def _desktop(action, value=""):
    return lambda _args=None: system.desktop_action(action, value)


def _project_choices():
    return [(project["id"], project["name"]) for project in system.projects()]


def _window_choices():
    return [(str(window["id"]), f"{window['app']} {window['title']}") for window in machine.windows()]


def _phone_display():
    import phone_display
    return phone_display


def _percent(asked, _chosen):
    value = number_in(asked)
    return {"to": max(0, min(100, value))} if value is not None else None


def built_in():
    """Every action the link itself offers."""
    actions = [
        Action("lock", ["lock", "lock computer", "lock display"], lambda a: _ok(desktop.power("lock"), "Locked"),
               "Lock the computer", "safe", "allow_power"),
        Action("display-off", ["display off", "turn display off", "turn off display"],
               lambda a: _ok(desktop.power("screen-off")), "Turn the screen off", "safe", "allow_power"),
        Action("suspend", ["suspend", "sleep", "go to sleep"], lambda a: _ok(desktop.power("suspend")),
               "Put the computer to sleep", "cuts", "allow_power"),
        Action("restart", ["restart", "reboot"], lambda a: _ok(desktop.power("reboot")),
               "Restart the computer - unsaved work is lost", "destroys", "allow_power"),
        Action("shut-down", ["shut down", "power off", "turn off computer"], lambda a: _ok(desktop.power("poweroff")),
               "Shut the computer down - unsaved work is lost", "destroys", "allow_power"),

        Action("play-pause", ["play", "pause", "resume", "play pause"], lambda a: _ok(desktop.media("play-pause"), "Play / pause"),
               "Play or pause what is playing"),
        Action("next", ["next", "next track", "skip"], lambda a: _ok(desktop.media("next"), "Next"), "Next track"),
        Action("previous", ["previous", "previous track", "back track"], lambda a: _ok(desktop.media("previous"), "Previous"),
               "Previous track"),
        Action("mute", ["mute", "unmute", "silence"], _mute, "Mute, or unmute, the sound"),
        Action("louder", ["louder"], lambda a: _ok(desktop.set_volume("up"), f"Volume {desktop.volume()['percent']}%"), "A little louder"),
        Action("quieter", ["quieter"], lambda a: _ok(desktop.set_volume("down"), f"Volume {desktop.volume()['percent']}%"), "A little quieter"),
        Action("volume", ["volume", "set volume", "volume to"], _volume, lambda a: f"Set the volume to {a['to']}%", args=_percent),
        Action("brightness", ["brightness", "set brightness", "brighter", "dimmer"], _brightness,
               lambda a: f"Set the brightness to {a['to']}%", "changes", "allow_input",
               args=lambda asked, c: {"to": max(1, min(100, number_in(asked)))} if number_in(asked) is not None else None),

        _switchable("wifi", ["wifi"], "Wi-Fi", lambda: system.network()["wifi_on"], _wifi, "cuts"),
        _switchable("bluetooth", ["bluetooth"], "Bluetooth", lambda: machine.bluetooth()["on"],
                    lambda state: machine.bluetooth_action("power", state)),
        _switchable("focus", ["focus", "do not disturb"], "focus", lambda: system.desktop_state()["focus"],
                    lambda state: system.desktop_action("focus", state)),
        Action("dark", ["dark", "dark mode", "dark appearance"], _desktop("scheme", "dark"), "Use the dark appearance", "changes", "allow_input"),
        Action("light", ["light mode", "light appearance"], _desktop("scheme", "light"), "Use the light appearance", "changes", "allow_input"),

        Action("join", ["join", "connect to wifi", "join network", "connect wifi"],
               lambda a: system.network_action("join", a["network"])[:2], lambda a: f"Join the Wi-Fi network {a['network']}",
               "cuts", "allow_input",
               choices=lambda: [(n["name"], n["name"]) for n in system.wifi_networks() if n["known"] or not n["security"]],
               args=lambda asked, chosen: {"network": chosen[0]}),
        Action("bluetooth-connect", ["connect", "connect bluetooth", "disconnect"],
               lambda a: machine.bluetooth_action(a["how"], a["device"]),
               lambda a: f"{a['how'].capitalize()} {a['name']}", "changes", "allow_input",
               choices=lambda: [(d["address"], d["name"]) for d in machine.bluetooth()["devices"]],
               args=lambda asked, chosen: {"device": chosen[0], "name": chosen[1],
                                           "how": "disconnect" if "disconnect" in tidy(asked).split() else "connect"}),
        Action("sound-output", ["sound", "sound output", "play through", "output"], _sound_output,
               lambda a: f"Play sound through {a['name']}", "changes", "allow_input",
               choices=lambda: [(d["name"], d["label"]) for d in machine.sound()["outputs"]],
               args=lambda asked, chosen: {"device": chosen[0], "name": chosen[1]}),
        Action("profile", ["power saver", "performance", "balanced", "power profile", "save power"], _profile,
               lambda a: f"Use the {a['profile'].replace('-', ' ')} power profile", "changes", "allow_power",
               choices=lambda: [(name, name.replace("-", " ")) for name in machine.health()["profiles"]],
               args=lambda asked, chosen: {"profile": chosen[0]}),

        Action("project", ["project", "switch project", "switch to project", "work on"],
               lambda a: system.desktop_action("project", a["project"]), lambda a: f"Switch to the project {a['name']}",
               "changes", "allow_input", choices=_project_choices,
               args=lambda asked, chosen: {"project": chosen[0], "name": chosen[1]}),
        Action("window", ["window", "show", "bring", "switch to", "go to"],
               lambda a: machine.window_action("show", a["window"]), lambda a: f"Bring {a['name'][:60]} to the front",
               "safe", "allow_input", choices=_window_choices,
               args=lambda asked, chosen: {"window": chosen[0], "name": chosen[1]}),
        Action("to-phone", ["send to phone", "window to phone", "put on phone", "move to phone", "on the phone",
                            "phone display", "to phone screen"],
               lambda a: _phone_display().bring("", ""), "Put the window in front on the phone's display",
               "safe", "allow_input"),
        Action("tile-left", ["window left", "tile left", "left half"], _desktop("tile", "left"), "Put the window in front on the left", "safe", "allow_input"),
        Action("tile-right", ["window right", "tile right", "right half"], _desktop("tile", "right"), "Put the window in front on the right", "safe", "allow_input"),
        Action("maximise", ["maximise", "maximize", "full size"], _desktop("tile", "maximize"), "Maximise the window in front", "safe", "allow_input"),
        Action("note", ["note", "remember", "write down", "jot"],
               lambda a: system.note(a["text"]), lambda a: f"Note: {a['text'][:80]}", "safe", "allow_input",
               args=lambda asked, c: {"text": re.sub(r"^\s*(please\s+)?(note|remember|write down|jot( down)?)\s*(that|this|to)?\s*:?\s*", "",
                                                    str(asked), flags=re.I).strip()} if len(str(asked).split()) > 1 else None),
        Action("save-session", ["save session", "save windows"], _desktop("session-save"), "Save the session", "safe", "allow_input"),

        Action("memory", ["memory", "using memory", "ram", "what using memory"], _busiest("memory"), "What is using the memory", "safe", "allow_exec"),
        Action("processor", ["processor", "cpu", "busy", "slow", "what using processor"], _busiest("cpu"), "What is keeping the processor busy", "safe", "allow_exec"),
        Action("disk", ["disk", "space", "storage", "disk space", "how much space"], _disk, "How much disk space is left"),
        Action("battery", ["battery", "charge", "how much battery"], _battery, "How the battery is"),
    ]
    return actions


def plug_ins(folder=PLUGIN_DIR):
    """Actions other programs have added: each a small file that says what
    it is called, the words for it, and the command that does it.

        {"id": "backup", "title": "Back up the project", "words": ["backup", "back up"],
         "command": ["/home/me/bin/backup"], "risk": "changes"}

    The command is run as it is written, with nothing added to it and no
    shell in between; what it prints is what is said back.
    """
    found = []
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return found
    for file in files:
        try:
            spec = json.loads(file.read_text(encoding="utf-8"))
            ident, title, command = spec["id"], spec["title"], spec["command"]
            words = spec.get("words") or [title]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if (not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", ident) or not isinstance(title, str)
                or not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command)
                or not isinstance(words, list) or not all(isinstance(word, str) for word in words)):
            continue
        risk = spec.get("risk") if spec.get("risk") in RISKS else "changes"

        def do(_args, command=command):
            try:
                done = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            except (OSError, subprocess.SubprocessError) as error:
                return False, str(error)
            return done.returncode == 0, (done.stdout + done.stderr).strip()[-600:]

        found.append(Action(f"x-{ident}", words, do, title[:120], risk, "allow_exec"))
    return found


# ---------------------------------------------------------------- the book

class Book:
    """The actions, the chains made of them, and what was last done."""

    def __init__(self, link_dir, plugin_dir=PLUGIN_DIR, actions=None):
        self._path = Path(link_dir) / "chains.json"
        self._plugin_dir = plugin_dir
        self._built_in = actions if actions is not None else built_in()
        self.journal = []   # newest last: {"id", "args", "say", "at", "back"}
        self.chains = self._load()

    def actions(self):
        return {action.id: action for action in self._built_in + plug_ins(self._plugin_dir)}

    def _load(self):
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(name)[:60]: steps for name, steps in data.items()
                if isinstance(steps, list) and all(isinstance(step, dict) and isinstance(step.get("id"), str) for step in steps)} \
            if isinstance(data, dict) else {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self.chains, indent=2) + "\n", encoding="utf-8")

    def ask(self, asked, allowed=lambda switch: True):
        """The best few things `asked` could mean, each ready to be done."""
        plain = tidy(asked)
        if not plain:
            return []
        actions = self.actions()
        found = []
        if plain in ("undo", "undo that", "turn it back", "undo last"):
            last = next((entry for entry in reversed(self.journal) if entry["back"]), None)
            if last:
                back = actions.get(last["back"][0])
                found.append((2.0, {"id": "undo", "args": {}, "risk": "changes",
                                    "say": f"Undo “{last['say']}”" + (f": {back.say(last['back'][1])}" if back else "")}))
        for name, steps in self.chains.items():
            score = closeness(asked, name)
            if score >= 0.6:
                risk = max((actions[step["id"]].risk for step in steps if step["id"] in actions), key=RISKS.index, default="safe")
                found.append((1.0 + score, {"id": "chain", "args": {"name": name}, "risk": risk,
                                            "say": f"{name}: " + ", then ".join(
                                                actions[s["id"]].say(s.get("args", {})) for s in steps if s["id"] in actions)}))
        for action in actions.values():
            if action.switch and not allowed(action.switch):
                continue
            try:
                resolved = action.resolve(asked)
            except Exception:  # noqa: BLE001 - one action that cannot answer does not silence the rest
                resolved = None
            if resolved:
                score, args = resolved
                found.append((score, {"id": action.id, "args": args, "say": action.say(args), "risk": action.risk}))
        found.sort(key=lambda item: -item[0])
        return [dict(match, sure=score >= 0.8) for score, match in found[:MATCHES]]

    def run(self, ident, args, allowed=lambda switch: True, record=True):
        """Do one action. Returns (done, what to say)."""
        actions = self.actions()
        if ident == "undo":
            last = next((entry for entry in reversed(self.journal) if entry["back"]), None)
            if last is None:
                return False, "there is nothing to undo"
            self.journal.remove(last)
            return self.run(last["back"][0], last["back"][1], allowed, record=False)
        if ident == "chain":
            said = []
            for step in self.chains.get(str((args or {}).get("name")), []):
                done, text = self.run(step["id"], step.get("args", {}), allowed)
                said.append(text or ("done" if done else "it did not work"))
                if not done:
                    return False, "; ".join(said)
            return bool(said), "; ".join(said) if said else "no such chain"
        action = actions.get(ident)
        if action is None:
            return False, "nothing by that name"
        if action.switch and not allowed(action.switch):
            return False, "that is turned off on the computer"
        try:
            result = action.do(args if isinstance(args, dict) else {})
        except (KeyError, TypeError, ValueError):
            return False, "it was not said what to do it to"
        done, text = result[0], result[1]
        back = result[2] if len(result) > 2 else None
        if done and record:
            self.journal = (self.journal + [{"id": ident, "args": args, "say": action.say(args), "at": int(time.time()),
                                             "back": back}])[-JOURNAL:]
        return bool(done), str(text or "")

    def remember(self, name, count):
        """Keep the last `count` things done as a chain called `name`."""
        name = " ".join(str(name or "").split())[:60]
        steps = [{"id": entry["id"], "args": entry["args"]} for entry in self.journal[-max(1, min(int(count), 10)):]]
        if not name or not steps:
            return False
        self.chains[name] = steps
        self._save()
        return True

    def forget(self, name):
        if self.chains.pop(str(name), None) is None:
            return False
        self._save()
        return True

    def catalogue(self):
        """Everything that can be asked for, for a list to browse."""
        return [{"id": action.id, "say": action.say({}) if not action.choices and not action._args else action.words[0].capitalize(),
                 "risk": action.risk} for action in self.actions().values()] + \
            [{"id": "chain", "say": name, "risk": "changes", "args": {"name": name}} for name in self.chains]
