# Kinect: one app for fitness, games, the camera, the room, 3D scanning and your history

What the Kinect research in `kinect/` became. Every claim it rests on was checked first:
[KINECT_RESEARCH_VERIFICATION.md](KINECT_RESEARCH_VERIFICATION.md). The sensor itself, mounting
and the hub: [KINECT.md](KINECT.md).

**Status (2026-11-18): built and checked in software; not yet accepted live.** The live
acceptance needs people in front of the Kinect, in the light and in the dark, and a known object
to scan; see [Acceptance](#acceptance-what-is-measured-live). Until full fitness and games are
shown to work in darkness, this is not called ready.

## The app

One window, **Kinect** in the app grid (`apps/kinect/kinect.py`), with seven sections:

| Section | What it is |
| --- | --- |
| **Home** | The room as the Kinect sees it now (everyone as a figure), how many are in view, hidden and playing, the way into everything, and *your space*: how many activities fit where the Kinect is, with a one-press tilt fix |
| **Fitness** | 14 exercises with a 3D demonstration each, workouts, a rep race, the fitness check; a session with a countdown, a figure per person with a ring that fills each repetition, per-person coaching, rests that show the next move, and a summary that includes how well the Kinect saw you |
| **Games** | Wall Dodge, Pose Match, Body Racer as 3D scenes with a tutorial, sounds and scores; Kinect Pad (your body as a gamepad) |
| **Camera** | What Kinect Studio did: colour or infrared with everyone's skeleton, depth, the 3D point cloud (PLY export), picture mode, the "Kinect Camera" webcam, tilt, LED, measuring people, depth statistics, frame pairing |
| **Room** | The floor from above with everyone, where each activity fits (from the camera's real geometry), the room's measured end, zones, the coverage map, the event feed |
| **Scan** | Guided 3D scans: choose the subject, frame it, capture, build, inspect, export or save |
| **History** | People, the week, movement summaries, how well the Kinect saw each person, games, fitness checks, workouts; equipment; deleting history |

Navigation: the tabs, the keyboard (arrows and Enter, Escape back, 1 to 7 for the sections,
Space pauses a workout), or **the hand cursor**: hold a hand out towards the screen and a ring
follows it; hover over anything for 1.3 s to choose it. **F11** or the corner button: full
screen. Settings (the gear): voice, sounds, the hand cursor, your floor space, keeping the room
watched, and the full *where things fit* report.

Open it from the app grid, or `apps/kinect/kinect.py [home|fitness|games|camera|room|scan|history]
[--fullscreen] [--demo]` (`fitness/squat`, `games --game walls` open one thing directly). It is
one instance: a second command moves the open window. The old commands still work and open the
matching section: `apps/kinect-motion/motion.py fitness|arcade|room`, `apps/kinect-studio/studio.py`,
`scripts/adaptive-air.sh --studio`, Mario's "open Kinect Studio". `--demo` runs the app with two
synthetic people and its own settings and history (none of yours). The right-click menu of the
launcher has Fitness, Games, Camera and 3D Scan.

Install / reinstall: `./install.sh --only motion` (needs Air: `./install.sh --only air`). It puts
one launcher in the app grid and removes the old Kinect Fitness, Arcade, Room and Studio ones.
Kinect Studio's own page is still at http://127.0.0.1:8792 for a browser.

## How it fits together

```
Kinect v1 ─USB─▶ Kinect hub (adaptive-kinect, :8792)                      services/adaptive-air/
                 the one owner of the Kinect. Each picture is published only with the depth taken
                 with it (device clocks within two frames), as one snapshot: picture, depth, mode,
                 lens numbers, sequence, capture time, camera epoch.
                 PoseSource: person detector in its own thread, one warmed pose model per person,
                 the infrared picture cleaned first, each crop masked by depth around its person
                 people.py: floor plane, room depth, 33 depth-fused joints per person, identities by
                 global assignment, crossings marked unsure, hidden people listed apart
                 holds infrared for a live activity (no colour checks) and for a scan (a lease)
                           │ /api/people (long poll: always the newest state)
                           ▼
Kinect Motion (kinect-motion, :8793)                                       services/kinect-motion/
  engine.py      drops repeated and late frames; the watchdog (30 a second, frames or not)
  skeleton.py    One Euro smoothing; bone-length and speed checks demote joints to inferred
  players.py     slots 1-4: active / unsure / hidden / rejoin / away; rejoin only when unambiguous
  calibration.py what fits where, from the camera's height, tilt, lens, the room and your body
  exercises.py   14 exercises: repetitions only from rest seen, holds, cues, insufficient evidence
  games.py       Wall Dodge, Pose Match, Body Racer on the same evidence rules
  training.py, store.py   maths and history (results only; migrated in place)
  scan.py + scan_worker.py   3D scan jobs in a supervised process
  room.py, pad.py, bodygestures.py, demos.py
                           │ /ws (state per frame, and from the watchdog), /api/..., /hub/... (proxy)
                           ▼
apps/kinect/kinect.py: one GTK/WebKit window on /app (static/: core.js, gl.js, scene.js and a file
per section; app.src.css from the design tokens)
```

## Tracking: what was measured, what changed

The baseline was measured first, on this Kinect (0.80 m up, nobody in view), with
`scripts/kinect-baseline.py`:

| | Before | After |
| --- | --- | --- |
| Skeleton updates a second (hub) | 11.3 | 28.9 |
| Camera to Kinect Motion, median / 95th percentile | 79 / 259 ms | 21 / 38 ms |
| Repeated frames | 0 | 0 |

The numbers with people in view are part of the live acceptance (each pose model costs about
25 ms on this CPU when warmed; two run in parallel in about 26 ms).

What was wrong and what was done:

- **The detector was on the frame path.** The person detector takes ~70 ms and a new pose model
  ~150 ms to build (measured); both ran inside the frame loop. Now the detector runs in its own
  thread on the newest frame, newcomers arrive with a model already built and warmed (a model's
  first inference costs ~3x a later one), and a "person" that depth keeps rejecting (a coat, a
  poster) is let go and its place ignored until something moves there.
- **Pictures could be paired with the wrong depth.** After a colour/infrared switch the first
  picture was ~0.5 s older than its depth (device timestamps 31-38 million ticks apart, against
  2-3.3 million normally), and the switch takes ~0.83 s, not the 0.3 s once assumed. The hub now
  drops any pair more than two frames apart and publishes one snapshot (picture, depth, mode, lens
  numbers, times, epoch) under one lock; the point cloud, PLY export and the people tracker use
  only snapshots; the scanner skips frames from another epoch.
- **Infrared for bodies.** The pose path now cleans the infrared picture (median filter for the
  projector's dots, CLAHE) as Air does for hands, and greys out what depth says is far behind or
  in front of each person in their crop. A workout or game in progress tells the hub so: no look
  at colour interrupts infrared play.
- **Identity.** One global assignment per frame (cheapest overall, not nearest-first) on predicted
  position, depth and a body signature (height, shoulder width, limb lengths). Two people whose
  assignment could go either way are marked *unsure* until they are apart; then their bodies
  decide, or both numbers are retired rather than guessed. Players follow hub numbers, never
  positions in the picture; an unsure player does not count, a retired one must raise a hand,
  and someone coming back is matched automatically only when exactly one player could be them.
- **Present, hidden and playing are counted apart.** The hub lists only people seen in this frame;
  someone behind another person is *hidden* (with how long ago they were seen, no joints). A
  remembered position is never drawn or counted as a sighting.
- **Freshness.** Kinect Motion drops repeated and late frames (captured more than 0.5 s ago), and a
  watchdog 30 times a second marks a player *lost* after 0.35 s without a fresh sighting: their
  repetition in progress is dropped (a repetition counts only from a rest the camera saw), a
  timed step waits while nobody is seen (from the last sighting), game lanes freeze, Kinect Pad
  lets go, and the screen says what to do.
- **Evidence.** Joints moving faster than a limb can (12 m/s) or breaking their learnt bone length
  are demoted to inferred; counting needs the exercise's joints seen; Arcade's old left-to-right
  numbering and its page-side scoring from whatever joints it had last are gone: the games run on
  the server on the same rules.
- **Lean was the wrong way round.** `lean` was +1 for the person's left (the picture's right);
  Wall Dodge, Body Racer's lean steering and Kinect Pad's lean mode now use the person's own sides.
- **Drawing is smooth, deciding is not.** The page draws each joint between the last two real
  observations (never ahead of them); every count and score is the server's.

## Where things fit (calibration.py)

The fixed play area (1.3 to 4.2 m) is gone. From the hub's floor fit (the Kinect's height and its
full up vector), the lens of the picture the joints came from, the room's measured end (depth of
what stands 0.3-2 m high), your floor space (`space_m`, 2 m unless you change it) and the
player's height, every activity's envelope (the joints it counts from: a squat needs feet to
shoulders, jumping jacks feet to raised hands and arms out, a curl hips to shoulders) is projected
into the picture. The answer is a band of distances where it fits, or exactly why it fits nowhere:
*"It needs feet to raised hands in view: your raised hands would leave the top of the picture
closer than 3.1 m and you have 2.0 m."* Players standing where their activity does not fit are
paused with the reason. Settings also suggests a tilt: *"Tilt it up 10° and curls, raises,
punches and Body Racer fit too, but not jumps, planks and balance."*

