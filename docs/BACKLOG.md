# Product Backlog

Status:

- ✅ Done
- 🟡 In progress / partial
- ⬜ Not started
- 🔬 Needs verification
- ⚠️ Safety-critical

## Milestone 0 — Baseline and recovery

### Done

- ✅ Captured Ubuntu baseline.
- ✅ Confirmed Ubuntu 22.04.5 LTS.
- ✅ Confirmed GNOME Shell 42 and GDM.
- ✅ Confirmed Intel iGPU and 16 GB RAM.
- ✅ Freed disk space to approximately 41 GB.
- ✅ Created `~/adaptive-desktop`.
- ✅ Initialized Git repository.
- ✅ Backed up initial GNOME/dconf state.
- ✅ Defined normal Ubuntu as mandatory fallback.

### Remaining

- ✅ Add dedicated recovery runbook.
- ✅ Add environment verification script.
- ✅ Add stable Git checkpoint tags.
- 🔬 Test recovery from TTY.

## Milestone 1 — Separate Adaptive session

### Done

- ✅ Created `Adaptive Desktop` GDM entry.
- ✅ Adaptive Desktop appears in the gear menu.
- ✅ Successfully logged into Adaptive Desktop.
- ✅ Wrapper reuses Ubuntu's existing GNOME session.
- ✅ Created isolated dconf profile.
- ✅ Normal Ubuntu remains available.

### Remaining

- ✅ Verify normal Ubuntu never inherits Adaptive settings.
- ✅ Add automatic session validation script.
- ✅ Add uninstall/recovery documentation.

## Milestone 2 — Shell

### Done

- ✅ Created `adaptive-shell@local`.
- ✅ Added repo-to-live sync script.
- ✅ Added Adaptive top-bar identity.
- ✅ Added `PROJECT · NONE` placeholder.
- ✅ Added navigation rail.
- ✅ Replaced letter placeholders with symbolic icons.
- ✅ Added Projects overlay.
- ✅ Added Workspaces overlay.
- ✅ Added Command overlay.
- ✅ Added System Center overlay.
- ✅ Hidden stock GNOME left panel content.
- ✅ Hidden stock GNOME date menu.
- ✅ Disabled Ubuntu Dock only in Adaptive Desktop.

### In progress

- ✅ Replace the left rail with a centered bottom application dock.
- ✅ Dock shows GNOME favorites plus running non-favorite applications.
- ✅ One icon per application; running-window count is shown with dots.
- ✅ Right-click supports Keep in Dock / Remove from Dock and window actions.
- ✅ Hover magnification animates the active icon and its nearest neighbors.
- ✅ Home, Workspaces, Command and System controls are not permanent dock items.
- ✅ Command remains available from the global keyboard shortcut.
- ✅ Keep stock top-right controls until System Center is functional.

### Acceptance criteria

- dock centered on the bottom edge;
- favorites persist through the normal GNOME favorites backend;
- running apps appear once even with multiple windows;
- Files uses one dock icon with per-window indicators;
- maximized/tiled windows do not overlap the dock;
- hover magnification is smooth and restrained;
- Applications button opens the full app grid.

## Milestone 3 — Project Context Service

- ✅ Define project registry schema.
- ✅ Persistent registry.
- ✅ Add folder as project.
- ✅ Remove project.
- ✅ Rename project display name.
- ✅ Active project state.
- ✅ Recent projects.
- ✅ Pinned folders.
- ✅ Project actions.
- ✅ Optional accent.
- ✅ Update top bar dynamically.
- ✅ Make Projects overlay data-driven.
- ✅ No-project state.
- ✅ Verify service autostart inside Adaptive Desktop.
- ✅ Verify shell DBus updates after extension reload.

## Milestone 4 — Workspaces

- ✅ Read GNOME workspace state.
- ✅ Workspace switch UI.
- ✅ Project-to-workspace mapping.
- ✅ Restore project workspace.
- ✅ Remember window placement where safe.
- 🔬 Workspace overview redesign.
- ✅ Keyboard shortcuts.
- 🔬 Multi-monitor behavior.
- ✅ Reduced-motion behavior.

## Milestone 5 — Universal Command

One surface: the palette app. Alt+Space opens it; the permanent dock no longer
contains a Command icon. Search lives in the app process, never in the shell.

- ✅ Palette redesigned to the Command screen in the design system.
- ✅ Searches apps, files, folders, projects, settings and desktop actions.
- ⬜ Space Grotesk is not installed on this machine, so the palette falls back
  to Ubuntu. `sudo apt install fonts-space-grotesk` if it should match the
  design typeface exactly.
- 🔬 plocate's index is rebuilt daily and was two days stale when tested. A
  live home walk covers recent files; `sudo updatedb` refreshes the rest.
- ✅ Global shortcut.
- ✅ Application search.
- ✅ File/folder search.
- ✅ Project switching.
- ✅ Desktop actions.
- ✅ Settings search.
- ✅ Recent actions.
- ✅ Keyboard navigation.
- ✅ Extensible provider model.
- ✅ Permission/safety model.

## Milestone 6 — System Center

### Current

- ✅ First functional shell menu exists with volume, settings, lock, suspend, logout, and power actions.
- ✅ Read-only status rows refresh on open for network, Bluetooth, power, and audio output.
- 🔬 Audio output selection submenu exists and needs live device verification.
- 🔬 Restart and shut down entries use GNOME-native confirmation actions where available.
- ✅ Performance row shows load and memory summary.

### Required

- ✅ Network status.
- ✅ Bluetooth status.
- 🔬 Audio device selection.
- ✅ Audio output status.
- ✅ Volume.
- ✅ Battery/power status.
- ✅ Performance summary.
- ✅ Notifications/focus.
- ✅ Settings launcher.
- ✅ Lock.
- ✅ Logout.
- ✅ Suspend.
- 🔬 Reboot/shutdown confirmation.
- ✅ Return to Ubuntu.

⚠️ Do not remove GNOME top-right controls until these replacements work reliably.

## Milestone 7 — File Explorer

### Defined

- ✅ Ubuntu Files structure used as behavioral reference.
- ✅ Project-aware explorer concept defined.
- ✅ Full state list defined.

### Remaining

- ✅ Home/Recents.
- ✅ Project Files.
- ✅ Folder browse.
- ✅ Grid/list.
- ✅ Search/filters.
- ✅ Preview/Inspector.
- ✅ Split view.
- ✅ Multi-select.
- ✅ Transfers.
- ✅ Conflict resolution.
- ✅ Trash/recovery.
- ✅ Devices/network.
- ✅ Empty/error states.
- ✅ Linux permissions/hidden files.
- ✅ Decide Nautilus integration vs separate frontend.

### Current

- ✅ Forked Nautilus is the Adaptive session's file manager, activated the way
  Ubuntu activates its own. One instance, windows reused, no stock Nautilus
  being killed.
- ✅ Standalone GTK4 Adaptive Files app retired in favour of the fork.
- ✅ Nautilus native preview/inspector layer exists.
- ✅ Project registry format is understood by Adaptive Files.
- 🔬 Nautilus preview has a Project tab backed by Project Context Service.
- ✅ Files redesigned on the shared skin: Finder-style sidebar, path bar and
  selection; the inspector is one 260px column - preview and details for a
  selection, and for the current folder a kind breakdown, largest items,
  14-day activity, its project and a one-line disk bar.
