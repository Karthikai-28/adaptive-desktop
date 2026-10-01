# Adaptive Command Permission Model

Adaptive Command is allowed to run frequent desktop actions directly when the
action is local, reversible, or already guarded by GNOME.

## Direct actions

- Open applications, files, folders, settings panels, and Adaptive Desktop apps.
- Switch projects and apply project metadata.
- Toggle focus mode and appearance preferences.
- Move, tile, save, or restore the active window.
- Copy file paths and other clipboard-only actions.

- Copy a snippet or clipboard entry, tick a task in a project's inbox, start
  a timer, open a file at a line, open a terminal or an SSH session.
- Switch the active project's git branch (`git switch`, which itself refuses
  when it would lose work), create a project from a template.

## Guarded actions

- Lock, logout, suspend, restart, shut down, and return-to-Ubuntu actions must
  route through GNOME session APIs or local helper scripts that provide the
  platform confirmation dialog where available.
- File deletion must use Trash by default.
- Saved window placement restore clamps geometry to the current visible display.

- Ending a process is offered only in the palette's `kill` mode, only for
  your own processes, never for the session's (the shell, the session manager,
  the display server, the bus, audio), and only as SIGTERM, so the process
  gets to save and clean up. The process is checked by start time before the
  signal is sent, so a reused pid is never hit.

## Your own commands

Executables in `~/.config/adaptive-desktop/commands/` appear in the palette as
actions. They are yours and run as you, so the palette only offers a regular
file that you own, that is executable, and that nobody else can write. They
are run as an argument list, never through a shell string, and the result is
shown in a notification.

A project's startup commands (`project-cli.py startup add`) are the same kind
of thing: commands you chose, stored in your registry, run in the project
folder when you resume the project or ask for them from its menu. Nothing
sets them but you, or a project template you chose to create a project from.

## Out of scope without a prompt

- Permanent file deletion.
- Package installation or system package removal.
- Disabling the Ubuntu fallback session.
- Rewriting GNOME or GDM configuration outside the Adaptive session profile.
- Running network-downloaded commands.

## Provider rules

- Providers should return a label, a short source/category, and a callable
  action.
- Actions that can destroy data or change system availability need a guarded
  helper or an explicit confirmation surface before they are exposed.
- Recent actions may only replay commands from known providers, not arbitrary
  shell strings.
- A mode (`apps/adaptive-command/modes.py`) returns its actions as data - a
  small tuple naming one of a fixed set of things the palette can do - rather
  than as code, so every mode can be checked without a display and no mode can
  do something the palette does not already know how to do.
