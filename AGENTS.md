# adaptive-desktop - map for agents

A desktop experience layer over Ubuntu 22.04 / GNOME Shell 42 / X11 ("Karthi's OS"). Ubuntu stays
underneath as the recovery path: own the experience layer, reuse GNOME's backends. `README.md` is
the human overview; `docs/BACKLOG.md` is the status source of truth (it beats `MASTER_PROMPT.md`).

Target is this machine only: Jammy, GNOME 42, X11, Intel iGPU, 1920x1200. Do not broaden
compatibility without keeping GNOME 42 working first.

## Where things are

| Area | Source | Notes |
| --- | --- | --- |
| Shell extension (rail, top bar, dock, control center, dynamic island) | `shell/adaptive-shell@local/` | `extension.js` wires modules; `shell*.js` dock/displays/lock, `cc*.js` control center, `island*.js` dynamic island, `shellActions.js` = bridge the command palette calls. Live copy: `~/.local/share/gnome-shell/extensions/adaptive-shell@local/` |
| Command palette (Alt+Space) | `apps/adaptive-command/` | answers in `providers.py`, prefix modes (`snip`, `todo`, `git`, ...) in `modes.py` |
| Files (forked Nautilus 42.6) | `extension/adaptive_files/` (inspector side panel, Python), fork build in `.local/adaptive-nautilus*` | routing: `scripts/adaptive-files-dispatch.sh`; architecture rule: `docs/UBUNTU_FILES_PARITY.md` |
| Settings | `apps/adaptive-settings/` (Adaptive-only sections); rest is skinned gnome-control-center 41.7 | |
| Project context (D-Bus) | `services/project-context/main.py` | |
| Phone link | daemon `services/adaptive-link/` (`server.py` + one module per feature), Android app `apps/adaptive-link-android/` (Kotlin, Gradle) | `docs/ADAPTIVE_LINK.md` |
| Agent Office (AI company, :8790) | `services/agent-office/`: `server.py`, `office/*.py` (`manager.py`, `agy.py` Gemini, `local.py` Ollama, `codex.py` Codex (meetings, first backup), `claude_agent.py` Claude Haiku backup, `quota.py`, `ledger.py`, `graphs.py`, `study.py`), UI in `static/` | `docs/AGENT_OFFICE.md` (sections: setup, safety, providers, ledger, gotchas). All Agent Office work happens here and nowhere else |
| Screenshot annotate / screen text | `apps/adaptive-annotate/`, `shell/.../screenText*.js` | |
| Design system | `tokens/adaptive.tokens.json`, `theme/`, `icons/`, `design/` | `docs/DESIGN_SYSTEM.md` |
| systemd units, autostart | `services/*.service`, `*.timer` | |
| Install/uninstall pieces | `scripts/install-*.sh`, run in order by `./install.sh` | |

Untracked noise at the root (`*.log`, `*-audit.txt`, `build/`, `dist/`, `logs/`, `vendor/`) is build
output - not source.

## Run and check

```sh
./install.sh --status                     # what is installed / out of date
./scripts/sync-shell.sh                   # shell source -> live extension
./scripts/reload-adaptive-shell.sh --restart-shell   # GNOME 42 caches extension JS per shell process
./scripts/verify-all.sh --quick           # syntax + pure logic, seconds (CI "quick" job)
./scripts/verify-all.sh                   # + sandboxes: nested shell, palette, Files on a virtual display, ~2 min
./scripts/build-link-app.sh [--install]   # Android APK -> dist/
./scripts/verify-agent-office.sh          # Agent Office
```

Run the sandboxes before `sync-shell.sh`: that is how a shell change is tried without restarting
the session. Area-specific checks are `scripts/verify-*.{sh,py,js}`, named after what they check.
"Passed in a sandbox" is not "verified live" - `docs/BACKLOG.md` keeps those apart; physical checks
are recorded with `scripts/record-live-verification.py`.

## Rules that bite

- One shell extension only (`adaptive-shell@local`). Do not recreate the retired v16 duplicate.
- Normal Ubuntu must stay selectable in GDM and stock Nautilus stays installed. Recovery:
  `gnome-extensions disable adaptive-shell@local`; `docs/RECOVERY_RUNBOOK.md`.
- Never restart the user's shell from a script unless asked; `install.sh` never does.
- Repo conventions (single `master` branch, commit identity, commit cadence, UI palette, Files
  inspector scope) are in this repo's memory: `memctl read`.

<!-- map-check: commit=cd00d8c0a4d9 time=1791823562 -->
