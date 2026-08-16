# Adaptive Command Permission Model

Adaptive Command is allowed to run frequent desktop actions directly when the
action is local, reversible, or already guarded by GNOME.

## Direct actions

- Open applications, files, folders, settings panels, and Adaptive Desktop apps.
- Switch projects and apply project metadata.
- Toggle focus mode and appearance preferences.
- Move, tile, save, or restore the active window.
- Copy file paths and other clipboard-only actions.

## Guarded actions

- Lock, logout, suspend, restart, shut down, and return-to-Ubuntu actions must
  route through GNOME session APIs or local helper scripts that provide the
  platform confirmation dialog where available.
- File deletion must use Trash by default.
- Saved window placement restore clamps geometry to the current visible display.

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
