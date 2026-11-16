#!/usr/bin/env python3
"""Read-only fingerprint detection and setup guards; no physical reader required."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fingerprint", ROOT / "scripts/fingerprint.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


class Reader:
    def devices(self): return ["/reader"]
    def default_device(self): return "/reader"
    def name(self, path): return "Fixture reader"
    def stages(self, path): return 6
    def fingers(self, path): return ["right-index-finger", "left-thumb"]


def main():
    result = F.probe(Reader)
    assert result["state"] == "enrolled" and result["readers"][0]["enrolled"] == 2
    assert result["readers"][0]["default"] and result["readers"][0]["stages"] == 6
    with patch.object(Reader, "fingers", side_effect=F.ProbeError(F.BUS + ".Error.NoEnrolledPrints", "none")):
        assert F.probe(Reader)["state"] == "enrollment-required"
    with patch.object(Reader, "devices", return_value=[]):
        result = F.probe(Reader)
        assert result["state"] == "no-supported-reader" and not result["can_setup"]
        with patch.object(F.subprocess, "call") as run:
            assert F.enable_sudo(result) == 1
            assert F.setup(result) == 1
            run.assert_not_called()
    for error in ("PermissionDenied", "DeviceDisconnected", "NoReply"):
        with patch.object(Reader, "fingers", side_effect=F.ProbeError(error, "unavailable")):
            result = F.probe(Reader)
            assert result["state"] == "unavailable" and not result["can_setup"]
    with patch.object(Reader, "devices", side_effect=F.ProbeError("bus-unavailable", "offline")):
        assert F.probe(Reader)["state"] == "unavailable"
    result = F.probe(Reader)
    result.update(gdm_pam_present=True, sudo_enabled=False)
    with patch.object(F, "login_policy") as policy:
        policy.return_value.get_boolean.return_value = False
        policy.return_value.is_writable.return_value = False
        assert F.enable_login(result) == 1
        policy.return_value.set_boolean.assert_not_called()
    with patch.object(F.Path, "is_file", return_value=True), patch.object(F.shutil, "which", return_value="pkexec"), \
            patch.object(F.subprocess, "call", return_value=126) as run:
        assert F.enable_sudo(result) == 126
        assert run.call_args.args[0] == ["pkexec", "/usr/sbin/pam-auth-update", "--enable", "fprintd"]
    # Small-sensor matcher: only the VFS7552 needs it; installed means both files.
    tmp = Path(__import__("tempfile").mkdtemp())
    dropin, lib = tmp / "dropin.conf", tmp / "libfprint-2.so.2"
    assert F.matcher_state([{"name": "Fixture reader"}], dropin, lib) == "not-needed"
    vfs = [{"name": "Validity VFS7552"}]
    assert F.matcher_state(vfs, dropin, lib) == "missing"
    dropin.write_text("[Service]\n")
    assert F.matcher_state(vfs, dropin, lib) == "missing"
    lib.write_bytes(b"")
    assert F.matcher_state(vfs, dropin, lib) == "installed"

    # Enrollment hints walk the fingertip: centre, then tip, then edges.
    ui = importlib.util.spec_from_file_location("fingerprint_ui", ROOT / "apps/adaptive-settings/fingerprint_ui.py")
    source = (ROOT / "apps/adaptive-settings/fingerprint_ui.py").read_text()
    hint_src = source[source.index("def placement_hint"):source.index("\nclass ")]
    space = {}
    exec(hint_src, space)
    hint = space["placement_hint"]
    assert "centre" in hint(1, 12) and "tip" in hint(5, 12) and "edges" in hint(9, 12)
    assert "Saving" in hint(12, 12) and "1 of 12" in hint(1, 12)

    # The shipped patch keeps the measured threshold and never ships the frame dump.
    patch_text = (ROOT / "fingerprint/libfprint-vfs7552-pattern.patch").read_text(errors="replace")
    assert "+#define VFS7552_PATTERN_THRESHOLD 15" in patch_text
    assert "+#define VFS7552_ENROLL_STAGES 12" in patch_text
    assert "+#ifndef VFS7552_RESEARCH_DUMP" in patch_text
    print("Fingerprint detection, multiple fingers, permission failures, setup guards, "
          "small-sensor matcher state and enrollment hints passed")


if __name__ == "__main__":
    main()
