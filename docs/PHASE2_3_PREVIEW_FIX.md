# Adaptive Files Visual + Preview v1.2

This is a targeted fix for the state visible in the 1920×1200 screenshot where:

- the Adaptive Files theme is active;
- custom large folder SVGs are active;
- the `ADAPTIVE FILES / Inspector / Storage / Network` strip is visible;
- the right inspector never attaches.

## Root cause fixed

The preview controller held the Nautilus window using only a Python weak
reference.

The LocationWidgetProvider callback returned normally, its temporary PyGObject
window wrapper could then be released, and the deferred `GLib.idle_add()`
attachment found no window. It therefore returned without ever logging
`Inspector attached`.

v1.2 keeps the window strongly for the controller lifetime and releases it
when the Nautilus window is destroyed.

It also:

- attempts attachment immediately;
- retries after GTK layout;
- logs each early attachment attempt;
- relaxes initial geometry thresholds;
- keeps the existing overlay plus horizontal-container fallback;
- makes Preview/Storage/Network buttons force a new attachment attempt;
- verifies the running process using `/proc/*/exe`, not `pgrep -x nautilus`.

## Sidebar SVG completion

The large folder icons were already custom in v1.1, but many sidebar rows ask
for `*-symbolic` icon names.

v1.2 adds custom scalable symbolic SVGs for:

- Home;
- Desktop;
- Recent;
- Starred;
- generic folders;
- Documents;
- Downloads;
- Pictures;
- Music;
- Videos;
- Templates;
- Public;
- remote folders;
- saved search;
- Trash;
- network/workgroup/server;
- hard disks;
- removable media.

Unknown icons still inherit from Adwaita/hicolor so Nautilus features are not
lost.

## Install

```bash
cd ~/adaptive-desktop

unzip -o ~/Downloads/adaptive-files-visual-preview-v1.2.zip -d .

./scripts/phase2.3-install-visual-preview.sh
```

Completely close old Files instances:

```bash
/usr/bin/nautilus -q || true
pkill -x nautilus || true
sleep 2
```

Launch v1.2 and keep this terminal open:

```bash
./scripts/phase2.3-run-visual-preview.sh
```

The right inspector is visible by default.

Single click a folder or file. Double-click remains the native Nautilus
open/navigation behavior.

## Verify in a second terminal

```bash
cd ~/adaptive-desktop
./scripts/phase2.3-verify-preview.sh
```

Expected log sequence:

```text
Adaptive Preview extension initialized.
Process icon theme set to AdaptiveFilesIcons.
Inspector attach attempt 1: ...
LocationWidgetProvider active ...
Inspector attached to overlay ...
```

or:

```text
Inspector attached to horizontal box ...
```

If no `Inspector attached` line appears, run:

```bash
./scripts/phase2.3-debug-preview.sh
```

The attachment-attempt output will now tell us the exact remaining GTK
container issue rather than silently returning.

## Visual direction

The inspector uses layered translucent navy surfaces, subtle cyan/blue edge
light, compact typography and vector assets.

GTK 3 can draw these translucent internal surfaces. Actual desktop-background
blur remains a compositor/shell feature and is intentionally not faked with
heavy glow.
