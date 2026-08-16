# Notification and Focus Policy

Adaptive Desktop keeps GNOME Shell's native calendar and notification center as
the source of truth. Adaptive styling may change presentation, but notification
storage, grouping, calendar behavior, and critical alert handling remain GNOME
native.

## Normal Notifications

- Normal notification banners follow `org.gnome.desktop.notifications show-banners`.
- Adaptive Focus turns banners off.
- Focus Off restores banners.
- Focus timers temporarily turn banners off, then restore them.

## Critical Notifications

- Critical notification delivery is not reimplemented by Adaptive Desktop.
- GNOME Shell remains responsible for urgency handling and notification history.
- Adaptive styling must not hide the native date menu, calendar, or message list.

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
