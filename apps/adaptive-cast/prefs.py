"""Cast settings and state kept between runs.

~/.config/adaptive-desktop/cast.json holds choices (quality, sound, overlays)
and what was learnt about the TV (its network address and the key it issued
when it was paired). It is written 0600 because the TV key lets this laptop
control the TV.
"""

import json
import os
from pathlib import Path

PATH = Path.home() / ".config/adaptive-desktop/cast.json"

DEFAULTS = {
    "quality": "sharp",        # wfd.QUALITY key
    "sound": "tv",             # tv | laptop | both
    "fit": "fit",              # fit | fill | safe
    "cursor": "ring",          # off | ring | spotlight
    "clock": False,
    "badge": "",               # corner text, e.g. "Presenting: Karthi"
    "caption": "",             # bar along the bottom
    "hide_windows": True,      # black out windows whose class is listed below
    "hidden_classes": ["keepassxc", "1password", "bitwarden", "seahorse", "secrets"],
    "quiet": True,             # no notification banners while casting
    "record": False,           # keep a copy in ~/Videos/Cast
    "reconnect": True,         # rejoin when the link drops by itself
    "tv_setup": True,          # wake the TV and open Screen Share before joining
    "tv_end": "restore",       # restore | off | nothing, after casting
    "last_display": None,      # {"name", "address"} of the Wi-Fi Direct peer
    "tvs": {},                 # LAN address -> {"name", "mac", "key", "p2p"}
}


def load():
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(PATH.read_text()))
    except (OSError, ValueError):
        pass
    return data


def save(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, PATH)


def update(**changes):
    data = load()
    data.update(changes)
    save(data)
    return data
