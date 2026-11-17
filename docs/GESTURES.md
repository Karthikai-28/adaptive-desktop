# Air gestures: what each one is for, exactly how to do it, and why it might not work

The complete reference for every hand gesture Air knows. For each one: what it is for, how to do
it, what it does on the desktop, which of the Kinect's senses it needs, the exact rule the engine
uses (in centimetres and seconds), and what usually goes wrong. The sensor, mounting and
troubleshooting are in [KINECT.md](KINECT.md); the overview is in [AIR.md](AIR.md).

The rules live in `services/adaptive-air/gestures.py` (`DEFAULTS` holds every number), and what
each gesture does on the desktop lives in `shell/adaptive-shell@local/air.js` (`_onEvent`).

## How to read the numbers

With the Kinect knowing your distance, the area your hand moves in for the whole screen is
**45 cm wide and 28 cm tall** (`box_metres`), wherever you sit. Many rules are in "hand sizes":
one hand size is your wrist to the knuckle of your middle finger, about **9 cm**. "Screen" means
a fraction of the screen (1920 x 1200 here). Fast movement is measured in box widths or heights
per second.

**Senses** (KINECT.md §2):

- **fingers**: needs the colour or infrared picture (MediaPipe's 21 landmarks). Works lit or dark,
  but not with a hand found by depth alone.
- **depth**: needs the Kinect's depth (not the laptop webcam).
- **any**: works even with a hand found by depth alone (the chip says DEPTH ONLY).

## The basics

### Engage: start using Air

- **For**: telling Air that you, not someone walking past, want the pointer.
- **Do**: raise an **open palm** (fingers spread, facing the TV) and **hold it still** for about
  half a second. The ring fills, brackets slide in, the LED goes solid green.
- **Rule**: pose `open` (four fingers straight, or three with the little finger down), palm
  moving slower than 3 hand sizes/s (27 cm/s), for `engage_hold` 0.55 s. Wherever your palm is
  then becomes the middle of the screen.
- **Senses**: any (a depth-only hand counts as open).
- **Goes wrong**: the hand is moving (rest your elbow); the fingers are together (spread them);
  the hand is out of the picture (Studio: is it in view?).

### Disengage: stop

- **Do**: drop the hand out of view, or lower it into your lap.
- **Rule**: the hand that engaged is unseen for `lost_after` 0.7 s. Anything held (a pressed
  button, a carried window) is let go.

### Move the pointer

- **For**: pointing.
- **Do**: move the engaged hand. 45 cm sideways crosses the whole screen; 28 cm up or down.
- **Rule**: the pointer follows the **palm** (depth's palm with the Kinect), not a fingertip, so
  pinching does not move it. Smoothed by a One Euro filter (`one_euro`: steady when still, little
  lag when fast).
- **Senses**: any.
- **Goes wrong**: shaking: the palm has no depth reading (closer than 0.5 m, or something shiny);
  the pointer stops at an edge: you engaged near the picture's side, so drop the hand and engage
  again nearer the middle.

## One hand

### Pinch: click, double-click, drag

- **For**: everything a left mouse button does.
- **Do**: touch thumb and index fingertips; open again. Twice quickly is a double-click. Pinch,
  move, open is a drag (select text, move a slider, drag a file).
- **Rule**: press when thumb to index tip is under `pinch_on` 0.30 hand size (~2.7 cm); release
  over `pinch_off` 0.42 (~3.8 cm). The two levels stop it chattering. The pointer freezes for
  `pinch_freeze` 0.12 s as the pinch closes. A release within `click_max_move` 2.5% of the screen
  (~1.1 cm of hand) of the press is a **click**, otherwise a drag.
- **Senses**: fingers.
- **Goes wrong**: from 2.7 m the fingertips are a few pixels apart, so make the pinch clear (tips
  really touching, then really apart). A fist with the thumb on the index is not a pinch: a fist
  wins. A closed L is a pinch (see L zoom).

### Thumb on the middle finger: right-click

- **For**: context menus.
- **Do**: touch thumb to the **middle** fingertip, keeping the index up and away.
- **Rule**: thumb to middle tip under 0.30 hand size while thumb to index is over 0.42. Once per
  touch (lift and touch again for another). A purple ripple shows it.
- **Senses**: fingers.
- **Goes wrong**: index and middle together read as a pinch: move the index clearly away.

### Fist: pick up a window and carry it

- **For**: moving windows.
- **Do**: point at a window, **make a fist**: it follows your hand. **Open the hand** to put it down.
- **Rule**: all four fingertips nearer the wrist than their middle joints (pose `fist`, held 3
  frames). Grabs the window under the pointer.
- **Senses**: fingers.

### Fling it: tile, maximise, minimise

- **For**: arranging windows with one movement.
- **Do**: while holding a window, **flick** the hand and open it at the same time.
- **Rule**: at the moment the fist opens, the window's fastest speed over 0.1 s in the last
  0.25 s is at least `throw_speed` 1.2 screens/s (~54 cm/s sideways, ~34 cm/s up or down).
  Left / right: that half of the screen. Up: maximise. Down: minimise.
- **Senses**: fingers.
- **Goes wrong**: opening the hand after the hand has stopped: it is a drop, not a throw.

### Carry it to another desktop

- **Do**: holding a window, take it to the left or right edge of the screen and hold it there.
- **Rule**: the pointer within `edge` 1.5% of the side for `edge_hold` 0.5 s. You go to the next
  desktop that way with the window; keep holding to go on (one per second).
- **Senses**: fingers.

### V sign: scroll the window under the pointer (and zoom)

- **For**: reading: a feed, a page, a document, steadily, as far as you like.
- **Do**: index and middle fingers up (ring and little finger folded), and **move the V**. The
  pointer stays where it is; the window under it scrolls. Chevrons show on the reticle.
- **Direction** (`natural_scroll`, on by default): the page follows the hand, like dragging on a
  phone. **Move the V up to go down the page** (to see what is below), down to go back up.
  Sideways scrolls sideways.
- **Rule**: one wheel step for every `scroll_step` 3.5% of the screen the V moves: **~1.6 cm
  sideways, ~1.0 cm up or down**; at most 5 steps a frame.
- **Zoom with the V**: push it **toward the TV** to zoom in, pull it back to zoom out: a step for
  every `zoom_mm` 4.5 cm (Ctrl + wheel: browsers, Files, editors, image viewers). With the laptop
  webcam (no depth): the hand looking 12% bigger or smaller (`zoom_size`).
- **Senses**: fingers (zoom by pushing: also depth).
- **Goes wrong**: the V must last 3 frames (0.1 s) before it counts, and moving toward the TV
  while scrolling also zooms, so keep the V at a steady distance while you scroll.

### Wave: scroll a chunk at a time

- **For**: a quick jump through a feed without holding a pose.
- **Do**: an **open hand**, either hand, **flicked quickly** up or down, then let it come back.
- **Direction** (`natural_scroll` on): **wave up to scroll down** (the page follows the hand),
  wave down to scroll up. A toast shows "↓ Scroll" or "↑ Scroll".
- **Rule**: it has to be a flick, not a movement. The palm travels at least `swipe_distance` 30% of
  the box height (**~8.4 cm**) within `swipe_window` 0.3 s, its peak speed is at least
  `swipe_speed` 2.2 box heights/s (**~62 cm/s**), and it moves twice as far vertically as
  sideways. It scrolls `wave_steps` 6 wheel steps (the shell sends at most 5). Another wave the
  same way counts after `wave_again` 0.3 s. A wave the other way within `wave_return` 0.7 s is
  taken as the hand coming back and ignored, and the pointer is held still meanwhile.
- **Senses**: any.
- **Goes wrong** ("scrolling a feed does nothing"):
  1. **The direction.** Waving *down* to go down a feed scrolls *up*. At the top of a feed nothing
     visibly happens. Wave **up**, or set `"natural_scroll": false` in air.json to make down mean
     down (this also flips the V sign).
  2. **Too slow.** A calm movement is just the pointer moving. Flick it.
  3. **The pointer is not over the feed.** Wheel steps go to the window under the pointer.
  4. **Straight down your arm's line.** A wave with as much sideways as up-and-down is neither.

### Swipe sideways: change desktop

- **For**: going to the next or previous desktop.
- **Do**: an open hand swept **fast** left or right.
- **Rule**: travels at least 30% of the box width (**~13.5 cm**) within 0.3 s at a peak of at
  least 2.2 box widths/s (**~1 m/s**), twice as far sideways as vertically. Left: the next
  desktop; right: the previous one. The pointer is put back where it was and held for
  `cooldown` 0.8 s while your hand comes back ("clutch", like lifting a mouse).
- **Senses**: any.
- **Goes wrong**: moving the pointer fast across the screen can be taken for a swipe. Move it
  steadily (under ~60 cm/s).

### L: zoom with one hand

- **For**: zooming without a second hand.
- **Do**: make an **L**: thumb out to the side, index up, other fingers folded, with a **clear
  gap** between thumb and index. Then open the L wider to zoom in, close it to zoom out.
- **Rule**: thumb tip more than 0.55 hand size from the middle knuckle (else it is "pointing").
  Each `lzoom_gap` 0.2 hand size (~1.8 cm) of change in the thumb–index gap is one step
  (Ctrl + wheel). The pointer holds still. Closing it all the way is part of the zoom, not a click.
- **Senses**: fingers.
- **Goes wrong**: starting with the thumb near the index: that is a pinch, and a pinch clicks.

### Push: click by pushing toward the TV

- **For**: clicking with an open hand, and clicking when only depth sees you (in the dark,
  too far for fingers).
- **Do**: push the open (or pointing) palm about 7 cm toward the TV, quickly.
- **Rule**: the palm comes `push_mm` 70 mm closer within `push_window` 0.3 s. Then `cooldown`
  0.8 s before the next.
- **Senses**: depth (any hand, including depth alone).
- **Goes wrong**: pushing slowly (more than 0.3 s): no click. Pushing while moving sideways also
  moves the pointer, so push straight.

## Two hands

The hand that engaged drives the pointer; the other only counts in these.

| Do | It does | Rule | Senses |
| --- | --- | --- | --- |
| Both hands pinch, pull apart / together | Zoom in / out (Ctrl + wheel) | a step per 15% change in distance between the palms (`zoom_ratio`) | fingers |
| Holding a window with a fist, make a fist with the other, pull apart / together | Resize it around its centre (orange reticle) | scale = distance now / distance at the start, 0.3x to 4x; open the second hand to carry on | fingers |
| Both **open palms** pulled apart | Every window (overview) | distance grows to 1.6x (`spread_ratio`) | any |
| ... pushed together | Back to work | distance shrinks to 0.6x (`collapse_ratio`) | any |

Two open hands never swipe or wave.

## In the dark, and with depth alone

- **Infrared + depth** (the room dark, `"video": "auto"`): every gesture above works. MediaPipe
  reads the cleaned infrared picture; it is less sure of itself than in colour, so make poses
  clearly.
- **Depth alone** (the chip says DEPTH ONLY; the HUD shows a glowing palm instead of a skeleton):
  hold the hand **out toward the TV**, at least 20 cm ahead of your body, and raise it first so
  it counts. Then engage (hold still), move the pointer, push to click, wave to scroll, swipe
  for desktops, and spread two hands for the overview. Pinch, fist, V, L and right-click need
  fingers and do nothing here.

## When one gesture looks like another

| Meant | Taken as | Why | Instead |
| --- | --- | --- | --- |
| L zoom | Click | A closed L is a pinch | Start the L wide open |
| Fist | Pinch | (no: a fist is checked first) | |
| Pointer move | Swipe / wave | Moved faster than ~60 cm/s | Move steadily |
| Scroll down a feed with a wave | Scroll up | Natural scroll: wave up to go down | Wave up, or `natural_scroll: false` |
| V scroll | V zoom | The V moved toward or away from the TV by 4.5 cm | Keep the V at one distance |
| Pinch click | Drag | The hand moved more than ~1 cm while pinched | Pinch without moving; the pointer freezes for 0.12 s to help |
| Any new pose | Nothing for a moment | A pose must last 3 frames (0.1 s), except a pinch, which counts at once | Hold the pose |

## Every setting

All in `"gestures"` in `~/.config/adaptive-desktop/air.json`; restart Air (Super+G twice) to apply.

| Setting | Default | Means |
| --- | --- | --- |
| `box_metres` | 0.45 | metres of arm movement for the screen's width (with depth) |
| `box_min_metric` | 0.06 | ... never less than this share of the picture |
| `box_hands` | 4.0 | without depth: the box is this many hand sizes wide |
| `box_min`, `box_max` | 0.15, 0.6 | ... kept within this share of the picture |
| `box_width` | null | a fixed share of the picture instead of either |
| `box_aspect` | 1.6 | screen width / height |
| `engage_hold` | 0.55 | s an open palm is held still to engage |
| `engage_still` | 3.0 | hand sizes/s: "still" |
| `min_hand` | 0.015 | smallest hand used (image heights): ignores people far behind you |
| `lost_after` | 0.7 | s without the hand before disengaging |
| `pinch_on`, `pinch_off` | 0.30, 0.42 | thumb–index gap (hand sizes) to press / release |
| `pinch_freeze` | 0.12 | s the pointer holds as a pinch closes |
| `click_max_move` | 0.025 | screen a pinch may move and still be a click |
| `pose_frames` | 3 | frames a new pose must last |
| `swipe_speed` | 2.2 | box widths (heights)/s at the peak of a swipe (wave) |
| `swipe_distance` | 0.30 | box widths (heights) a swipe (wave) travels |
| `swipe_window` | 0.30 | s it has to do that in |
| `cooldown` | 0.8 | s after a swipe, throw, push, spread or collapse |
| `wave_steps` | 6 | wheel steps per wave |
| `wave_again` | 0.3 | s before another wave the same way |
| `wave_return` | 0.7 | s in which a wave back is the hand returning |
| `lzoom_gap` | 0.2 | hand sizes of L opening per zoom step |
| `edge`, `edge_hold` | 0.015, 0.5 | a carried window this near the side, this long, changes desktop |
| `push_mm`, `push_window` | 70, 0.30 | mm toward the Kinect, within s, to click |
| `throw_speed` | 1.2 | screens/s when a fist opens to throw |
| `scroll_step` | 0.035 | screen of V movement per wheel step |
| `natural_scroll` | true | the page follows the hand (wave or V up = scroll down) |
| `zoom_mm` | 45 | mm of V push per zoom step |
| `zoom_size` | 0.12 | without depth: the hand this much bigger per step |
| `zoom_ratio` | 1.15 | two pinching hands this much farther apart per step |
| `spread_ratio`, `collapse_ratio` | 1.6, 0.6 | two open palms apart / together |
| `one_euro` | 1.4, 4.0, 1.0 | pointer smoothing: min_cutoff (lower = steadier, more lag), beta (higher = less lag when fast) |
| `smooth_shape` | 3.0, 0.5, 1.0 | smoothing of the finger shapes (poses) |
| `smooth_depth` | 1.5, 0.02, 1.0 | smoothing of the palm's distance |

## Trying and checking

```sh
scripts/adaptive-air.sh --demo                      # every gesture played by scripted hands, no camera
services/adaptive-air/air.py --print                # each gesture event printed as you make it
services/adaptive-air/air.py --print --preview      # ... and the picture with what was found
scripts/verify-air.py                               # the engine against synthetic hands
```

`--print` is the quickest way to see whether a gesture is recognised at all: make it and watch
for `scroll`, `zoom`, `press`, `grab` and so on.
