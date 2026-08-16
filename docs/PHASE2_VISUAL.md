# Phase 2 — Adaptive Files visual layer

## Goal

Make the successfully built Nautilus 42.6 fork look like Adaptive Files while
preserving Nautilus behavior.

This milestone changes presentation, not the file-operation engine.

## What changes now

- dark deep-navy application surface;
- compact header/titlebar;
- smaller window controls;
- compact location/search controls;
- custom hover and selected states;
- restrained electric-blue/cyan accenting;
- redesigned Places/sidebar surface;
- compact sidebar rows;
- dark file/list surface;
- redesigned list headers;
- tabs;
- context menus/popovers;
- dialogs;
- progress bars;
- scrollbars;
- switches/checks;
- separators;
- tooltips;
- infobars.

## What is intentionally not implemented in this milestone

The following require source-level widget/layout work and are Phase 2.1+:

- permanent right preview inspector;
- folder single-click inspector content;
- custom storage inspector;
- custom folder/file icon artwork replacing all inherited icons;
- pinned/project sections integrated into Nautilus sidebar;
- Adaptive Command integration;
- project context;
- structural replacement of Nautilus header widgets.

## Isolation

The launcher uses:

`GTK_THEME=AdaptiveFiles`

only in the Adaptive Files process.

It also puts the local Nautilus prefix first in `XDG_DATA_DIRS`, so GTK can
discover the theme under the fork prefix.

This avoids changing:

- the system GTK theme;
- stock Ubuntu Files;
- other applications;
- the normal Ubuntu session.

## Acceptance gate

Phase 2 passes when:

1. `phase2-run-visual.sh` launches the local Nautilus 42.6 fork;
2. visual chrome is no longer the stock Ubuntu/GNOME appearance;
3. double-click, selection, tabs, search, Trash and network functions still work;
4. stock `/usr/bin/nautilus` remains unchanged.

Once this passes, start Phase 2.1: structural right inspector + custom app UI.
