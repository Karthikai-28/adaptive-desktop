"""Puts the link's own Python packages first on the path.

The peer-to-peer library (aiortc) lives beside the repository's other local
tools, in .local/link-pydeps, with the newer cryptography and pyOpenSSL it
needs; Ubuntu 22.04's python3-cryptography (3.4) is too old for them. One
process has one cryptography, and it is whichever is imported first, so this
must be imported before anything that imports cryptography - the identity
module included. Only this process sees the order; the system's packages are
untouched.
"""

import os
import sys
from pathlib import Path

PATH = os.environ.get("ADAPTIVE_LINK_PYDEPS") or str(
    Path(__file__).resolve().parent.parent.parent / ".local" / "link-pydeps")

if os.path.isdir(PATH):
    if PATH in sys.path:
        sys.path.remove(PATH)
    sys.path.insert(0, PATH)
