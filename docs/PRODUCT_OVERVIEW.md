# Karthi's OS — Product Overview

## Working name

**Karthi's OS**  
Internal implementation name: **Adaptive Desktop**

## Product statement

Karthi's OS is a productivity-first desktop experience layer built on top of Ubuntu.

It is **not** a Linux distribution, launcher, theme pack, or irreversible replacement for Ubuntu. Ubuntu remains the base operating system and the normal Ubuntu desktop remains available as a fallback.

The custom experience is delivered through a separate login session with its own desktop configuration and shell extension.

## Primary goal

Create a desktop experience that feels like a new operating system while preserving Ubuntu underneath.

The system should:

- feel coherent across shell, projects, files, settings, search, system controls, and workspaces;
- prioritize productivity rather than visual spectacle;
- be project-aware without being project-dependent;
- expose important context only when it is useful;
- support keyboard-first workflows while remaining excellent with mouse and touchpad;
- be safe to experiment with and easy to roll back;
- remain generic enough that any user can create their own projects and workflows.

## Core principles

### Ubuntu remains recoverable

The normal Ubuntu session must remain usable even if the custom desktop breaks.

### Separate desktop state

Adaptive Desktop uses a separate dconf profile so desktop configuration changes do not intentionally modify the normal Ubuntu session.

### Productivity over spectacle

Visual depth, animation, transparency, and spatial organization should explain hierarchy and state. They should never make basic work slower.

### Calm when idle

The desktop should not permanently display unnecessary telemetry, widgets, animations, or notifications.

### Project-aware

A project may define project root, pinned folders, workspace association, recent files, project actions, development context, focus profile, and optional project accent.

The desktop must still work normally when no project is selected.

## Product areas

1. Desktop shell
2. Project context
3. Workspace management
4. Universal command/search
5. Window management
6. File explorer
7. Settings
8. System center
9. Notifications and focus
10. Development/advanced tools
11. Lock/login/session experience
12. Recovery and fallback

## Non-goals

The first versions are not intended to:

- replace the Linux kernel;
- replace Ubuntu's package manager;
- fork every GNOME application;
- remove the standard Ubuntu session;
- depend on cloud services to function;
- copy another operating system's branding or proprietary assets.

## Success criteria

Karthi's OS is successful when:

1. Adaptive Desktop is reliable enough for daily work.
2. Normal Ubuntu can always be selected as a fallback.
3. The desktop has a distinct visual and interaction identity.
4. Projects, files, workspaces, search, settings, and system controls behave as one coherent product.
5. The user can add new projects without code changes.
6. Shell failures do not make the machine unrecoverable.
7. Major changes are version-controlled and have a rollback path.
