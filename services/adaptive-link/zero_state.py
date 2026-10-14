"""The phone-facing half of Zero-State.

A paired phone may record that its owner wants to retire this computer.  That
is deliberately only an *arming* record: it cannot erase storage, reboot the
machine, or run the Zero-State command.  The actual sanitization remains a
local operation from trusted external boot media; see docs/ZERO_STATE_PROTOCOL.md.
"""

import json
import os
import time
from pathlib import Path


STATE_FILE = Path.home() / ".local" / "state" / "adaptive-desktop" / "zero-state-request.json"


def arm(state_file=STATE_FILE, now=None):
    """Privately record a requested Zero-State handoff, without destroying anything."""
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(state_file.parent, 0o700)
    request = {
        "state": "armed",
        "requested_at": int(time.time() if now is None else now),
        "instruction": "Boot trusted external media and follow docs/ZERO_STATE_PROTOCOL.md.",
    }
    temporary = state_file.with_name(state_file.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(request, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, state_file)
    return True, ("Zero-State is armed. No storage was erased and this computer was not rebooted. "
                  "Boot trusted external media and follow the Zero-State protocol to sanitize it.")
