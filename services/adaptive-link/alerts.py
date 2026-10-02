"""Adaptive Link - what the computer tells the phone without being asked.

Two kinds of thing:

  notifications   what the desktop's own notification daemon is asked to
                  show, read off the session bus as it goes by
  alerts          what the link notices about the machine itself: a disk
                  nearly full, memory running out, a low battery, a hot
                  processor, a device plugged in, a service that failed, a
                  command started from the phone that has finished

Both end up in Events, which keeps the last hundred and hands each to every
phone that is listening (server.py, /v1/events). Nothing is sent anywhere
else, and nothing is kept on disk.

`decide` is the whole of what counts as worth an alert, with no machine in
it, so verify-link.py checks it directly.
"""

import asyncio
import re
import time

import machine
import system

EVENT_LIMIT = 100
DISK_FREE_PERCENT = 5
MEMORY_FREE_PERCENT = 6
BATTERY_LOW, BATTERY_CRITICAL = 15, 5
TOO_HOT = 90
# Once said, a thing is not said again until it has been put right by this much.
DISK_CLEAR_PERCENT, MEMORY_CLEAR_PERCENT, COOL_AGAIN = 8, 12, 80


class Events:
    """The last things said to the phone, numbered so a phone that was away
    can ask for what it missed."""

    def __init__(self, limit=EVENT_LIMIT):
        self._limit = limit
        self._items = []
        # Numbered from the clock, so numbers keep rising across a restart
        # and a phone never mistakes a new event for one it has seen.
        self._next = int(time.time() * 1000)
        self._listeners = set()

    def add(self, kind, title, text="", app=""):
        item = {"id": self._next, "at": int(time.time()), "kind": kind,
                "title": str(title)[:120], "text": str(text)[:600], "app": str(app)[:60]}
        self._next += 1
        self._items = (self._items + [item])[-self._limit:]
        for queue in list(self._listeners):
            if queue.qsize() < self._limit:
                queue.put_nowait(item)
        return item

    def since(self, after):
        return [item for item in self._items if item["id"] > after]

    def listen(self):
        queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def leave(self, queue):
        self._listeners.discard(queue)


# ------------------------------------------------------------------ alerts

def reading():
    """What `decide` looks at, read from the machine now."""
    summary = system.summary()
    well = machine.health()
    return {
        "disks": [(disk["mount"], disk["free"], disk["total"]) for disk in summary["disks"]],
        "memory": (summary["memory"]["available"], summary["memory"]["total"]),
        "battery": well["battery"],
        "hottest": max((sensor["celsius"] for sensor in well["temperatures"]), default=0),
        "usb": {device["port"]: device["name"] for device in system.usb_devices()},
        "failed": sorted(unit["name"] for unit in machine.services() if unit["failed"]),
    }


