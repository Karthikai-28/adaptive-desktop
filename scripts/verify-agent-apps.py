#!/usr/bin/env python3
"""Check adaptive-agent (agy, claude, codex as apps) on a private tmux server, without opening windows.

Stand-ins replace the agents and the login shell; nothing real is started.
"""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


REPO = Path(__file__).resolve().parent.parent
if not shutil.which("tmux"):
    print("SKIP adaptive-agent: tmux is not installed")
    sys.exit(0)


def load():
    spec = importlib.util.spec_from_file_location("adaptive_agent", REPO / "terminal/agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait(predicate, what, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return
        time.sleep(.1)
    raise AssertionError(what)


with tempfile.TemporaryDirectory(prefix="adaptive-agent-") as temporary:
    root = Path(temporary)
    (root / "bin").mkdir()
    (root / "work").mkdir()
    # The agent records what it was given, then exits: its shell must stay.
    (root / "bin/claude").write_text('#!/bin/sh\nprintf "%s|%s|%s|%s\\n" "$PWD" "${DISPLAY:-}" '
                                     '"${ADAPTIVE_MOBILE_ROOT:-}" "${GDK_SCALE:-}" >> "$AGENT_OUT"\n')
    # A login shell that reads no rc files, so the stand-in agent is found.
    (root / "sh").write_text('#!/bin/sh\nwhile [ $# -gt 0 ] && [ "$1" != -c ]; do shift; done\n'
                             '[ "$1" = -c ] && exec /bin/sh -c "$2"\nexec sleep 300\n')
    (root / "bin/kterm-terminal").write_text('#!/bin/sh\necho "$$ $*" > "$AGENT_OUT.terminal"\n')
    for name in ("bin/claude", "sh", "bin/kterm-terminal"):
        (root / name).chmod(0o755)
    out = root / "out"
    os.environ.update(ADAPTIVE_AGENT_SOCKET=f"adaptive-agent-verify-{os.getpid()}", ADAPTIVE_AGENT_ENV="inherit",
                      SHELL=str(root / "sh"), PATH=f"{root / 'bin'}:{os.environ['PATH']}", AGENT_OUT=str(out),
                      ADAPTIVE_MOBILE_ROOT=str(root / "phone"), GDK_SCALE="2", QT_SCALE_FACTOR="2", DISPLAY=":91")
    os.environ.pop("TMUX", None)
    agent = load()
    clients = []
    try:
        # Opened from the phone, the agent still gets the laptop's
        # environment: never the phone's display, root or scale.
        env = agent.laptop_env()
        env["SHELL"] = str(root / "sh")
        assert not {"ADAPTIVE_MOBILE_ROOT", "GDK_SCALE", "QT_SCALE_FACTOR", "DISPLAY"} & set(env), sorted(env)

        first = agent.choose("claude", False, None, env)
        assert first == "claude", first
        wait(lambda: out.is_file(), "the agent did not start in its session")
        folder, display, mobile, scale = out.read_text().splitlines()[0].split("|")
        assert (display, mobile, scale) == ("", "", ""), (display, mobile, scale)
        # It exited; its session stays, at a shell in the same folder.
        time.sleep(.3)
        assert agent.sessions("claude", env) == ["claude"]
        assert agent.choose("claude", False, None, env) == "claude"   # nothing shows it yet: reuse
        assert agent.choose("claude", True, None, env) == "claude-2"  # --new
        assert agent.choose("claude", False, root / "work", env) == "claude-3"
        wait(lambda: len(out.read_text().splitlines()) == 3, "the third session did not start")
        assert out.read_text().splitlines()[2].split("|")[0] == str(root / "work")

        # A session with a terminal on this screen is skipped; another
        # screen (the laptop, another phone) is offered it to share.
        def attach(name, **screen):
            client_env = dict(os.environ, TERM="xterm-256color", **screen)
            command = f"tmux -L {agent.SOCKET} -f {agent.config_file()} attach-session -t {name}"
            clients.append(subprocess.Popen(["script", "-qfc", command, "/dev/null"], env=client_env,
                                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        attach("claude", ADAPTIVE_MOBILE_ROOT=str(root / "phone"), DISPLAY=":91")
        wait(lambda: "claude" in agent.shown_here(env), "the phone's client was not seen")
        latest = agent.sessions("claude", env)
        assert latest[0] == "claude", latest  # attaching made it the most recent
        assert agent.choose("claude", False, None, env) == latest[1]
        os.environ.update(ADAPTIVE_MOBILE_ROOT="", DISPLAY=":1")  # the laptop
        assert agent.shown_here(env) == set()
        assert agent.choose("claude", False, None, env) == "claude"

        # From a desktop entry (no terminal), the launcher becomes the
        # terminal - the same process - titled after the agent.
        launched = subprocess.run([sys.executable, str(REPO / "terminal/agent.py"), "claude", "--new"],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        assert launched.returncode == 0, launched.stderr
        record = Path(str(out) + ".terminal").read_text().split()
        assert record[1:4] == ["--title", "Claude", "Code"] and record[4] == "4", record
        assert record[5:7] == ["-x", "tmux"] and record[-2:] == ["-t", "claude-4"], record
        assert agent.AGENTS.keys() == {"agy", "claude", "codex"}
        print("PASS adaptive-agent: laptop environment, shared sessions, one terminal per screen")
    finally:
        for client in clients:
            client.kill()
        subprocess.run(["tmux", "-L", os.environ["ADAPTIVE_AGENT_SOCKET"], "kill-server"], capture_output=True)
