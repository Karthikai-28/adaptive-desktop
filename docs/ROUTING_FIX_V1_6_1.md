# Adaptive Desktop Routing Fix v1.6.1

This is the corrective release for the installer error:

```text
Extension “adaptive-shell-v16@local” does not exist
v1.6 INSTALL FAILED
```

## What actually happened

The extension files were copied to the correct per-user extension directory,
but the already-running GNOME Shell 42 process had not rescanned the new UUID.

The file-routing changes had already succeeded.

That is why the diagnostics showed:

- `org.gnome.Nautilus.desktop` correctly pointing to
  `adaptive-files-launch-v1.6.sh`;
- the old `adaptive-shell@local` disabled;
- no `adaptive-shell-v16@local` in `gnome-extensions info`.

## v1.6.1 behavior

The installer now:

1. installs the new UUID files;
2. disables the old live UUID;
3. updates `org.gnome.shell enabled-extensions` while preserving every unrelated
   extension already in that list;
4. enables user extensions;
5. checks whether the current Shell already discovered the new UUID;
6. if not, finishes successfully and requests exactly one logout/login;
7. after login, `post-login-v1.6.1.sh` confirms discovery and enables/verifies
   the new shell module.

The installer no longer aborts merely because the current Shell has not
rescanned a newly-created extension directory.

## Install

```bash
cd ~/adaptive-desktop

unzip -o \
  ~/Downloads/adaptive-desktop-routing-fix-v1.6.1.zip \
  -d .

./scripts/install-v1.6.1.sh
```

### If the script says logout/login is required

Save your work and log out normally.

At the login screen select:

`Adaptive Desktop`

Log back in.

Then:

```bash
cd ~/adaptive-desktop
./scripts/post-login-v1.6.1.sh
```

## Final verification

```bash
./scripts/verify-v1.6.1.sh
```

Optional actual Files-routing launch test:

```bash
./scripts/test-files-route-v1.6.1.sh
```

## Expected result after login

### File Explorer

Both:

- the left Adaptive Files button; and
- the ordinary GNOME/Ubuntu `Files` application entry

route to the local Adaptive Nautilus build.

### Dock

The v1.6 shell module provides working:

- Overview;
- Adaptive Files;
- Applications;
- Workspaces;
- Search;
- Settings.

### Top time

The real GNOME date/time menu is restored.

Clicking it still opens GNOME's native calendar and notification menu.

### Overview

The redundant stock bottom dash is hidden and the Adaptive overview styling is
loaded.

## Diagnostic

```bash
./scripts/diagnose-v1.6.1.sh
```

## Rollback

```bash
./scripts/rollback-v1.6.1.sh
```
