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
date menu popup as an **information center**: a clock, notifications grouped per
application, and full system telemetry, beside GNOME's own calendar.

The system block has no natural bound - sixteen cores, eleven sensors and five
process rows run past the bottom of a laptop panel - so it lives in a scroll view
whose height is set from the monitor when the popup opens. It wraps only that
block, not the whole column: GNOME's message list does its own scrolling, and a
scroll view inside a scroll view gives neither a sane size.

It contains **no controls at all**. GNOME's aggregate menu in the top-right owns
network, bluetooth, audio, brightness and power, and a second place to change
them was a second thing to keep in sync. `verify-live-readiness.sh` fails if a
control reappears.

It does not replace the notification list. GNOME's `CalendarMessageList` actor is
taken out of `#calendarArea` and reparented into the shade column, so message
sections, grouping, the Do Not Disturb switch, the Clear button and notification
history are all still the code GNOME ships. The calendar column to the right is
not touched at all.

Because the shade rearranges actors the shell owns, `Shade.detach()` records the
message list's original parent, index and `y_expand` at attach time and restores
all three. Disabling the extension must leave a working stock date menu; that is
the invariant to check after any change to this file.

Telemetry polls only while the popup is open, and every device path it reads is
discovered at runtime rather than hardcoded.

## Normal Notifications

- Normal notification banners follow `org.gnome.desktop.notifications show-banners`.
- Adaptive Focus turns banners off.
- Focus Off restores banners.
- Focus timers temporarily turn banners off, then restore them.
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

`notifications.js` groups by `MessageTray.Source`. It deliberately does not
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
