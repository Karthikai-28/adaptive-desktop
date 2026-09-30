#!/usr/bin/env python3
"""SSH to a device from the shell's Network panel, remembering the password.

    ssh_connect.py saved <host>          {"user": ..., "has_password": bool}
    ssh_connect.py connect <host> [user] try the login, then open a terminal
    ssh_connect.py forget <host>         drop the remembered user and password
    ssh_connect.py askpass               (internal) the ssh password prompt

`connect` reads {"user": ..., "password": ...} as JSON on stdin (both optional:
the remembered ones fill in). It logs in once in the background first, so a
wrong password, a closed port or a changed host key is reported to the panel
instead of dying in a terminal that flashes shut. Only when that works is a
terminal opened, running the same ssh; the password is saved to the login
keyring at that point and never earlier.

The password is never in argv or in a file. ssh asks for it through
SSH_ASKPASS, which is this script: during the probe it is handed over in the
environment, in the terminal it is read back from the keyring.

Output is one JSON object: {"ok": true} or {"ok": false, "error": "...",
"need_password": bool}.
"""

import json
import os
import shutil
import subprocess
import sys

import gi

gi.require_version("Secret", "1")
from gi.repository import Secret  # noqa: E402

SCHEMA = Secret.Schema.new(
    "local.adaptive.ssh", Secret.SchemaFlags.NONE,
    {"host": Secret.SchemaAttributeType.STRING, "user": Secret.SchemaAttributeType.STRING},
)
STATE = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                     "adaptive-desktop", "ssh_hosts.json")
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "NumberOfPasswordPrompts=1"]


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), mode=0o700, exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f)


def get_password(host, user):
    try:
        return Secret.password_lookup_sync(SCHEMA, {"host": host, "user": user}, None)
    except Exception:
        return None


def store_password(host, user, password):
    try:
        return Secret.password_store_sync(
            SCHEMA, {"host": host, "user": user}, Secret.COLLECTION_DEFAULT,
            f"SSH {user}@{host}", password, None)
    except Exception:
        return False


def clear_password(host, user):
    try:
        Secret.password_clear_sync(SCHEMA, {"host": host, "user": user}, None)
    except Exception:
        pass


def ssh_env(host, user, password=None):
    env = dict(os.environ)
    env["SSH_ASKPASS"] = os.path.abspath(__file__)
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["ADAPTIVE_SSH_HOST"] = host
    env["ADAPTIVE_SSH_USER"] = user
    if password is not None:
        env["ADAPTIVE_SSH_PASSWORD"] = password
    return env


def explain(stderr, host):
    text = stderr.strip()
    low = text.lower()
    if "permission denied" in low:
        return "Wrong username or password"
    if "remote host identification has changed" in low or "host key verification failed" in low:
        return f"Host key for {host} changed - remove it from ~/.ssh/known_hosts if expected"
    if "connection refused" in low:
        return "SSH is not running on that device (connection refused)"
    if "timed out" in low:
        return "No answer - the device is off, asleep or blocks SSH"
    if "no route to host" in low or "network is unreachable" in low:
        return "No route to that device"
    if "could not resolve" in low:
        return f"Could not resolve {host}"
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "SSH failed"


def probe(host, user, password):
    # With no password, BatchMode says whether a key (or agent) already works.
    argv = ["/usr/bin/ssh", *SSH_OPTS, "-o", "ConnectTimeout=6"]
    argv += ["-o", "BatchMode=yes"] if password is None else []
    argv += [f"{user}@{host}", "true"]
    try:
        run = subprocess.run(argv, capture_output=True, text=True, timeout=20,
                             env=ssh_env(host, user, password), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, "No answer - the device is off, asleep or blocks SSH"
    if run.returncode == 0:
        return True, ""
    return False, explain(run.stderr, host)


def open_terminal(host, user):
    ssh = ["ssh", *SSH_OPTS, f"{user}@{host}"]
    if shutil.which("terminator"):
        argv = ["terminator", "-T", f"{user}@{host}", "-x", *ssh]
    elif shutil.which("gnome-terminal"):
        argv = ["gnome-terminal", "--title", f"{user}@{host}", "--", *ssh]
    else:
        argv = ["x-terminal-emulator", "-e", *ssh]
    subprocess.Popen(argv, env=ssh_env(host, user), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def connect(host, user_arg):
    try:
        given = json.load(sys.stdin)
    except ValueError:
        given = {}
    state = load_state()
    user = given.get("user") or user_arg or state.get(host) or os.environ.get("USER", "")
    typed = given.get("password") or None
    password = typed or get_password(host, user)

    ok, error = probe(host, user, password)
    if not ok and password is None:
        # No key and nothing remembered: the panel has to ask.
        if "permission denied" in error.lower() or "Wrong username" in error:
            return {"ok": False, "need_password": True, "user": user,
                    "error": "This device needs a password"}
    if not ok:
        if password is not None and not typed and error == "Wrong username or password":
            clear_password(host, user)  # the remembered one is stale
            return {"ok": False, "need_password": True, "user": user,
                    "error": "Saved password no longer works"}
        return {"ok": False, "need_password": error == "Wrong username or password",
                "user": user, "error": error}

    if typed:
        store_password(host, user, typed)
    state[host] = user
    save_state(state)
    open_terminal(host, user)
    return {"ok": True}


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "askpass":
        # ssh calls this with the prompt as argv[1]; stdout is the answer.
        prompt = sys.argv[2] if len(sys.argv) > 2 else ""
        if "password" not in prompt.lower():
            sys.exit(1)  # host-key or passphrase questions: not ours to answer
        host, user = os.environ.get("ADAPTIVE_SSH_HOST", ""), os.environ.get("ADAPTIVE_SSH_USER", "")
        password = os.environ.get("ADAPTIVE_SSH_PASSWORD") or get_password(host, user)
        if not password:
            sys.exit(1)
        print(password)
        return
    if command == "saved" and len(sys.argv) > 2:
        host = sys.argv[2]
        user = load_state().get(host)
        result = {"user": user, "has_password": bool(user and get_password(host, user))}
    elif command == "connect" and len(sys.argv) > 2:
        result = connect(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    elif command == "forget" and len(sys.argv) > 2:
        host = sys.argv[2]
        state = load_state()
        user = state.pop(host, None)
        if user:
            clear_password(host, user)
        save_state(state)
        result = {"ok": True}
    else:
        result = {"ok": False, "error": "bad command"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