On 2026-11-18 (Kinect 0.80 m up, 4° down, 2 m of floor): 13 of 17 activities fit; jumping jacks,
the shoulder press, Wall Dodge and Pose Match do not (raised hands leave the picture), and tilting
up 9° fits all 17. A Kinect v1 sees 43° vertically: at 2 m that is 1.6 m of height in all.

## Fitness

Choose an exercise (its tile says whether it fits here, and why not), a workout, a challenge or
the fitness check; every exercise has a looping 3D demonstration made from the same joint angles
the counter measures. Pick a profile and any weights for each player. In the session: a countdown
with the demonstration in the corner, everyone as a figure (or over the camera picture), a ring
over each head that fills through a repetition with the count inside, the cue for each person, a
card per player (count, form, partials, tempo, left/right, jump height, sway, reach), rests that
show the next exercise, and a summary with *next time* advice and how well the Kinect saw each
person (share of time seen, losses, updates a second, share in infrared).

Body controls (held, so exercising does not trigger them): raise a hand to join (or rejoin), both
hands up and hold to pause, swipe between sets to skip, T-pose to recalibrate.

The exercises, their counting rules, cues and MET values are unchanged from the first version
(table in `exercises.py`); what changed is that a repetition counts only from a rest position the
camera saw, so a set started mid-movement (or interrupted by lost tracking) does not count its
second half, and that sit-to-stand can start seated (the standing hip height comes from the leg's
own length until the person has stood).

