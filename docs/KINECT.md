# The Kinect: the sensor, how Adaptive Desktop uses it, and how to set it up

This is the complete reference for the Kinect v1 on this machine: what the hardware is, what each
of its senses can and cannot do, how the software combines them, how to mount it on the TV, and
what to check when something is wrong. The gestures themselves are in [GESTURES.md](GESTURES.md);
the Air service as a whole is in [AIR.md](AIR.md); the spoken commands are in
[MARIO_COMMANDS.md](MARIO_COMMANDS.md).

## 1. The hardware

The Kinect here is a **Kinect for Xbox 360, model 1414** (the 1473 and Kinect for Windows work
too). Inside it are:

| Part | What it is | Used for |
| --- | --- | --- |
| Colour camera | 640 x 480 at 30 fps, ~62° x 48° view | Finding hands and people (MediaPipe) when the room is lit; the "Kinect Camera" webcam |
| Infrared projector | Throws a fixed pattern of invisible dots into the room | Lighting for the infrared camera; how depth is made |
| Infrared camera | 640 x 488, 8 bit, ~58° x 46° view | Depth; finding hands in the dark |
| Depth | 640 x 480, millimetres per pixel, 30 fps | Distance of every pixel: the palm's distance, the air push, finding hands without a picture, height |
| Tilt motor | ±27° up and down | Aiming at the couch ("Mario, tilt the Kinect down by 10") |
| Accelerometer | Which way is down | Pitch and roll in Studio; height measuring |
| LED | Green, red, yellow, blinking | Blinks green while Air looks for a hand, solid green while engaged |
| Four microphones | | Not used (Mario uses the laptop's microphone) |

**Power.** USB alone powers only the motor and LED. The cameras need the Kinect's own **12 V
supply** (the "Kinect power/USB adapter"). With it, `lsusb` lists *Xbox NUI Camera* (045e:02ae)
and *Xbox NUI Audio*; without it, only *Xbox NUI Motor*. `scripts/adaptive-air.sh --status` and
the Air menu in the top bar say which.

**Driver.** libfreenect 0.7.5, built without root into `.local/libfreenect` by
`kinect/build-libfreenect.sh` and loaded with ctypes (`services/adaptive-air/kinect.py`).
Nothing is installed system-wide.

## 2. The three senses, and the one rule that shapes everything

The Kinect v1 sends **colour or infrared, never both at once**: they share one USB stream, and a
switch between them takes about 0.8 s (measured: 0.78-0.84 s on this Kinect). **Depth always comes alongside** whichever one is on,
because it is made inside the Kinect from the infrared camera and the projector's dots.

So "use all three" means: depth all the time, and colour or infrared depending on the light.

| | Colour | Infrared | Depth |
| --- | --- | --- | --- |
| Works in the dark | No (below ~4% brightness MediaPipe finds nothing) | Yes (the projector is its light) | Yes |
| Sees fingers | Yes | Yes, after cleaning (see below) | Not at couch distance |
| Gives distance | No | No | Yes, 0.5 to 4.5 m |
| Fooled by | Dim light, posters, people on a screen | Sunlight (drowns the projector) | Glass, mirrors, black velvet, very shiny things |
| At 2.7 m (8.9 ft) | 1 px ≈ 5 mm; a hand is ~20 px wide | the same | steps of ~2 cm in distance; a few mm at 1 m |

### Which picture: `"video"` in `~/.config/adaptive-desktop/kinect.json`

- **`auto`** (the default): colour while the room is lit, infrared in the dark. If the colour
  picture stays darker than `dark_below` (0.04) for 2 s, the hub switches to infrared. From
  infrared it cannot see the room's light, so every 20 s it looks at colour for a moment and stays
  there if the picture is brighter than `light_above` (0.07). The gap between the two levels stops
  a dim room flipping back and forth. That look never happens **while you are engaged** (Air tells
  the hub) or **while the Kinect webcam is on**, so it never interrupts you.
- **`rgb`** or **`ir`**: always that picture.

Choose it in Kinect Studio (*Auto / Colour / Infrared*) or tell Mario: "night vision on",
"switch to colour", "night vision auto".

### In infrared

- The picture is the projector's dot pattern over the room. Before MediaPipe sees it, the dots are
  smoothed away (a 5 px median filter) and the contrast is evened out (CLAHE), giving a plain grey
  picture of you.
- Depth then comes in the infrared camera's own geometry (`FREENECT_DEPTH_MM`), not registered to
  the colour camera. A hand found in the infrared picture has its own distance under it, not a
  point a few centimetres to the side.
- Each camera has its own lens numbers (`kinect.INTRINSICS`): colour fx = 525, infrared fx = 575.8.
  The point cloud, height measuring and arm movement in metres all use the right one.

## 3. How hands are found: the fusion (`services/adaptive-air/fusion.py`)

Every frame, in `air.py`'s `Tracker`:

1. **Mirror** the picture and depth, so your right hand moves the pointer right.
2. **Follow** each hand already known: MediaPipe Hands (the more accurate model) looks in a square
   around where the hand was in the last frame, enlarged to 256 px. Two hands run in two threads.
3. **Find** a hand that is missing, beside the following (in its own thread):
   - near (the desk): MediaPipe Hands in the whole picture;
   - across the room: MediaPipe Pose finds you, then Hands looks in a square around each wrist.
4. **Check against depth.** A hand must be the right size for how far away depth says it is, and
   so must a person found by Pose. This rejects a hand on a poster, a person on a TV or laptop
   screen, and the "people" Pose sometimes sees in a dark corner (both happened in tests in this
   room). With no depth reading there, nothing is rejected.
5. **Refine with depth.** The palm's centre and distance come from the depth pixels on the palm
   (`refine_palm`: the near end of the pixels around the landmarks' palm, then a mean shift onto
   the hand itself). Across the room the 21 landmarks wobble by a pixel or two (about 1 cm at
   2.7 m); the centre of a few hundred depth pixels wobbles far less. The pointer follows this palm.
6. **Find hands from depth alone** (`DepthHands`): a hand-sized blob at least 20 cm ahead of
   everything around it, followed from frame to frame. It counts only after it has moved 12 cm
   (been raised), or where MediaPipe found a hand. That keeps out a lamp, a cup, the arm of the
   couch, a head (it has shoulders at its own distance) and a pole (too thin).
   - If MediaPipe has just lost a hand, depth carries it for 0.5 s with its last pose.
   - After that, or for a hand MediaPipe never saw, it is an **open hand with no fingers**:
     the pointer, push, swipes and waves work, pinch and fist do not.

Then the gesture engine (`gestures.py`) gets, per hand: the landmarks (or none), the palm, the
distance, and `scale` (how many metres the picture's width is at that distance).

**What the numbers say.** In the checks (`scripts/verify-air.py`), with a synthetic room:

- a still hand at 2.7 m moves the pointer by **2.7 px** (one standard deviation) on depth's palm,
  against **15.7 px** on landmarks alone;
- 20 cm of arm movement moves the pointer the same distance at 1 m, 2.7 m and 3.6 m;
- depth finds a raised hand within 3 px and 20 mm in ~4 ms a frame, and never the lamp, table,
  head, torso or couch.

On the real Kinect a frame takes ~32 ms in colour and ~36 ms in infrared (about the camera's own
30 fps). These are measurements on synthetic scenes and an empty room. How steady it is from
the couch is still to be tried (`docs/BACKLOG.md`, "Live, not yet tried").

## 4. Mounting it on the TV

Target: Kinect on top of the TV, ~1.92 m (6.3 ft) up; you on the couch 2.4 to 2.7 m (8 to 9 ft) away.

1. **Place it** centred on the TV, front edge flush with the screen, pointing into the room.
2. **Tilt it down** about 10° so it sees from the floor in front of the couch to above your head:
   "Mario, tilt the Kinect down by 10", or Studio's tilt slider. Check in Studio's colour view
   that your whole upper body and both raised hands are in the picture while sitting.
3. **Set its height** if the floor is out of view: `"mount_height": 1.92` in `kinect.json`
   (metres from the floor). With the floor in view the hub measures it.
4. **Check depth** in Studio's Depth panel: you should be a solid shape at ~2.5 m (orange-green),
   with no reading (black) only around edges and shiny things.
5. **Try the light**: switch the room lights off. Within ~2 s Studio's picture turns grey
   (infrared, "auto: the room is dark"). Lights on: within ~20 s it is colour again.

At 2.7 m the picture is **3.29 m wide and 2.47 m tall**, so there is plenty of room for both arms.
The whole screen width is **45 cm of arm movement** (`box_metres`) at any distance; the height
is 28 cm.

**Distances.** Depth reads 0.5 to 4.5 m. Closer than 0.5 m there is no depth: the pointer falls
back to the landmarks and push is off. Farther than ~4 m MediaPipe struggles even with the crops.

## 5. Kinect Studio and the hub

One process opens the Kinect: the hub (`services/adaptive-air/kinect_hub.py`, user service
`adaptive-kinect.service`). Air, Kinect Studio and the webcam all read from it at the same time,
through shared memory (`/dev/shm/adaptive-kinect-<uid>`, mode 0600) and HTTP on 127.0.0.1:8792.
It stops itself 20 s after nothing uses it.

Kinect Studio is the **Camera** section of the Kinect app now ([KINECT_MOTION.md](KINECT_MOTION.md);
`scripts/adaptive-air.sh --studio` and `apps/kinect-studio/studio.py` open it there). Its page is
still served at http://127.0.0.1:8792 for a browser: the colour or infrared picture, depth, the 3D
point cloud (drag, right-drag, scroll; PLY export), the accelerometer with pitch and roll, the
tilt motor, the LED, depth statistics, the frame rate, whether Air is reading, and the webcam
switch.

**Every published frame is one consistent snapshot.** libfreenect hands out the newest picture
and the newest depth separately; each carries the Kinect's own 60 MHz timestamp. A pair is
published only when the two were taken within two frames of each other (normally 2 to 3.3
million ticks apart; the first pair after a colour/infrared switch was measured 31 to 38 million
apart: a picture from before the switch beside depth in the new geometry). The hub keeps the
picture, depth, mode, the lens numbers of that mode, the sequence number, the capture time and
the camera *epoch* (how many switches so far) together under one lock; the point cloud, the PLY
export and the people tracker use only that; the shared frame store carries the epoch too, so a
reader can tell a switch away and back from one long run (the scanner skips other epochs).

**The people tracker** (`PoseSource`, `people.py`): the person detector runs in its own thread on
the newest frame (it costs ~70 ms; a new pose model ~150 ms to build, ~3x more on its first
inference, so models are built and warmed ahead); each person has a pose model on their own
crop, the infrared picture cleaned first and what depth says is far behind or in front of them
greyed out; a "person" depth keeps rejecting is let go and its place ignored until something
moves there. Identities: one global assignment per frame on predicted position, depth and body
signature; crossings that could go either way are *unsure* until resolved by the bodies, or both
numbers retired. `/api/people` lists only people seen in that frame; `hidden` lists the rest
without joints; `room` gives how far the floor goes before a wall; `timing` the costs.

Hub API (POST JSON `{"value": ...}` to `/api/<name>`): `led`, `tilt`, `video`
(`auto`/`rgb`/`ir`), `webcam` (true/false), `busy` (Air: engaged or not), `activity` (seconds, at
most 10, re-sent while a workout or game is live: no colour checks from infrared meanwhile), and
`lease` (`{"owner", "mode", "seconds"}` holds one picture mode for a 3D scan, up to 10 minutes per
request; `null` lets it go). GET `/api/status` reports `mode` (the picture frames are in now),
`next_mode`, `video` (the setting), `auto` (`lit`/`dark`), `light`, `epoch`, `unpaired` (pairs
dropped), `activity`, `lease`, `intrinsics`, depth statistics, accelerometer, tilt and more.

## 6. Settings, all optional

`~/.config/adaptive-desktop/kinect.json` (the hub):

```json
{"video": "auto", "dark_below": 0.04, "light_above": 0.07,
 "webcam": false, "tilt": null, "mount_height": 1.92}
```

`~/.config/adaptive-desktop/air.json` (Air):

```json
{"source": "auto", "webcam": 0, "tracking": "auto",
 "gestures": {"box_metres": 0.45, "natural_scroll": true},
 "fusion": {"ahead": 0.20, "arm_move": 0.12}}
```

- `source`: `auto` (the Kinect when its camera is on USB, else the laptop webcam), `kinect`, `webcam`.
- `tracking`: `auto`, `near` (desk only), `room` (always through your body first).
- `gestures`: every value in `gestures.DEFAULTS`; [GESTURES.md](GESTURES.md) lists them with what
  they mean in centimetres and seconds.
- `fusion`: every value in `fusion.DEFAULTS`: `band` (how deep a hand is, 0.10 m), `ahead` (how
  far ahead of the body a depth-only hand must be, 0.20 m), `ring_near`, `area_min`/`area_max`
  (0.005 to 0.035 m²), `elongation`, `arm_move` (0.12 m), `match`, `lost`.

Restart Air after changing these (Super+G twice); restart the hub for `kinect.json`
(`systemctl --user restart adaptive-kinect`), or use Studio's buttons, which apply at once.

## 7. When something is wrong

| You see | Why | Do |
| --- | --- | --- |
| Air menu: "Kinect has no power" | The 12 V supply is not plugged in | Plug in the Kinect's adapter; `lsusb` must list *Xbox NUI Camera* |
| Nothing engages from the couch | You are not in the picture, or MediaPipe does not see the hand | Studio: are you and both hands in view? Tilt down. Hold an open palm still, facing the TV, for half a second |
| Engages, but the pointer shakes | No depth on the palm (too close, a shiny ring, glass in between) | Studio's depth view: is your hand a solid colour? Sit 1 to 4 m away |
| In the dark: nothing | Infrared not on, or the cleaned picture is still too poor at that distance | Studio should say "Infrared · auto: the room is dark". Hold the hand out toward the TV: depth alone then gives the pointer (the chip says DEPTH ONLY) |
| Flips between colour and infrared | The room is right at the levels | Set `dark_below` lower or `light_above` higher in `kinect.json`, or fix `video` to `rgb` or `ir` |
| A phantom hand | Something hand-sized and hand-coloured at a hand's distance | `air.py --print --preview` shows what it found (`rgb`, `ir` or `depth` beside each hand) |
| Sunlight on the couch: no depth there | Sunlight drowns the projector's dots | Close the curtain on that side |

Tools:

```sh
scripts/adaptive-air.sh --status                    # running? which camera? what is on USB?
services/adaptive-air/air.py --print --preview      # events in the terminal + the picture and hands
scripts/adaptive-air.sh --studio                    # Kinect Studio
curl -s 127.0.0.1:8792/api/status | python3 -m json.tool   # the hub: picture, light, depth
scripts/verify-air.py --hardware                    # every check, plus the Kinect on USB
```

## 8. Privacy

Camera pictures stay in memory: the hub's shared memory is readable by you only, HTTP listens on
127.0.0.1 only, and nothing is written to disk except a point cloud you export yourself. Air sends
the shell only hand positions (21 points per hand, the palm, the distance), never pictures. The
camera is never on at login; the top bar shows a camera icon whenever Air runs.

## 9. Where the code is

| File | What |
| --- | --- |
| `services/adaptive-air/kinect.py` | libfreenect through ctypes: pictures, depth, motor, LED, accelerometer, lens numbers, USB probe |
| `services/adaptive-air/kinect_hub.py` | The one owner of the Kinect: shared memory, Studio, webcam, the light switch, `PoseSource` (person detector + one pose follower per person), `/api/people`, `/api/measure` |
| `services/adaptive-air/frames.py` | The shared-memory frame store |
| `services/adaptive-air/fusion.py` | Light switch, palm refinement, plausibility, hands from depth alone (pure) |
| `services/adaptive-air/air.py` | Air: the camera loop and the `Tracker` |
| `services/adaptive-air/gestures.py` | The gesture engine (pure) |
| `services/adaptive-air/people.py` | Everyone in view: floor plane, each person's depth, posture, straightness, tracking, height in cm, Mario's sentences (pure) |
| `services/adaptive-air/measure.py` | One-person height from depth and the accelerometer (kept for its helpers) |
| `services/adaptive-air/studio/` | Kinect Studio's page |
| `shell/adaptive-shell@local/air.js` | The HUD and what each gesture does on the desktop |
| `scripts/verify-air.py` | Every check (synthetic hands, a synthetic living room, the hub, height, rooms of posed people) |
