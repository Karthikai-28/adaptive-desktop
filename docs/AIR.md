# Air: the desktop in your hands

Air turns a Kinect v1 ("Kinect for Xbox 360", models 1414 and 1473) into a hand-gesture
controller for the Adaptive session: raise an open palm, and a reticle locks onto it; pinch to
click, make a fist to pick up a window and fling it, sweep between desktops, pull two hands apart
to see every window. Until the Kinect has power, or on a machine without one, the webcam
stands in (no depth, so no air push).

Super+G starts and stops it. The camera is never on at login, the top bar shows a camera icon
whenever Air runs (its menu has Stop), and camera pictures never leave the process or touch the
disk: only hand landmarks (21 points per hand) go to the shell over the session bus.

## Gestures

| Do this | It does |
| --- | --- |
| Raise an open palm and hold it still (~½ s) | **Engage**: the ring fills, brackets slide in, a scan line sweeps the screen. Where your palm was becomes the middle of the screen. |
| Move the hand | The pointer follows the palm (not the fingertip, so pinching does not move it). |
| Pinch thumb and index | Press; let go to release. A pinch that hardly moved is a click; one that moved is a drag (select text, move a slider, drag a file). |
| Push the open palm ~7 cm toward the Kinect, quickly | Click (Kinect only: it needs depth). |
| Make a fist over a window | Grab it; it follows your hand. Open the hand to put it down. |
| ... and fling it as you open the hand | **Throw**: left/right takes that half of the screen, up maximises, down minimises. |
| Sweep the open hand fast to the left / right | Next / previous desktop. The pointer stays where it was ("clutch") while your hand comes back. |
| Sweep it fast upward | Overview. |
| Pinch with both hands and pull them apart | Every window (overview). |
| ... or push them together | Back to work. |
| Drop your hand out of view | Disengage. Anything held (a pressed button, a carried window) is let go. |

Try every gesture with no camera at all: `scripts/adaptive-air.sh --demo` plays a scripted pair
of hands through the real engine and the real HUD.

## How it is built

```
Kinect v1 ──USB──▶ libfreenect 0.7.5 (.local/libfreenect, ctypes)        services/adaptive-air/
   │  RGB 640x480 + depth registered to it, in mm                          kinect.py
   ▼
MediaPipe Hands (CPU, ~20 ms/frame)  ── 21 landmarks per hand ──┐        air.py (Tracker)
   + the palm's depth from the registered depth image           │
   ▼                                                            ▼
gesture engine (pure): poses, pinch hysteresis, One Euro filter,         gestures.py
engage/clutch, push, swipe, grab/throw, two-hand spread
   │
   ▼  org.adaptive.Air.Frame(s json) on the session bus, per frame      protocol.py
GNOME Shell: air.js draws the HUD and acts: Clutter virtual pointer,      shell/.../air.js
Meta window moves, workspace and overview through shellActions.js
```

- **The Kinect.** Only the C core and the C sync wrapper of libfreenect are built
  (`kinect/build-libfreenect.sh`, checksum-pinned, no root). Air asks for
  `FREENECT_DEPTH_REGISTERED`: depth in millimetres aligned pixel for pixel with the colour
  picture, so a hand found in colour has a true distance.
- **The motor and LED** are spoken to directly over libusb (three vendor control requests), because
  libfreenect only opens a Kinect whose camera is on USB. That works on USB power alone. The LED
  blinks green while Air looks for a hand and is solid green while engaged.
- **Hands** are MediaPipe Hands 0.10.14 (model complexity 0) in a private venv,
  `.local/air-venv`. The picture is mirrored first, so your right hand moves the pointer right.
- **The engine** (`gestures.py`) is pure Python with no camera, D-Bus or numpy in it, and
  `scripts/verify-air.py` drives it with synthetic hands built joint by joint
  (`synthetic.py`).
- **The shell side** (`air.js`) never moves the pointer unless the frame says Air is engaged, and
  lets go of everything if frames stop for 3.5 s.

## Install, run, check

```sh
./install.sh --only air            # libfreenect, MediaPipe venv (~650 MB), the user service
./scripts/install-keybindings.sh   # Super+G
scripts/adaptive-air.sh --status   # running? which camera? what of the Kinect is on USB?
scripts/adaptive-air.sh --demo     # the scripted hands, no camera
services/adaptive-air/air.py --print --preview   # events in the terminal + a camera window (tuning)
scripts/adaptive-air.sh --led green | --tilt 10  # the Kinect's LED and motor
scripts/verify-air.py [--hardware]  # engine, probe, protocol, demo (in verify-all.sh --quick)
scripts/verify-shell-nested.sh --extra scripts/verify-air-nested.sh   # end to end in a nested shell
```

Settings, all optional, in `~/.config/adaptive-desktop/air.json`:

```json
{"source": "auto", "webcam": 0, "tilt": null,
 "gestures": {"box_width": 0.42, "engage_hold": 0.55, "swipe_speed": 2.2, "push_mm": 70}}
```

`source` is `auto` (the Kinect when its camera is on USB, else the webcam, and back to the Kinect
as soon as it gets power), `kinect` or `webcam`. Every tuning value is in `gestures.DEFAULTS`;
`box_width` is how much of the camera's view maps onto the whole screen (smaller means less arm
movement).

## Gotchas

- **Only "Xbox NUI Motor" in `lsusb`** (045e:02b0 behind an NEC hub 0409:005a) means the Kinect has
  no 12 V. The Xbox 360 Kinect's camera and microphones need its own power supply (the "Kinect
  power/USB adapter" for the original 360; the 360 S had it built into the console). With power,
  `lsusb` also lists *Xbox NUI Camera* (02ae) and *Xbox NUI Audio* (02ad). Air reports this in the
  top-bar menu and keeps using the webcam until the camera appears.
- The tilt motor needs the 12 V supply too; the LED and accelerometer work without it.
- The Kinect's USB nodes must be readable and writable by you. On this machine they are already
  (`crw-rw-rw-` from an existing udev rule). Elsewhere, install libfreenect's
  `51-kinect.rules` (it gives the `plugdev` group access) and replug.
- Depth needs 0.5 to 4 m. A hand closer than about 50 cm reads no depth, and push is then off.
- The webcam on this laptop drops to ~10 fps in a dim room (auto exposure). The Kinect runs at a
  steady 30.
- MediaPipe's handedness can flip when a hand turns over. The engine follows hands by side but
  never lets two live hands claim the same side, and the primary hand is the one that engaged.
- Any process on the session bus could own `org.adaptive.Air` and drive the pointer. That is no
  more than `xdotool` can already do from the same session; the shell only acts while frames
  say engaged.
