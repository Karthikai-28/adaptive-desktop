"""The operator key: proof that a request comes from the owner, not from the manager or an agent.

Approving a hardware/external workflow run, deleting records with retention, and changing a saved
workflow need it. It is a random secret in DATA (mode 0600), which no agent sandbox mounts and the
manager's Claude is denied reading. The owner's own `office` command attaches it; a browser gets it once
from `office operator-key`. The server never sends it over HTTP.
"""
import hmac
import os
import secrets

from .config import DATA

KEY_FILE = DATA / "operator.key"


def key():
    try:
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return KEY_FILE.read_text().strip()
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_urlsafe(32) + "\n")
    return KEY_FILE.read_text().strip()


def valid(given):
    given = (given or "").strip()
    return bool(given) and hmac.compare_digest(given.encode(), key().encode())
