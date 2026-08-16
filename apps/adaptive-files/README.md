# Adaptive Files v0.3

A compact, resolution-independent redesign of the Karthi's OS file explorer.

## Why v0.3 replaces v0.2

The previous build had two problems:

1. a GIO child-enumeration crash;
2. visual geometry that was much too large and card-heavy.

v0.3 is a clean replacement rather than an incremental style patch.

## Design target

Use the refinement, density, geometry and restraint of high-end native desktop software as the benchmark.

Apple/macOS is used as a benchmark for quality, not as an asset source. No Apple branding, proprietary icons or copied graphics are included.

## Main changes

- fixed the `GFileEnumerator` / NULL-child failure;
- 38 px custom titlebar;
- 28×28 px window controls;
- 44 px toolbar;
- 172 px sidebar;
- 56 px icon-only sidebar on narrow windows;
- optional 256 px inspector instead of a permanent right panel;
- 112×100 px clean grid items;
- no permanent large cards around every folder;
- restrained blue selection state;
- vector-only custom SVG assets;
- 1280×800 default window instead of launching huge;
- responsive behavior down to 820×560;
- grid/list views;
- current-folder search;
- hidden-file toggle;
- rename;
- ZIP compression;
- copy path;
- move to Trash;
- desktop launcher;
- optional default directory handler;
- Adaptive Shell dock integration patch.

## HiDPI / 4K / 8K

The UI is specified in GTK logical pixels, not physical pixels.

All custom artwork is SVG. GTK/GDK apply the desktop scale factor, so high-density monitors render vector artwork at the appropriate scale rather than stretching PNG files.

Do not force `GDK_SCALE` for normal use. Configure scaling in the desktop display settings.

## Dependencies

Ubuntu 22.04:

```bash
sudo apt update
sudo apt install -y \
  python3 \
  python3-gi \
  gir1.2-gtk-4.0 \
  librsvg2-common \
  desktop-file-utils \
  xdg-utils
```

## Validate before running

```bash
cd ~/adaptive-desktop/apps/adaptive-files
./validate.sh
```

Expected:

```text
SVG validation: PASS
Python syntax: PASS
Desktop entry: PASS
```

## Run from source

```bash
python3 main.py
```

Open a directory:

```bash
python3 main.py ~/Downloads
```

## Install

```bash
./install.sh
adaptive-files
```

After installation, `Files` is available through the normal desktop application search because the package installs a `.desktop` entry.

## Make external folder-opening requests use Adaptive Files

After testing the app:

```bash
./register-default.sh
```

Verify:

```bash
xdg-mime query default inode/directory
xdg-open "$HOME"
```

This covers folder-opening integration such as `xdg-open`. It does **not** replace GTK/portal file-picker dialogs embedded inside other applications. That requires a separate file-chooser/portal milestone.

## Add Files to the Adaptive Desktop rail

From the repository root:

```bash
python3 scripts/integrate-files-with-shell.py

./scripts/sync-shell.sh
gnome-extensions disable adaptive-shell@local
gnome-extensions enable adaptive-shell@local
```

The integration script creates:

```text
shell/adaptive-shell@local/extension.js.before-files-integration
```

before modifying the Shell extension.

## Search integration

### Implemented now

- in-app search filters the current directory;
- the installed `.desktop` entry makes Files searchable as an application;
- the Shell rail can launch Files after running the integration patch.

### Still to build

- global indexed filesystem search;
- Adaptive Command search provider;
- content search;
- file chooser portal.

## Responsive breakpoints

- below ~980 logical px:
  - sidebar becomes icon-only;
  - search box hides;
  - inspector hides;
- 980–1179:
  - full sidebar;
  - inspector hidden;
- 1180+:
  - full sidebar;
  - optional inspector.

## Interaction

- sidebar: single-click navigation;
- grid/list item: single-click selection;
- folder: double-click to enter;
- file: double-click to open using the default application;
- Info button: show/hide inspector on wide windows.


## v0.4 geometry correction

v0.4 changes the browser layout itself, not only CSS.

- Sidebar is explicitly non-expanding.
- Browser is explicitly expanding and fills all remaining space.
- Grid columns are recalculated from the browser's actual width.
- Grid is left/fill aligned.
- The inspector remains optional.
- Default size is 1180×740.
- Single click on a folder navigates into it immediately.
- Single click on a file selects it.
- Double click on a file launches it.

This directly addresses the large vacant content region seen in v0.3.


## v0.5 interaction and geometry update

### Navigation

- `Backspace`: Back
- `Alt+Left`: Back
- `Alt+Right`: Forward
- `Alt+Up`: Parent directory
- `Ctrl+F`: Focus search
- `Ctrl+L`: Select the copyable path field

### Item behavior

- Single click on any folder or file: select it and render a preview on the right.
- Double click folder: enter that folder.
- Double click file: open with its default application.
- Folder grid items no longer display a redundant `Folder` subtitle.
- File grid items continue displaying file size.

### Preview panel

The right panel is part of the normal layout and is separated with a resizable `Gtk.Paned`.

Preview support includes:

- folders: first visible child items;
- images: actual image;
- PDFs: rendered first page through `pdftoppm` when `poppler-utils` is installed;
- text/code/config files: read-only text preview;
- other files: custom generic file artwork + metadata.

### Storage

Click the Storage card in the sidebar to open:

- total storage;
- used storage;
- available storage;
- percentage used;
- filesystem type;
- animated radial utilization indicator.

### Toolbar geometry

- path field reduced and made selectable/copyable;
- search field reduced;
- toolbar and window controls remain compact.


## v0.6 storage, bookmarks and Samba

### Storage redesign

Click Storage in the sidebar for a reorganized volume overview:

- compact animated utilization ring;
- available and used values;
- capacity bar;
- total/free values;
- device;
- filesystem type;
- mount point;
- Home path;
- Open Home / Open Filesystem / Refresh actions.

### Pinned folders

- Use the pin button beside the location field to pin or unpin the current location.
- Pinned locations persist in:
  `~/.config/adaptive-desktop/bookmarks.json`
- They appear under the PINNED section in the sidebar.
- Remote Samba locations can also be pinned.

### Samba / remote locations

A NETWORK section is now available in the sidebar.

Choose:

`Connect to Server…`

and enter for example:

`sm​b://server/share`

For Ubuntu 22.04 install the GIO/GVfs Samba backend:

```bash
sudo apt install -y gvfs-backends
```

The remote connection uses GIO mounting and `Gtk.MountOperation`, so authentication can be requested when the backend needs credentials.

Previously connected remotes persist in:

`~/.config/adaptive-desktop/remotes.json`
