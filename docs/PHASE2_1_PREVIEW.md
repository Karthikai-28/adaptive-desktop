# Adaptive Files Phase 2.1 — Preview Inspector v1.0

This milestone adds the structural right-side inspector missing from the
previous visual-only theme pass.

## Architecture

Nautilus 42.6 continues to own:

- double-click open/navigation;
- keyboard navigation and Backspace;
- selection and multi-selection;
- copy/cut/paste;
- drag/drop;
- Trash;
- undo;
- MIME/Open With;
- permissions;
- bookmarks;
- search;
- devices;
- GIO/GVfs network connectivity.

The Adaptive extension observes selection and adds presentation on top.

## Inspector tabs

### Preview

Single click updates the right inspector.

Supported:

- folders: asynchronous content listing;
- images: actual image preview;
- PDFs: first-page render through `pdftoppm`;
- text/code/config: inline text preview;
- other files: type icon;
- path;
- size;
- modified/created time;
- permissions;
- copy path;
- native bookmark-current-location action.

Double click is not intercepted. Nautilus handles it normally.

### Storage

- total;
- used;
- available;
- usage ring;
- capacity bar;
- device;
- filesystem;
- mount point;
- Home;
- scrollable layout;
- larger readable typography.

### Network

This is only a front end to the existing Ubuntu GIO/GVfs stack.

- SMB;
- SFTP;
- FTP;
- WebDAV;
- secure WebDAV;
- NFS where the installed GVfs backend supports it;
- network:/// browsing;
- currently mounted remote locations;
- native credential/authentication flow.

No separate Samba implementation is introduced.

## Install

Extract into `~/adaptive-desktop`, then:

```bash
cd ~/adaptive-desktop

./scripts/phase2.1-install-preview.sh
```

Quit any already-running Nautilus processes before testing:

```bash
/usr/bin/nautilus -q || true
pkill -x nautilus || true
sleep 2
```

Launch:

```bash
./scripts/phase2.1-run-preview.sh
```

Single-click any folder or file.

## Verify

```bash
./scripts/phase2.1-verify-preview.sh
```

If the panel is still missing:

```bash
./scripts/phase2.1-debug-preview.sh
```

The extension writes a widget-tree/attachment log to:

`~/.cache/adaptive-files/preview-extension.log`

That makes the next correction deterministic instead of guessing about the
private Nautilus widget hierarchy.
