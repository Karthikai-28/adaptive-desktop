# Adaptive Desktop Icon Family

Adaptive Desktop uses a small symbolic icon family for shell navigation and app
chrome. Icons are simple filled SVGs, sized for 18-24 px use, and avoid text
inside the artwork.

## Shell Dock

- `overview.svg` — Home / overview
- `files.svg` — Adaptive Files
- `apps.svg` — Applications
- `workspaces.svg` — Workspaces
- `search.svg` — Command
- `settings.svg` — System Center

Source path: `shell/adaptive-shell@local/assets/dock/`

## Adaptive Files

Adaptive Files uses matching symbolic SVGs for navigation, view modes, file
types, sidebar locations, and window controls.

Source path: `apps/adaptive-files/assets/`

## Rules

- Use SVG viewBox `0 0 24 24` unless an existing icon requires otherwise.
- Prefer a single foreground fill color and let CSS/state containers provide
  hover, focus, and active treatment.
- Keep icons legible at 14 px in toolbar buttons and 20 px in the shell dock.
- Add new icons to this manifest when they become part of user-visible chrome.
