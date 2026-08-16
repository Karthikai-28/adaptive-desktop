# Adaptive Desktop

A productivity-first desktop experience layer built on Ubuntu 22.04, working
product name **Karthi's OS**. Ubuntu stays underneath as the stable foundation
and the guaranteed recovery path; the visible desktop stops feeling like Ubuntu.

Governing principle:

> Use Ubuntu/GNOME for proven infrastructure. Own the Adaptive experience layer.

This is not a distribution, a theme pack, or a launcher pasted over GNOME. Where
Ubuntu already has a mature backend — file operations, MIME, mounts, search,
notifications, workspaces, power — it is preserved and reskinned, not replaced.

## Target platform

Deliberately constrained to the development machine:

```text
Ubuntu 22.04.5 LTS · GNOME Shell 42.x · GDM · X11 Adaptive session
Intel integrated graphics · 16 GB RAM · 1920x1200
Nautilus baseline: Ubuntu Nautilus 42.6
```

Do not broaden compatibility on this branch without preserving Jammy/GNOME 42
first.

## Architecture

| Layer | What owns it |
| --- | --- |
| Shell (rail, top bar, overview, system panel) | `shell/adaptive-shell@local/` |
| File manager | Forked Nautilus in `.local/adaptive-nautilus/`, skinned |
| Settings | `gnome-control-center` 41.7 (GTK3), skinned |
| Project context | `services/project-context/` over D-Bus |
| Command palette | Shell menu + `apps/adaptive-command/` |
| Design system | `tokens/adaptive.tokens.json`, `theme/`, `icons/` |

### Canonical paths

```text
shell source   shell/adaptive-shell@local/
shell live     ~/.local/share/gnome-shell/extensions/adaptive-shell@local/
files fork     .local/adaptive-nautilus/bin/nautilus
files routing  scripts/adaptive-files-dispatch.sh
```

`adaptive-shell-v16@local` is a **retired duplicate kept for rollback**. Only
one Adaptive rail extension may be enabled at a time — with both enabled the
rails stack and the dock labels render with their first glyph covered.

## Development workflow

```sh
./scripts/sync-shell.sh                        # repo -> live extension
./scripts/reload-adaptive-shell.sh --restart-shell   # X11; JS is cached per shell process
```

GNOME 42 caches an extension's JavaScript for the life of the shell process and
`ReloadExtension` is deprecated, so disable/enable silently re-runs the old
code. The reload script detects this and says so.

Files activation needs no launcher. A dispatcher answers the standard D-Bus
names and picks the fork inside Adaptive Desktop, stock Nautilus everywhere
else:

```sh
./scripts/install-files-session-integration.sh
```

## Verification

```sh
./scripts/verify-environment.sh
./scripts/verify-session-isolation.sh
./scripts/verify-shell-source.sh
./scripts/verify-adaptive-files-stack.sh
./scripts/verify-project-context-service.sh
./scripts/verify-stability-suite.sh
./scripts/verify-live-readiness.sh      # from inside the Adaptive session
```

Physical checks — TTY recovery, GDM fallback, reboot, suspend/resume, external
monitor, long-running memory — cannot be proven from code. Record them with:

```sh
./scripts/record-live-verification.py status
```

Source present, automated test passed, live GUI verified, and physically
verified are four different things. `docs/BACKLOG.md` keeps them apart.

## Current work

Milestone 14 — one visual system over Ubuntu's apps. See `docs/BACKLOG.md`,
which is the status source of truth; older status claims in
`docs/MASTER_PROMPT.md` lose to it.

## Recovery

Normal Ubuntu must always remain selectable in GDM, and stock Nautilus stays
installed. If the shell misbehaves:

```sh
gnome-extensions disable adaptive-shell@local
```

Full procedures: `docs/RECOVERY_RUNBOOK.md`, `docs/UNINSTALL_AND_RECOVERY.md`.

## Documentation map

| Document | Purpose |
| --- | --- |
| `docs/BACKLOG.md` | Status source of truth |
| `docs/PRODUCT_OVERVIEW.md` | What the product is |
| `docs/DESIGN_SYSTEM.md` | Palette, spacing, type, motion |
| `docs/UBUNTU_FILES_PARITY.md` | File manager architecture rule |
| `docs/COMMAND_PERMISSION_MODEL.md` | Command surface safety model |
| `docs/RECOVERY_RUNBOOK.md` | Getting back to a working desktop |
| `docs/LEGACY_PHASES.md` | Which historical scripts are safe to ignore |
| `docs/REPO_DOCUMENTATION_MAP.md` | Everything else |
