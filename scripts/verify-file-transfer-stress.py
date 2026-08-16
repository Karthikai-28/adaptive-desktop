#!/usr/bin/env python3
import shutil
import tempfile
from pathlib import Path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def unique_destination(target):
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    parent = target.parent

    for index in range(1, 1000):
        candidate = parent / f"{stem} copy {index}{suffix}"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Unable to choose a unique name for {target.name}")


def copy_item(source, destination, policy):
    target = destination / source.name

    if target.exists():
        if policy == "skip":
            return None
        if policy == "keep":
            target = unique_destination(target)
        elif policy == "replace":
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()

    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)

    return target


def move_item(source, destination, policy):
    target = copy_item(source, destination, policy)
    if target is None:
        return None
    if source.is_dir():
        shutil.rmtree(source)
    else:
        source.unlink()
    return target


def main():
    with tempfile.TemporaryDirectory(prefix="adaptive-transfer-") as tmp:
        root = Path(tmp)
        source = root / "source"
        destination = root / "destination"
        source.mkdir()
        destination.mkdir()

        write(source / "alpha.txt", "alpha")
        write(source / "nested" / "beta.txt", "beta")
        write(destination / "alpha.txt", "old-alpha")

        kept = copy_item(source / "alpha.txt", destination, "keep")
        assert kept is not None and kept.name == "alpha copy 1.txt"
        assert kept.read_text(encoding="utf-8") == "alpha"
        assert (destination / "alpha.txt").read_text(encoding="utf-8") == "old-alpha"

        replaced = copy_item(source / "alpha.txt", destination, "replace")
        assert replaced == destination / "alpha.txt"
        assert replaced.read_text(encoding="utf-8") == "alpha"

        skipped = copy_item(source / "alpha.txt", destination, "skip")
        assert skipped is None

        moved = move_item(source / "nested", destination, "keep")
        assert moved is not None
        assert (moved / "beta.txt").read_text(encoding="utf-8") == "beta"
        assert not (source / "nested").exists()

    print("Adaptive Files transfer stress verified.")


if __name__ == "__main__":
    main()
