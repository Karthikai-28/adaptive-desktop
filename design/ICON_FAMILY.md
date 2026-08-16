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

Source path: `icons/AdaptiveFilesIcons/` — an icon theme (110 SVGs) consumed by
the forked Nautilus, not per-app assets. The standalone GTK4 app that used to
own `apps/adaptive-files/assets/` was retired; see Milestone 14 in
`docs/BACKLOG.md`.

The theme inherits Ubuntu's icons for everything it does not draw itself, so
the custom set stays small and deliberate. Coverage today spans programming
languages (Python, Jupyter, C/C++, CUDA, Arduino, JavaScript, TypeScript, Java,
Kotlin, Rust, Go, shell), config and data formats (JSON, YAML, TOML, SQL,
protobuf), build files (CMake, Makefile, Dockerfile), web formats (HTML, CSS,
SCSS, Markdown), and common media/document types. Do not replace these with
generic mimetype icons.

## Rules

- Use SVG viewBox `0 0 24 24` unless an existing icon requires otherwise.
- Prefer a single foreground fill color and let CSS/state containers provide
  hover, focus, and active treatment.
- Keep icons legible at 14 px in toolbar buttons and 20 px in the shell dock.
- Add new icons to this manifest when they become part of user-visible chrome.
