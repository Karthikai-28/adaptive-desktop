#!/usr/bin/env python3
"""Check that what one shell module takes from another is really there.

    const CC = Me.imports.ccUtil;
    ... CC.makeRow(...)                 <- is makeRow something ccUtil.js exports?
    const { run, makeRow } = CcUtil;    <- and these?

A GJS module exports its top-level `var`, `function` and `class`
declarations. A name that is not among them is `undefined` at the call site:
the module loads, the extension enables, and it throws when the code is
reached - for a menu, the first time it is opened. Moving a helper from one
file to another is exactly how that happens, and no syntax check or linter
sees it, because a property of another module is not a name in this one.

    verify-shell-imports.py shell/adaptive-shell@local
"""

import re
import sys
from pathlib import Path

IMPORT = re.compile(r"^const (\w+) = Me\.imports\.(\w+);", re.M)
EXPORT = re.compile(r"^(?:var|function|class)\s+([A-Za-z_]\w*)", re.M)
# `let` and `const` are reachable from another module too (GJS warns), so a
# use of one is not a failure - but it is reported, since ES modules drop it.
LEGACY = re.compile(r"^(?:let|const)\s+([A-Za-z_]\w*)", re.M)
DESTRUCTURE = re.compile(r"const \{([^}]*)\} = (\w+);", re.S)


def main(directory):
    directory = Path(directory)
    sources = {path.stem: path.read_text() for path in sorted(directory.glob("*.js"))}
    exports = {name: set(EXPORT.findall(text)) for name, text in sources.items()}
    legacy = {name: set(LEGACY.findall(text)) for name, text in sources.items()}
    failures = 0
    uses = 0

    for name, text in sources.items():
        for alias, module in IMPORT.findall(text):
            if module not in sources:
                print(f"FAIL {name}.js imports {module}.js, which does not exist")
                failures += 1
                continue
            wanted = set(re.findall(rf"\b{re.escape(alias)}\.([A-Za-z_]\w*)", text))
            for block, source in DESTRUCTURE.findall(text):
                if source == alias:
                    wanted |= {item.split(":")[0].strip() for item in block.split(",") if item.strip()}
            wanted.discard("imports")
            for member in sorted(wanted):
                uses += 1
                if member in exports[module]:
                    continue
                if member in legacy[module]:
                    print(f"note {name}.js uses {module}.{member}, declared with let/const")
                    continue
                line = next((number for number, row in enumerate(text.splitlines(), 1)
                             if re.search(rf"\b{re.escape(alias)}\.{member}\b|\b{member}\b,?$", row)), "?")
                print(f"FAIL {name}.js:{line} uses {module}.{member}, which {module}.js does not export")
                failures += 1

    if failures:
        print(f"{failures} import(s) point at something that is not exported")
        return 1
    print(f"OK {uses} uses of other shell modules all resolve to an export")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  Path(__file__).resolve().parent.parent / "shell" / "adaptive-shell@local"))
