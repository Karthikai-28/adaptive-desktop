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
    print("Fingerprint detection, multiple fingers, permission failures and setup guards passed")


if __name__ == "__main__":
    main()
