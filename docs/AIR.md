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

### One hand

| Do this | It does |
| --- | --- |
| Raise an open palm and hold it still (~½ s) | **Engage**: the ring fills, brackets slide in, a scan line sweeps the screen. Where your palm was becomes the middle of the screen. |
| Move the hand | The pointer follows the palm (not the fingertip, so pinching does not move it). |
| Pinch thumb and index | Press; let go to release. A pinch that hardly moved is a click (twice quickly: double-click); one that moved is a drag. |
| Thumb on the **middle** fingertip (index stays up) | **Right-click** (a purple ripple). |
| **Wave** an open hand down / up, either hand | **Scroll** up / down a chunk (6 wheel steps; the page follows the hand). Wave again to keep going; the hand coming back is ignored and does not move the pointer. |
| Make an **L** (thumb and index out, the rest folded), then open / close it | **Zoom** in / out (Ctrl + wheel). Start with a clear gap: a closed L is a pinch, and a pinch clicks. |
| **V sign** (index and middle up) and move it | **Scroll** the window under the pointer; the pointer stays put. Up/down and left/right; the page follows the hand (`natural_scroll`). Chevrons on the reticle. |
| V sign pushed toward / pulled away from the Kinect | **Zoom** in / out, one step per ~4.5 cm (Ctrl + wheel: browsers, Files, editors, image viewers). On the webcam: the hand growing or shrinking in view. |
| Push the open palm ~7 cm toward the Kinect, quickly | Click (Kinect only: it needs depth). |
| Make a fist over a window | Grab it; it follows your hand. Open the hand to put it down. |
| ... and fling it as you open the hand | **Throw**: left/right takes that half of the screen, up maximises, down minimises. |
| ... or carry it to the screen's left / right edge and hold ½ s | It goes to the **previous / next desktop**, and so do you; keep holding to go further. |
| Sweep the open hand fast to the left / right, either hand | Next / previous desktop. The pointer stays where it was ("clutch") while your hand comes back. |
| Drop your hand out of view | Disengage. Anything held (a pressed button, a carried window) is let go. |

### Two hands

The hand that engaged drives the pointer; the second hand only counts in these combinations.

| Do this | It does |
| --- | --- |
| Both hands pinch, pull apart / push together | **Zoom** in / out, a step for every 15% change in distance. |
| Hold a window with a fist, make a fist with the other hand, pull apart / together | **Resize** the window around its centre (the reticle turns orange with corner arrows). Open the second hand to go back to carrying it. |
| Both **open palms** pulled apart | Every window (overview). Two open hands never swipe. |
| ... pushed together | Back to work. |

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

## On top of the TV (across the room)

The Kinect is meant to sit on the TV, about 1.92 m (6.3 ft) up, looking into the room, with you
2 to 4 m away. Everything is set for that:

- **Hands at a distance.** A hand 3 m away is about 25 pixels wide, too small for MediaPipe
  Hands in the whole picture, so Air finds you first (MediaPipe Pose) and looks for each hand in
  a square cut around its wrist, enlarged to 256 pixels (`"tracking": "auto"` in air.json; `near`
  or `room` to force one).
- **The same arm movement at any distance.** The area your hand sweeps for the whole screen is
  4 hand-sizes wide (`box_hands`), so it shrinks in the picture as you step back; engaging and
  swiping are measured in hand-sizes too.
- **Tilt it down** a little so it sees from your head to the floor: "Mario, tilt the Kinect down
  by 10", or Studio's tilt slider. Studio's Depth panel shows how much of the room has a reading.
- **Its height** is found from the floor when the floor is in view; otherwise `mount_height` in
  `~/.config/adaptive-desktop/kinect.json` (default 1.92 m) is used.
- **A dark room**: the colour camera sees nothing, so neither does hand finding. Studio says so;
  "Mario, night vision on" switches to the infrared camera, which brings its own light.

## How tall you are

