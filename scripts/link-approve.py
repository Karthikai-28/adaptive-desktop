#!/usr/bin/env python3
"""Ask the owner's phone to approve something with its fingerprint.

Made for sudo, through PAM (scripts/install-link-sudo.sh):

    auth sufficient pam_exec.so quiet /usr/local/lib/adaptive-link/link-approve

It exits 0 if the phone said yes, and anything else falls through to the
password as before.

It runs as root and asks a daemon that runs as the user, so it does not take
the daemon's word for anything. It makes up a number, has the phone sign
that number with the key in its secure hardware, and checks the signature
itself against the phone's public key - a copy kept in /etc, where only root
can change it. A program running as the user can ask the phone (and the
owner will see a request they did not expect), but it cannot make up the
phone's answer.

Only the standard library and openssl, so that root needs nothing installed.
"""

import base64
import http.client
import json
import os
import pwd
import secrets
import socket
import subprocess
import sys
import tempfile

APPROVERS = "/etc/adaptive-link/approvers"
WAIT_S = 40


class _Unix(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def message(what, nonce):
    """What the phone signs. The same as companion.approval_message."""
    return f"adaptive-link approve\n{what}\n{nonce}".encode()


def ask(path, what, text, nonce):
    """The daemon's answer, or {} if it cannot be asked."""
    try:
        connection = _Unix(path, WAIT_S)
        connection.request("POST", "/approve", json.dumps({"what": what, "text": text, "nonce": nonce}),
                           {"Content-Type": "application/json"})
        reply = connection.getresponse().read(64 * 1024)
        answer = json.loads(reply)
    except (OSError, ValueError, http.client.HTTPException):
        return {}
    return answer if isinstance(answer, dict) else {}


def signed_by_a_phone(folder, what, nonce, signature_b64):
    """Whether the signature is that of one of the public keys in `folder`."""
    try:
        signature = base64.b64decode(str(signature_b64), validate=True)
        keys = sorted(entry.path for entry in os.scandir(folder) if entry.name.endswith(".pem"))
    except (OSError, ValueError):
        return False
    if not keys or not 8 <= len(signature) <= 200:
        return False
    with tempfile.TemporaryDirectory() as scratch:
        with open(os.path.join(scratch, "sig"), "wb") as handle:
            handle.write(signature)
        with open(os.path.join(scratch, "msg"), "wb") as handle:
            handle.write(message(what, nonce))
        for key in keys:
            try:
                done = subprocess.run(["openssl", "dgst", "-sha256", "-verify", key, "-signature",
                                       os.path.join(scratch, "sig"), os.path.join(scratch, "msg")],
                                      capture_output=True, timeout=10, check=False)
            except (OSError, subprocess.SubprocessError):
                continue
            if done.returncode == 0:
                return True
    return False


def main():
    user = os.environ.get("PAM_USER") or pwd.getpwuid(os.getuid()).pw_name
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return 1
    # Where the keys are and where the daemon is can be pointed elsewhere
    # only by someone who is not root: for the checks, never for sudo.
    testing = os.geteuid() != 0
    folder = (testing and os.environ.get("LINK_APPROVERS")) or os.path.join(APPROVERS, user)
    path = (testing and os.environ.get("LINK_SOCKET")) or f"/run/user/{uid}/adaptive-link.sock"
    what = "sudo"
    nonce = secrets.token_hex(16)
    answer = ask(path, what, f"{user} is asking for administrator rights on {socket.gethostname()}", nonce)
    if answer.get("ok") is True and signed_by_a_phone(folder, what, nonce, answer.get("signature", "")):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
