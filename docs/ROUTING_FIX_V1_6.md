# Adaptive Desktop Routing Fix v1.6

This package is specifically for the state shown in the two screenshots where:

1. Super/Overview still shows the stock Ubuntu bottom dock;
2. clicking Files opens the stock grey Ubuntu Files UI;
3. the custom left rail is present but its actions are effectively stale;
4. the GNOME top-bar time is missing.

The problem is not another File Explorer CSS bug. The active GNOME Shell
session is still using the older Adaptive Shell module/routing.

## Fix 1 — Files really opens Adaptive Files

v1.6 installs a per-user override for:

`org.gnome.Nautilus.desktop`

The system file in `/usr/share/applications` is not modified.

The override keeps the standard Files desktop ID but routes its `Exec` through:

`~/adaptive-desktop/scripts/adaptive-files-launch-v1.6.sh`

That means:

- the Adaptive left rail Files button opens Adaptive Files;
- the normal Ubuntu Files icon/search result opens Adaptive Files;
- `inode/directory` opens are routed through the same user-level entry.

Before starting the local fork, the launcher closes a running stock
`/usr/bin/nautilus` process when necessary so the local fork cannot silently
hand activation to the stock UI.

## Fix 2 — fresh shell code, working dock

The old extension UUID was:

`adaptive-shell@local`

v1.6 intentionally uses:

`adaptive-shell-v16@local`

This is not branding churn. GNOME Shell can keep an already-loaded extension
JavaScript module in the current session. A new UUID guarantees that v1.6 is a
new module rather than the stale code visible in the screenshots.

The new left rail actions are:

- Overview;
- Adaptive Files;
- Applications;
- Workspaces;
- Search;
- Settings.

The installer disables the old UUID before enabling v1.6.

## Fix 3 — Overview redesign

The redundant stock Ubuntu bottom dash is hidden.

The Overview search surface, workspace frames and hover states are restyled in
the Adaptive visual language while keeping GNOME's actual overview/workspace
functionality.

## Fix 4 — top time restored

v1.6 restores GNOME Shell's real `dateMenu` actor.

It does not replace the calendar with a fake label.

Therefore:

- the normal GNOME time formatting is preserved;
- your existing 12/24-hour preference is preserved;
- clicking the time opens the normal GNOME calendar/notifications menu;
- only the surface styling changes.

## Install

```bash
cd ~/adaptive-desktop

unzip -o \
  ~/Downloads/adaptive-desktop-routing-fix-v1.6.zip \
  -d .

./scripts/install-v1.6.sh
```

Because this uses a new extension UUID, it is designed to take effect without
depending on a logout merely to refresh cached extension JavaScript.

## Verify

```bash
./scripts/verify-v1.6.sh
```

If any of the three routing/shell checks is wrong:

```bash
./scripts/diagnose-v1.6.sh
```

## Manual verification

### 1. Overview

Press Super.

Expected:

- no stock bottom Ubuntu dock;
- Adaptive left rail remains;
- redesigned dark overview/search surface.

### 2. Files

Click the Files icon in the left rail.

Expected:

- dark Adaptive Files UI;
- custom icons;
- Preview/Storage/Network controls;
- right Inspector.

Then search/open the normal `Files` app from GNOME.

It should route to the same Adaptive Files launcher.

### 3. Dock

Click every left-rail button.

Settings must launch `gnome-control-center`.

### 4. Time

The real GNOME time must be visible in the top bar.

Click it.

The normal calendar/notification menu should open.

## Rollback

```bash
./scripts/rollback-v1.6.sh
```
