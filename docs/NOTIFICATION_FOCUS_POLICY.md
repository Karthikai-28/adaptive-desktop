# Notification and Focus Policy

Adaptive Desktop keeps GNOME Shell's native calendar and notification center as
the source of truth.

The line is drawn at **arrangement versus delivery**. Presentation - which card
sits under which header, in what order, at what size - is Adaptive's. Delivery,
storage, urgency, acknowledgement, actions, dismissal, history and calendar data
are GNOME's, and are never reimplemented.

An earlier version of this document put grouping on GNOME's side of that line.
It has moved: the shade groups notifications per application, because GNOME 42's
flat chronological list buries a chatty app's other notifications. Every card in
those groups is still a `Calendar.NotificationMessage` built from a
`MessageTray.Notification`, so nothing about how a notification arrives or is
dismissed has changed.

## The Adaptive Shade

The shade (`shell/adaptive-shell@local/shade.js`) rebuilds the *interior* of the
date menu popup as an **information center**: a clock, the Activity Center, and
notifications grouped per application, beside GNOME's own calendar. Hardware
telemetry is not here any more; it has its own System panel next to ROS 2.

The Activity Center is the Dynamic Island's cards (Overview, AI usage, Tasks,
Music, Focus), built by `islandUI.js` and mounted with
`Shade.mountActivityCenter()`. It has no natural bound, so it lives in a scroll
view whose height is set from the monitor, re-measured only when it changes size
or the monitors change. The scroll view wraps only that block, not the whole
column: GNOME's message list does its own scrolling, and a scroll view inside a
scroll view gives neither a sane size.

It contains **no duplicated system controls**. GNOME's aggregate menu in the
top-right (and the Control Center over it) owns network, bluetooth, audio,
brightness and power, and a second place to change them was a second thing to
keep in sync. `verify-live-readiness.sh` fails if one reappears. What the shade
does act on is what only it shows: clear one app's notifications, cancel an
Agent Office task, seek a track, start or stop a focus session.

Notifications are ordered urgent first, then newest first, both inside an app's
group and between groups, so a collapsed group never hides the newest message.

It does not replace the notification list. GNOME's `CalendarMessageList` actor is
taken out of `#calendarArea` and reparented into the shade column, so message
sections, grouping, the Do Not Disturb switch, the Clear button and notification
history are all still the code GNOME ships. The calendar column to the right is
not touched at all.

Because the shade rearranges actors the shell owns, `Shade.detach()` records the
message list's original parent, index and `y_expand` at attach time and restores
all three. Disabling the extension must leave a working stock date menu; that is
the invariant to check after any change to this file.

The cards draw only while on screen, and the music scrubber's one-second redraw
runs only while it is visible and a track is playing. AI quota snapshots slow
to five minutes while their cards and alerts are hidden. Agent Office tasks use
its live local WebSocket, with a guarded status-filtered poll as the fallback
and periodic consistency check.

While GNOME's built-in recorder is active, the island hides task names and
details, AI percentages, media metadata and already-queued event text. GNOME 42
on X11 cannot reliably discover screen sharing performed outside Shell (for
example an application's own X11 capture), so this automatic privacy boundary
is deliberately described as recorder-aware rather than universal.

## Normal Notifications

- Normal notification banners follow `org.gnome.desktop.notifications show-banners`.
- Adaptive Focus turns banners off.
- Focus Off restores banners.
- Focus timers temporarily turn banners off, then restore them. The island's
  Focus timer does this for focus sessions (not breaks) and gives back the
  previous value, unless the user changed it during the session. Its deadline
  is saved in `~/.local/state/adaptive-desktop/focus-timer.json`, so the session
  and the DND it holds survive suspend and a shell restart. Its arrival marker
  is saved with the deadline, and a bounded ledger in
  `~/.local/state/adaptive-desktop/notification-arrivals.json` counts arrivals
  even if an application withdraws them before the session ends. The ledger
  stores application keys and hashes, never notification text. When focus ends,
  the card shows how many notifications from how many apps arrived meanwhile.
- The shade's Focus tile writes that same key, so `scripts/focus-cli.py` and the
  tile are two views of one setting rather than two ideas of focus.

## Critical Notifications

- Critical notification delivery is not reimplemented by Adaptive Desktop.
- GNOME Shell remains responsible for urgency handling and notification history.
- Adaptive styling must not hide the native date menu, calendar, or message list.
- The shade may reparent the message list. It may not rebuild or replace it.
- Urgent notifications stay at the top of their group, and their group stays at
  the top of the list, exactly as GNOME's flat section ordered them.

## Grouping and its fallbacks

`notifications.js` groups by application ID when GNOME has one, falling back to
the visible source title. It deliberately does not
subclass `MessageList.MessageListSection`: that class defines `_messages` as
"every child of `_list`, unwrapped", so putting group headers in that list would
corrupt its own `empty`, `can-clear` and `clear()` logic. It implements the small
contract `CalendarMessageList` actually consumes instead.

An unreadable notification list is worse than an ugly one, so there are two ways
back to GNOME's own:

- `~/.config/adaptive-desktop/shade.json` with `{"notificationGrouping": false}`
  opts out permanently.
- If the grouped section throws while building, the shade catches it and puts
  GNOME's section straight back.

GNOME's section object is *removed* from the section list, never destroyed, so
detaching restores the original rather than constructing a replacement.

## Calendar

The calendar column is GNOME's, left stock.

An Adaptive month/agenda/week view over the same event source was built and then
removed - the default calendar is what was wanted. If one is ever attempted
again, the rule it has to respect is that `Calendar.DBusEventSource.requestRange()`
REPLACES the shared calendar server's time range rather than widening it, and
`Calendar.Calendar._rebuildCalendar()` already calls it for the displayed month.
Two callers fight, each forcing a reload. `verify-live-readiness.sh` fails if
anything in the shell reaches into the event source at all.

## Quick Controls

The shade's tiles and sliders are views onto backends GNOME already owns -
NetworkManager, the Rfkill daemon, the Gvc mixer, gnome-settings-daemon and
gsettings. A control reads its backend to render and writes it on click; it keeps
no copy of the state it shows and learns about outside changes from the backend's
own signal.

This is the line that separates the shade from the System Center that was
deliberately removed: nothing here reimplements a control, so nothing here can
disagree with the rest of the session about what is on. A tile's secondary click
opens GNOME's own panel for the subject rather than growing a submenu that would
duplicate it. `scripts/verify-live-readiness.sh` asserts both halves of this.

## Project Focus

- Projects may store `metadata.focus` as `on` or `off`.
- `focus-cli.py apply-project` applies that preference through the same GNOME
  notification setting.
- Missing project preference leaves the current focus state unchanged.

## Fullscreen and Quiet Behavior

- The shell rail tracks fullscreen windows through GNOME Shell chrome metadata.
- Quiet mode is expressed through Focus On, Focus Off, and timer controls.
- Any future per-app or fullscreen-specific policy must keep GNOME's native
  critical notification path intact.
