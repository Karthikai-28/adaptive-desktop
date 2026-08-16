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

- ✅ Convert rail from floating palette into a true docked shell rail.
- 🔬 Reserve application area to the right of the rail.
- 🟡 Add icon+text dock labels and live open-window switching.
- 🟡 Improve icon consistency and active states.
- 🟡 Keep stock top-right controls until System Center is functional.

### Acceptance criteria

- rail flush to left edge;
- rail occupies shell height below top bar;
- maximized windows do not overlap the rail;
- System Center control anchored near bottom;
- no rounded floating outer card look.

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
- 🔬 Verify service autostart inside Adaptive Desktop.
- 🔬 Verify shell DBus updates after extension reload.

## Milestone 4 — Workspaces

- ✅ Read GNOME workspace state.
- ✅ Workspace switch UI.
- ✅ Project-to-workspace mapping.
- ✅ Restore project workspace.
- ⬜ Remember window placement where safe.
- 🟡 Workspace overview redesign.
- ⬜ Keyboard shortcuts.
- ⬜ Multi-monitor behavior.
- ⬜ Reduced-motion behavior.

## Milestone 5 — Universal Command

- ⬜ Global shortcut.
- 🟡 Application search.
- 🟡 File/folder search.
- ✅ Project switching.
- ✅ Desktop actions.
- ✅ Settings search.
- ✅ Recent actions.
- 🟡 Keyboard navigation.
- 🟡 Extensible provider model.
- 🟡 Permission/safety model.

## Milestone 6 — System Center

### Current

- 🟡 First functional shell menu exists with volume, settings, lock, suspend, logout, and power actions.
- 🟡 Read-only status rows refresh on open for network, Bluetooth, power, and audio output.
- 🔬 Audio output selection submenu exists and needs live device verification.
- 🔬 Restart and shut down entries use GNOME-native confirmation actions where available.
- 🟡 Performance row shows load and memory summary.

### Required

- 🟡 Network status.
- 🟡 Bluetooth status.
- 🔬 Audio device selection.
- 🟡 Audio output status.
- ✅ Volume.
- 🟡 Battery/power status.
- 🟡 Performance summary.
- ⬜ Notifications/focus.
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

- 🟡 Home/Recents.
- ✅ Project Files.
- ✅ Folder browse.
- ✅ Grid/list.
- ✅ Search/filters.
- ✅ Preview/Inspector.
- ⬜ Split view.
- ⬜ Multi-select.
- ⬜ Transfers.
- ⬜ Conflict resolution.
- 🟡 Trash/recovery.
- 🟡 Devices/network.
- ✅ Empty/error states.
- ✅ Linux permissions/hidden files.
- ✅ Decide Nautilus integration vs separate frontend.

### Current

- ✅ Standalone Adaptive Files app exists.
- ✅ Nautilus native preview/inspector layer exists.
- ✅ Project registry format is understood by Adaptive Files.
- 🟡 Nautilus preview has a Project tab backed by Project Context Service.

## Milestone 8 — Settings

- ✅ 18-section information architecture defined.
- ✅ Settings shell.
- ✅ Search.
- 🟡 Appearance.
- 🟡 Projects & Workspaces.
- 🟡 Windows & Multitasking.
- 🟡 Notifications & Focus.
- 🟡 Search & Commands.
- 🟡 Display & Graphics.
- 🟡 Sound.
- 🟡 Input & Gestures.
- 🟡 Network & Connectivity.
- 🟡 Files & Storage.
- 🟡 Privacy & Security.
- 🟡 Accounts & Sync.
- 🟡 Power & Battery.
- 🟡 Accessibility.
- 🟡 Developer & Advanced.
- 🟡 Updates/Recovery/Session.
- 🟡 About.

## Milestone 9 — Notifications and Focus

- 🟡 Notification center.
- 🟡 Critical/normal policy.
- 🟡 Focus profiles.
- ✅ Project focus profile.
- ✅ Focus timer.
- 🟡 Quiet/fullscreen behavior.

## Milestone 10 — Window management

- 🟡 Smart tiling.
- ✅ Split presets.
- 🟡 Snapping.
- 🟡 Project-aware placement.
- 🟡 Visible open-window switching from the dock.
- ✅ Restore.
- 🟡 Fullscreen behavior.
- ⬜ Multi-monitor behavior.
- 🟡 Overview integration.

## Milestone 11 — Lock/Login/Session

- ⬜ Adaptive lock treatment.
- ⬜ Login compatibility.
- ⬜ Session status.
- ⬜ Return to Ubuntu.
- ⬜ Session save behavior.
- ⬜ Failed-session recovery.

## Milestone 12 — Visual system completion

- 🟡 Core palette defined.
- 🟡 Initial shell CSS implemented.
- ✅ Tokenize colors/spacing.
- ⬜ Final icon family.
- ✅ Typography scale.
- ✅ Motion tokens.
- ⬜ Reduced-motion mode.
- ⬜ High-contrast mode.
- ⬜ Light-theme decision.
- ✅ Component/state inventory.

## Milestone 13 — Stability

- ✅ Shell smoke tests.
- 🟡 No-extension fallback test.
- ⬜ GDM fallback test.
- ⬜ Reboot test.
- ⬜ Suspend/resume test.
- ⬜ External monitor test.
- ⬜ File transfer stress test.
- ⬜ Long-running shell memory test.
- ✅ Update compatibility check.
- 🟡 Backup/restore test.

## Immediate next work

1. Reload `adaptive-shell@local` inside Adaptive Desktop.
2. Verify docked navigation rail struts with maximized windows.
3. Verify Project Context Service autostart after logging into Adaptive Desktop.
4. Verify GNOME overview search discovers registered projects.
5. Continue System Center parity: safe toggles and reboot/shutdown confirmations.
