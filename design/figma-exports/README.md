# Figma exports

Drop exported frames from **Karthi OS Experience — Design System / Screens**
here. The Figma file itself is not reachable from tooling (figma.com returns
403 without a login), so these exports are the design source of truth in-repo.

## How to export

In Figma: select the frames → Export → **PNG, 2x** → export into this folder.

## Naming

Name each file after what it shows, so the intent survives without the Figma
canvas next to it:

```
files-window-list.png
files-window-grid.png
files-sidebar.png
settings-home.png
settings-appearance.png
quick-settings-panel.png
rail-states.png
```

## What is built from these

| Export | Drives |
| --- | --- |
| `files-*` | `AdaptiveFiles` GTK theme over the forked Nautilus |
| `settings-*` | GTK3 skin over `gnome-control-center` (41.7, links `libgtk-3` only) |
| `quick-settings-*` | Shell CSS for the top-right panel in `adaptive-shell@local` |
| `rail-*` | `.adaptive-rail` and dock button states |

Colors and spacing that appear here should end up in `tokens/adaptive.tokens.json`
rather than being hardcoded per app, so the shell, Files, and Settings stay in
one visual system.
