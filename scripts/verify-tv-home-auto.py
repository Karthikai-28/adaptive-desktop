#!/usr/bin/env python3
"""Pure checks for Adaptive Home's off/on edge detector."""

import importlib.util
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "apps/adaptive-tv/auto_launch.py"
spec = importlib.util.spec_from_file_location("adaptive_tv_auto", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

state = module.WakeState(off_samples=3)
assert state.update(True), "an already-on TV launches at service start"
assert not state.update(True), "an online TV does not relaunch repeatedly"
assert not state.update(False), "one failed probe does not re-arm"
assert not state.update(True), "a Wi-Fi wobble does not relaunch"
assert not state.update(False)
assert not state.update(False)
assert not state.update(False)
assert state.update(True), "a confirmed off/on cycle launches once"
assert not state.update(True)

print("Adaptive Home auto-launch: all checks passed")
