# Adaptive Desktop Complete Patch v1.5

Target:

- Ubuntu 22.04
- GNOME Shell 42
- local Nautilus 42.6 fork already built in `~/adaptive-desktop/.local/adaptive-nautilus`

This package combines the three requested areas into one controlled update.

## Part 1 — File-type visualization

Adaptive Files now includes dedicated scalable SVG identities for:

- Python;
- Jupyter Notebook;
- C;
- C++;
- CUDA;
- Arduino;
- JavaScript;
- TypeScript;
- Java;
- Kotlin;
- Rust;
- Go;
- Shell;
- Lua;
- Ruby;
- PHP;
- Swift;
- JSON;
- YAML;
- TOML;
- XML;
- HTML;
- CSS;
- SCSS;
- Markdown;
- SQL;
- CMake;
- Makefile;
- Dockerfile / Containerfile;
- Protocol Buffers;
- common config/text/document/media types.

The right Inspector shows a friendly type identity before the preview.

Code uses GtkSourceView for syntax-aware read-only rendering.

PDF/image previews use the native GNOME thumbnail pipeline.

## Part 2 — Working dock

The custom left rail is replaced with a functional GNOME Shell 42 extension.

Top actions:

1. Overview
2. Adaptive Files
3. Applications
4. Workspaces
5. Search

Bottom action:

6. Settings

The Adaptive Files button launches the local Nautilus fork through
`scripts/adaptive-files-launch.sh`.

A normal desktop entry is also installed as:

`~/.local/share/applications/com.karthi.AdaptiveFiles.desktop`

so Adaptive Files is available from the app grid/search as well.

## Part 3 — top clock/calendar restored

The extension no longer hides GNOME's real `dateMenu`.

That means:

- the normal time is visible again;
- existing GNOME clock-format settings are respected;
- clicking the time opens the real GNOME calendar/notification menu;
- only the visual styling changes.

This is intentionally safer than reimplementing the clock/calendar.

## Install

Extract the package into the repository:

```bash
cd ~/adaptive-desktop

unzip -o \
  ~/Downloads/adaptive-desktop-complete-v1.5.zip \
  -d .
```

Then run one installer:

```bash
./scripts/complete-install-v1.5.sh
```

The installer:

1. checks GNOME Shell 42 and the local Nautilus baseline;
2. creates a timestamped backup;
3. installs native preview dependencies and file-type icons;
4. installs the Adaptive Files app launcher;
5. replaces/reloads `adaptive-shell@local`;
6. runs non-destructive self-tests.

## Step-by-step verification

Run everything:

```bash
./scripts/verify-complete-v1.5.sh
```

Or one stage at a time:

```bash
./scripts/verify-01-file-icons.sh
./scripts/verify-02-native-preview.sh
./scripts/verify-03-dock.sh
./scripts/verify-04-clock.sh
./scripts/verify-05-shell-runtime.sh
```

## Manual verification sequence

### A. File visualization

Open Adaptive Files and inspect:

- `.py`
- `.cpp`
- `.js`
- `.sh`
- PDF
- PNG/JPEG

Verify the file-type icon and Inspector identity match the selected format.

### B. Dock

Click each icon one by one.

The Files and Settings buttons must launch applications; the other three shell
navigation buttons must open their GNOME surfaces.

### C. Clock

Verify the time is visible at the top.

Click it and confirm the normal calendar/notification menu opens.

## Rollback

```bash
./scripts/rollback-complete-v1.5.sh
```

The installer stores the backup path in:

`~/.config/adaptive-desktop/last-complete-patch-backup`
