# Adaptive Desktop Recovery Runbook

Adaptive Desktop is an Ubuntu experience layer. Normal Ubuntu must remain the fallback.

## Fast Recovery

From the broken Adaptive session:

```bash
gnome-extensions disable adaptive-shell@local
```

Then log out and choose the standard Ubuntu session from GDM.

## TTY Recovery

If the graphical session is not usable:

1. Press `Ctrl + Alt + F3`.
2. Log in with the normal user account.
3. Disable the shell extension:

```bash
gnome-extensions disable adaptive-shell@local
```

4. Remove the Adaptive session registration if needed:

```bash
cd ~/adaptive-desktop
./scripts/remove-adaptive-session.sh
```

5. Restart GDM only after saving work:

```bash
sudo systemctl restart gdm3
```

6. At GDM, choose the standard `Ubuntu` session.

## Full User-Level Rollback

This leaves normal Ubuntu intact and removes Adaptive login registration:

```bash
cd ~/adaptive-desktop
./scripts/remove-adaptive-session.sh
gnome-extensions disable adaptive-shell@local || true
```

Optional user-local cleanup:

```bash
rm -rf ~/.local/share/gnome-shell/extensions/adaptive-shell@local
rm -f ~/.config/autostart/adaptive-project-context.desktop
rm -f ~/.local/share/applications/adaptive-project-context.desktop
rm -f ~/.local/share/gnome-shell/search-providers/org.adaptive.ProjectContext.search-provider.ini
```

Do not delete `~/.config/adaptive-desktop/projects.json` unless the project registry should be discarded.

## Verification

Run:

```bash
cd ~/adaptive-desktop
./scripts/verify-environment.sh
./scripts/verify-session-isolation.sh
./scripts/verify-shell-source.sh
```

Expected recovery guarantees:

- `/usr/share/xsessions/ubuntu.desktop` exists.
- `/usr/share/xsessions/adaptive-desktop.desktop` can be removed without touching Ubuntu.
- `/etc/dconf/profile/adaptive` uses `user-db:adaptive`.
- Adaptive shell extension can be disabled independently.
- Normal Ubuntu user data remains in place.
