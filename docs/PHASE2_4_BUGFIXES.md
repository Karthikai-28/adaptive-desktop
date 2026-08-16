# Adaptive Files Visual + Preview v1.3

This release fixes the bugs visible in the v1.2 1920×1200 screenshot.

## Fixed

### Folder preview stuck on “Loading folder contents…”

The old implementation chained two PyGObject async callbacks and passed the
contents widget through a weak reference. The inspector could remain on the
loading state even though Nautilus already knew the folder contained files.

v1.3 performs the native GIO folder enumeration on the existing preview worker
pool and sends plain row data back to the GTK main loop.

The UI thread is not blocked.

### Wrong folder icon inside Inspector

Folder preview now uses the full `folder` vector from `AdaptiveFilesIcons`
instead of the white fallback `folder-symbolic` hero.

### Selected folder turning almost black

The visual theme now disables GTK icon effects for Adaptive Files icons so the
blue/cyan SVG palette is retained in selected states.

### Details appearing after Actions

The inspector now creates a fixed Details section before Location and Actions.
Asynchronous metadata fills that section in place.

The intended order is now:

1. Preview
2. Contents (folder only)
3. Details
4. Location
5. Actions

### Remaining inherited visual icons

Regular custom SVGs were added for Desktop, Recent and Starred in addition to
the symbolic sidebar set.

## Install

```bash
cd ~/adaptive-desktop

unzip -o ~/Downloads/adaptive-files-visual-preview-v1.3.zip -d .

./scripts/phase2.4-install-visual-preview.sh

/usr/bin/nautilus -q || true
pkill -x nautilus || true
sleep 2

./scripts/phase2.4-run-visual-preview.sh
```

Keep that terminal open.

Select a folder such as `ros_ws`. The Contents card should change from
`Loading folder contents…` to up to 12 actual child rows.

## Verify

In another terminal:

```bash
cd ~/adaptive-desktop
./scripts/phase2.4-verify-preview.sh
```

For a successful folder selection the log should include:

```text
Folder preview start: ...
Folder preview complete: ... rows=...
```

If the folder cannot be read, the inspector now displays the error instead of
staying permanently on Loading.
