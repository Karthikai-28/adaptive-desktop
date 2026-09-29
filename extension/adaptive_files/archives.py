"""Look inside archives without extracting them.

zip-family and tar-family files are read with the standard library; 7z and
RAR through 7z; .deb through dpkg-deb; AppImages by listing the SquashFS
image that follows their ELF runtime. Every reader is bounded in time and
entries, and says partial=True when it stopped early.
"""

import os
import stat
import struct
import subprocess
import tarfile
import time
import zipfile

ZIP_SUFFIXES = (".zip", ".jar", ".whl", ".apk", ".xpi", ".nupkg")
TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2", ".tar.zst")
SEVENZ_SUFFIXES = (".7z", ".rar")
DEB_SUFFIXES = (".deb",)
APPIMAGE_SUFFIXES = (".appimage",)

MAX_ENTRIES = 100000
MAX_SECONDS = 4.0


def handles(name):
    lower = name.casefold()
    return lower.endswith(
        ZIP_SUFFIXES + TAR_SUFFIXES + SEVENZ_SUFFIXES + DEB_SUFFIXES + APPIMAGE_SUFFIXES
    )


def inspect(path):
    lower = os.path.basename(path).casefold()
    if lower.endswith(ZIP_SUFFIXES):
        result = _zip(path)
    elif lower.endswith(TAR_SUFFIXES):
        result = _tar(path)
    elif lower.endswith(SEVENZ_SUFFIXES):
        result = _sevenz(path)
    elif lower.endswith(DEB_SUFFIXES):
        result = _deb(path)
    elif lower.endswith(APPIMAGE_SUFFIXES):
        result = _appimage(path)
    else:
        raise ValueError("not an archive")

    result["packed"] = os.path.getsize(path)
    result["top"] = _top_level(result.pop("entries"))
    return result


def _summary():
    return {"files": 0, "folders": 0, "unpacked": 0, "partial": False, "entries": [], "details": {}}


def _add(result, name, size, is_dir):
    name = name.strip("/")
    if not name or name == ".":
        return
    if is_dir:
        result["folders"] += 1
    else:
        result["files"] += 1
        result["unpacked"] += size
    result["entries"].append((name, size, is_dir))


def _top_level(entries):
    """Aggregate entries under their first path component."""
    top = {}
    for name, size, is_dir in entries:
        head, sep, _rest = name.partition("/")
        folder = bool(sep) or is_dir
        entry = top.setdefault(head, {"name": head, "bytes": 0, "is_dir": folder, "count": 0})
        entry["bytes"] += size
        entry["count"] += 0 if is_dir else 1
        entry["is_dir"] = entry["is_dir"] or folder
    return sorted(top.values(), key=lambda e: e["bytes"], reverse=True)


def _zip(path):
    result = _summary()
    with zipfile.ZipFile(path) as archive:
        for index, info in enumerate(archive.infolist()):
            if index >= MAX_ENTRIES:
                result["partial"] = True
                break
            _add(result, info.filename, info.file_size, info.is_dir())
    return result


def _tar(path):
    # Compressed tars have no index: listing means decompressing. Bounded,
    # so a multi-gigabyte backup shows a partial count instead of hanging.
    result = _summary()
    started = time.monotonic()
    with tarfile.open(path, "r:*") as archive:
        for index, member in enumerate(archive):
            if index >= MAX_ENTRIES or time.monotonic() - started > MAX_SECONDS:
                result["partial"] = True
                break
            _add(result, member.name, member.size, member.isdir())
    return result


def _run(command, timeout=8):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _sevenz(path):
    result = _summary()
    proc = _run(["7z", "l", "-slt", "-ba", path])
    entry = {}
    for line in proc.stdout.splitlines() + [""]:
        if not line.strip():
            if "Path" in entry:
                _add(
                    result,
                    entry["Path"],
                    int(entry.get("Size") or 0),
                    entry.get("Folder") == "+" or "D" in entry.get("Attributes", "")[:1],
                )
            entry = {}
            continue
        key, _, value = line.partition(" = ")
        entry[key.strip()] = value.strip()
    if proc.returncode not in (0, 1) and not result["entries"]:
        raise RuntimeError(proc.stderr.strip() or "7z could not read this archive")
    return result


def _deb(path):
    result = _summary()
    proc = _run(["dpkg-deb", "-c", path])
    for line in proc.stdout.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        perms, _owner, size, _date, _time, name = parts
        name = name.split(" -> ")[0]
        _add(result, name.lstrip("./"), int(size), perms.startswith("d"))

    fields = _run(["dpkg-deb", "-f", path, "Package", "Version", "Architecture", "Description"])
    for line in fields.stdout.splitlines():
        key, _, value = line.partition(": ")
        if key in ("Package", "Version", "Architecture", "Description") and value:
            result["details"][key] = value.strip()
    return result


def _elf_end(path):
    """Byte offset where an AppImage's ELF runtime ends and SquashFS starts:
    the end of the section header table."""
    with open(path, "rb") as handle:
        header = handle.read(64)
    if header[:4] != b"\x7fELF":
        raise ValueError("not an ELF AppImage")
    if header[4] == 2:  # 64-bit
        shoff, = struct.unpack_from("<Q", header, 0x28)
        shentsize, shnum = struct.unpack_from("<HH", header, 0x3A)
    else:
        shoff, = struct.unpack_from("<I", header, 0x20)
        shentsize, shnum = struct.unpack_from("<HH", header, 0x2E)
    return shoff + shentsize * shnum


def _appimage(path):
    result = _summary()
    offset = _elf_end(path)
    proc = _run(["unsquashfs", "-lls", "-o", str(offset), path], timeout=10)
    for line in proc.stdout.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[0][:1] in "-dl":
            continue
        perms, _owner, size, _date, _time, name = parts
        name = name.split(" -> ")[0]
        if name.startswith("squashfs-root"):
            name = name[len("squashfs-root"):]
        try:
            size = int(size)
        except ValueError:
            size = 0
        _add(result, name, size, perms.startswith("d"))

    for name, _size, _is_dir in result["entries"]:
        if "/" not in name and name.endswith(".desktop"):
            desktop = _run(["unsquashfs", "-cat", "-o", str(offset), path, name], timeout=5)
            for line in desktop.stdout.splitlines():
                if line.startswith("Name="):
                    result["details"]["Application"] = line[5:].strip()
                    break
            break

    mode = os.stat(path).st_mode
    result["details"]["executable"] = bool(mode & stat.S_IXUSR)
    if not result["entries"]:
        raise RuntimeError("could not read the AppImage's file system")
    return result


def make_executable(path):
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | (stat.S_IXGRP if mode & stat.S_IRGRP else 0))
