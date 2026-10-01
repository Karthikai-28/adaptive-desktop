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
| Settings | `gnome-control-center` 41.7 (GTK3), skinned; Adaptive-only sections in `apps/adaptive-settings/` |
| Project context | `services/project-context/` over D-Bus |
| Command palette | `apps/adaptive-command/` (`providers.py` answers, `modes.py` modes), the shell bridge `shellActions.js` |
| Screenshot annotation | `apps/adaptive-annotate/` |
| Design system | `tokens/adaptive.tokens.json`, `theme/`, `icons/` |

### Canonical paths

```text
shell source   shell/adaptive-shell@local/
shell live     ~/.local/share/gnome-shell/extensions/adaptive-shell@local/
files fork     .local/adaptive-nautilus/bin/nautilus
files routing  scripts/adaptive-files-dispatch.sh
```

Only one Adaptive shell extension exists. The retired `adaptive-shell-v16@local`
duplicate and the v1.x/v2.x one-off scripts were deleted; git history holds them
if a rollback is ever needed.

## Install

```sh
./install.sh --status     # what is installed and what is out of date
./install.sh              # everything that needs no sudo
./install.sh --session    # also the login session (sudo)
./uninstall.sh --dry-run  # the other direction; your data is left alone
```

`install.sh` runs the per-part scripts in `scripts/` in order; each still works
on its own. It never restarts your shell.

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

The fork only scans its own prefix for extensions, so apt-installed ones (the
gnome-terminal extension behind "Open in Terminal") have to be linked in. This
runs as part of `install-nautilus-fork-local.sh`, or on its own:

```sh
./scripts/install-nautilus-fork-extensions.sh
```

Adaptive Settings (projects and workspaces, shortcuts and search, updates and
recovery) installs into the app grid with:

```sh
./scripts/install-adaptive-settings.sh
```

Day to day: Alt+Space opens the Command palette, which also calculates
(`12*7`), converts (`5 km to mi`), finds emoji (`:rocket`), open windows and
clipboard history (`clip`, Ctrl+P pins an entry). A word in front asks for one
thing:

| Type | For |
| --- | --- |
| `snip`, `snip save <name>` | saved snippets |
| `todo` | the project's quick-note inbox as tasks; Enter ticks one |
| `git` | every project's branch and uncommitted or unpushed work |
| `time` | time per project, today and this week |
| `/text` or `grep text` | search inside the active project's files |
| `branch` | switch the active project's git branch |
| `timer 10m tea` | a notification after that long |
| `keys` | every Adaptive keyboard shortcut (also Super+/) |
| `kill <name>` | ask one of your processes to quit |
| `ssh <host>` | hosts from `~/.ssh/config`, in a terminal |
| `new <template> <folder>` | a project from a template |

Executables in `~/.config/adaptive-desktop/commands/` show up as actions.

The active project and its git status sit at the top left; its menu parks and
resumes the project, running its startup commands when it comes back.
Super+Alt+N takes a quick note, Super+Return drops a terminal from the top of
the screen, Super+Shift+S annotates a screenshot. See Milestones 15 and 16 in
`docs/BACKLOG.md`.

## Verification

Everything that needs no physical machine, in one run:

```sh
./scripts/verify-all.sh           # about two minutes
./scripts/verify-all.sh --quick   # skip the sandboxes: a few seconds
```

The sandboxes run the real things - the extension in a nested GNOME Shell, the
palette and Annotate windows, Files with the inspector - on a virtual display
with a throwaway HOME and session bus, so they cannot touch the desktop you are
using. Run them before `sync-shell.sh`: they are how a change to the shell is
tried without restarting it.

The checks specific to this machine and session:

```sh
./scripts/verify-environment.sh
./scripts/verify-session-isolation.sh
./scripts/verify-shell-source.sh
./scripts/verify-adaptive-files-stack.sh
./scripts/verify-project-context-service.sh
./scripts/verify-stability-suite.sh
./scripts/verify-adaptive-settings.py   # no display needed
./scripts/verify-feature-logic.py       # palette, quick notes, workspace names
./scripts/verify-shell-helpers.js       # shell decisions, under Node
./scripts/verify-live-readiness.sh      # from inside the Adaptive session
```

Physical checks — TTY recovery, GDM fallback, reboot, suspend/resume, external
monitor, long-running memory — cannot be proven from code. Record them with:

```sh
./scripts/record-live-verification.py status
```

Source present, automated test passed, live GUI verified, and physically
verified are four different things. `docs/BACKLOG.md` keeps them apart. A pass
in a sandbox is the second of those, not the third.

## Current work

Milestone 16 is built and passes its checks; what is open is installing it
into the live session and the physical checks. Milestone 14 — one visual system
over Ubuntu's apps — is still waiting on the Figma exports. See `docs/BACKLOG.md`,
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
| `docs/GNOME_PORT.md` | What a move to GNOME 45+ and Wayland would take |
| `docs/REPO_DOCUMENTATION_MAP.md` | Everything else |
