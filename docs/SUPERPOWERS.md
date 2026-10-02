# Superpowers — where Adaptive Desktop goes next

The features are there. This document is about the step after features: the
desktop, the phone and everything around them behaving as one instrument that
does what you mean, at once, every time. The picture to hold is a workshop
where you say or gesture what you want and it happens — not because there is
a lot of technology, but because none of it gets in the way.

It is a plan, not a record. `BACKLOG.md` says what exists; this says what to
build on top of it, in what order, and how to tell when it is good enough.

## What "superpowers" means here

Four qualities, each with a test that can be failed.

| Quality | What it means | It is there when |
| --- | --- | --- |
| **Compatibility** | It works with what you already own and already run, without each thing needing its own setup. | A new phone, monitor, headset, network or app is usable in under a minute with no command typed. |
| **Ease** | One way in to everything, in your words. | Any action in the system can be reached from one place, by typing or saying what you want, without knowing which screen it lives on. |
| **Smoothness** | Nothing waits, stutters or loses its place. | Every action answers in under 100 ms or shows that it is working; nothing is ever re-entered after a disconnect, a sleep or a restart. |
| **Flawless workarounds** | When something cannot work, the system takes the next best path by itself and says so in one line. | No failure ends in a dead screen. Every "cannot" comes with what was done instead, or the one thing to do. |

These sit under the product's existing principles and do not replace them:
productivity over spectacle, calm when idle, Ubuntu always recoverable,
nothing that depends on a cloud service to function.

## Where it stands today

What is already strong:

- **Reach.** The phone sees and controls the screen as video with sound, and
  the machine itself: processes, drives, network, Bluetooth, displays, sound,
  services, windows. It works at home and away, with no port open to the
  internet.
- **Trust.** Mutual TLS to keys held in phone hardware; every change that
  could cut the phone off is undone unless the phone comes back; the phone's
  fingerprint can approve things on the computer with a signature root checks
  for itself.
- **Recovery.** A separate session, a separate dconf profile, an uninstall
  path, and checks that never touch the machine they run on.

What stands between that and the feeling described above:

1. **Every capability has its own door.** Nineteen tiles on the phone, a
   palette on the desktop, a dozen `*-cli.py` tools. You have to know where a
   thing lives before you can ask for it.
2. **Nothing is anticipated.** The system does what it is told and never
   offers the next step, though it knows the project, the time, the network,
   what is plugged in and what you did last time in the same situation.
3. **Setup is typed.** Pairing a phone, a relay, wake-on-LAN, sudo approval,
   the virtual camera — each is a command and a paragraph of documentation.
4. **Much is proven only against stand-ins.** The checks are thorough about
   logic and honest about what they have not touched: real Bluetooth, real
   displays, a real phone's hardware.
5. **Seams show under stress.** A reconnect is visible; a slow link makes
   screens wait rather than degrade; errors are accurate but are still errors.

The five parts below answer these in order.

## Part 1 — One way in: the command layer

*Answers: ease. The single largest change in how it feels.*

Everything the system can do becomes an **action** in one registry, with a
name, the words people use for it, what it needs, what it changes, and
whether it is safe to do without asking. The desktop palette, the phone, the
widget, NFC tags and voice all read the same registry.

- **A registry, not a rewrite.** Each existing endpoint and CLI verb is
  described once (`services/adaptive-actions/`): `lock`, `join wifi <name>`,
  `move window to <display>`, `switch project <name>`, `send <file> to phone`.
  The handlers stay where they are.
- **Ask in your own words.** A box on the phone's home screen and in the
  desktop palette that takes "turn off bluetooth", "what's using the disk",
  "put this window on the big screen". Matching is local first: verb and
  object against the registry's words, fuzzy, ranked by what you use. No
  model is needed for the common cases, and none is in the path by default.
- **Say it.** The same box by voice. On the phone the microphone button
  already types what is heard; here it runs it. On the desktop, a push-to-talk
  key. Recognition stays on the device.
- **Show before doing, for anything that changes something.** "Turn Wi-Fi
  off — the phone will lose the computer for a moment. Go ahead?" The registry
  knows which actions are reversible, which cut the link, which destroy.
- **Chains.** "Start the meeting" is a named list of actions: focus on,
  webcam and microphone from the phone, the meeting app to the left display,
  notifications held. Chains are made by doing the steps once and saying
  "remember this as…".

It is done when every tile on the phone can be removed and nothing is lost —
the tiles become shortcuts, not the only route.

## Part 2 — Anticipation: scenes and the next step

*Answers: ease and smoothness. The part that makes it feel aware.*

The system already knows a great deal at any moment. It should use it.

- **Context, as one small object**: active project, time of day, network,
  what is plugged in, which displays, whether the phone is here, what is
  playing, battery and load. `services/adaptive-context/` publishes it on the
  session bus; everything reads it from there instead of working it out again.
- **Scenes.** A scene is a context that recurs — *at the desk* (dock, two
  displays, phone here), *away* (battery, one screen, phone on mobile data),
  *presenting* (external display, focus), *leaving* (phone gone). On entering
  a scene the desktop applies what you always do there: window layout, sound
  output, power profile, which project. Scenes are learnt from what you
  repeat and offered for confirmation the first few times, never imposed.
- **The next step, offered once.** After you plug in the drive you always
  back up to: "Back up *project* to this drive?" After a build finishes while
  you are elsewhere: the phone says so and offers the log. After a call ends:
  resume what was paused. One line, one tap, and it stays quiet if you ignore
  it twice.
