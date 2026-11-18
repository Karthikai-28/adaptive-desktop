# Kinect Motion: Kinect Fitness, Kinect Arcade, Kinect Room, Kinect Pad, and the scanner

What the Kinect research in `kinect/` became. Every claim it rests on was checked first:
[KINECT_RESEARCH_VERIFICATION.md](KINECT_RESEARCH_VERIFICATION.md). The sensor itself, mounting
and the hub: [KINECT.md](KINECT.md).

| App | What it is | Open it |
| --- | --- | --- |
| **Kinect Fitness** | Workouts for one to four people: counts repetitions, coaches form aloud, times holds, rep races, a fitness check every four weeks, history | App grid "Kinect Fitness", or http://127.0.0.1:8793/fitness |
| **Kinect Arcade** | Whole-body games (Wall Dodge, Pose Match, Body Racer) and **Kinect Pad** (your body as a gamepad for any game) | App grid "Kinect Arcade", or /arcade |
| **Kinect Room** | Who is in the room and where, zones, sitting reminders, pointing at things, the tracking-coverage map, the event stream | App grid "Kinect Room", or /room |
| **Kinect scanner** | 3D snapshots, measurements, turntable and rotation scans, STL/PLY/OBJ export | `scripts/kinect-scan.sh <command>` |

From a terminal: `apps/kinect-motion/motion.py fitness|arcade|room [--fullscreen]`. **F11** toggles
full screen (for the TV). `--demo` opens the same apps with two synthetic people, no Kinect needed.
Install / reinstall: `./install.sh --only motion` (needs Air: `./install.sh --only air`).

## How it fits together

```
Kinect v1 ─USB─▶ Kinect hub (adaptive-kinect, :8792)                      services/adaptive-air/
                 one owner of the Kinect; colour/infrared + depth
                 PoseSource: person detector + one pose model per person (MediaPipe, up to 6)
                 people.py: floor plane, each person's depth, posture, height,
                   33 joints in the ROOM frame, depth-fused, each Tracked / Inferred / Missing
                           │ /api/people (long poll, every frame)
                           ▼
Kinect Motion (kinect-motion, :8793)                                       services/kinect-motion/
  skeleton.py     angles; One Euro smoothing; bone-length sanity per person
  bodygestures.py raise a hand, both hands up, T-pose, clap, swipe, point, jump, duck, lean, wheel
  players.py      join, slots 1-4, identity kept across exits, play area and spacing
  exercises.py    14 exercises: repetition machine, form cues, holds, "insufficient evidence"
  training.py     MET calories (estimate), trusted load, volume, progression, workouts, the check
  store.py        SQLite history: results only
  room.py         occupancy, zones, sit and slouch reminders, point-at-zone, coverage map
  pad.py          uinput virtual gamepad / arrow keys
  engine.py       all of the above, once per frame       server.py  pages, /ws, /events, API
                           │
              /fitness  /arcade  /room   (static/, motion.src.css from the design tokens)
```

