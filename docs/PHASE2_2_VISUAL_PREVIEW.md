# Adaptive Files Visual + Preview v1.1

This update fixes the invisible preview issue and makes the visual direction
much more distinct from stock Ubuntu Files.

## Root causes fixed

1. GTK 3 rejected the preview CSS because several font weights such as `750`
   and `720` are not accepted by the GTK 3 parser used on Ubuntu 22.04.
2. The old preview extension waited for selection/menu provider activity before
   it had a deterministic window hook.
3. Stock Nautilus could already be running, causing a local fork launch to hand
   activation to the existing process and then exit.

## v1.1 behavior

A compact strip appears below the normal navigation area:

- ADAPTIVE FILES
- Inspector
- Storage
- Network

The Inspector is visible by default.

Single click updates Preview. Double click is still handled by Nautilus.

## Custom visual language

The package installs a process-local SVG icon theme:

`AdaptiveFilesIcons`

It replaces common folder, Home, storage, removable-media, network, Trash,
generic document, image, PDF, audio, video, executable and app icons.

Unimplemented icon names inherit from Adwaita/hicolor so features are not lost.

No PNG assets are needed for these core icons; SVG is used so the UI remains
sharp at high DPI.

## Install

```bash
cd ~/adaptive-desktop
unzip -o ~/Downloads/adaptive-files-visual-preview-v1.1.zip -d .

./scripts/phase2.2-install-visual-preview.sh

/usr/bin/nautilus -q || true
pkill -x nautilus || true
sleep 2

./scripts/phase2.2-run-visual-preview.sh
```

Keep the launch terminal open.

## Verify

In another terminal:

```bash
cd ~/adaptive-desktop
./scripts/phase2.2-verify.sh
```

The log should contain:

- `Process icon theme set to AdaptiveFilesIcons`
- `LocationWidgetProvider active`
- `Inspector attached to overlay ...` or `Inspector attached to horizontal box ...`

There should be no `gtk-css-provider-error`.

## Existing Nautilus functionality

This remains an additive presentation layer over the Nautilus 42.6 engine.
It does not reimplement copy, move, Trash, MIME handling, permissions,
bookmarks, devices or GVfs networking.

## Translucency

GTK 3 can provide layered alpha/translucent surfaces inside the application.
True compositor background blur is a separate shell/compositor feature and is
not faked here with heavy glow.
