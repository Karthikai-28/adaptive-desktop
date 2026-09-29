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
- ⬜ Adaptive-only sections (Projects & Workspaces, Search & Commands,
  Updates/Recovery/Session) still need a home; `gnome-control-center` has no
  panel for them.

## Milestone 9 — Notifications and Focus

- ✅ Notification center.
- ✅ Critical/normal policy.
- ✅ Focus profiles.
- ✅ Project focus profile.
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
- 🔬 Files window under the session theme; the running instance predates it.
- ⬜ Top-right panel restyled in shell CSS; rail System button removed once it
  lands, so system controls live in one place.
- ⬜ Session wrapper reinstall (needs sudo) to pick up `XDG_DATA_DIRS`.
- ⬜ Frame-exact match to the Figma screens.

The token-driven baseline is built and applied. Exact frame matching is blocked
on `design/figma-exports/`, which still contains only its README — see §12 of
the handoff: do not mark the Figma-skin items complete without the exports.

## Immediate next work

1. Reinstall the session wrapper so `XDG_DATA_DIRS` takes effect:
   `./scripts/install-adaptive-session.sh` (asks for sudo), then log out and in.
2. Export the Figma frames into `design/figma-exports/`, then build
   `theme/Adaptive`.
3. Click through the restored Workspaces and Command rail menus (System
   Center is confirmed opening to the right of the rail).
4. Type a project name in the overview and confirm results appear; the
   provider itself answers `GetInitialResultSet` and passes `should_show()`.
5. Verify audio output switching — five sinks are present on this machine,
   so the submenu can finally be exercised.

## Known live-only traps

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
