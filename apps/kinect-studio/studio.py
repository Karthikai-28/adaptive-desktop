#!/usr/bin/env python3
"""The old Kinect Studio command, kept for shortcuts, Mario and scripts.

Kinect Studio is the Camera section of the Kinect app now (apps/kinect/kinect.py): this opens it
there, in the window that is already open if there is one. The hub still serves Studio's own page
at http://127.0.0.1:8792 for a browser.
"""

import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "kinect" / "kinect.py"

if __name__ == "__main__":
    os.execv(sys.executable, [sys.executable, str(APP), "camera", *sys.argv[1:]])
