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
import stat
import subprocess
import sys
import tempfile

APPROVERS = "/etc/adaptive-link/approvers"
PHONES = ".config/adaptive-desktop/link/phones.json"
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


def paired_keys(phones_file):
    """The public keys of the devices the user has paired now, from the
    daemon's own list, as openssl writes them (which is how the installer
    wrote root's copies). Read as root from a file the user controls, so
    it only ever narrows what root's copies allow: a device unpaired since
    install-link-sudo.sh ran is trusted no longer."""
    try:
        fd = os.open(phones_file, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return set()
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            return set()
        with os.fdopen(fd, "rb") as handle:
            fd = None
            phones = json.loads(handle.read())["phones"]
    except (OSError, ValueError, KeyError, TypeError):
        return set()
    finally:
        if fd is not None:
            os.close(fd)
    keys = set()
    for phone in phones if isinstance(phones, list) else []:
        pem = phone.get("cert_pem") if isinstance(phone, dict) else None
        if not isinstance(pem, str):
            continue
        try:
            done = subprocess.run(["openssl", "x509", "-pubkey", "-noout"], input=pem.encode(),
                                  capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and done.stdout:
            keys.add(done.stdout)
    return keys


def signed_by_a_phone(folder, what, nonce, signature_b64, paired=None):
    """Whether the signature is that of one of the public keys in `folder`
    (of those, with `paired`, only the ones that are in it)."""
    try:
        signature = base64.b64decode(str(signature_b64), validate=True)
        keys = sorted(entry.path for entry in os.scandir(folder) if entry.name.endswith(".pem"))
        if paired is not None:
            keys = [key for key in keys if open(key, "rb").read(64 * 1024) in paired]
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
    home = (testing and os.environ.get("HOME")) or pwd.getpwnam(user).pw_dir
    paired = paired_keys(os.path.join(home, PHONES))
    if not paired:
        return 1
    what = "sudo"
    nonce = secrets.token_hex(16)
    answer = ask(path, what, f"{user} is asking for administrator rights on {socket.gethostname()}", nonce)
    if answer.get("ok") is True and signed_by_a_phone(folder, what, nonce, answer.get("signature", ""), paired):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