- **Handoff as the default.** What you are doing follows you. Reading a page
  on the desktop, pick up the phone: it is there. A file open on the desktop
  is the first thing the phone's Files screen shows. The clipboard, the
  active project and what is playing are already shared; this makes the
  activity itself shared.

It is done when a normal day involves no window arranging, no output
switching and no "now where was I".

## Part 3 — Zero-setup compatibility

*Answers: compatibility. Each item removes a command from the documentation.*

- **Pairing by being near.** A phone with the app, on the same network, is
  seen by the computer; one tap on each to pair. The QR code and the account
  remain for when that cannot work.
- **Devices that describe themselves.** A new Bluetooth headset, display or
  drive brings up one card: what it is, the sensible default (use for sound;
  extend to the right; open in Files), and done. The choice is remembered
  per device.
- **Setup that needs root, asked for once and in one place.** The virtual
  camera, USB switching, sudo approval, wake-on-LAN and the session wrapper
  are one screen in Settings: each line says what it changes and why, with one
  authorisation for those chosen. Today they are five scripts.
- **Wayland.** Screen capture through the portal and PipeWire, input through
  libei. This is the largest compatibility gap; X11-only will not stay
  acceptable. `docs/GNOME_PORT.md` has the groundwork.
- **Other phones and other computers.** The link's protocol is small and
  documented by its checks. An iOS app is the same client in Swift; a second
  desktop is the same daemon. Neither should need a protocol change — keeping
  it so is the requirement.
- **Apps that take part.** A short contract by which any program on the
  desktop can register actions and report state (a build tool its progress, a
  player its queue), so that it shows up in the command layer and on the
  phone without the desktop knowing the app.

## Part 4 — Smoothness, measured

*Answers: smoothness. Budgets, with a check that fails when one is missed.*

| Thing | Budget | How it is held |
| --- | --- | --- |
| Any tap on the phone | visible response in 100 ms | optimistic state: the switch moves, then is confirmed or put back with the reason |
| Screen as video | under 150 ms glass to glass on Wi-Fi | hardware encoding (VA-API) on the computer where there is one; adapt bitrate before dropping frames |
| Opening any screen | content in 300 ms | last known state shown at once, refreshed underneath |
| Reconnecting | invisible under 2 s; one line above that | requests are held and replayed; sockets resume where they were |
| Desktop shell | no frame over 16 ms from our code | the existing long-run memory and frame checks, made part of every change |
| Cold start of the link | ready before the session is | start with the session, not after it |

Three engineering changes carry most of this:

- **One connection, kept.** The phone holds a single multiplexed connection
  to the computer that survives network changes (the address moves, the
  session does not). Every screen uses it; none opens its own.
- **State, pushed.** Screens stop polling every two to five seconds. The
  computer says what changed; the phone always has the current picture and
  shows it instantly.
- **A real-machine run before each release.** `record-live-verification.py`
  becomes a guided session on your own hardware — it walks through each item,
  measures what it can, and records the result — so that "checked against a
  stand-in" stops being the final word on anything.

## Part 5 — Workarounds that need no one

*Answers: flawless workarounds. Every dead end gets a second path.*

The rule: **a failure the system can route around is never shown as a
failure.** It is shown as what was done.

- **A ladder for every capability.** Screen: hardware video → software video
  → pictures → the last frame with "the computer is out of reach". Reaching
  the computer: its network → direct through the account → your relay →
  "waking it" → what to do. Each step down is automatic and is said once, in
  a line, not a dialog.
- **Self-repair.** The link notices its own faults — a port taken, a missing
  dependency, a service that failed, a certificate about to expire — and
  fixes what it may, or offers the one command that will. `link-cli.py doctor`
  runs the same checks on demand and reads as a short list of green lines.
- **Undo, everywhere.** The keep-or-undo used for network changes becomes a
  general journal: every action from the command layer records how to reverse
  it. "Undo that" works for the last thing, whatever it was.
- **Nothing lost in transit.** A file sent as the connection dropped, a note,
  a text: queued on the phone and delivered on return, with a count of what
  is waiting.
- **Explain in one sentence.** Every refusal names its cause and its remedy
  in plain words, as the link's messages already try to. A review of every
  message in the app against that rule is part of this.

## Order of work

Each stage leaves the system better on its own; none depends on finishing
the whole.

1. **Prove what exists.** Run the real-machine session; fix what it finds.
   Nothing new until the present features hold on real hardware.
2. **The connection and pushed state** (Part 4). Everything after feels
   better for it, and it removes the polling that the rest would otherwise
   multiply.
3. **The action registry and the ask box** (Part 1). The change in feel.
4. **Ladders, doctor and the undo journal** (Part 5).
5. **Context and scenes** (Part 2), built on the registry.
6. **One setup screen, pairing by nearness, self-describing devices**
   (Part 3).
7. **Wayland**, then **hardware video encoding**.
8. **The app contract, iOS, voice on the desktop.**

## What it must never become

- **A show.** No animation that explains nothing, no telemetry on screen
  while idle, no assistant that speaks unasked. Stark's workshop is quiet
  until he talks to it.
- **Dependent on a service.** Words are matched and speech is recognised on
  the device. A model may be offered as an option for free-form requests; the
  system is complete without it.
- **Less safe for being easier.** One way in means one place to get
  permissions right: the registry carries each action's risk, the owner's
  switches still narrow everything, and what destroys or exposes always asks.
- **Unrecoverable.** Ubuntu's own session stays one logout away, and every
  stage above has its own way back.

## How to tell it worked

Not by the list of features. By a week of ordinary use in which you never
open a terminal for the system itself, never arrange a window twice, never
re-enter something after a disconnect, and never read an error that leaves
you to work out what to do. That is the test, and it is one the system either
passes or does not.
