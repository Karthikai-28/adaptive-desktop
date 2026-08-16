# Ultimate Requirements

These are the non-negotiable requirements for Karthi's OS.

## Complete experience

Build a coherent desktop experience that feels like its own operating system while Ubuntu remains underneath.

It must not feel like:

- a GNOME theme;
- a launcher;
- unrelated extensions;
- a sci-fi skin;
- a dashboard pasted onto Ubuntu.

## Ubuntu remains available

There must always be a practical path back to standard Ubuntu.

Required:

- Ubuntu stays in GDM;
- Adaptive Shell can be disabled;
- Adaptive session can be removed;
- normal user data remains intact;
- Adaptive Desktop failure does not prevent recovery.

## Separate session

Adaptive Desktop must run as a distinct login option with isolated settings wherever feasible.

## Full product scope

The target includes:

- desktop shell;
- navigation;
- workspaces;
- window management;
- command/search;
- project system;
- file explorer;
- settings;
- notifications;
- focus mode;
- system controls;
- lock/session/recovery;
- developer/advanced tooling.

## Project-aware by design

The user adds projects and the OS adapts around them.

Projects may influence:

- active context;
- workspace;
- files;
- recent work;
- actions;
- focus;
- development context;
- optional accent.

No project names should be hardcoded into the generic product.

## Generic behavior

Although this is Karthi's OS, the product should remain usable by another person.

Do not embed personal names, calibration content, or one-off workflow assumptions into generic shell components.

## Productivity first

Every persistent UI element must justify its screen space.

Prefer:

- fast switching;
- keyboard access;
- clear hierarchy;
- predictable placement;
- fewer interruptions;
- useful state.

Avoid:

- permanent visual noise;
- decorative telemetry;
- unnecessary animation;
- duplicate controls.

## Visual identity

The final identity must be independent.

Do not use:

- Iron Man branding;
- Jarvis branding;
- Stark branding;
- macOS branding;
- copied proprietary Apple icons/assets.

## Consistency

Shell, Projects, Workspaces, Command, Files, Settings, System Center, Notifications, and Lock/Session must share one design language.

Consistency includes:

- color;
- spacing;
- icon style;
- typography;
- motion;
- states;
- terminology;
- interaction patterns.

## Keyboard-first, mouse-excellent

Core actions should be accessible without the mouse, while remaining discoverable and comfortable with mouse/touchpad.

## Calm idle desktop

When idle, the desktop should be quiet.

Do not permanently show CPU charts, debug information, long project metadata, or unnecessary animation.

## Functional before decorative

Do not remove a working Ubuntu/GNOME feature before the Adaptive replacement really works.

Do not create fake controls that imply unavailable system functionality.

## Recovery before risk

High-impact changes must have a rollback path.

This applies especially to:

- session behavior;
- system controls;
- file operations;
- login behavior;
- project actions.

## Local-first

Core desktop functionality must work without cloud services.

AI/cloud integration may be additive, not foundational.

## Maintainability

The project must evolve into maintainable software with:

- modular source;
- explicit services;
- clear schemas;
- version control;
- diagnostics;
- tests;
- documented recovery;
- tracked backlog;
- design tokens;
- release/checkpoint process.

## Ultimate acceptance test

> A user can boot Ubuntu, choose Adaptive Desktop, perform a full workday using projects, files, windows, search, settings, and system controls, then safely return to standard Ubuntu without damaging their environment.

If that statement is not true, the product is not finished.
