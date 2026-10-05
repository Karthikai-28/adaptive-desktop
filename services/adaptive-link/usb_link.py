"""Adaptive Link - the link over a USB cable.

Wi-Fi is shared and uneven; a cable is neither, and it charges the phone
while it is being a display. With USB debugging on, Android's own bridge
(adb) can carry a connection made on the phone to a port on the computer:
`adb reverse` makes the phone's 127.0.0.1:PORT this computer's link port.
The app tries that address first, and when it answers it is the cable that
is used (LinkClient.kt).

Nothing about trust changes: what comes through is the same mutual TLS,
between the same two certificates, as on Wi-Fi. adb is only the road.

This watches for phones being plugged in and sets the road up for each.
Without adb, or with no phone that has allowed this computer to debug it,
it does nothing.
"""

import asyncio
import shutil
from pathlib import Path

EVERY_S = 5
_SDK_ADB = Path(__file__).resolve().parent.parent.parent / ".local" / "android-sdk" / "platform-tools" / "adb"


def adb():
    """The adb to use: the repository's own SDK's, or the system's. "" if none."""
    if _SDK_ADB.exists():
        return str(_SDK_ADB)
    return shutil.which("adb") or ""


def phones(listed):
    """The devices `adb devices` lists that can be used: plugged-in phones
    that have allowed this computer, not emulators. No side effects."""
    found = []
    for line in listed.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and not parts[0].startswith("emulator-"):
            found.append(parts[0])
    return found


async def _adb(*args, timeout=8):
    tool = adb()
    if not tool:
        return False, ""
    try:
        process = await asyncio.create_subprocess_exec(tool, *args, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (OSError, asyncio.TimeoutError):
        return False, ""
    return process.returncode == 0, out.decode(errors="replace")


connected = []   # the phones the road is set up for just now


async def watch(port, report=None):
    """Keep `adb reverse` set up for every phone plugged in, for as long as
    the link runs."""
    report = report or (lambda _what: None)
    if not adb():
        return
    while True:
        ok, listed = await _adb("devices")
        now = phones(listed) if ok else []
        for serial in now:
            ok, routes = await _adb("-s", serial, "reverse", "--list")
            if f"tcp:{port}" not in routes:
                done, _ = await _adb("-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}")
                if done:
                    report(f"a phone is plugged in ({serial[-4:]}): the link can go over the cable")
        for serial in connected:
            if serial not in now:
                report(f"the phone on the cable ({serial[-4:]}) was unplugged")
        connected[:] = now
        await asyncio.sleep(EVERY_S)
