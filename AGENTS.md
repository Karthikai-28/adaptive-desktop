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
| Shade (date menu) | `shade.js` (clock, uptime; no Activity Center or physical-checks line since 2026-11-12), `notifications.js` (per-app groups and durable arrival ledger; order/journal logic in `notificationOrder.js`) | `docs/NOTIFICATION_FOCUS_POLICY.md`; checks `scripts/verify-notification-order.js`, `verify-dynamic-island.js`, `verify-island-frontend.js` (all in `verify-all.sh --quick`) |
| Command palette (Alt+Space) | `apps/adaptive-command/` | answers in `providers.py`, prefix modes (`snip`, `todo`, `git`, ...) in `modes.py` |
| Terminal (KTERM modern profile) | `terminal/launcher.py`, `scripts/install-terminal.py`; agy/claude apps: `terminal/agent.py` (`adaptive-agent`, private tmux server `adaptive-agents`, `agents.tmux.conf`, `terminal/icons/`) | `./install.sh --only terminal`; user defaults, legacy command aliases and Antigravity profiles, and the colour scheme (the tokens' `terminal` section replaces KTERM's Catppuccin in the profile, prompts and shell); `scripts/verify-terminal.py`, `scripts/verify-agent-apps.py`. An agent app is one session shared by the laptop terminal and the phone session, always in the laptop's environment |
| Files (forked Nautilus 42.6) | `extension/adaptive_files/` (inspector side panel, Python), `extension/preview.css` (Files-only sheet: liquid glass window, floating sidebar/inspector panes), fork build in `.local/adaptive-nautilus*`; the glass behind the window is the shell's `windowGlass.js`: the wallpaper blurred once into `~/.cache/adaptive-desktop/glass.png` by `tools/glass_wallpaper.py` (no live blur; Home uses the same picture), checked by `scripts/verify-window-glass-nested.sh` | routing: `scripts/adaptive-files-dispatch.sh`; architecture rule: `docs/UBUNTU_FILES_PARITY.md` |
| Cast (wireless display to the TV) | `apps/adaptive-cast/`: `controller.py` drives one cast for every caller (window `window.py`, `main.py` command line, `Super+K`, palette `cast` mode, Files "Play on the TV", phone actions); `p2p.py` Wi-Fi Direct, `session.py` RTSP on :7236, `wfd.py` pure protocol, `stream.py` pipeline + cairo overlays, `tv.py` webOS pairing/wake/remote, `media.py` + `player.html`/`wall.html` media on the TV's browser, `audio.py`, `desk.py`; shell side `castStatus.js` (Control Center tile, island activity) | `docs/CAST.md` (gotchas: encoder, X connections, DLNA); `./install.sh --only cast`; check `scripts/verify-cast.py`; state in `$XDG_RUNTIME_DIR/adaptive-cast.json` |
| Adaptive Home (launcher installed on the LG TV) | `apps/adaptive-tv/`: `app/` page (`home.js` UI, `model.js` pure tiles/favourites/arrow navigation), `service/` webOS JS service (`service.js` methods, `ssap.js` plain-Node WebSocket to the TV's own `wss://127.0.0.1:3001`); manual launch only from LG Home or an explicit install/launch command | `docs/TV_HOME.md`; `scripts/install-tv-home.sh [--setup|--check]` (TV needs LG Developer Mode; not in `install.sh`); check `scripts/verify-tv-home.js` |
| Settings | `apps/adaptive-settings/` (Adaptive-only sections); `fingerprint_ui.py` enrolls/tests multiple fingers with fprintd, `fingerprint_visual.py` draws scan-driven progress; status and guarded PAM setup in `scripts/fingerprint.py`; rest is skinned gnome-control-center 41.7 | `docs/FINGERPRINT.md`; `verify-fingerprint.py`, `verify-fingerprint-ui.py` (virtual display) |
| Project context (D-Bus) | `services/project-context/main.py` | |
| Phone link | daemon `services/adaptive-link/` (`server.py` + one module per feature; `ai_usage.py` projects the shell's plan-limit snapshot without local paths; `zero_state.py` records a phone arm request only), Android app `apps/adaptive-link-android/` (Kotlin, Gradle); continuity/navigation state is in `ContinuityState.kt`, protected typed clipboard + focused send action in `ClipboardSync.kt` / `ClipboardSendActivity.kt`, launcher grid, dock and icon tiles are in `HomeGrid.kt` (sizes in `HomeMetrics`, unit-tested), AI usage is on Mobile Desktop Home and in `UsageWidget`, and full-screen trackpad/Ink Studio is in `RemoteScreens.kt` / `InkStudio.kt`; phone session apps share the laptop's profiles and keyring (`secrets_bridge.py`, one running copy: `mobile_launch.holders`) and are drawn at the phone's size and scale: `phone_form.py` (laptop), `LaptopApps.kt` (home-screen shortcuts, Laptop apps widget) and `Motion.kt` (phone) | `docs/ADAPTIVE_LINK.md`, `docs/PHONE_TRACKPAD_AND_INK.md`; phone appearance in `LinkDesign.kt`, island setup in `IslandUI.kt`, Android overlay in `IslandOverlay.kt` (owned by `NotificationRelay`), usage parsing/cache in `UsageState.kt`, widget work in `WidgetRefreshJob.kt`; `scripts/verify-link-island.sh` covers lint and real widget rendering |
| Device retirement | `scripts/zero-state-protocol.sh`, with guard test `scripts/verify-zero-state-protocol.sh` | `docs/ZERO_STATE_PROTOCOL.md`; external boot only, never remotely erases storage |
| Agent Office (AI company, :8790) | `services/agent-office/`: `server.py`, `office/*.py` (`manager.py`, providers, `mission_templates.py`, `capsules.py`, `evidence.py`; workflow/audit/retention/ROS comparison in `workflows.py`, `audit_export.py`, `retention.py`, `ros_compare.py`; private records + operator key + manager-call detection + PASS/FAIL judging in `records.py`, `operator.py`, `callers.py`, `verdicts.py`; quota/ledger/graphs/study), UI in `static/`; Mission Control groups checked work over tasks | `docs/AGENT_OFFICE.md` (sections: setup, safety, providers, missions/capsules, ledger, gotchas); page check `scripts/verify-agent-office-ui.py` (headless Chrome). Bounded India AV research dispatch: `docs/INDIA_AV_{OFFICE_BRIEF.txt,RESEARCH_PLAN.md}`, `scripts/start-india-av-research.sh`. All Agent Office work happens here and nowhere else |
| Mario (assistant: Home on Super+H, Super+J panel, :8791) | `services/mario-hub/` (`hub.py` aiohttp server + WebSocket, `collectors.py` per-card readers, `brain.py` pure decisions: instant answers, answer vs hand-off, hand-off limits, Next step; `voice.py` bounds native microphone sessions and `voice_transcribe.py` runs local recognition; `engines.py` who answers: Claude, Gemini (agy) at Claude's limit, LOOM/Ollama last; `config.py` + `~/.config/adaptive-desktop/mario.json`), page `apps/mario-home/static/` (edit `home.src.css`), host `apps/mario-home/host.py` (Home is a dock-type layer over the work area, loaded hidden at login, shown by `scripts/adaptive-home.sh` over D-Bus; one WebKit view per tab from `"tabs"` in `mario.json`; Adaptive session only; `--panel` toggles) | `docs/MARIO.md`; `scripts/install-mario.sh [--status]` (`./install.sh --only mario`), Super+J in `install-keybindings.sh`; checks `scripts/verify-mario.py`, `verify-mario-voice.py`, `verify-mario-ui.py`; voice setup: `scripts/install-mario-voice.sh`. Answers: Claude first, Gemini when Claude is at its limit, LOOM/Ollama only offline; code hand-offs run only after Run |
| ROS 2 panel (top bar, left of Network) | `shell/adaptive-shell@local/rosPanel.js` (New package dialog: `rosPackageWizard.js`, pure logic `rosPackageModel.js`; packages only in `~/ros2_ws/src`), helper `shell/adaptive-shell@local/tools/ros_info.py` (setup from the login shell's rc files, supervised launches, colcon builds and rosbag, launch-argument forms, robot and parameter profiles, live `watch` over stdin/stdout with health, confirmed writes and streamed plots/goal feedback); palette `ros` mode in `apps/adaptive-command/modes.py` | `docs/ROS2_PANEL.md`; checks `scripts/verify-ros-panel.py` (real nodes), `scripts/verify-ros-package-create.py` (every template built and run), `scripts/verify-ros-package-model.js`, `scripts/verify-ros-controllers.py` (fixture manager; sourced ROS + controller messages), `scripts/verify-ros-nested.sh` |
| System monitor panel (top bar, next to ROS 2) | `shell/adaptive-shell@local/systemPanel.js`, `telemetry.js`, helper `tools/gpu_sampler.py` | CPU/GPU (Intel and NVIDIA), memory, disks, network, thermals and processes; polls only while open |
| Phone (the paired Android phone and its apps in windows here) | `apps/adaptive-phone/phone.py` (`adaptive-phone`; scrcpy pinned in `.local/scrcpy` by `scripts/install-phone.sh`, adb from `.local/android-sdk`), palette `phone` mode in `apps/adaptive-command/modes.py` | `./install.sh --only phone`; `scripts/verify-phone.py`; falls back to Adaptive Link's `phone_screen.py` without adb |
| Screenshot annotate / screen text | `apps/adaptive-annotate/`, `shell/.../screenText*.js` | |
| Design system | `tokens/adaptive.tokens.json` is the only place a colour, radius or duration is defined; `scripts/build-tokens.py` (library `scripts/adaptive_tokens.py`) writes every stylesheet from it: each `*.src.css` → the `.css` beside it (shell, Files, Mario Home, Agent Office, TV page, GTK apps) and `theme/Adaptive` through `build-adaptive-theme.py`. Code that draws by itself reads generated modules: `shell/adaptive-shell@local/designTokens.js` (colours and animation durations for the shell's JavaScript) and `extension/adaptive_files/design_tokens.py` (the Files extension, incl. its terminal). **Edit the `.src.css`, never the generated `.css`.** `icons/`, `design/`; file/folder icons are generated by `scripts/build-file-icons.py` (never hand-edit `icons/AdaptiveFilesIcons/scalable/{places,devices,mimetypes}`), MIME types for them in `icons/adaptive-files-mime.xml` | `docs/DESIGN_SYSTEM.md` (palette tables generated into it), `design/ICON_FAMILY.md`; guard `scripts/build-tokens.py --check` in `verify-all.sh --quick`: no hand-written colour beyond `tokens/handwritten-colours.json`, which only shrinks |
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
./scripts/build-tokens.py                 # tokens -> every stylesheet (after editing a *.src.css or the tokens)
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

- Colours are named, never written: `$role` or `$hue/alpha` in a `*.src.css`, `adaptive_tokens.load()` in Python.
  The quick check fails on a hand-written colour. `docs/DESIGN_SYSTEM.md`.
- One shell extension only (`adaptive-shell@local`). Do not recreate the retired v16 duplicate.
- No fixed paths to the checkout or a home folder. Scripts source `scripts/adaptive-paths.sh` and use
  `$ADAPTIVE_REPO`; Python uses `Path(__file__)`; the shell uses `adaptivePaths.adaptiveDir()`; units and
  desktop entries hold `@ADAPTIVE_REPO@` and are installed with `adaptive_render`.
- Normal Ubuntu must stay selectable in GDM and stock Nautilus stays installed. Recovery:
  `gnome-extensions disable adaptive-shell@local`; `docs/RECOVERY_RUNBOOK.md`.
- Never restart the user's shell from a script unless asked; `install.sh` never does.
- Repo conventions (single `master` branch, commit identity, commit cadence, UI palette, Files
  inspector scope) are in this repo's memory: `memctl read`.

<!-- map-check: commit=1eadf9d98cd0 time=1793125087 -->