**Tracking.** Microsoft's Kinect found joints with a forest classifying every depth pixel
(Shotton et al. 2011); that model and its training data are not available on Linux. Here,
MediaPipe's pose model runs on each person separately (top-down, so six people each get a full
33-joint skeleton, where the Kinect v1 SDK gave full skeletons to two), and **Kinect depth fixes
where each joint really is**: the depth under each landmark, pushed back by the limb's radius
(the same correction Shotton's method makes), checked against the model's own skeleton. A joint
whose depth agrees is *tracked*; a hidden one is *inferred* from the model anchored on the
depth-measured torso; and the screen draws them solid and hollow. Joints are smoothed with a
One Euro filter, and a joint that suddenly breaks its learnt bone length (a depth pixel on the
sofa) is demoted to inferred.

## Kinect Fitness

**Players.** Alone in the room you are Player 1 by being there. In a group, **raise a hand** for
a moment to join, or press **Start** and everyone in view plays (up to four, each in their own
colour). Pick a **profile** for each player (History → People: add a name, and body weight if you
want calorie estimates); a Guest's results are shown but not saved. Step out and back within
25 s and you keep your slot: you are matched by where you stood and your height.

**Choosing** (side panel):

- **Train**: any exercise, with a target. Ends when you press Finish (or swipe between sets).
- **Workouts**: Quick start, Strength, Cardio burst, Balance and mobility: steps with rests.
- **Challenge**: a rep race (30/60/90 s). Only full, clean repetitions count.
- **Check**: the fitness check: sit-to-stands in 30 s, jumping jacks in 30 s, one-leg balance
  (time and sway), toe-touch reach (how close to the floor), squat-jump height. Retake every four
  weeks; each number is compared with *your* last check (better / same / worse). No population
  norms are claimed.
- **History**: the week's workouts, reps, minutes, estimated kcal, kg lifted, streak; past
  checks; recent sets; people and their weights.

**Controls without a remote** (all held or fast on purpose, so exercising does not trigger them):

| Do | It does |
| --- | --- |
| Raise one hand above your head (~½ s) | Join |
| Both hands up and hold (~1 s; ~2 s during a set, so a press is not a pause) | Pause / resume |
| Swipe a hand across your chest, between sets | Skip to the next step |
| T-pose (arms straight out) and hold | Recalibrate (forget learnt bone lengths) |

**On screen:** your skeleton (or, with **Camera** on, over the Kinect's picture), a ring above
your head that fills through each repetition with the count inside, the cue for you in yellow,
and the scoreboard: reps / target, form %, partial reps, seconds per rep, left/right counts, best
jump, sway, reach. **Voice** speaks the cues (speech-dispatcher, one line at a time, at most every
2.5 s per player).

**The exercises** (MET from the 2024 Adult Compendium; *proxy* = no entry, nearest one used):

| Exercise | Counts | Coaches | MET |
| --- | --- | --- | --- |
| Squat | knees from straight (> 155°) to < 100° and back | "Go a little deeper" (half reps are not counted), "Keep your chest up", "Push your knees out over your toes", "Sit evenly on both legs", "Lower yourself more slowly" | 5.0 (02052) |
| Lunge | either knee to < 108°; left/right legs counted | "Drop your back knee lower", "Keep your torso upright" | 3.8 (02022) |
| Jumping jacks | arms from down to overhead | "Arms all the way up", "Jump your feet wider" | 7.5 (02020) |
| High knees | each knee to hip height, each side counted | "Knees higher" | 7.5 proxy |
| Biceps curl | elbow 145° → 62°; both arms together count once, alternating each | "Curl all the way up", "Keep your elbows by your sides", "Don't swing your body", "Lower the weight slowly" | 3.5 (02054) |
| Shoulder press | wrists from shoulder rack to straight overhead | "Press all the way up", "Brace your core, don't lean back", "Press both arms evenly" | 3.5 (02054) |
| Lateral raise | arms to shoulder height | "Raise to shoulder height", "Stop at shoulder height", "Raise both arms evenly" | 3.5 (02054) |
| Sit to stand | hips from seated to your standing height | "Stand all the way up" | 3.0 (02056) |
| Squat jump | hips above standing height; **jump height in cm** | — | 6.5 (02057) |
| Punches | each arm's elbow to straight | — | 7.5 proxy |
| Plank (side-on to the TV) | seconds in a straight line | "Lift your hips a little", "Lower your hips into a straight line" | 2.8 (02024) |
| Wall sit | seconds with knees ~90° | "Slide down to about a right angle", "Not quite that low" | 3.8 proxy |
| One-leg balance | seconds on one leg, **sway in cm** | "Lift one foot off the floor" | 2.3 proxy |
| Toe-touch reach | seconds folded, **hands' lowest height in cm** | "Keep your knees straight" | 2.3 (02101) |

**Honest by design.**
- If the Kinect cannot see the joints an exercise needs (any of them missing, or too many only
  estimated), it stops counting and coaching and says *"I can't see you well enough"*, rather
  than coach from a guess. Joint angles from a depth camera are good when the joint is visible
  and poor when it is hidden, so this matters.
- **Calories** are estimates (MET x 3.5 x kg / 200 per minute of work, ACSM), shown only when
  you have entered a body weight.
- **Weights** are never guessed from the picture (no camera can see a dumbbell's mass). Register
  your equipment (History → a person → "Add weight"), then pick it for a player; or choose "Other
  weight…" and type it. The source is recorded with the set (catalog / confirmed).
- **Next time** suggestions use double progression: all sets done well → +2 reps; high reps with
  a weight → +2.5 kg; poor form → same again, cleaner.

**Safety.** The safe area is where a whole body stays in the Kinect's view: 1.3 to 4.2 m from
the TV and away from the picture's edges. Too close to the TV, out of the area, or two players
closer than 0.9 m: that player's count pauses and the screen and voice say why.

## Kinect Arcade

Everyone who joined in Fitness plays; with nobody joined, everyone in view plays (up to four).

- **Wall Dodge**: walls rush at each player's lane; **duck, jump, lean left/right, arms up or
  arms out** to fit through as it arrives. Three lives; walls speed up.
- **Pose Match**: copy the white figure (Star, Robot, Goalpost, T, Skier, Reach up, Half star)
  and hold it for a second; similarity is from your joint angles; quicker scores more.
- **Body Racer**: one road per player, 60 s. Steer an imaginary wheel (or by leaning, chosen in
  the panel), push your hands out to speed up, pull them back to brake. Coins and cones.

`motion.py arcade --game walls|pose|race` opens straight into a game.

### Kinect Pad: your body as a game controller

Off / **Wheel** / **Lean** / **Arrow keys** in the Arcade panel. It makes a virtual device through
Linux uinput that games see as an ordinary controller:

| | Wheel | Lean | Arrow keys |
| --- | --- | --- | --- |
| Steer | tilt the wheel in your hands → left stick X | lean your body | Left / Right |
| Accelerate | hands pushed out → right trigger | — | Up |
| Brake | hands back at the chest → left trigger | — | Down |
| Jump / duck | A / B | A / B | Space / Ctrl |
| Both hands up | Start | Start | Enter |

Steering has a dead zone and an exponential response, and **every input is released the moment
you leave the picture**. Works with Steam, emulators and native games; and with **chiaki-ng**
(open-source PS5/PS4 Remote Play for Linux), which makes this the route from your body to a PS5:
unofficial, not Sony-endorsed, with Remote Play's own latency on top. On this machine /dev/uinput
is already writable for you; on another one run `scripts/install-kinect-motion.sh --pad` once
(udev rule for the `input` group, asks for sudo).

## Kinect Room

- **The floor from above**: the Kinect and its 57° view, the safe area (dashed), everyone as a
  dot with their shoulders, posture and height, zones, and where anyone is pointing.
- **Coverage map**: walk slowly over the area you use for a minute, alone; each 25 cm cell turns
  green (the Kinect saw your whole body there), yellow or red. Move the Kinect or furniture until
  where you exercise is green: the research's "room-specific tracking heat map".
- **Zones**: name rectangles on the floor (sofa, desk, mat) or on the TV wall (lamp, picture);
  stand somewhere to read your position in the "In the room" panel.
- **Events**, live at `ws://127.0.0.1:8793/events` as JSON lines: `room_occupied`,
  `room_empty`, `people_count`, `person_enter_zone` / `person_leave_zone`, `raise_hand`,
  `point_at_zone` / `point_at`, `sit_reminder` (after `sit_minutes` sitting, spoken),
  `posture_warning` (slouching for ten minutes while sitting), and from Fitness `exercise_rep`,
  `exercise_set`, `joined`, `paused`... Only the event leaves the service, never a picture or a
  skeleton (`person 2 / squat / repetition 14`).
- **Home Assistant**: put its webhook URL in `motion.json` as `"webhook"`; each event is POSTed
  as JSON (HA's webhook trigger reads it directly). With `mosquitto_pub` installed, `"mqtt":
  {"host": "...", "topic": "kinect"}` publishes to `kinect/<event>` too.

The room is watched only while one of the pages is open, unless you tick "Keep watching the room
with no page open" (`room_always`): then the Kinect stays on.

## The scanner

The Ubuntu scanner from the research (`kinect/kinect-v1-ubuntu-scanner`), run from this checkout:

```sh
scripts/kinect-scan.sh doctor                                   # what is installed, what is on USB
scripts/kinect-scan.sh probe --out ~/Kinect\ Scans/intrinsics.json   # factory calibration (hub stopped)
scripts/kinect-scan.sh background --out ~/Kinect\ Scans/empty.npz --samples 30
scripts/kinect-scan.sh snapshot --background ~/Kinect\ Scans/empty.npz --z-min 0.6 --z-max 1.5 --out ~/Kinect\ Scans/mug
scripts/kinect-scan.sh record --background ~/Kinect\ Scans/empty.npz --seconds 40 --fps 5 --delay 5 --out ~/Kinect\ Scans/turn
scripts/kinect-scan.sh reconstruct --session ~/Kinect\ Scans/turn --mode auto --out ~/Kinect\ Scans/turn-mesh
scripts/kinect-scan.sh convert --input ~/Kinect\ Scans/turn-mesh/fused_mesh.ply --input-units m --out print.stl
```

It reads the Kinect through the hub when the hub runs (so the apps can stay open; frames are
never mixed between the colour and infrared geometries), otherwise directly through
`.local/libfreenect`. Outputs: PLY/PCD/XYZ points and PLY/OBJ/STL meshes (STL in millimetres with
a units file) and a measurements report that says what was and was not observed. The full guide:
`kinect/kinect-v1-ubuntu-scanner/docs/INSTALL_AND_USAGE.md`; what was run here: its
`docs/VALIDATION.md` addendum.

## Settings

`~/.config/adaptive-desktop/motion.json` (all optional; the pages write `zones`, `voice`,
`room_always`):

```json
{"voice": true, "auto_solo": true, "sit_minutes": 45, "slouch_degrees": 25,
 "zones": [{"name": "sofa", "on": "floor", "x": [-1.2, 0.4], "z": [3.4, 4.2]}],
 "room_always": false, "webhook": null, "mqtt": null}
```

History: `~/.local/share/adaptive-desktop/fitness.db` (mode 600). "Forget <name>" in History
deletes a person and every result recorded for them.

## Privacy

Pictures never leave the hub (shared memory readable by you only, HTTP on 127.0.0.1). Kinect
Motion sees joints only and stores results only: no images, no depth, no skeletons on disk.
Nothing leaves the computer unless you configure a webhook or MQTT, and then only the small
semantic events above. The Kinect is off unless an app is open (or `room_always`).

## Checks

```sh
scripts/verify-kinect-motion.py      # ~90 checks, seconds, no Kinect (in verify-all.sh --quick)
apps/kinect-motion/motion.py fitness --demo    # the whole app with two synthetic people
```

The checks drive everything with synthetic people built from joint angles, so each one knows
the right answer: exact repetition counts for every exercise, also under 3 cm of noise and with a
quarter of the frames lost; each form fault produces its cue and clean form does not; hidden
knees stop the count; gestures fire when held and not when brief (and a press is not a pause);
the steering wheel's sign; rejoining by position and height (and a 30 cm shorter stranger is
not taken for the player); spacing and the play area; the calorie, load, volume and progression
maths; the history and "forget"; a two-player 20 s squat race end to end (8 squats, the guest not
saved); room events; the pad's release on tracking loss; the depth-fused joints on Air's
synthetic room (head within 4 cm, hips within 6 cm); the server, pages and scripts.

## Not yet verified live

Measured on the real Kinect so far: the hub → Kinect Motion pipeline (~9 skeleton updates a
second, latency median 86 ms, 95th percentile 292 ms with nobody in view), the floor plane, the
scanner's snapshot both ways. **Not yet tried with people in front of it**:

- Repetition counts and cues against a person (count by hand on a recorded set and compare;
  the research's acceptance protocol), for each exercise.
- Two to four people at once: tracking rate with several pose followers, identity swaps when
  people cross.
- The mount: the Kinect was 0.79 m up on Nov 18; the coverage map at the final ~1.9 m TV mount.
- Plank and other floor exercises from the final mount (the floor is near the picture's bottom).
- Kinect Pad in a real game, and through chiaki-ng to a PS5.
- Wall Dodge jump timing at the real frame rate.

## When something is wrong

| You see | Do |
| --- | --- |
| "Kinect hub: ..." in the status pill | `systemctl --user status adaptive-kinect`; the Kinect needs its 12 V supply ([KINECT.md](KINECT.md)) |
| Nobody appears | Stand 2 to 3.5 m away, facing the TV; light the room or let infrared take over; Kinect Studio shows what the Kinect sees |
| "I can't see you well enough" | Step back until your feet are in the picture; move furniture from between you and the TV |
| Counts look wrong for an exercise | Face the TV (plank: side-on); slow down; check the scoreboard's partials: half reps are not counted on purpose |
| Kinect Pad: "No access to /dev/uinput" | `scripts/install-kinect-motion.sh --pad` once, then log out and in |
| A Kinect process will not stop | `scripts/adaptive-air.sh --stop-all` closes the windows and stops Motion, Air and the hub. Stop them with `systemctl --user stop`, not `kill -9`, though a `kill -9` now also stays stopped. Each service also stops itself when unused: Motion a minute after the last page closes, the hub 20 s after nothing uses it |
| Latency feels high | Close Kinect Studio's point cloud; fewer people in view; the status pill's tooltip shows the median and 95th percentile |
