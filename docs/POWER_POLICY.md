# Power policy

A laptop running this project must behave like any other laptop. It was not
doing that: an always-on-display experiment left the machine unable to sleep on
battery, and closing the lid only locked it. The machine stayed awake with the
screen lit inside a bag, got hot, and drained.

These are the rules that stop it happening again. They apply to everything in
this repository.

## The rules

**1. The lid closing puts the machine to sleep.**
Locking is not enough. `scripts/adaptive-lid-watch.sh` locks and then suspends.
GNOME will not do it here itself: `gsd-power` takes a block inhibitor on
`handle-lid-switch` whenever an external display is attached, and
`lid-close-suspend-with-external-monitor` is false.

**2. Clamshell is opt-in and conditional.**
Working with the lid shut on an external display is legitimate, but defaulting
to it is how a laptop ends up awake in a bag. It requires:

```sh
touch ~/.config/adaptive-desktop/clamshell
```

and it only applies while an external display is actually connected. Unplug the
display and the lid suspends again.

**3. Nothing may disable suspend on battery.**
`sleep-inactive-battery-type` is not `nothing` under any feature, ever. This is
the single setting that caused the incident. An always-on display is a
mains-power feature; `adaptive-aod.sh` refuses to run on battery and no longer
touches the battery keys at all.

**4. Anything that changes power settings saves the old values and can restore
them.**
Saved state is quoted, because `gsettings get` returns `uint32 300` and an
unquoted `source` of that runs `300` as a command - which is how the first
restore silently did nothing while reporting success. Round-trip the switch
before trusting it.

**5. Nothing in this repository may hold the machine awake.**
No idle inhibitors, no wake locks, no polling that prevents sleep. Background
watchers must be cheap and must not resist suspend. Suspending is allowed to
interrupt them; they resume with the session.

**6. Defaults are the conservative ones.**
Features that trade battery for convenience ship off. The user turns them on
deliberately, on mains.

## Expected behaviour

| Situation | What happens |
| --- | --- |
| Lid closed | Lock, then suspend |
| Lid closed, clamshell opted in, external display attached | Lock only |
| Idle 5 min | Screen dims, then blanks |
| Idle on battery, 20 min | Suspend |
| Idle on mains, 60 min | Suspend |
| Always-on display on | Mains only; battery suspend still active |

## Checking

```sh
./scripts/adaptive-power-check.sh
```

Reports anything that would keep the machine awake, and fails if a rule above
is broken.

One thing it deliberately does not require: a non-zero X DPMS timeout. GNOME
leaves `xset`'s own standby/suspend/off timers at 0 and blanks from `gsd-power`
watching the idle monitor, so a zero there is normal. What matters is that DPMS
is *enabled* and that something owns the blanking - the check fails only if
neither is true.

## The screen that blanked every 30 seconds

A second incident, different cause, same shape: a display behaviour that no
setting could reach.

The panel powered down about 30 seconds after the last keypress, over and over.
Every setting said it should not: `idle-delay` was 0 (Never), auto-suspend was
off, dimming was off, X's own screen-saver timeout was 0 and its DPMS
standby/suspend/off timeouts were all 0. Changing them made no difference,
because none of them was what was doing it.

`gsd-power` arms a 30-second blank timer, but only while it believes the screen
saver is active. Something told it the saver came on and never told it the saver
went off, so that timer stayed armed for the rest of the session. Measured: the
display switched off at 30.3s, 30.6s and 30.7s of idle, with
`org.gnome.ScreenSaver.GetActive` returning false the whole time.

Restarting `gsd-power` cleared it - idle then reached 122 seconds with the
screen still on.

**7. A display that turns off while nothing asked it to is a bug, not a
setting.**
If the panel powers down while the screen saver is inactive and every X DPMS
timeout is zero, no timer expired - something forced it. Do not go looking for
the setting that stops it; there is none.

```sh
./scripts/adaptive-screen-blank-check.sh --check   # report
./scripts/adaptive-screen-blank-check.sh           # repair
```

The check can only see the fault while the screen is actually off, so run it
over SSH or within a few seconds of the screen going black.

## What went wrong, for the record

`adaptive-aod.sh on` set `idle-delay` to 0, both `sleep-inactive-*-type` to
`nothing`, `idle-dim` false, and disabled X's screen-saver and DPMS. Every path
to sleep was closed at once, on battery as well as mains. The lid watcher only
locked. The result was a machine that could not sleep, could not blank, and did
not suspend when shut.