"Mario, how tall am I?" (or Studio's *Measure my height*): stand 2 to 4 m in front of the
Kinect, facing it, all of you in view. `measure.py` takes about a second of frames: the
accelerometer gives which way is up, MediaPipe Pose finds your torso, the depth region around
it (with the floor cut away) is you, and your height is its top above the floor. Mario answers
in metres and feet and inches. Checked on rendered rooms to within 3 cm; the Kinect's own depth
error at 3 m is 1 to 3 cm.

## Kinect Studio and the Kinect webcam

libfreenect lets one process open the Kinect, so one does: the **Kinect hub**
(`services/adaptive-air/kinect_hub.py`, user service `adaptive-kinect.service`). Air, Kinect
Studio and the webcam all go through it, at the same time:

```
Kinect ──libfreenect──▶ kinect_hub.py ──▶ /dev/shm/adaptive-kinect-<uid>  (frames.py) ──▶ Air
                              ├──────────▶ http://127.0.0.1:8792  Kinect Studio (page in studio/)
                              └──────────▶ GStreamer ▶ /dev/video11 "Kinect Camera" (v4l2loopback)
```

- **Kinect Studio** (app grid, or `scripts/adaptive-air.sh --studio`, or any browser at
  http://127.0.0.1:8792): the colour or infrared picture, depth (near warm, far cool, black =
  no reading), the coloured **point cloud** in 3D (drag to turn, right-drag to move, scroll to
  zoom; density, point size, colour by picture or depth, orbit), the **accelerometer** with an
  artificial horizon, pitch and roll, the **tilt motor** (slider, Down/Level/Up), the **LED**,
  depth statistics with a histogram, the stream rate, and **Export point cloud** (binary PLY for
  MeshLab, CloudCompare, Blender, Open3D).
- **Infrared** switches the Kinect's picture to its IR camera: it sees in the dark and shows the
  projector's dot pattern. Air, Studio and the webcam all get it.
- **The webcam**: switch *Webcam* on in Studio (or `scripts/adaptive-air.sh --webcam on`) and pick
  **Kinect Camera** in Meet, Zoom, OBS, Cheese or the browser. It needs a second v4l2loopback
  device, made once with `scripts/install-virtual-cameras.sh` (sudo; it keeps the phone's
  "Phone Camera" at /dev/video10 and adds "Kinect Camera" at /dev/video11). The switch is kept
  in `~/.config/adaptive-desktop/kinect.json`; while it is on, the hub keeps the camera running.
- **The hub stops itself** (LED off) 20 s after nothing uses it: no Air, no Studio page open,
  webcam off. Anything that needs it starts it again.
- Frames in shared memory are private to you (mode 0600). HTTP listens on 127.0.0.1 only.

## Mario drives all of it

Everything here is also a sentence to Mario ("Hey Mario …" or Super+J): how tall am I, how far
am I, open Kinect Studio, tilt the Kinect, level it, night vision on, use the Kinect as a
webcam, take a 3D snapshot, start/stop gestures, show the gesture demo, and the light. The full
list, with the TV, apps, windows, desktops, sound and more, is docs/MARIO_COMMANDS.md (or ask
Mario "what can I say?").

## Install, run, check

```sh
./install.sh --only air            # libfreenect, MediaPipe venv (~650 MB), the user service
./scripts/install-keybindings.sh   # Super+G
scripts/adaptive-air.sh --status   # running? which camera? what of the Kinect is on USB?
scripts/adaptive-air.sh --demo     # the scripted hands, no camera
services/adaptive-air/air.py --print --preview   # events in the terminal + a camera window (tuning)
scripts/adaptive-air.sh --led green | --tilt 10  # the Kinect's LED and motor
scripts/adaptive-air.sh --studio | --webcam on   # Kinect Studio; the Kinect as a webcam
scripts/install-virtual-cameras.sh               # once, sudo: the "Kinect Camera" device
scripts/verify-air.py [--hardware]  # engine, probe, protocol, demo (in verify-all.sh --quick)
scripts/verify-shell-nested.sh --extra scripts/verify-air-nested.sh   # end to end in a nested shell
```

Settings, all optional, in `~/.config/adaptive-desktop/air.json`:

```json
{"source": "auto", "webcam": 0, "tilt": null,
 "gestures": {"box_width": 0.42, "engage_hold": 0.55, "swipe_speed": 2.2, "push_mm": 70,
              "scroll_step": 0.035, "natural_scroll": true, "zoom_mm": 45, "zoom_ratio": 1.15}}
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
  Sit 1 to 2 m away for gestures: Studio's Depth panel shows how much of the picture has a reading.
- The webcam on this laptop drops to ~10 fps in a dim room (auto exposure). The Kinect runs at a
  steady 30.
- MediaPipe's handedness can flip when a hand turns over. The engine follows hands by side but
  never lets two live hands claim the same side, and the primary hand is the one that engaged.
- Any process on the session bus could own `org.adaptive.Air` and drive the pointer. That is no
  more than `xdotool` can already do from the same session; the shell only acts while frames
  say engaged.
