# Adaptive Calendar + Notification Center v1.6.2

This patch updates the top-clock popup visible in the supplied screenshot.

It intentionally keeps GNOME Shell's real:

- notification list;
- notification history;
- Do Not Disturb;
- calendar;
- events;
- world clocks;
- weather integration;
- clock/date menu.

Only the presentation is changed.

## Visual changes

### Notification center

- narrower, more intentional notification column;
- Adaptive navy/cyan surfaces;
- redesigned empty state;
- compact notification cards;
- redesigned Do Not Disturb row and switch;
- clearer title/body hierarchy.

### Calendar

- dedicated dark calendar column;
- compact date header;
- smaller month navigation;
- tighter calendar grid;
- Ubuntu orange "today" state replaced by Adaptive blue/cyan;
- softer other-month dates;
- improved event-day hierarchy.

### Events / auxiliary cards

- events, world clocks and weather use the same Adaptive card geometry;
- event time uses the Accent blue;
- borders and hover states match the rest of the desktop.

## Install

```bash
cd ~/adaptive-desktop

unzip -o \
  ~/Downloads/adaptive-desktop-calendar-center-v1.6.2.zip \
  -d .

./scripts/install-calendar-center-v1.6.2.sh
```

This patch does not rerun the Nautilus build or apt dependency installation.

It only backs up and replaces the live v1.6 Shell stylesheet, then reloads the
extension so the change can be verified immediately.

## Verify

```bash
./scripts/verify-calendar-center-v1.6.2.sh
```

Then click the top time.

## Rollback

```bash
./scripts/rollback-calendar-center-v1.6.2.sh
```
