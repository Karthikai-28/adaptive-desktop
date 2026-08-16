# Architecture Decision — Fork Nautilus, Do Not Reimplement It

## Decision

The Python/GTK Adaptive Files prototype is no longer the long-term file-manager engine.

For Ubuntu 22.04 the production implementation should be based on the Ubuntu Nautilus 42 source.

## Why

The requirement is:

> Preserve everything Ubuntu Files already provides, change the experience layer, then add new capability.

Independent reimplementation creates avoidable risk around:

- click/selection semantics;
- drag/drop;
- copy/move conflicts;
- MIME handling;
- Trash and undo;
- permissions;
- removable devices;
- authentication;
- GVfs remote protocols;
- Tracker search;
- context menus;
- extensions;
- operation progress.

## Target stack

```text
Layer 4 — Karthi's OS additions
  Preview inspector
  Project context
  Storage visualization
  Adaptive command/search

Layer 3 — Adaptive Nautilus UI fork
  Window geometry
  Toolbar
  Sidebar
  Iconography
  Preview-pane integration
  Adaptive surfaces

Layer 2 — Nautilus behavior
  Selection
  File operations
  Search
  Tabs
  Properties
  MIME
  Extensions

Layer 1 — Ubuntu/GNOME services
  GIO
  GVfs
  Tracker
  udisks
  MIME database
  portals
```

## Safety

Do not uninstall `/usr/bin/nautilus`.

Build the Adaptive fork into a repository-local/user-local prefix until parity testing is complete.

Stock Ubuntu Files remains the recovery implementation.
