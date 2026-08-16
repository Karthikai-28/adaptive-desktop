# Adaptive Files — Ubuntu Files / Nautilus 42 Feature Parity

Target platform: Ubuntu 22.04 LTS  
Engine target: Ubuntu Nautilus 42.x

## Architecture rule

Adaptive Files must not replace mature Nautilus behavior with a partial reimplementation.

```text
Ubuntu / GVfs / GIO / Tracker / MIME / Nautilus engine
                     |
                     v
             Adaptive Files fork
                     |
        +------------+------------+
        |                         |
 existing Nautilus behavior   Karthi's OS additions
 preserved                    preview / project context /
                              storage visualization /
                              custom design / command layer
```

Parity rule:

> Existing Ubuntu Files capability is preserved unless a replacement is demonstrably equivalent or better.

## Navigation and opening

- Double-click folder to enter.
- Double-click file to open with the default application.
- Middle-click folder to open in a new tab.
- Right-click folder to open in a new tab or new window.
- Back, Forward and Parent navigation.
- Editable location/path mode.
- Breadcrumb navigation.
- New window and tabs.
- Keyboard navigation.
- Search/type-ahead behavior.
- Open passed file/directory URIs.
- Home, Recent, bookmarks, Trash, volumes and network locations.

Adaptive additions:
- single-click rich preview;
- project context;
- project roots;
- persistent inspector.

## Selection

- Single selection.
- Ctrl-click multi-selection.
- Shift-click range selection.
- Keyboard selection.
- Select all.
- Select by filename pattern.
- Multi-selection context actions.
- View-appropriate pointer/rubber-band selection.

## Copy, move and paste

- Ctrl+C copy.
- Ctrl+X cut.
- Ctrl+V paste.
- Drag and drop.
- Same-device drag move behavior.
- Cross-device drag copy behavior.
- Ctrl-drag force copy.
- Shift-drag force move.
- Recursive folder operations.
- Duplicate.
- Paste into folder.
- Conflict resolution.
- Replace / skip / rename decisions.
- Progress reporting.
- Cancellation.
- Error handling.
- Read-only handling.

## Delete and Trash

- Delete sends to Trash.
- Shift+Delete permanently deletes.
- Appropriate destructive confirmation.
- Undo where Nautilus supports it.
- Restore from Trash.
- Restore to original location.
- Empty Trash.
- Filesystem/device Trash behavior.
- Busy/error handling.

## Rename and creation

- F2 rename.
- Extension-aware rename selection.
- File/folder rename.
- Batch rename.
- Batch rename templates.
- Find/replace rename.
- Sequential numbering.
- Undo rename.
- Create folder.
- New Document from ~/Templates.

## Search

- Ctrl+F.
- Type to search.
- Search under the current location.
- Filename search.
- File-type filters.
- Date filters.
- Tracker-backed full-text search where available.
- Search results support normal file operations.
- Search-location configuration.
- Bookmarks as search locations.
- Escape/cancel search.

Adaptive additions:
- project-scoped search;
- Adaptive Command integration;
- rich result preview.

## Views, sorting and display

- Grid view.
- List view.
- Expandable/tree-style list capability where available.
- Zoom/icon sizing.
- A-Z / Z-A.
- Modified date.
- Reverse modified order.
- Size.
- Type.
- Folder grouping preference.
- Configurable list columns.
- Name.
- Size.
- Type.
- Modified.
- Owner.
- Group.
- Permissions.
- MIME/detailed type.
- Location.
- Accessed.
- Created.
- Icon captions.
- Thumbnail preferences.

## Preview

- Space-bar preview.
- Documents.
- Images.
- Video.
- Audio.
- Document scrolling.
- Audio/video seeking where supported.
- Fullscreen preview.
- Dismiss preview.

Adaptive additions:
- permanent inspector;
- single-click preview;
- folder-contents preview.

## Properties and metadata

