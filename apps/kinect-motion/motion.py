#!/usr/bin/env python3
"""The old Kinect Fitness / Kinect Arcade / Kinect Room command, kept for shortcuts and scripts.

    motion.py fitness | arcade | room [--fullscreen] [--demo] [--game walls|pose|race]

Everything is one app now (apps/kinect/kinect.py): this opens it on the matching section
(arcade = Games), in the window that is already open if there is one.
"""

import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "kinect" / "kinect.py"

if __name__ == "__main__":
    os.execv(sys.executable, [sys.executable, str(APP), *(sys.argv[1:] or ["fitness"])])
