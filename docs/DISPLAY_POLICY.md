# Display policy

A window you cannot see is still a window you are running. This is about the
two ways a display change can take one away from you.

## The incident

An external display was connected, Chrome and a terminal were used on it, and
then it was disconnected. Both windows stayed open, kept running, and could not
be brought back to the laptop screen by any means.

They were not lost. They were on `HDMI-1`, which X reported as `connected` -
with no EDID, no physical size, and a single generic 1024x768 mode. Nothing was
plugged into that port. X invented a screen there, mutter laid out a monitor on
it, and windows were placed on a display that does not physically exist.

That is why nothing worked: from the window manager's point of view the windows
were on a perfectly good monitor, so there was nothing to fix.

## The rules

**1. A connected output with no EDID is not a display.**
Every real monitor publishes an EDID. An output that claims to be connected and
publishes none has nothing on the end of it.
`scripts/adaptive-display-guard.py` turns those off, on login and whenever the
displays change.

**2. The guard never blanks the only screen, and never the primary.**
A built-in panel that comes up without an EDID must not be switched off, and
turning off the last enabled output leaves nowhere to work. Both are refused
and logged.

**3. It is possible to opt out.**
Some KVMs and cheap adapters drop EDID for a real monitor. If that is this
machine:

```sh
touch ~/.config/adaptive-desktop/allow-phantom-displays
```

**4. Windows that end up unreachable are brought back.**
When the displays change, any window less than half visible on any real monitor
is moved to the primary monitor and clamped into its work area, and a
notification says how many moved. Mutter already does this for most cases; this
is the net for what it leaves behind.

**5. The rescue waits for mutter rather than racing it.**
It runs 1.5s after the change. Acting immediately means moving windows twice -
once by us, once by mutter - and the second move undoes the first.

**6. Half visible is reachable.**
A window with its title bar on screen can be dragged back by hand, and moving
windows the user deliberately placed is worse than leaving them. Only windows
that are genuinely gone are touched.

## Checking

```sh
./scripts/adaptive-display-guard.py --check   # report ghosts, change nothing
./scripts/adaptive-display-guard.py           # turn them off
node scripts/verify-window-rescue.js          # rescue geometry
```

Both are wired into `scripts/verify-live-readiness.sh`. The guard logs every
decision, including the ones where it declined to act, to
`~/.local/state/adaptive-desktop/display-guard.log`.

## What this does not do

It does not remember window positions across an unplug and put them back when
the display returns. Windows come home to the primary monitor and stay there.
