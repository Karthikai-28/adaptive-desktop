# Technical Requirements

## Current target platform

- Ubuntu 22.04.5 LTS
- GNOME Shell 42
- GDM
- X11 session
- Intel integrated graphics
- 16 GB RAM
- 1920×1200 primary display
- approximately 41 GB free disk space at the current development checkpoint

## Architecture

```text
Ubuntu 22.04
│
├── Standard Ubuntu session
│   ├── normal Ubuntu GNOME
│   └── normal desktop configuration
│
└── Adaptive Desktop session
    ├── Ubuntu GNOME runtime
    ├── DCONF_PROFILE=adaptive
    ├── adaptive-shell@local
    ├── project context service
    ├── command/search layer
    ├── workspace layer
    ├── file experience
    ├── settings experience
    └── recovery/session controls
```

## Session isolation

Adaptive Desktop must be exposed as a separate GDM session.

Current files:

```text
/usr/share/xsessions/adaptive-desktop.desktop
/usr/local/bin/adaptive-desktop-session
/etc/dconf/profile/adaptive
```

The wrapper reuses Ubuntu's GNOME session while setting:

```bash
DCONF_PROFILE=adaptive
GNOME_SHELL_SESSION_MODE=ubuntu
XDG_CURRENT_DESKTOP=ubuntu:GNOME
```

The standard Ubuntu session must never be removed.

## Configuration isolation

Adaptive Desktop uses:

```text
user-db:adaptive
```

through `/etc/dconf/profile/adaptive`.

Before applying Adaptive-specific GNOME settings:

```bash
echo "$DCONF_PROFILE"
```

Expected:

```text
adaptive
```

## Shell extension

Primary extension UUID:

```text
adaptive-shell@local
```

Source of truth:

```text
~/adaptive-desktop/shell/adaptive-shell@local/
```

Live location:

```text
~/.local/share/gnome-shell/extensions/adaptive-shell@local/
```

Repository files are authoritative. Deploy using the sync script instead of editing the live extension directly.

## GNOME Shell compatibility

Current extension target:

```json
{
  "shell-version": ["42"]
}
```

The extension must provide clean `init()`, `enable()`, and `disable()` behavior.

Anything created or hidden by `enable()` must be destroyed or restored by `disable()`.

## Stock shell takeover rules

Adaptive Desktop may hide or replace stock GNOME chrome only inside the Adaptive session.

Current direction:

- Ubuntu Dock disabled in Adaptive Desktop, not uninstalled.
- Stock left panel content hidden while Adaptive shell is active.
- Stock date menu hidden while Adaptive shell is active.
- Top-right network/audio/power controls retained until Adaptive System Center reaches functional parity.

Do not remove working system controls before replacements exist.

## Navigation rail

Requirements:

- flush to the left display edge;
- start below the top bar;
- occupy available vertical shell space;
- reserve application space using shell struts;
- maintain consistent width;
- system/settings control anchored near the bottom;
- no giant rounded floating outer container;
- individual buttons may use rounded states;
- icons readable at 18–22 px.

Initial target width: **72 px**.

## Project Context Service

Must support:

- persistent project registry;
- active project;
- project root;
- project display name;
- pinned directories;
- recent projects;
- workspace mapping;
- project actions;
- optional project metadata;
- graceful no-project state.

No personal or calibration-specific project names should be hardcoded in generic UI.

## File Explorer

Must support:

- Recent
- Starred
- Home
- Documents
- Downloads
- Music
- Pictures
- Videos
- Trash
- mounted devices
- network locations
- pinned folders
- project roots
- grid/list modes
- search and filters
- preview/inspector
- split view
- multi-select actions
- transfer progress
- conflict resolution
- trash/recovery
- permissions and hidden-file awareness

## Settings

Must cover:

1. Home
2. Appearance
3. Projects & Workspaces
4. Windows & Multitasking
5. Notifications & Focus
6. Search & Commands
7. Display & Graphics
8. Sound
9. Input & Gestures
10. Network & Connectivity
11. Files & Storage
12. Privacy & Security
13. Accounts & Sync
14. Power & Battery
15. Accessibility
16. Developer & Advanced
17. Updates, Recovery & Session
18. About

## Recovery

At minimum:

- Adaptive Shell can be disabled.
- Stock shell chrome is restored by extension disable.
- Normal Ubuntu GDM session remains available.
- Adaptive session registration can be removed.
- System-level modifications are backed up.
- Stable milestones are committed to Git.
- High-impact changes have rollback instructions.

Emergency extension rollback:

```bash
gnome-extensions disable adaptive-shell@local
```

## Performance

- no permanent high-frequency polling;
- avoid blocking GNOME Shell's main thread;
- filesystem scans should live outside Shell when expensive;
- cache project metadata;
- prefer event-driven updates;
- keep idle CPU use negligible;
- avoid uncontrolled animation loops.

## Security

- do not run shell UI as root;
- do not store secrets in extension source;
- validate project paths;
- confirm destructive file/system operations;
- never silently elevate privileges;
- keep local-first behavior as the default.

## Development rules

1. Repository source is authoritative.
2. Test inside Adaptive Desktop.
3. Prefer small incremental changes.
4. Document system-level modifications.
5. Verify rollback before adding the next risky layer.
6. Prefer real functionality over visual placeholders.
