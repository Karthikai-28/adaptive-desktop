# Uninstall And Recovery

## Remove Adaptive Desktop Session

```bash
cd ~/adaptive-desktop
./scripts/remove-adaptive-session.sh
```

This removes:

- `/usr/share/xsessions/adaptive-desktop.desktop`
- `/usr/local/bin/adaptive-desktop-session`
- `/etc/dconf/profile/adaptive`

The script backs up removed files under:

```text
~/adaptive-desktop/backups/remove-*
```

## Disable Adaptive Shell

```bash
gnome-extensions disable adaptive-shell@local
```

## Restore Normal Ubuntu

At GDM, select:

```text
Ubuntu
```

Do not remove `/usr/share/xsessions/ubuntu.desktop`.

## Keep Or Remove User Data

Keep these for future Adaptive Desktop use:

```text
~/.config/adaptive-desktop/projects.json
~/.config/dconf/adaptive
```

Remove them only if Adaptive Desktop state should be discarded.

## Post-Uninstall Check

```bash
test -f /usr/share/xsessions/ubuntu.desktop
test ! -f /usr/share/xsessions/adaptive-desktop.desktop
test ! -f /usr/local/bin/adaptive-desktop-session
test ! -f /etc/dconf/profile/adaptive
```
