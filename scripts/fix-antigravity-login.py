#!/usr/bin/env python3
"""Check or repair Antigravity IDE 2.5.5's login persistence.

This build saves unified state only on clean shutdown. Persist OAuth state
changes as they arrive so a killed process does not lose the login. Uses the
IDE's existing storage; never reads or copies account credentials.

Default: check only. --apply backs up the application bundle and patches it;
--restore restores that bundle only if it still matches this patch. Restart
the IDE after applying or restoring. A missing login still needs a sign-in.
"""

import argparse
import json
import os
from pathlib import Path
import stat
import tempfile


VERSION = "2.5.5"
BEFORE = "this._updateEmitters[n].emit(o);return}finally{i.dispose()}}async pushSerializedUpdateIPC"
AFTER = ('this._updateEmitters[n].emit(o);if(n==="uss-oauth")'
         'await this._persistTopic(n);return}finally{i.dispose()}}async pushSerializedUpdateIPC')


def patched(source):
    if source.count(AFTER) == 1 and BEFORE not in source:
        return source
    if source.count(BEFORE) != 1 or AFTER in source:
        raise ValueError("Unrecognized application code; no files changed")
    return source.replace(BEFORE, AFTER, 1)


def replace_file(path, content, mode):
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
            os.fchmod(out.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=Path("/opt/antigravity-ide"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    app = args.app_dir / "resources/app"
    version = json.loads((app / "product.json").read_text())["ideVersion"]
    if version != VERSION:
        raise ValueError(f"Expected IDE {VERSION}, found {version}; no files changed")
    bundle = app / "out/main.js"
    backup = bundle.with_name("main.js.adaptive-login-backup")
    source = bundle.read_text(encoding="utf-8")
    mode = stat.S_IMODE(bundle.stat().st_mode)

    if args.restore:
        original = backup.read_text(encoding="utf-8")
        if BEFORE not in original or source != patched(original):
            raise ValueError("Bundle differs from the saved patch; refusing to overwrite it")
        replace_file(bundle, original, mode)
        print("Original bundle restored. Restart Antigravity IDE to use it.")
        return

    fixed = patched(source)
    if fixed == source:
        print("Login persistence patch is already installed.")
        return
    if not args.apply:
        print(f"IDE {version}: login state is saved only at clean shutdown.")
        print("Compatible patch available. Use --apply, then restart the IDE and sign in.")
        return

    if backup.exists():
        if backup.read_text(encoding="utf-8") != source:
            raise ValueError("An unrelated backup exists; no files changed")
    else:
        # Exclusive creation preserves any previous backup.
        with backup.open("x", encoding="utf-8", newline="") as out:
            out.write(source)
            out.flush()
            os.fsync(out.fileno())
            os.fchmod(out.fileno(), mode)
    replace_file(bundle, fixed, mode)
    print("Login changes now persist without waiting for a clean exit.")
    print(f"Backup: {backup}")
    print("Restart Antigravity IDE to load the patch, then sign in if needed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from None