- ⬜ Files window skinned to the Figma frames.

## Milestone 8 — Settings

Settings is `gnome-control-center` under our skin, not a reimplementation.
It is GTK3 on Ubuntu 22.04 (41.7), so the session GTK theme is what makes it
ours. The previous ✅ marks here described an 18-section launcher menu whose
sections mostly ran `gnome-control-center <panel>`; that app has been retired,
so the marks are restated against what is actually true.

- ✅ 18-section information architecture defined.
- ✅ Panels reachable from the rail and Command menu.
- ⬜ Settings skinned to the Figma frames.
- ✅ Adaptive-only sections have a home: **Adaptive Settings**
  (`apps/adaptive-settings`, installed by `install-adaptive-settings.sh`).
  `gnome-control-center` has no panel for them, so they sit beside it, not in
  it. Like the Shade it reimplements nothing; every control is a view onto a
  backend that already exists:
  - *Projects & Workspaces*: the registry over the Project Context Service's
    D-Bus API (add, rename, remove, make active, workspace, focus profile),
    plus mutter's workspace count/dynamic/primary-only keys and Focus now.
  - *Search & Commands*: the `adaptive-*` shortcuts from
    `install-keybindings.sh`, editable, refusing any accelerator a
    window-manager or shell keybinding already grabs (the "Failed to grab
    accelerator" trap below); plocate index age with a rebuild; the overview's
    project search provider on/off.
  - *Updates & Recovery*: this checkout's branch and a fast-forward-only update
    that refuses a dirty or diverged tree; Ubuntu's pending update count;
    session facts from `session-cli.py`, Return to Ubuntu, the TTY recovery
    steps; the clamshell opt-in `adaptive-lid-watch.sh` reads; and the
    `record-live-verification.py` checks, recordable from a dropdown.
  - The Command palette lists all three sections.
    `verify-adaptive-settings.py` (in the stability suite) covers what needs
    no display; the window was exercised end to end under Xvfb against the real
    service. 🔬 Still to be clicked through in the live session.

## Milestone 9 — Notifications and Focus

- ✅ Notification center.
- ✅ Critical/normal policy.
- ✅ Focus profiles.
- ✅ Project focus profile. The preference was stored but nothing applied it;
  the Project Context Service now applies `metadata.focus` on every switch
  (same key as `focus-cli.py`), and a project with no preference leaves a
  hand-started focus session alone.
- ✅ Focus timer.
- ✅ Quiet/fullscreen behavior.
- ✅ Adaptive Shade. The notification center is now an Adaptive surface rather
  than restyled GNOME chrome: header, brightness/volume sliders, an eight-tile
  quick-toggle grid, and live system telemetry, stacked above GNOME's own
  message list. This is the `Notification Service` and `System Center` layers in
  `config/architecture.md` finally landing - and unlike the System Center that
  was removed at Milestone 6, it reimplements nothing: every tile and slider is
  a view onto a backend GNOME already owns. See `docs/NOTIFICATION_FOCUS_POLICY.md`.
- ✅ System telemetry. CPU load/frequency/package temperature, Intel GPU busy and
  clock, memory and swap, filesystem usage, every thermal sensor, battery and
  network throughput. Sourced from procfs and sysfs directly; polling runs only
  while the shade is open.
- ✅ Shade v2 — information center. Every control was removed: the tile grid,
  both sliders and the header's session buttons are gone and `tiles.js` is
  deleted. GNOME's aggregate menu already owned network, bluetooth, audio,
  brightness and power, and a second place to change them was a second thing to
  keep in sync. `verify-live-readiness.sh` now fails if a control reappears.
- ✅ Notifications grouped per application, Android-style, with a count badge and
  collapse past three. Cards are still `Calendar.NotificationMessage` over
  `MessageTray.Notification`, so only arrangement changed. Two fallbacks to
  GNOME's flat list: `~/.config/adaptive-desktop/shade.json`
  `{"notificationGrouping": false}`, and an automatic catch if the grouped
  section fails to build.
- ⬜ Calendar: an Adaptive month/agenda/week view was built over the date menu's
  existing event source and then **removed** — the stock GNOME calendar is what
  was wanted. `verify-live-readiness.sh` now fails if anything in the shell
  reaches into the event source, so this stays deliberate rather than drifting
  back. The constraint if it is ever revisited is recorded in the gotchas below.
- ✅ Show more/less on the system block. Summary — CPU, GPU, memory, disk,
  battery — always shows; core bars, load, swap, disk I/O, network,
  temperatures and processes fold away. Defaults to expanded and the choice is
  saved to `~/.config/adaptive-desktop/shade.json`. Collapsing also stops the
  `/proc` walk and the hidden-widget updates: 4.98 → 1.89 ms/s amortised, worst
  tick 19.7 → 2.9 ms.
- ✅ The shade scrolls instead of overflowing. The system block is sized against
  the monitor when the popup opens; only that block scrolls, because GNOME's
  message list already scrolls itself and nesting the two sizes neither.
- ✅ Typography. Inter installed to `~/.local/share/fonts`, and nothing in the
  shade is below 11px — v1.7 had fifteen rules at 8–9px on a 96 DPI screen with
  no scaling, which was the whole of the clarity problem.
- ✅ More metrics: top processes aggregated by command name, load average,
  uptime, disk read/write throughput, and per-interface network.

### Shade v3.1 — finish and harden (2026-10-20)

Telemetry moved to the System panel next to ROS 2; the Shade now holds the
Activity Center (the Dynamic Island's cards) above the grouped notifications.
The rule changed from "no controls" to "no duplicated system controls". All of
the items below pass in the nested-shell sandbox and the headless suites (now
part of `verify-all.sh --quick`). **None is verified live yet.**

- ✅ Notification order. Inside a group, urgent first and then newest first, so
  a collapsed group can no longer hide the message that just arrived behind
  three older ones. Groups move up when their app speaks again. The rule is in
  `notificationOrder.js`; `scripts/verify-notification-order.js` tests it.
- ✅ Per-app triage: Clear for one app, Expand all / Collapse all, a red dot on
  any group holding a critical notification, and a link to Settings →
  Notifications (GNOME 42 cannot open one app's page directly).
- ✅ Tasks card shows every running Agent Office task with its agent, step and
  age, the selected task's last four office events, and Cancel. The old card
  showed hard-coded sample output and a Pause button that did nothing; Agent
  Office has no per-task pause, so that button is gone. Cancel used GET and
  sent no `X-Office` header; Agent Office rejects both, so it now POSTs through
  curl with the header.
- ✅ Music card: cover art, elapsed and length, a scrubber sized to its track,
  click or ←/→ to seek, and a player switcher when more than one MPRIS player is
  open. It also fixes a live-only bug. GLib hands over MPRIS properties as
  variants and signals come from a player's unique bus name, so in the real
  shell the play state and title never updated (the headless mock passed plain
  values and hid this).
- ✅ Focus timer counts down to a wall-clock deadline that is saved to
  `~/.local/state/adaptive-desktop/focus-timer.json`, so suspend and a shell
  restart no longer lose or stretch a session. A focus session (not a break)
  turns Do Not Disturb on through `show-banners`, the key the Control Center
  tile and `focus-cli.py` use, and gives back the previous value afterwards
  unless the user changed it meanwhile. +5m and Stop redraw at once.
- ✅ Focus digest: when a session ends, "N notifications from M apps" that
  arrived during it, on the expiry alert and the Focus card.
- ✅ Overview tab (tightest AI limit, running tasks, current track, focus time
  left) and live tab badges (task count, ▶, countdown, ! on a tight limit).
- ✅ Accessibility: every card control takes keyboard focus and shows a focus
  ring, and icon buttons have accessible names. Nothing in the Shade or island
  blocks is below 11px; the readiness check now actually covers both blocks.
  Its old range began at a "Shade v2" heading that no longer existed, so it
  matched nothing and always passed.
- ✅ Less background work: the Shade clock ticks at the next second (or minute,
  when seconds are hidden) and reads uptime once a minute. The Activity Center
  is re-measured only when it changes size or the monitors change, not every
  second. Cards draw only while on screen, AI-usage rows rebuild only when they
  change, and the music scrubber's 1 s redraw runs only while it is visible and
  playing.
- ✅ The island mounts its cards with `Shade.mountActivityCenter()` /
  `unmountActivityCenter()` instead of writing into the Shade's private
  `_systemSection`.
- ⬜ Live check: notifications from two apps plus one critical; cancel a real
  Agent Office task; Spotify/Firefox art, seek and switch; a focus session
  across suspend and across `--restart-shell`. Record each one with
  `scripts/record-live-verification.py`.

### Shade v3.2 — correctness and idle-work pass (2026-10-20)

- ✅ Focus summaries now use a bounded durable arrival ledger, so withdrawn
  notifications still count and the marker survives a Shell restart. The file
  stores hashes rather than notification text. Restored sessions that expired
  while Shell was down also retain their digest.
- ✅ Recorder privacy is live rather than a test-only backend switch. Starting
  GNOME's recorder immediately projects already-surfaced and queued events,
  tasks, AI usage and media through redacted views; stopping restores the
  original state. GNOME cannot reliably observe arbitrary X11 application
  capture, so that remains outside the automatic guarantee.
- ✅ Tasks request `status=running` directly and render every result. Agent
  Office's WebSocket supplies task and log changes immediately; non-overlapping
  polling remains as fallback and consistency check. The Events API accepts a
  task ID so the card no longer downloads a task's full 400-event history for
  four lines. Visible ages and logs keep moving even when a task's step count
  is quiet.
- ✅ One-second timer ticks update state directly instead of occupying the
  eight-entry event queue. Start, pause, resume, digest and expiry remain real
  surfaced events.
- ✅ AI usage refreshes as soon as its card opens and watches the active Codex
  rollout, its session directory and Claude's local usage cache for changes.
  Visible fallback polling is 15 seconds for Gemini and missed file events,
  then switches to five minutes while the card and alert are hidden.
  A fresh lower reading automatically clears a previously sticky critical or
  caution alert, so the pill cannot keep displaying an obsolete percentage.
  Antigravity transcript monitoring is debounced, parses only appended records
  on the Shell thread and selects the newest transcript.
- ✅ Island attachment is transactional: a failure restores the clock, actors,
  providers and signal handlers before the extension drops the object.
- ✅ A notification whose urgency changes after creation is re-sorted and its
  application's critical marker is refreshed.
- ✅ Activity Center height uses the monitor work area and measured visible
  chrome instead of a fixed 260px reservation.
- ⬜ Live check the v3.1 list above plus start/stop GNOME screen recording while
  a task, quota alert and track title are visible.

## Milestone 10 — Window management

- ✅ Smart tiling.
- ✅ Split presets.
- ✅ Snapping.
- ✅ Project-aware placement.
- ✅ Visible open-window switching from the dock.
- ✅ Restore.
- ✅ Fullscreen behavior.
- ✅ Multi-monitor behavior.
- ✅ Overview integration.

## Milestone 11 — Lock/Login/Session

- 🔬 Adaptive lock treatment.
- 🔬 Login compatibility.
- ✅ Session status.
- ✅ Return to Ubuntu.
- ✅ Session save behavior.
- ✅ Failed-session recovery.

## Milestone 12 — Visual system completion

- ✅ Core palette defined.
- ✅ Initial shell CSS implemented.
- ✅ Tokenize colors/spacing.
- ✅ Final icon family.
- ✅ Typography scale.
- ✅ Motion tokens.
- ✅ Reduced-motion mode.
- ✅ High-contrast mode.
- ✅ Light-theme decision.
- ✅ Component/state inventory.

## Milestone 13 — Stability

- ✅ Shell smoke tests.
- ✅ No-extension fallback test.
- 🔬 GDM fallback test.
- ✅ Reboot test.
- 🔬 Suspend/resume test.
- 🔬 External monitor test.
- ✅ File transfer stress test.
- 🔬 Long-running shell memory test.
- ✅ Update compatibility check.
- ✅ Backup/restore test.

## Milestone 14 — One visual system over Ubuntu's apps

Direction: keep Ubuntu's engine and behaviour, own the appearance. Applies to
Files, Settings, and the top-right system panel alike.

- ✅ Forked Nautilus wired in as the session file manager.
- ✅ Bespoke Files and Settings apps retired.
- ✅ `theme/Adaptive` GTK3 theme importing Yaru-dark, then overriding it with
  `tokens/adaptive.tokens.json`, generated by `scripts/build-adaptive-theme.py`
  and applied through the Adaptive dconf profile only.
- ✅ `AdaptiveFilesIcons` inherits Yaru before Adwaita. Confirmed by testing:
  Yaru ships concrete folder, drive, pdf, image, text and home icons where
  Adwaita 42 does not.
- ✅ Settings carries the Adaptive palette — `gnome-control-center` renders
  90.8% `bg.canvas` with `surface.2` chrome, no CSS parse errors.
- ✅ Files window under the session theme. The separate AdaptiveFiles GTK
  theme is gone; Files uses theme/Adaptive plus extension/preview.css.
- ✅ theme/Adaptive imports Yaru-blue-dark through a gtk.gresource symlink,
  so widgets without an Adaptive rule look like Yaru, not raw GTK.
- ✅ Session font is Inter, the shell's typeface.
- ✅ Top-right panel restyled in shell CSS: the aggregate menu is the Adaptive
  Control Center (`controlCenter.js`, `.adaptive-cc*`), and the rail with its
  System button was replaced by the bottom dock, which has none - system
  controls live in one place.
- ⬜ Session wrapper reinstall (needs sudo) to pick up `XDG_DATA_DIRS`.
- ⬜ Frame-exact match to the Figma screens.

The token-driven baseline is built and applied. Exact frame matching is blocked
on `design/figma-exports/`, which still contains only its README — see §12 of
the handoff: do not mark the Figma-skin items complete without the exports.

## Milestone 15 — Daily-use features

Code complete and checked here without a display (`verify-shell-helpers.js`,
`verify-feature-logic.py`, `verify-adaptive-settings.py`, all in the stability
suite). The GTK parts (palette, quick note, Settings) were also driven under
Xvfb, and the palette against a stand-in that exports the shell's exact D-Bus
interface.

When this milestone was written GNOME Shell 42 could not be run where it was
built, so every shell-side item was marked 🔬. That has since changed:
`scripts/verify-shell-nested.sh` (Milestone 16) loads the extension into a
real nested GNOME Shell and exercises these items. Where an item below says
**runs in a real shell**, that is what it means: the code has run, on a
virtual display, in a sandbox. It is not the same as you using it in the live
session, so the 🔬 stays until the matching check in
`record-live-verification.py` is recorded.

The first nested run found that the top-bar project menu **could never
open**: `PopupMenu.open()` returns early on an empty menu, and the menu was
only filled as it opened. Fixed in `projectIndicator.js` (the menu is kept
filled). It had never run before, which is the point of the paragraph above.

- 🔬 **Shell bridge.** `org.adaptive.Shell` (shellActions.js), which already
  served the gesture daemon, now also lists and activates windows, switches
  workspace, serves and sets the clipboard history, parks and resumes
  projects, and starts screen text. Results are JSON; nothing passed in is
  evaluated. Runs in a real shell: every method, including refusing unknown
  actions, windows and workspaces.
- 🔬 **Clipboard history** (`clipboardHistory.js`). Text only, newest first,
  50 entries, memory only: never written to disk, gone at logout. Skips what
  password managers mark secret and anything copied while locked. Palette:
  type `clip` or `clip <text>`; "Clear Clipboard History" forgets it. Runs in
  a real shell.
- 🔬 **Project park / resume** (`projectSnapshots.js`). Parks every window on
  the project's workspace to `~/.config/adaptive-desktop/snapshots/<id>.json`
  and closes them politely. Windows with no app to relaunch are left open, never
  lost. Resume relaunches terminals in the project folder, Files and editors
  on the folder, everything else plain, and puts each window back. From the
  top-bar project menu or the palette. Runs in a real shell: a real window is
  parked, closed, relaunched and the snapshot cleared.
- 🔬 **Project in the top bar** (`projectIndicator.js`). The active project
  with live git status (`main ±3 ↑1 ↓2`), and a menu: terminal, Files, quick
  note, all projects, park/resume, project settings. The backlog's old
  `PROJECT · NONE` label no longer existed in code; this replaces it. Runs in
  a real shell, against a real repository, after the menu fix above.
- ✅ **Quick note** (`scripts/adaptive-quick-note.py`, Super+Alt+N). One line
  into `notes/<project>/Inbox.md`, the Projects app's notes folder.
- ✅ **Palette answers** (`apps/adaptive-command/providers.py`). Calculator
  (parsed, never `eval`'d, exponents bounded), unit conversion, `:emoji`,
  open windows by title, named workspaces, plus actions for park/resume,
  quick note, screen text and clearing the clipboard.
- ✅ **Named workspaces.** The Project Context Service names a project's
  workspace after it; a name you type (Settings → Workspace names) is never
  replaced, and a slot is emptied only if it still holds the service's name.
- 🔬 **Battery health** in the Control Center's power dropdown: wear %,
  cycles, and the charge limit if the firmware sets one.
- 🔬 **Copy text from screen** (`screenText.js`): area select, the shell's
  own screenshot, `tesseract` locally. Needs `sudo apt install tesseract-ocr`.
- 🔬 **Phones** in the Network panel (`tools/phone_info.py`): KDE Connect or
  GSConnect devices, battery (KDE Connect), Ring and Send file.
- 🔬 **Crash watchdog** (`watchdog.js`). Three desktop starts in ten minutes
  without five minutes of uptime and the extension stands down to stock GNOME
  with a notification. Clean disables and `reload-adaptive-shell.sh` restarts
  never count. Settings → Updates & Recovery shows it and re-arms it. Runs in
  a real shell: a clean disable clears the record, a tripped state leaves
  stock GNOME in place, and re-arming brings the desktop back.
- ✅ **Physical checks in the Shade.** A status line, not a control:
  "N of M physical checks done", hidden once all pass.
- ✅ Per-app volume was proposed but already existed (Control Center → Sound
  → Apps); nothing was added.
- ✅ `verify-live-readiness.sh`'s "the shade holds no controls" check scanned
  every module, so it had failed since the Control Center landed. It now
  scans the shade's own modules, which is what it protects.

## Milestone 16 — Verification you can run, structure, and the next daily-use features

### Verification

- ✅ **The extension in a real GNOME Shell** (`scripts/verify-shell-nested.sh`).
  A nested `gnome-shell` on a virtual X display with its own session bus,
  HOME, runtime directory and dconf, so it cannot reach the session you are
  in. It enables the extension, opens every panel menu and every Control
  Center dropdown, drives the bridge, the clipboard, the project indicator,
  park and resume with a real window, the drop-down terminal, lock and unlock,
  and the watchdog, disables and re-enables it, and fails on any JS error in
  the shell's log. A sandbox-only probe extension (`scripts/nested-probe/`)
  lets the check look inside the shell; it refuses to start anywhere else.
- ✅ **The palette and Annotate windows** on a virtual display
  (`verify-palette.py`, `verify-annotate.py`): the real GTK windows, typed
  into and read back, against the Project Context Service on a private bus.
- ✅ **Files with the inspector** (`verify-files-inspector.py`): the real
  Nautilus fork, the inspector loaded from the repository, the selection
  walked across one file of each kind. Its first run found the Share and Tags
  context menu **failed entirely on any machine without Slack**:
  `Gio.DesktopAppInfo.new()` raises for a missing app in Python rather than
  returning None. Fixed in `adaptive_files/share.py`.
- ✅ **Static checks for what a GJS module cannot tell you until it runs**:
  `verify-shell-methods.py --class` (a method called across the files of one
  class), `verify-shell-imports.py` (a helper taken from another module that
  no longer exports it - which is what moving a function breaks, and no
  linter sees), and ESLint `no-undef` (`config/eslint-shell.json`).
- ✅ **One command**: `scripts/verify-all.sh` (`--quick` skips the
  sandboxes). `.github/workflows/checks.yml` runs it on every push.
  🔬 The workflow has not run on GitHub yet; the script it calls passes here.
- ⬜ What still needs a person at the machine is unchanged and is listed by
  `record-live-verification.py status`: TTY recovery, GDM fallback, reboot,
  suspend/resume, external monitor, audio output switching, a paired phone,
  and screen text (needs `tesseract-ocr`).

### Structure

No behaviour changed in these; each was a move of whole methods, checked by
comparing the set of methods before and after and by the sandboxes above.

- ✅ `extension.js` (4,557 lines, one class) is now `extension.js` (the
  object and its lifecycle) plus `shellLock.js`, `shellDock.js`,
  `shellDockFeatures.js`, `shellDockDnd.js`, `shellDockAutohide.js` and
  `shellDisplays.js`. Their methods are copied onto the one class, so `this`
  is the same object everywhere.
- ✅ `controlCenter.js` (4,138 lines) is now `controlCenter.js` plus
  `ccNetwork.js`, `ccBluetooth.js`, `ccMedia.js`, `ccSystem.js`, with the
  shared helpers in `ccUtil.js`. Three panels were taking `makeRow` and
  `makeHeading` from `controlCenter.js`; the nested shell caught that when
  their menus opened, and `verify-shell-imports.py` exists because of it.
- ✅ `adaptive_preview.py` (4,566 lines) is now the extension classes and the
  controller's lifecycle, with its methods in
  `adaptive_files/inspector_{host,folder,file,info,widgets}.py` as mixins and
  the shared pieces in `adaptive_files/common.py`.
- ✅ `./install.sh` runs the per-part installers in order; `--status` says
  what is installed and what is out of date, changing nothing. `./uninstall.sh`
  is the other direction (`--dry-run` first) and leaves your data alone.
- ✅ Repository: bytecode and the `.before-*` backup copies are no longer
  tracked; `scripts/adaptive-backup.py dconf-snapshot` makes a full dconf dump
  with accounts, calendars, contacts and any value holding an address removed,
  for `backups/`.
- ⬜ The two KTERM installers under `terminal/` differ by three lines but are
  self-contained on purpose (each is run on its own on a new machine), so
  they were left as they are.

### Projects

- ✅ **Git status of every project.** `project-cli.py git`, and `git` in the
  palette: work to commit, push or pull first.
- 🔬 **Time per project.** The Project Context Service counts a minute
  towards the active project while you are at the machine (not idle five
  minutes, not locked). `project-cli.py time`, `time` in the palette. Needs
  the service restarted to start counting.
- ✅ **Startup commands.** `project-cli.py startup add [--background] <cmd>`;
  run when the project is resumed, or from its menu. Runs in a real shell.
- ✅ **Inbox as tasks.** Every quick note is a task; `todo` in the palette
  lists the open ones and Enter ticks one (`- [x]` in the same file).
  `project-cli.py tasks`.
- ✅ **Templates.** `project-cli.py new <folder> --template python|web|writing`
  or `new` in the palette; your own go in
  `~/.config/adaptive-desktop/project-templates/`. Nothing existing is
  overwritten and nothing is created outside the folder.

### Command palette

- ✅ **Modes** (`apps/adaptive-command/modes.py`): `snip`, `todo`, `git`,
  `time`, `/text` or `grep`, `kill`, `ssh`, `branch`, `timer`, `keys`, `new`.
  A mode word has to stand alone, so `github` is still an ordinary search.
  Each is also offered by name ("Snippets", "Keyboard Shortcuts").
- ✅ **Your own commands**: executables in
  `~/.config/adaptive-desktop/commands/` (see `COMMAND_PERMISSION_MODEL.md`).
- ✅ **Fresh file search.** `scripts/adaptive-index.sh` keeps a private
  plocate database of your home folder, rebuilt every fifteen minutes by a
  user timer (`install-file-index.sh`); the palette searches it as well as
  the system one. Not installed until you run the installer.
- 🔬 **Clipboard pins and images.** Ctrl+P pins the selected entry: it is kept
  when the history fills up and when it is cleared. The last five copied
  images are kept and copied back by id. Still memory only. Runs in a real
  shell; pasting an image into another app is the live part.

### Desktop

- 🔬 **Drop-down terminal** (`dropdownTerminal.js`, Super+Return). Terminator
  if installed, otherwise GNOME Terminal, in the active project's folder.
  Runs in a real shell with GNOME Terminal on Wayland; Terminator on X11, and
  finding the window again by role after a shell restart, are the live part.
- 🔬 **Annotate a screenshot** (`apps/adaptive-annotate`, Super+Shift+S).
  Arrow, box, pen, highlight, redact, text; copy or save. The window is
  driven in a sandbox; the area capture (`gnome-screenshot --area`) is live.
- ✅ **Keyboard shortcuts** (`keys` in the palette, Super+/), read from
  gsettings so an edited shortcut shows as it is.
- 🔬 **Power profile follows the charger** (`adaptive-power-auto.py`). Off
  until `--enable`. Touches no suspend, lid or blanking setting. Not run
  through a plug/unplug.
- 🔬 **Send clipboard to phone** (Network panel, palette). Needs a paired
  phone to try.
- ✅ **Settings export / import** (`adaptive-backup.py export|import|show`).
  A named list of files and GNOME keys, not a dump; import keeps what it
  replaces.
- ✅ **AMD sensors** in the Shade: `k10temp`/`zenpower` CPU temperature,
  `amdgpu` busy percentage and temperature. 🔬 Untested: this machine is
  Intel. An NVIDIA-only machine still shows no GPU row (it needs
  `nvidia-smi`).

### Looked at and not built

- **Display profiles.** Mutter already remembers a layout per set of
  connected monitors (`~/.config/monitors.xml`) and Super+P switches mirror /
  extend / single. A second copy would be a second thing to keep in sync.
- **Battery charge limit control.** This machine's firmware exposes no
  `charge_control_end_threshold`, so there is nothing to set. The Control
  Center still shows a limit where the firmware has one.
- **Continuous clipboard sync and notification mirroring to a phone.** Both
  are settings of KDE Connect and GSConnect themselves.
- **GNOME 45+ and Wayland.** Assessed, not started: `docs/GNOME_PORT.md`.

## Milestone 17 — Adaptive Link: the computer from your phone

Everything about it, and its security model, is in `docs/ADAPTIVE_LINK.md`.

- ✅ **Daemon** (`services/adaptive-link/`). Mutual TLS to one paired phone;
  nothing listens until one is paired. Screen as JPEG frames, pointer and
  keyboard, commands, files, clipboard, media (MPRIS), volume, power, phone
  notifications, phone camera into a v4l2loopback device. Private addresses
  only. An audit log. `scripts/link-cli.py`.
- ✅ **Pairing**: a QR code for two minutes, six digits compared on both
  screens, the owner's confirmation on the computer.
- ✅ **Android app** (`apps/adaptive-link-android/`, Kotlin and Compose). Key
  in the hardware keystore, the computer's certificate pinned, locked behind
  fingerprint or screen lock. Screen, Trackpad, Media, Presenter, Run, Files,
  Webcam, More.
- ✅ **Checked without a phone**: `verify-link.py` (the daemon against a
  phone and three intruders) and `verify-link-android.py` (the app on an
  emulator: keystore, pairing, mutual TLS, every screen opened, a command
  typed on the phone).
- 🔬 **Your own phone on Wi-Fi.** Not yet installed on a real device.
- 🔬 **Your own Google project.** Sign-in and away access need a free
  Firebase project (`docs/ADAPTIVE_LINK.md`, *Your Google project*) and its
  five values given to `link-cli.py setup` and the app's `cloud.properties`.
- 🔬 **Phone camera as webcam.** Written, never run: the virtual camera needs
  `scripts/install-link-camera.sh` (sudo), and the emulator's camera is not a
  test of a real one. Phone notifications on the computer are in the same
  state: the request is checked, the listener service needs a real phone.
- ✅ **Sign in with Google instead of pairing.** The computer signs in by a
  code entered at google.com/device (`link-cli.py signin`), the phone with
  Android's account picker. Both meet in a database in the owner's project
  that only that account can read; the phone asks from there with no pairing
  code, and the owner approves once on the computer (or automatically with
  `allow auto-approve on`). The account lets a device ask; the phone's
  hardware key is still what the computer trusts.
- ✅ **Away, directly.** With no address of the computer answering, the phone
  and the computer open a direct connection to each other (WebRTC, set up
  through the account) and the link runs inside it unchanged. No open port,
  no relay, and only the link's port is reachable through it. A private
  network between the devices (Tailscale) was tried first and removed: run
  without root it handed every allowed port to the computer's loopback, so
  services bound to localhost became reachable from the other devices.
  Checked against a stand-in for Google in `verify-link.py`, and with the
  app's own code and screens on an emulator. 🔬 Google's real sign-in, and a
  direct connection from mobile data, are the remaining checks.
- ✅ **The machine itself, from the phone.** Tasks (processes, priority,
  battery, temperatures, power profile), Devices (USB on and off, drives
  mounted, unmounted and safely removed), Network (Wi-Fi, joining, VPNs),
  Bluetooth, Display and sound devices, Services, Windows, and the desktop's
  own features. A change that could cut the phone off is undone unless the
  phone comes back to keep it. Checked against stand-ins for NetworkManager,
  UDisks, BlueZ, PulseAudio, systemd and the power profiles
  (`scripts/fake_system_tools.py`). 🔬 The real ones.
- ✅ **The screen as video, with sound.** H.264 or VP8 and Opus over a media
  connection set up through the link (`media.py`), with JPEG frames as the
  fallback. Checked with a second WebRTC peer in `verify-link.py`, with the
  app's own decoder on an emulator, and by hand against this machine's real
  screen and sound. 🔬 Sound on a real phone.
- ✅ **Without being asked.** The computer's alerts (disk, memory, battery,
  heat, devices, failed services, a finished command) and its notifications
  on the phone; share to the computer from any app; a home-screen widget and
  quick-settings tiles for lock, media and focus; commands kept as buttons.
  🔬 The widget and tiles on a real home screen.
- ✅ **Several devices**, up to five, each of which can be allowed less than
  the others (`link-cli.py phone NAME deny exec`).
- ✅ **Waking it** (`link-cli.py wake on`, wake-on-LAN, its own network only)
  and **a relay of your own** (`link-cli.py relay`, a TURN server) for
  networks that forbid direct connections. 🔬 Both written and checked only
  as far as their settings go: neither a sleeping computer nor a relay was
  available to try.
- ✅ **The phone and the computer together** (`companion.py`): the clipboard
  both ways, the computer locking when the phone leaves and unlocking on its
  fingerprint, sudo approved by the phone (a signature root checks for
  itself, `scripts/link-approve.py`), calls and texts on the computer and a
  text sent from it, making the phone ring, its battery and signal, new
  photos copied over. 🔬 sudo through PAM and the proximity lock on a real
  network.
- ✅ **More of the phone used**: its microphone as a microphone on the
  computer, a document scanner, the phone aimed as a pointer, dictation, NFC
  tags that press the owner's own buttons, a game pad, a page of the owner's
  own controls, several computers, a two-pane layout on tablets, one display
  or the phone as another. 🔬 Everything an emulator has no hardware for.
- ✅ **One way in, and what comes after features** (`docs/SUPERPOWERS.md`):
  asking in ordinary words from the phone, `link-cli.py ask` and the palette;
  undo; chains; scenes; plug-in actions; `link-cli.py doctor`; state pushed
  to open screens; pairing by being near; an outbox on the phone.
- ✅ **Both ways with the screen.** The phone's screen in a window on the
  computer and used from it (`phone_screen.py`), and the phone as another
  display through a display made for it (`virtual_display.py`). 🔬 The
  second needs `scripts/install-link-display.sh` (sudo) and has not run: the
  laptop's own driver will not light an empty output, which was tried.
- ✅ **Four home-screen widgets**: quick actions, status, media, the owner's
  own buttons.
- ✅ **Every app from the phone, with buttons of your own**
  (`app_workspace.py`, `control_profiles.py`, the app's Apps screen). The app
  grid on the phone; an app opened into a workspace of its own, moved to the
  phone's display where there is one and a crop that follows its window where
  there is not; several named layouts per app and a global set, kept on the
  computer and each phone, edits from two phones never lost; buttons of up to
  30 steps that stop on the first failure, can be stopped, and are never
  replayed; starter layouts and extra screens for browsers, Files, terminal,
  editors, media players and Impress. One phone types at a time. Checked by
  `verify_link_workspace.py`, the real routes in `verify-link.py`, and the
  Apps and layout screens on an emulator. 🔬 The three `link_app_workspaces`,
  `link_layouts_sync` and `link_macro_cancel` checks on a real phone and
  desktop.
- ⬜ Not there: a watch app of its own (the notification's buttons reach a
  watch), browsing the phone's files from the desktop's file manager, the
  phone's battery in the panel (it is in `link-cli.py status`), Wayland, iOS,
  and finding each other with no network at all (Apple's Bluetooth and
  peer-to-peer Wi-Fi).

## Milestone 18 — ROS 2 in the top bar

`rosPanel.js` and `tools/ros_info.py`; `docs/ROS2_PANEL.md`.

- ✅ **ROS 2 dropdown** just left of Network, with the ROS logo. Follows
  `~/.bashrc` (distro, `ROS_DOMAIN_ID`, `ROS_LOCALHOST_ONLY`,
  `RMW_IMPLEMENTATION`, a sourced workspace); domain, discovery, middleware
  and workspace can be changed in the panel. Checked in the nested shell
  against real demo nodes (`verify-ros-nested.sh`) and the helper on its own
  (`verify-ros-panel.py`).
- ✅ **Live graph**: nodes, topics, services, actions; expanding a node shows
  its topics with types, peers and QoS, services and clients, actions,
  parameters, lifecycle state; any type opens its definition; Hz measures a
  topic for two seconds.
- ✅ **Launch** RViz2 (and recent `.rviz` configs), rqt, rqt_graph, a terminal
  on the same setup, the demo talker and listener; Show and Stop for running
  ones. RViz2 opened and stopped on a virtual display.
- ✅ **Hardening (v2 audit)**: Stop ends only process groups the panel
  started; a failed attach is rolled back; settings are written atomically
  under a lock; a half-started demo is stopped; hidden namespaces and topics
  only hidden nodes use are left out; ros2_control polling always cleans up;
  the "elsewhere" hint compares the middleware too; details are read again
  after the watcher restarts; the watcher scans every 10 s while closed.
- ✅ **Panel v2** (`verify-ros-panel.py` against real nodes, 80+ checks;
  `verify-ros-nested.sh` in the nested shell): search; Health (no publisher,
  no server, duplicate names, QoS mismatches, `/diagnostics` merged with
  stale detection, TF warnings); favourites; previews with image thumbnails
  and message age; the TF tree with rates and stale frames; confirmed writes:
  typed parameters, lifecycle transitions, service calls, action goals,
  one-off messages; launch files with arguments, saved launches, supervised
  runs with exit codes, crashes with Log and Restart; rosbag record and play
  with summaries and free space; saved setups; following Project Context's
  workspace; Dynamic Island alerts (crash, diagnostics, starred node lost,
  recording) and a red icon while recording; the palette's `ros` mode. The
  list is rebuilt per block, only where its inputs changed, forty rows a page.
- 🔬 **Live in the session**: needs `sync-shell.sh` and a shell restart.
- 🔬 **Gazebo**: installed now (`ros_gz_sim`, so the panel starts
  `ros2 launch ros_gz_sim gz_sim.launch.py`); opening a world from the panel
  has not been tried live.
- ✅ **Controller service operations**: Load / Configure / Activate / Deactivate /
  Unload and rejection handling pass against real Humble message types with an
  isolated fixture manager (`verify-ros-controllers.py`, domain 89). No hardware
  controller plugins have been exercised. `controller_manager_msgs` remains
  absent from the system installation; live use needs it in the selected setup.
- ✅ **ROS panel cleanup**: searchable inline dropdowns replace wrapping file
  chips; workspace selection includes None, discovered workspaces and a custom
  path. Package selection scopes launch files and installed executable nodes.
  Names-first parameters fetch one value on demand, paged forty at a time.
  Calls/goals/messages have typed per-field editors; arrays use JSON inputs.
  Folding a row cancels active Hz/Preview subscriptions. Recording has a
  persistent island activity with screen-sharing privacy.
- ✅ **Workflow: build → launch → inspect → stop** (`verify-ros-panel.py`, a
  real colcon build included; `verify-ros-nested.sh` drives each in the panel):
  workspace build of all or one package the way it was built last (a
  `.build/<distro>` tree's sources from its colcon log), with progress and
  environment checks; launch argument forms (descriptions, defaults, choices,
  required); one run manager with in-panel logs filtered by severity and text,
  pause, restart and stop; parameter profiles compared before a confirmed
  restore; robot profiles (setup, package, favourites, saved launches); rosbag
  topic ticks, playback speed, loop, `/clock` and pause through rosbag2's
  service; a live numeric plot with rqt_plot for the larger view; TF lookup
  between two frames; action feedback and Cancel goal; lifecycle groups with
  each node's outcome; a focused graph view; palette `ros build`, robot
  profiles. Recording cannot pause on Humble (no recorder service).
- 🔬 **Physical session**: source changes pass helper checks and ROS interaction
  checks in a nested shell; appearance and hardware behavior still need live
  verification after the next shell restart. The wider nested desktop check
  also reported an unrelated project-indicator git-status failure.

## Milestone 19 — Mission Control and reproducible engineering work

- ✅ **Outcome-based missions.** Agent Office launches a mission with an objective,
  measurable acceptance criteria, a project and one writable repository. Mission
  state follows its linked work; cancelling a mission stops every active task.
- ✅ **Evidence contract.** The mission prompt requires PASS/FAIL evidence for every
  criterion and preserves the completed task reports as the mission evidence report.
- ✅ **Mission Control UI and CLI.** Missions can be launched, inspected and cancelled
  in the Office UI or with `office mission`.
- ✅ **Reproducible work capsules.** A mission can save a readable JSON manifest with
  the git revision and dirty files, dependency-lock fingerprints, runtime, command,
  launch arguments, parameters, dataset references and result artifacts. Capsules are
  available through the UI, API and `office capsule`.
- ✅ **Isolated verification.** The throwaway Office integration test covers mission
  validation, cancellation, persistence, capsule creation and capsule path guards.
- ✅ **Local project evidence search.** Mission Control searches the mission contract,
  task reports, work capsules, Office project artifacts and the explicitly scoped
  repository. It returns source references (including file lines), skips secret-shaped
  files and does not send indexed content to a model.
- ✅ **ROS failure-investigation mission template.** The Mission Control **ROS failure**
  flow captures the current ROS setup, recording reference and a work capsule, then
  requires reproduction, correlated diagnostics, cited root-cause evidence, a repeatable
  regression check and an uncertainty-aware engineering report. It now compares rosbag2
  metadata against a baseline (topics, types and message counts), flags regressions, and stores
  the exact simulation or replay command in the mission and its capsule for bounded execution.
- ✅ **Phone Mission Control.** Adaptive Link's native Office now receives live mission
  state, launches bounded missions, shows their criteria/tasks/reports, searches their
  evidence and cancels active work through the existing mutually authenticated Office
  gateway. The APK builds; physical-device verification is still required.
- ✅ **Team workflows and permissions.** Missions can be saved as parameterized workflow
  contracts with role allowlists, risk classes and repository boundaries. Read-only workflows
  cannot grant writes, saved repository scope cannot be widened at run time, and hardware or
  external workflows require one-run approval in both the UI and CLI.
- ✅ **Portable audit exports and retention.** A mission exports its contract, linked tasks,
  events, policy and work capsules as one readable JSON bundle. Dry-run-first retention can
  list and remove old capsule/export JSON without touching task history or project source.
- ✅ **Private deployment boundary.** The Office remains loopback-only with Host/Origin/write
  guards; phone use stays behind Adaptive Link's paired gateway and Commands permission. A
  health endpoint reports this local-only state. The integration suite verifies these guards.

## Immediate next work

0. ROS 2 panel: `./scripts/sync-shell.sh`, restart the shell, open the
   nine-dot button left of Network, Start demo, expand `/talker`, open RViz2.
   Then Gazebo with a world, Record and Stop (watch the icon and the island),
   a launch file with an argument, and `ros` in the command palette. Then
   Build on `robotics_learning_lab` (its `.build/humble` tree), a plot, the
   graph view, and a parameter profile restore.
0. `./install.sh --status`, then `./install.sh`, then
   `./scripts/reload-adaptive-shell.sh --restart-shell`. As of Milestone 16
   the live extension is two milestones behind the repository, four
   shortcuts are missing and the file index is not installed. Then work
   through `record-live-verification.py status`.

1. Reinstall the session wrapper so `XDG_DATA_DIRS` takes effect:
   `./scripts/install-adaptive-session.sh` (asks for sudo), then log out and in.
2. Export the Figma frames into `design/figma-exports/`, then build
   `theme/Adaptive`.
3. `./scripts/sync-shell.sh && ./scripts/reload-adaptive-shell.sh --restart-shell`
   and `./scripts/install-keybindings.sh` (Super+Alt+N), then work through
   the six new checks in Settings → Live verification. Optional extras:
   `sudo apt install tesseract-ocr` (screen text), KDE Connect or GSConnect
   (phones).
4. `./scripts/install-adaptive-settings.sh`, restart the Project Context
   Service (or log out and in) so it applies project focus profiles, then click
   through all three Adaptive Settings sections. Record the physical checks
   from its Live verification list as you do the rest of this list.
5. Type a project name in the overview and confirm results appear; the
   provider itself answers `GetInitialResultSet` and passes `should_show()`.
6. Verify audio output switching — five sinks are present on this machine,
   so the submenu can finally be exercised.

## Known live-only traps

- **A helper moved to another file is `undefined` where it used to be found,
  and nothing says so until that code runs.** `CC.makeRow` kept parsing,
  linting and loading after `makeRow` left `controlCenter.js`; it threw when a
  menu opened. `verify-shell-imports.py` checks every `Module.name` and every
  destructured import against what the module really exports.
- **`PopupMenu.open()` does nothing on an empty menu.** A panel button whose
  menu is built in its `open-state-changed` handler therefore never opens.
  Fill the menu before it can be asked to open.
- **PyGObject raises where C returns NULL.** `Gio.DesktopAppInfo.new(id)` for
  an app that is not installed is a `TypeError`, not `None`.
- **A nested shell's children need to be told where it is.** Apps the shell
  launches, and services D-Bus activates, inherit no `WAYLAND_DISPLAY` in a
  nested session and open on the X display behind it. `verify-shell-nested.sh`
  sets it in the shell process and in the bus's activation environment.
- **argparse: a positional named like the subparser's `dest` replaces it.**
  `startup add <command>` stored its words in `args.command`, which is also
  where the chosen subcommand lives, so no branch matched and the CLI printed
  nothing and exited 0.
- **Stopping a wrapper is not stopping what it wraps.** `xvfb-run` and
  `dbus-run-session` each start their command in a way that a signal to the
  wrapper, or to its process group, does not reach. A test that started the
  link daemon that way left it running and holding its port, and the next
  run failed with "address already in use". Find the processes by something
  they all carry (the sandbox path in their environment) and stop those.
- **A preference saved with `apply()` may not be saved.** Android writes it
  in the background; a process that ends first loses it. The app's pairing
  record is written with `commit()`.
- **Closing a listener does not close its connections.** Switching the link
  off closed the port but left an open screen stream running until aiohttp's
  shutdown timeout, a minute later. Open sockets are tracked and closed first.
- Only one Adaptive rail extension may be enabled. `adaptive-shell-v16@local`
  is a retired duplicate kept for rollback; when both it and
  `adaptive-shell@local` are enabled, two rails stack and every dock label
  renders with its first glyph covered. `verify-live-readiness.sh` now fails
  on this.
- GNOME disables user extensions on the lock screen, so `gnome-extensions
  enable` looks like a no-op (state stays DISABLED, no error) until unlock.
- Window-manager keybindings beat `media-keys` custom keybindings. A custom
  shortcut that duplicates one in `org.gnome.desktop.wm.keybindings` never
  grabs, and the only symptom is a "Failed to grab accelerator" line at login.
- Apps launched from Files inherit its journal identifier, so Antigravity's
  Electron errors appear under `org.gnome.Nautilus[pid]`. Check the pid with
  `ps` before treating those as file-manager faults.
- GNOME 42 caches an extension's JS module for the life of the shell process
  and `ReloadExtension` is deprecated, so disable/enable re-runs the old code.
  Changed rail source needs `reload-adaptive-shell.sh --restart-shell` (X11)
  or a fresh login.
- **`node --check` is not enough for a GJS module.** GJS resolves method names
  at call time, so a method deleted by a bad edit still parses, still loads, and
  fails only when something calls it — for a menu handler, the first time the
  popup is opened. This bit twice while building v2. `verify-shell-methods.py`
  now cross-checks every `this._x()` call site against the definitions in the
  same file, and runs in both verification suites.
- St's CSS parser rejects a quoted, comma-separated `font-family` list: it logs
  "Couldn't parse family in font property" and drops the declaration silently,
  so the font never applies. A single unquoted family works. GNOME's own shell
  CSS sets no `font-family` at all.
- `CalendarMessageList` stacks the "No Notifications" placeholder over the whole
  list with a `Clutter.BinLayout`, sharing that space with the box that holds the
  scroll view *and* the Do Not Disturb row. Stock GNOME only gets away with it
  because the list is tall enough that the centred placeholder clears the
  controls; compress the list and they overlap. The shade moves the placeholder
  into that vertical box so it is in normal flow and cannot overlap at any
  height — and puts it back on detach, like every other GNOME actor it moves.
- `/proc/loadavg`'s fourth field counts **tasks**, kernel threads included —
  ~3100 against ~500 real processes on this machine. Labelling it "processes"
  is wrong by a factor of six; the process count comes from the `/proc` walk.
- `verify-stability-suite.sh` resolved three paths against the caller's cwd
  instead of `${REPO}`, so it only passed when run from the repo root. Fixed,
  and it now syntax-checks every shell module rather than just extension.js.
- `Calendar.DBusEventSource.requestRange()` REPLACES the calendar server's time
  range rather than widening it, and `Calendar.Calendar._rebuildCalendar()`
  already calls it for the displayed month grid. A second caller makes the two
  fight, each forcing a reload on a shared server. The shade's calendar reads
  with `getEvents()` and never requests a range.
- GNOME's `CalendarEvent` keeps only `{id, date, end, summary}` — it discards the
  DBus `a{sv}` extras — and the Google source's local `.source` file has an empty
  `Color=`. There is no upstream per-calendar colour to honour, so the shade
  hashes the source uid out of the event id prefix onto the Adaptive palette.
- `MessageList.MessageListSection` defines `_messages` as "every child of `_list`,
  unwrapped", so inserting group headers into that list corrupts its own
  `empty`/`can-clear`/`clear()` logic. Group by implementing the contract
  `CalendarMessageList` consumes, not by subclassing the section.
- **Reading a temperature is not always cheap.** An NVMe hwmon `temp1_input`
  issues a SMART admin command to the drive and costs ~27 ms on this machine;
  every other sensor here is 0.01-0.14 ms. v1.7 read them all synchronously
  every second, blocking the compositor's main loop for 27 ms a second the whole
  time the shade was open. v2 times every sensor once at discovery, reads
  anything over 2 ms asynchronously via `load_contents_async`, and only every
  ten seconds. Measured, not guessed by device name, because which sensors are
  slow is a property of the hardware and driver.
  Result: median tick 1.37 ms, max 12.6 ms, 3.44 ms/s amortised, and zero ticks
  over a 16.7 ms frame budget - from 11.0 ms/s with a 48 ms worst case.
- Never let two expensive samplers run on the same tick. The `/proc` walk and a
  slow sensor together were ~38 ms, two dropped frames; each is scheduled on its
  own next-due counter and yields if the other already ran.
- A `Clutter.FixedLayout` child is positioned in absolute coordinates, so
  anything laid out inside one must be placed against the width the container is
  actually allocated, via `notify::width` - not against the constant it was
  built with. An `x_expand` column is never the width you asked for.
- Events from `DBusEventSource` are shared cache objects and the same event can
  appear in several day columns. Never write layout state onto them; keep it in
  a Map beside them.
- A full `/proc` walk costs ~5 ms across ~500 processes. That is far too much to
  spend every second on the compositor's main loop, so the process table samples
  every third tick. Per-process CPU also has to skip processes that appeared
  since the last scan, or their whole lifetime's CPU is reported as if it were
  spent in the last interval.
- `notify-send --app-name` is not enough to prove grouping across applications:
  the notification daemon may fold several senders into one source. Check the
  group count in the popup, not just that the notifications arrived.
- Intel `gt_act_freq_mhz` reads 0 whenever the render engine is in RC6, which is
  correct but looks like a dead sensor. GPU busy comes from RC6 residency deltas
  instead (`100 - Δrc6_ms/Δwall_ms`), which needs no perf access and no
  `intel_gpu_top`; measured 17% idle against 100% under `glxgears`. The shade
  shows "Idle" rather than "0 MHz" when the clock is genuinely down.
- Thermal zone indices and DRM card numbers are assigned in probe order, not
  fixed, so `telemetry.js` resolves sensors by reading each zone's `type` and
  each card's attributes. `thermal_zone10` is the package sensor on this machine
  today and need not be tomorrow. `INT3400` is an ACPI policy device, not a
  sensor: it reports a constant 20°C and is filtered out.
- `intel-rapl` `energy_uj` is root-only, so package wattage is not available to
  the shell, and this machine exposes no fan tachometer. Both are deliberately
  absent from the shade rather than faked.
- Assigning `actor.style` forces St to reparse the rule. Per-tick colour writes
  across sixteen core bars and a dozen temperature chips are real work, so the
  shade only writes a style when the value's colour band actually changes.
- `adaptive-project-context.desktop` must keep `NoDisplay=false`. GNOME's
  `loadRemoteSearchProviders` drops any provider whose `DesktopId` fails
  `should_show()`, so hiding the service from the app grid also removes
  project results from overview search.