def decide(state, now):
    """(what is remembered for next time, [(title, text)] worth saying now).

    `state` is what the last call returned, or None the first time - when
    nothing is said about what was already so: the alerts are about change.
    """
    first = state is None
    state = dict(state or {})
    said = []

    full = set(state.get("full", ()))
    for mount, free, total in now.get("disks", ()):
        percent = free * 100 / total if total else 100
        if percent < DISK_FREE_PERCENT and mount not in full:
            full.add(mount)
            said.append(("A disk is nearly full", f"{mount} has {max(0, free) // (1 << 20)} MB left"))
        elif percent > DISK_CLEAR_PERCENT:
            full.discard(mount)
    state["full"] = sorted(full)

    available, total = now.get("memory", (0, 0))
    percent = available * 100 / total if total else 100
    if percent < MEMORY_FREE_PERCENT and not state.get("memory"):
        state["memory"] = True
        said.append(("Memory is running out", f"{available // (1 << 20)} MB is free"))
    elif percent > MEMORY_CLEAR_PERCENT:
        state["memory"] = False

    battery = now.get("battery")
    level = state.get("battery", 0)   # 0 fine, 1 low, 2 nearly empty
    if battery and not battery["charging"]:
        wanted = 2 if battery["percent"] <= BATTERY_CRITICAL else 1 if battery["percent"] <= BATTERY_LOW else 0
        if wanted > level:
            said.append(("The computer's battery is nearly empty" if wanted == 2 else "The computer's battery is low",
                         f"{battery['percent']}% left"))
        state["battery"] = max(wanted, level) if wanted else 0
    else:
        state["battery"] = 0

    hottest = now.get("hottest", 0)
    if hottest >= TOO_HOT and not state.get("hot"):
        state["hot"] = True
        said.append(("The computer is running hot", f"{int(hottest)}°C"))
    elif hottest < COOL_AGAIN:
        state["hot"] = False

    usb, before = now.get("usb", {}), state.get("usb", {})
    for port in usb.keys() - before.keys():
        said.append(("Plugged in", usb[port]))
    for port in before.keys() - usb.keys():
        said.append(("Unplugged", before[port]))
    state["usb"] = dict(usb)

    failed = now.get("failed", [])
    for name in failed:
        if name not in state.get("failed", ()):
            said.append(("A service has failed", name.removesuffix(".service")))
    state["failed"] = list(failed)

    return state, [] if first else said


# ----------------------------------------------------------- notifications

OWN_APP = "Adaptive Link"
_STRING = re.compile(r'^   string "(.*)$')


def parse_notify(lines):
    """(app, title, text) of one Notify call as dbus-monitor prints it, or
    None for one that is the phone's own, or the link's.

    The arguments are, in order: the app's name, the icon, the title, the
    text. Each is a line of three spaces and `string "..."`; text with line
    breaks in it runs on over the following lines.
    """
    strings, index = [], 0
    while index < len(lines):
        match = _STRING.match(lines[index])
        if match:
            value = match.group(1)
            while not value.endswith('"') and index + 1 < len(lines):
                index += 1
                value += "\n" + lines[index]
            strings.append(value[:-1] if value.endswith('"') else value)
        index += 1
    if len(strings) < 4:
        return None
    body = "\n".join(lines)
    # What the phone itself sent to be shown here is not sent back to it.
    if re.search(r'string "category"\s+variant\s+string "device"', body) or strings[0] == OWN_APP:
        return None
    app, _icon, title, text = strings[:4]
    text = re.sub(r"<[^>]{1,80}>", "", text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if not (title or text).strip():
        return None
    return app, title, text


async def watch_notifications(events):
    """Read the desktop's notifications off the session bus as they are
    asked for, for as long as the daemon runs."""
    while True:
        try:
            process = await asyncio.create_subprocess_exec(
                "dbus-monitor", "--session",
                "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
        except OSError:
            return   # no dbus-monitor here: there is nothing to watch with
        block = []
        try:
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\n")
                # A line that starts at the margin and names a message begins the next one.
                if re.match(r"^(method call|method return|signal|error) ", line):
                    found = parse_notify(block) if block and "member=Notify" in block[0] else None
                    if found:
                        events.add("notification", found[1], found[2], found[0])
                    block = [line]
                else:
                    block.append(line)
                    # The last argument: the call is complete without waiting for another.
                    if re.match(r"^   int32 -?\d+$", line) and "member=Notify" in block[0]:
                        found = parse_notify(block)
                        if found:
                            events.add("notification", found[1], found[2], found[0])
                        block = []
        except asyncio.CancelledError:
            process.kill()
            raise
        await process.wait()
        await asyncio.sleep(5)   # the session bus went away; look for it again


async def watch_machine(events, every):
    state = None
    while True:
        try:
            state, said = decide(state, await asyncio.to_thread(reading))
        except Exception:  # noqa: BLE001 - a reading that fails is tried again
            said = []
        for title, text in said:
            events.add("alert", title, text)
        await asyncio.sleep(every)