## Games

Wall Dodge (walls with real cut-outs rush down each player's lane; seen from behind your own
figure), Pose Match (copy the white figure and hold it), Body Racer (3D roads with coins and
cones; steer with an imaginary wheel or by leaning). Each has a tutorial with demonstrated moves,
a 3-2-1, sounds and a game-over screen; named players' scores are saved. Nobody is penalised for
being out of sight: a wall waits, the round clock stops, the car coasts and meets nothing, and a
wall that arrives while the joints it needs cannot be seen is waved through (no point, no life).

Kinect Pad (Off / Wheel / Lean / Arrow keys) is unchanged and lets go the moment its player is out
of sight or frames stop, from the watchdog, not only when a frame says so.

## Camera and Room

Camera is Kinect Studio inside the app (through `/hub/`, so one origin): the picture mirrored
like everywhere else with skeletons, depth, the point cloud (drag, right-drag, scroll; PLY),
picture mode, webcam, tilt, LED, measuring everyone, depth statistics, and the hub's frame figures
(camera switches, pairs dropped, whether a scan holds the picture).

Room: the floor from above with the Kinect's real lens, your floor limit and the room's end,
where a chosen activity fits, zones (with *Where I stand*), the coverage map and the event feed.
Events and Home Assistant / MQTT are as before (`ws://127.0.0.1:8793/events`, `motion.json`).