- Properties dialog.
- Name.
- Type.
- Size.
- Folder item count.
- Free space.
- Parent/location.
- Accessed.
- Modified.
- Created where supported.
- Image/video metadata.
- Owner/group.
- Permissions.
- Open With/default application.

## Permissions and executables

- Owner permissions.
- Group permissions.
- Other-user permissions.
- Read/write.
- Execute.
- Folder access semantics.
- Protected/read-only handling.
- Executable text behavior.
- Nautilus Scripts behavior.

## MIME and Open With

- Default application.
- Open With.
- Recommended applications.
- All applications.
- Change default application by MIME type.
- System MIME database integration.

## Hidden files

- Ctrl+H.
- Dotfiles.
- Backup files ending in ~.
- Hidden folders.
- Nautilus preference persistence.

## Bookmarks

- Add bookmark.
- Remove bookmark.
- Rename bookmark.
- Sidebar bookmarks.
- Navigate to bookmark.
- Bookmarks participate in search-location settings.

Adaptive additions:
- project-aware pins;
- pinned remote roots.

## Remote/network locations

Preserve GIO/GVfs instead of implementing another network stack.

- Other Locations.
- Local-network discovery provided by GVfs.
- Recent servers.
- Connect to Server.
- SSH.
- FTP.
- Anonymous FTP.
- SMB / Windows shares.
- WebDAV.
- Secure WebDAV.
- NFS where supported by installed GVfs backends.
- Credential dialogs.
- Remote permissions.
- Upload/download.
- Rename/delete where permitted.
- Local-to-remote copy/move.
- Remote mounts in sidebar.
- Unmount/disconnect.

Adaptive additions:
- redesigned connection UI;
- project-linked remote roots;
- connection status.

## Removable media

- USB drives.
- External disks.
- Optical media where supported.
- Sidebar devices.
- Mount.
- Unmount.
- Eject.
- Safely remove.
- Busy-volume handling.
- Automount integrations.
- Read/write.
- Cross-device copy semantics.

## Context menus

- Open.
- Open in new tab.
- Open in new window.
- Open With.
- Cut.
- Copy.
- Paste.
- Rename.
- Move to Trash.
- Permanent-delete path.
- Properties.
- Compress/archive integration.
- Extract integration where available.
- Scripts.
- Nautilus extension actions.
- Background context menu.
- Templates/New Document.

Adaptive additions:
- Pin.
- Add to project.
- Open in project workspace.
- Copy project-relative path.

## Scripts and extensions

- ~/.local/share/nautilus/scripts.
- Local selected files passed to scripts.
- Nautilus extension API.
- Compatible Ubuntu Nautilus extensions.
- Open in Terminal extension.
- Other installed providers.

## Operation feedback / undo

- File-operation progress.
- Copy/move progress.
- Conflict dialogs.
- Delete/trash feedback.
- Undo supported operations.
- Rename undo.
- Cancellation.
- Errors.

## Preferences

- Single-click vs double-click opening.
- Executable text behavior.
- Trash behavior.
- Display/icon-caption preferences.
- Thumbnail preferences.
- List columns.
- Default sorting/grouping.
- GNOME search location configuration.

Adaptive default:
- single click = select/preview;
- double click = open.

## Adaptive-only additions

- Always-available right inspector.
- PDF/image/text/folder preview.
- Project Context Service.
- Project-scoped search.
- Storage visualization.
- Karthi's OS icon system.
- Adaptive dock integration.
- Adaptive Command integration.
- Future split view.
- Future transfer center.

## Definition of parity

Adaptive Files is not parity-complete until:

1. Normal Nautilus keyboard and mouse workflows work.
2. Native GVfs/GIO remote and device behavior remains intact.
3. Nautilus extension compatibility is evaluated.
4. Existing file operations have no regressions.
5. MIME, permissions, mount, search and Trash semantics are inherited rather than approximated.
6. Stock Ubuntu Files remains installed as a fallback/reference.
