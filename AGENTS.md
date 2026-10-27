# adaptive-desktop - map for agents

A desktop experience layer over Ubuntu 22.04 / GNOME Shell 42 / X11 ("Karthi's OS"). Ubuntu stays
underneath as the recovery path: own the experience layer, reuse GNOME's backends. `README.md` is
the human overview; `docs/BACKLOG.md` is the status source of truth (it beats `MASTER_PROMPT.md`).

Target is this machine only: Jammy, GNOME 42, X11, Intel iGPU, 1920x1200. Do not broaden
compatibility without keeping GNOME 42 working first.

## Where things are

| Area | Source | Notes |
| --- | --- | --- |
| Shell extension (rail, top bar, dock, control center, dynamic island) | `shell/adaptive-shell@local/` | `extension.js` wires modules; `shell*.js` dock/displays/lock, `cc*.js` control center, `island*.js` + `dynamicIsland.js` dynamic island, `shellActions.js` = bridge the command palette calls. Live copy: `~/.local/share/gnome-shell/extensions/adaptive-shell@local/` |
| Shade (date menu) and Activity Center | `shade.js` (clock, hosts the island's cards via `mountActivityCenter()`), `notifications.js` (per-app groups and durable arrival ledger; order/journal logic in `notificationOrder.js`) | `docs/NOTIFICATION_FOCUS_POLICY.md`; checks `scripts/verify-notification-order.js`, `verify-dynamic-island.js`, `verify-island-frontend.js` (all in `verify-all.sh --quick`) |
| Command palette (Alt+Space) | `apps/adaptive-command/` | answers in `providers.py`, prefix modes (`snip`, `todo`, `git`, ...) in `modes.py` |
| Terminal (KTERM modern profile) | `terminal/launcher.py`, `scripts/install-terminal.py` | `./install.sh --only terminal`; user defaults, legacy command aliases and Antigravity profiles; `scripts/verify-terminal.py` |
| Files (forked Nautilus 42.6) | `extension/adaptive_files/` (inspector side panel, Python), fork build in `.local/adaptive-nautilus*` | routing: `scripts/adaptive-files-dispatch.sh`; architecture rule: `docs/UBUNTU_FILES_PARITY.md` |
| Cast (wireless display, Miracast over Wi-Fi Direct) | `apps/adaptive-cast/`: `p2p.py` (NetworkManager P2P find/join, volatile connection), `session.py` (RTSP server on :7236 driving M1-M7, GStreamer pipeline), `wfd.py` (pure: WFD IEs, RTSP framing, format choice) | `./install.sh --only cast`; needs `gstreamer1.0-plugins-bad` + `gstreamer1.0-vaapi`; check `scripts/verify-cast.py`; CLI `main.py --list` / `--connect NAME` |
| Settings | `apps/adaptive-settings/` (Adaptive-only sections); rest is skinned gnome-control-center 41.7 | |
| Project context (D-Bus) | `services/project-context/main.py` | |
| Phone link | daemon `services/adaptive-link/` (`server.py` + one module per feature; `zero_state.py` records a phone arm request only), Android app `apps/adaptive-link-android/` (Kotlin, Gradle); continuity/navigation state is in `ContinuityState.kt`, protected typed clipboard + focused send action in `ClipboardSync.kt` / `ClipboardSendActivity.kt`, and full-screen trackpad/Ink Studio in `RemoteScreens.kt` / `InkStudio.kt`; phone session apps share the laptop's profiles and keyring (`secrets_bridge.py`, one running copy: `mobile_launch.holders`) and are drawn at the phone's size and scale: `phone_form.py` (laptop), `LaptopApps.kt` (home-screen shortcuts, Laptop apps widget) and `Motion.kt` (phone) | `docs/ADAPTIVE_LINK.md`, `docs/PHONE_TRACKPAD_AND_INK.md` |
| Device retirement | `scripts/zero-state-protocol.sh`, with guard test `scripts/verify-zero-state-protocol.sh` | `docs/ZERO_STATE_PROTOCOL.md`; external boot only, never remotely erases storage |
| Agent Office (AI company, :8790) | `services/agent-office/`: `server.py`, `office/*.py` (`manager.py`, providers, `mission_templates.py`, `capsules.py`, `evidence.py`; workflow/audit/retention/ROS comparison in `workflows.py`, `audit_export.py`, `retention.py`, `ros_compare.py`; private records + operator key + manager-call detection + PASS/FAIL judging in `records.py`, `operator.py`, `callers.py`, `verdicts.py`; quota/ledger/graphs/study), UI in `static/`; Mission Control groups checked work over tasks | `docs/AGENT_OFFICE.md` (sections: setup, safety, providers, missions/capsules, ledger, gotchas); page check `scripts/verify-agent-office-ui.py` (headless Chrome). Bounded India AV research dispatch: `docs/INDIA_AV_{OFFICE_BRIEF.txt,RESEARCH_PLAN.md}`, `scripts/start-india-av-research.sh`. All Agent Office work happens here and nowhere else |
| ROS 2 panel (top bar, left of Network) | `shell/adaptive-shell@local/rosPanel.js` (New package dialog: `rosPackageWizard.js`, pure logic `rosPackageModel.js`; packages only in `~/ros2_ws/src`), helper `shell/adaptive-shell@local/tools/ros_info.py` (setup from the login shell's rc files, supervised launches, colcon builds and rosbag, launch-argument forms, robot and parameter profiles, live `watch` over stdin/stdout with health, confirmed writes and streamed plots/goal feedback); palette `ros` mode in `apps/adaptive-command/modes.py` | `docs/ROS2_PANEL.md`; checks `scripts/verify-ros-panel.py` (real nodes), `scripts/verify-ros-package-create.py` (every template built and run), `scripts/verify-ros-package-model.js`, `scripts/verify-ros-controllers.py` (fixture manager; sourced ROS + controller messages), `scripts/verify-ros-nested.sh` |
| System monitor panel (top bar, next to ROS 2) | `shell/adaptive-shell@local/systemPanel.js`, `telemetry.js`, helper `tools/gpu_sampler.py` | CPU/GPU (Intel and NVIDIA), memory, disks, network, thermals and processes; polls only while open |
| Screenshot annotate / screen text | `apps/adaptive-annotate/`, `shell/.../screenText*.js` | |
| Design system | `tokens/adaptive.tokens.json`, `theme/`, `icons/`, `design/` | `docs/DESIGN_SYSTEM.md` |
| systemd units, autostart | `services/*.service`, `*.timer` | |
| Machine repairs | `scripts/fix-antigravity-login.py` (Antigravity IDE 2.5.5 keeps its login; checks by default, `--apply` / `--restore`) | |
| Install/uninstall pieces | `scripts/install-*.sh`, run in order by `./install.sh` | |
| New machine from nothing | `bootstrap.sh` (apt, Files fork build, session, `install.sh`, link extras, first-login `--finish`) | `docs/NEW_MACHINE.md`. Writes GNOME settings with `DCONF_PROFILE=adaptive` only |
| Permanent handoff / retirement | `scripts/zero-state-protocol.sh` | Read-only plan by default; external boot, exact disk confirmation, and a supported sanitization method are required to execute. See `docs/ZERO_STATE_PROTOCOL.md`. |

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
- No fixed paths to the checkout or a home folder. Scripts source `scripts/adaptive-paths.sh` and use
  `$ADAPTIVE_REPO`; Python uses `Path(__file__)`; the shell uses `adaptivePaths.adaptiveDir()`; units and
  desktop entries hold `@ADAPTIVE_REPO@` and are installed with `adaptive_render`.
- Normal Ubuntu must stay selectable in GDM and stock Nautilus stays installed. Recovery:
  `gnome-extensions disable adaptive-shell@local`; `docs/RECOVERY_RUNBOOK.md`.
- Never restart the user's shell from a script unless asked; `install.sh` never does.
- Repo conventions (single `master` branch, commit identity, commit cadence, UI palette, Files
  inspector scope) are in this repo's memory: `memctl read`.

<!-- map-check: commit=002dbb05f4f4 time=1793111875 -->
