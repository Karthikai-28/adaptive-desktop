"""Adaptive Link - talking to the running daemon from this computer.

The daemon listens on a Unix socket in the user's runtime directory
(server.control_socket_path). This is the small client for it, used by
link-cli, the pairing window and the palette. No dependencies beyond the
standard library, so it loads anywhere.
"""

import http.client
import json
import os
import socket
from pathlib import Path


def socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "adaptive-link.sock"


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


class NotRunning(Exception):
    """The daemon is not running (or not answering)."""


def call(method, path, body=None, timeout=10):
    """One request to the daemon; the decoded JSON reply."""
    connection = _UnixConnection(str(socket_path()), timeout)
    try:
        payload = json.dumps(body or {}).encode() if method == "POST" else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=payload, headers=headers)
        reply = connection.getresponse()
        return json.loads(reply.read() or b"{}")
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise NotRunning(str(error)) from None
    finally:
        connection.close()


def status():
    return call("GET", "/status")
