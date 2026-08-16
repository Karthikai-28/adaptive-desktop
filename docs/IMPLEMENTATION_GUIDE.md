# Implementation Guide

## Purpose

This is the operating guide for developing Karthi's OS safely and consistently.

## Product boundary

Karthi's OS is an experience layer on Ubuntu.

Before any implementation decision, ask:

1. Can this be user-local?
2. Can this affect Adaptive Desktop only?
3. Can it be rolled back?
4. Does normal Ubuntu still work?
5. Is the feature functional or merely visual?

## Development environment

Repository:

```text
~/adaptive-desktop
```

Before applying Adaptive-specific GNOME settings:

```bash
echo "$DCONF_PROFILE"
```

Expected:

```text
adaptive
```

If it is not `adaptive`, stop.

## Repository is authoritative

Do not make long-lived manual edits in:

```text
~/.local/share/gnome-shell/extensions/adaptive-shell@local/
```

Edit:

```text
~/adaptive-desktop/shell/adaptive-shell@local/
```

Then deploy:

```bash
./scripts/sync-shell.sh
```

## Development loop

```text
edit
↓
review diff
↓
sync
↓
reload extension
↓
test
↓
check logs
↓
commit
```

Typical commands:

```bash
cd ~/adaptive-desktop
git diff
./scripts/sync-shell.sh
gnome-extensions disable adaptive-shell@local
gnome-extensions enable adaptive-shell@local
```

On X11, when a Shell restart is required:

```text
Alt + F2
r
Enter
```

Diagnostics:

```bash
journalctl --user -b | grep -iE 'adaptive-shell|gnome-shell.*error'
```

## Shell coding rules

### Lifecycle

Everything created in `enable()` must be removed/restored in `disable()`.

### Performance

Do not perform expensive recursive filesystem operations in GNOME Shell's main process.

Use separate services/processes for heavy work.

### Preserve functionality

Do not hide a working GNOME capability before Adaptive Desktop has a reliable functional replacement.

## Visual development

Use `DESIGN_SYSTEM.md` as the authority.

Before adding a new color, check whether one of these is appropriate:

```text
#08111B
#07101A
#111A28
#162233
#30425C
#F2F6EF
#96A4B8
#78A9FF
#66E0FF
#9A8BFF
#F3C96B
#FF7A90
#65D9B5
```

If a new token is required, document it first.

## Generic project behavior

Never hardcode a personal project into a generic product component.

Runtime project names are allowed because they come from user data.

## Implement vertical slices

Prefer:

```text
project registry
→ active project
→ top-bar label
→ Projects overlay
→ switching
→ persistence
```

over building many disconnected mock screens.

## System-level changes

Before writing to `/usr/share`, `/usr/local`, or `/etc`:

1. identify the exact file;
2. back up any existing file;
3. document why the change exists;
4. provide a removal/restore path;
5. avoid modifying unrelated files.

## Package installation

- prefer Ubuntu repositories;
- record new dependencies;
- explain why each is required;
- avoid unnecessary desktop stacks;
- avoid random PPAs for core shell functionality.

## Recovery-first workflow

Before risky shell changes:

```bash
git status
git add .
git commit -m "checkpoint: known-good adaptive shell"
```

Extension rollback:

```bash
gnome-extensions disable adaptive-shell@local
```

TTY recovery:

```text
Ctrl + Alt + F3
```

Normal Ubuntu must remain selectable in GDM.

## Shell milestone test checklist

### Basic

- [ ] extension enables;
- [ ] extension disables;
- [ ] no shell crash;
- [ ] no major errors in logs;
- [ ] top bar usable;
- [ ] keyboard/mouse input works;
- [ ] maximize/restore works;
- [ ] fullscreen behavior acceptable.

### Recovery

- [ ] disable restores stock chrome;
- [ ] logout works;
- [ ] Adaptive login works;
- [ ] Ubuntu login works.

### Visual

- [ ] no overlaps;
- [ ] no clipped text;
- [ ] spacing follows design system;
- [ ] icon sizes consistent;
- [ ] active state obvious;
- [ ] destructive state uses correct color;
- [ ] readable at 1920×1200.

## Definition of done

A feature is done when:

1. UI exists.
2. Primary interaction works.
3. Required state persists.
4. Error/empty state exists.
5. Keyboard behavior is defined.
6. Recovery is known.
7. Logs show no serious errors.
8. Documentation/backlog is updated.

## Commit strategy

Suggested prefixes:

```text
shell:
project:
workspace:
command:
files:
settings:
system:
design:
docs:
recovery:
fix:
```

Examples:

```text
shell: dock navigation rail into reserved workspace
project: add persistent project registry
system: add volume control to system center
docs: update shell backlog
```

## Documentation rule

When architecture changes, update `TECHNICAL_REQUIREMENTS.md`.

When visual tokens/components change, update `DESIGN_SYSTEM.md`.

When scope/goal changes, update `PRODUCT_OVERVIEW.md`.

Update `BACKLOG.md` whenever milestone status changes.