## Scan

**Choose → Frame → Capture → Build → Inspect → Export.**

| Subject | Capture | What you get |
| --- | --- | --- |
| Object | one view, the median of 15 depth frames | the side facing the Kinect; the back is reported as not seen |
| Turning object | 12 held turns of about 30° (anticlockwise seen from above), let go each time | the whole way round |
| Person | 8 held turns of 45°, standing still at each | a 3D you |

*Frame* shows depth live with the subject lit: a depth range, an area you drag on the picture, and
the empty background captured first if you like; it says what to do (too close, off the edge, the
room is in it, ready). *Capture* tells you when to turn and waits until you hold still. *Build*
lines up each held view from its turn about the subject's own vertical axis (the axis and the way
it turned are found from the first turn; ICP may only nudge after that) and fuses them (TSDF).
*Inspect* is an orbitable surface or point view with the size (along the camera's axes and the
scan's own), views fused, open edges, and plainly what was not seen: a turn that did not line up
is left out and named, and the scan is not called complete. Nothing unseen is filled in.
*Export*: STL in millimetres, OBJ and PLY in metres or millimetres, each with a `.units.json`;
*Save* puts every format and the measurement report in `~/Kinect Scans/<name>/` and lists it in the
Scan section (remove from the list, or delete the files).

While framing and capturing, the hub is leased into infrared depth (the scanner's geometry); a
workout or game must be paused first (the app asks). The capture and build run in
`scan_worker.py`, a separate process: Cancel stops it at once. Depth captures live in
`$XDG_RUNTIME_DIR/kinect-scan/` (yours only) and are deleted as soon as the build ends, whether it
worked or not; the built geometry is deleted when you discard the scan, scan again, or the service
stops. `scripts/kinect-scan.sh` (the scanner's own command line) is unchanged.

**Accuracy measured on synthetic depth** (boxes of known size ray-cast through the Kinect's
infrared lens, `scripts/verify-kinect-scan.py`): a single view measures the face it sees within
6 mm; a 370 x 260 x 150 mm object turned in 12 held steps, each up to 8° off, comes out within
4 mm in height and 8-37 mm too large in width and depth (flat faces register least well); a
body-sized subject in 8 turns comes out within 30 mm in height. Turning objects were first
registered frame to frame from continuous capture, which drifted 50 to 110 mm over a turn; that
was replaced. Real accuracy on the Kinect, with its noise, is part of the live acceptance.

## History

Results only, on this computer (`~/.local/share/adaptive-desktop/fitness.db`, mode 600): people,
equipment, workouts and sets (with each repetition's range and tempo), fitness checks, game scores,
how well the Kinect saw each person per activity, and the list of saved scans. Older files are
migrated in place (schema version 2), keeping everything. History shows movement summaries (form,
range of motion, tempo, left/right per exercise over four weeks) and tracking quality by activity.
Delete one workout, one person's history (they and their weights stay), forget a person entirely,
or delete everyone's history; deleted rows are gone from the file too (VACUUM).

## Settings

`~/.config/adaptive-desktop/motion.json` (all optional; the app writes what you change):

```json
{"voice": true, "space_m": 2.0, "auto_solo": true, "sit_minutes": 45, "slouch_degrees": 25,
 "zones": [{"name": "sofa", "on": "floor", "x": [-1.2, 0.4], "z": [3.4, 4.2]}],
 "room_always": false, "webhook": null, "mqtt": null}
```

`space_m`: metres of floor in front of the Kinect you can use (null: only the room's own end).

## Privacy

Pictures never leave the hub (shared memory readable by you only, HTTP on 127.0.0.1). Kinect
Motion keeps results only: no images, no depth, no skeletons on disk; the only depth it ever
writes is a scan's temporary captures, while you scan, deleted as soon as the build ends. Nothing
leaves the computer unless you configure a webhook or MQTT, and then only small semantic events.
The Kinect is off unless the app is open (or `room_always`).

## Checks

```sh
scripts/verify-kinect-motion.py   # ~140 checks in seconds (verify-all.sh --quick): exercises,
                                  # gestures, freshness and the watchdog, identity, games, calibration,
                                  # history and migration, server
scripts/verify-air.py             # the hub: frame pairing, snapshots, lease, crops, identity in people.py
scripts/verify-kinect-scan.py     # scanning on synthetic depth, ~30 s (verify-all.sh, full)
xvfb-run -a -s "-screen 0 1920x1200x24" python3 scripts/verify-kinect-app.py [--shots DIR]
                                  # the real window on a virtual display: every section, the old
                                  # commands, full screen, a workout, the games, reconnecting
scripts/kinect-baseline.py --seconds 30 --players 1 --label "..." --save   # live tracking figures
```

## Acceptance: what is measured live

Done in software (the checks above); **to do with people and the real room**, in this order:

1. Tracking figures with `scripts/kinect-baseline.py --save`: one person, then two, lights on,
   then lights off (infrared). Targets: 15 updates a second for one, 12 for two, camera to here
   under 200 ms at the 95th percentile, no repeated frames, ids kept while two people cross
   repeatedly.
2. Rendering: the app full screen on this laptop during each game, the page's own figure (the
   `fps` in `curl 127.0.0.1:8793/api/ui`): 60 aimed for, 30 sustained required. On a virtual
   display (software rendering) it is 21-22; that is not the measurement.
3. Repetitions: for each exercise that fits, three sets counted by hand against the app, in light
   and in the dark: at least 95% correct, at most one error in a 20-repetition set, and none from
   a stale frame (cover the Kinect mid-set: nothing may count).
4. Every game in light and dark: no life, point or crash from tracking loss alone; identities
   stable while two players cross.
5. Scanning: a box or book of known size (object and turning object), a failed alignment (move
   it while it is taken), incomplete coverage (stop half way), export units in a slicer,
   Cancel leaves nothing in `$XDG_RUNTIME_DIR/kinect-scan/`, and a person scan. Record the
   measured error.

**Darkness is a release gate**: infrared viewing alone does not pass; if body tracking in the dark
fails these tests, that is reported as unmet and the app is not called ready.

## When something is wrong

| You see | Do |
| --- | --- |
| "Kinect hub: ..." in the status pill | `systemctl --user status adaptive-kinect`; the Kinect needs its 12 V supply ([KINECT.md](KINECT.md)) |
| An activity says it does not fit | Settings (gear) → *Where things fit* says why; try the tilt it suggests, or stand where Room shows the green band |
| Nobody appears | Stand where Room's band is, facing the TV; Camera shows what the Kinect sees |
| "I've lost you" | Step back into view; nothing counts while you are not seen, and the clock waits |
| "Raise a hand so I know which one you are" | Two people crossed and could not be told apart: raise a hand to take your slot back |
| A scan says the room is in it | Narrow the depth range, drag an area on the picture, or capture the empty background first |
| A Kinect process will not stop | `scripts/adaptive-air.sh --stop-all` closes the app and stops Motion, Air and the hub |
| Latency feels high | Close Camera's point cloud; fewer people in view; the status pill's tooltip shows the figures |
