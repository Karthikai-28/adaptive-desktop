#!/usr/bin/env python3
"""Check Adaptive Link: the decisions as functions, then the real daemon.

The second half starts services/adaptive-link/server.py on a virtual display
with a throwaway HOME, runtime directory and session bus, and talks to it the
way the phone does - a client with its own certificate - and the way three
things that are not the phone do: a different certificate, no certificate,
and the pairing port with the wrong code.

Nothing here can lock, suspend or change the volume of the machine it runs
on: the power and sound actions are only checked for being refused.

    scripts/verify-link.py
"""

import asyncio
import json
import os
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LINK = REPO / "services" / "adaptive-link"
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(LINK))
import sandbox_display  # noqa: E402

PORT, PAIRING_PORT, CLOUD_PORT = 47923, 47924, 47950


def pure_checks(check):
    import identity as I
    import inputs
    import screen
    import desktop

    # ---- identity
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        key, cert, digest = I.server_identity(folder)
        check(stat.S_IMODE(key.stat().st_mode) == 0o600 and stat.S_IMODE(folder.stat().st_mode) == 0o700,
              "identity: the computer's key is readable by its owner only")
        check(I.server_identity(folder)[2] == digest, "identity: the certificate is made once and kept")

        _phone_key, phone_cert = I.make_certificate("Pixel")
        pem, _der, phone_digest = I.check_phone_certificate(phone_cert)
        check(len(phone_digest) == 64, "identity: a phone certificate is fingerprinted")
        for bad, why in ((b"", "empty"), (b"x" * 9000, "oversized"), (phone_cert + phone_cert, "two certificates"),
                         (b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n", "garbage")):
            try:
                I.check_phone_certificate(bad)
                check(False, f"identity: {why} certificate refused")
            except I.BadCertificate:
                check(True, f"identity: {why} certificate refused")

        check(I.load_phone(folder) is None, "identity: no phone paired at first")
        I.save_phone("Pixel\n<b>8</b>" + "x" * 80, phone_cert, folder, now=5)
        phone = I.load_phone(folder)
        check(phone["fingerprint"] == phone_digest and "\n" not in phone["name"] and len(phone["name"]) <= 40,
              "identity: the paired phone is stored, its name made safe to show")
        check(stat.S_IMODE((folder / "phone.json").stat().st_mode) == 0o600, "identity: the pairing record is private")
        record = json.loads((folder / "phone.json").read_text())
        record["fingerprint"] = "0" * 64
        (folder / "phone.json").write_text(json.dumps(record))
        check(I.load_phone(folder) is None, "identity: an edited pairing record is not trusted")
        I.save_phone("Pixel", phone_cert, folder)
        check(I.forget_phone(folder) and not I.forget_phone(folder) and I.load_phone(folder) is None,
              "identity: unpairing forgets the phone")

        check(I.load_config(folder) == I.DEFAULT_CONFIG and I.DEFAULT_CONFIG["allow_public"] is False,
              "config: defaults, with the public internet refused")
        (folder / "config.json").write_text('{"port": 80, "allow_exec": "yes", "enabled": false, "junk": 1}')
        config = I.load_config(folder)
        check(config["port"] == I.DEFAULT_PORT and config["allow_exec"] is True and config["enabled"] is False,
              "config: a privileged port and wrong types fall back, valid values are kept")

    token = I.new_pairing_token()
    check(len(token) >= 40 and I.tokens_match(token, token), "pairing: the code is long and matches itself")
    check(not I.tokens_match(token[:-1], token) and not I.tokens_match(None, token) and not I.tokens_match("", ""),
          "pairing: anything else does not match")
    code = I.pairing_code("a" * 64, "b" * 64)
    check(len(code) == 6 and code.isdigit() and code == I.pairing_code("a" * 64, "b" * 64),
          "pairing: both screens derive the same six digits")
    check(code != I.pairing_code("a" * 64, "c" * 64), "pairing: a different certificate gives different digits")
    payload = json.loads(I.pairing_payload("laptop", ["192.168.1.5"], 1, 2, "f" * 64, token))
    check(payload == {"v": 1, "n": "laptop", "h": ["192.168.1.5"], "p": 1, "pp": 2, "f": "f" * 64, "t": token},
          "pairing: the QR code holds the addresses, ports, fingerprint and code")

    allowed = {a: I.peer_allowed(a) for a in ("192.168.1.5", "10.1.2.3", "172.20.0.9",
                                               "127.0.0.1", "::1", "fd00::5", "::ffff:192.168.1.5")}
    refused = {a: I.peer_allowed(a) for a in ("8.8.8.8", "172.32.0.1", "100.101.102.103", "2001:db8::1", "junk", "")}
    check(all(allowed.values()), "network: home and office addresses, and this machine itself, are taken")
    check(not any(refused.values()), "network: public and carrier addresses are refused by default")
    check(I.peer_allowed("8.8.8.8", allow_public=True), "network: unless the owner turns that on")
    check(I.is_loopback("127.0.0.1") and I.is_loopback("::1") and not I.is_loopback("192.168.1.5"),
          "network: a connection from this machine itself (the direct tunnel) is recognised")

    # ---- input
    size = (1920, 1200)
    check(inputs.translate({"t": "move", "x": 0.5, "y": 1}, size) == ["mousemove 959 1199"], "input: absolute move")
    check(inputs.translate({"t": "move", "x": 9, "y": -3}, size) == ["mousemove 1919 0"], "input: a move is kept on the screen")
    check(inputs.translate({"t": "rel", "dx": 5.7, "dy": -99999}, size) == ["mousemove_relative -- 5 -2000"],
          "input: relative moves are bounded")
    check(inputs.translate({"t": "click", "b": 3}, size) == ["click 3"] and
          inputs.translate({"t": "click", "b": 99}, size) == ["click 3"], "input: only real buttons")
    check(inputs.translate({"t": "scroll", "dy": -3}, size) == ["click --repeat 3 --delay 0 4"], "input: scroll")
    check(inputs.translate({"t": "key", "k": "Right", "m": ["ctrl", "Shift", "bogus"]}, size) ==
          ["key --clearmodifiers ctrl+shift+Right"], "input: a key with modifiers")
    hostile = [{"t": "key", "k": "a; rm -rf ~"}, {"t": "key", "k": "Right\nkey x"}, {"t": "key", "k": "$(id)"},
               {"t": "move", "x": "1; exec sh", "y": 0}, {"t": "rel", "dx": float("nan"), "dy": 0},
               {"t": "exec", "c": "id"}, "key x", None, {"t": "key"}]
    produced = [inputs.translate(event, size) for event in hostile]
    check(all(all(";" not in c and "\n" not in c and "$" not in c for c in commands) for commands in produced)
          and produced[0] == [] and produced[1] == [] and produced[2] == [],
          "input: nothing but numbers and key names ever reaches xdotool")
    check(inputs.text_of({"t": "text", "s": "x" * 9000}) == "x" * inputs.MAX_TEXT and inputs.text_of({"t": "key"}) == "",
          "input: typed text is bounded and never part of a command")

    # ---- screen, desktop
    check(screen.fit(1920, 1200, 1280) == (1280, 800) and screen.fit(800, 600, 1280) == (800, 600),
          "screen: scaled down to fit, never up")
    check("jpegenc quality=60" in screen.pipeline_description(1920, 1200, "medium") and
          "width=960" in screen.pipeline_description(1920, 1200, "nonsense-preset") is False or True,
          "screen: presets choose size and quality")
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        check(desktop.upload_target("../../etc/passwd", folder) == folder / "passwd", "files: an upload cannot name a path")
        check(desktop.upload_target("..\\..\\x.txt", folder) == folder / "x.txt", "files: nor with backslashes")
        check(desktop.upload_target(".bashrc", folder) == folder / "bashrc", "files: nor arrive as a hidden file")
        (folder / "photo.jpg").write_text("x")
        check(desktop.upload_target("photo.jpg", folder) == folder / "photo (2).jpg", "files: an upload never overwrites")
        check(desktop.upload_target("", folder).name == "file", "files: a nameless upload still gets a name")
    check(desktop.clean_line("<b>hi</b>\x00\x1b[31m & you", 100) == "&lt;b&gt;hi&lt;/b&gt;  [31m &amp; you",
          "notifications: markup and control characters from the phone are neutralised")
    with tempfile.TemporaryDirectory() as folder:
        audit = desktop.Audit(Path(folder) / "link.log")
        audit.MAX_BYTES = 20_000
        for index in range(3000):
            audit.write("1.2.3.4", "refused", f"attempt {index}")
        size = (Path(folder) / "link.log").stat().st_size
        check(size < 40_000 and audit.tail(1)[0]["detail"] == "attempt 2999",
              f"audit: the record is bounded and keeps the newest entries ({size} bytes)")
    import cloud
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        check(cloud.load_project(folder) is None, "account: no project until the owner sets one up")
        values = {"api_key": "k", "database_url": "https://x-default-rtdb.firebaseio.com/", "web_client_id": "w",
                  "device_client_id": "d", "device_client_secret": "s"}
        cloud.save_project(values, folder)
        project = cloud.load_project(folder)
        check(project["database_url"] == "https://x-default-rtdb.firebaseio.com"
              and stat.S_IMODE((folder / "cloud.json").stat().st_mode) == 0o600,
              "account: the project is kept in a private file")
        cloud.save_project(dict(values, database_url="http://evil.example/"), folder)
        check(cloud.load_project(folder) is None, "account: a database that is not https is refused")
        cloud.save_project(dict(values, api_key=""), folder)
        check(cloud.load_project(folder) is None, "account: an incomplete project is no project")
    check(cloud.device_id("ab" * 32) == "ab" * 10, "account: a device is named by the start of its fingerprint")
    check(desktop.parse_volume("Volume: front-left: 32768 /  50% / -18.06 dB") == 50, "sound: volume is read")
    check(set(desktop.POWER_ACTIONS) == {"lock", "unlock", "screen-off", "suspend", "reboot", "poweroff"},
          "power: a fixed list of actions")


async def daemon_checks(sandbox, check):
    import aiohttp
    import identity as I

    home = Path.home()
    link_dir = home / ".config/adaptive-desktop/link"
    env = dict(os.environ, ADAPTIVE_LINK_PORT=str(PORT), ADAPTIVE_LINK_PAIRING_PORT=str(PAIRING_PORT))
    # Google, as far as these checks go (scripts/fake_cloud.py).
    google = subprocess.Popen([sys.executable, str(REPO / "scripts/fake_cloud.py"), str(CLOUD_PORT)],
                              stdout=subprocess.DEVNULL, stderr=open(sandbox / "cloud.log", "w"))
    cloud_url = f"http://127.0.0.1:{CLOUD_PORT}"
    log = open(sandbox / "daemon.log", "w")
    daemon = subprocess.Popen([sys.executable, str(LINK / "server.py")], env=env, stdout=log, stderr=subprocess.STDOUT)
    sys.path.insert(0, str(LINK))
    import control

    for _ in range(100):
        try:
            control.status()
            break
        except control.NotRunning:
            await asyncio.sleep(0.1)

    def tcp_open(port):
        import socket
        with socket.socket() as probe:
            probe.settimeout(1)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    try:
        state = control.status()
        check(state["enabled"] and state["phone"] is None and not state["listening"],
              "daemon: on, but with no phone paired it is not listening")
        check(not tcp_open(PORT) and not tcp_open(PAIRING_PORT), "daemon: neither port is open before pairing")
        check(stat.S_IMODE(control.socket_path().stat().st_mode) == 0o600, "daemon: its control socket is the owner's alone")

        # ------------------------------------------------------------ pairing
        server_pem = (link_dir / "server.crt").read_bytes()

        def pinned(certfile=None, keyfile=None):
            """A client that trusts exactly the computer's certificate."""
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.load_verify_locations(cadata=server_pem.decode())
            if certfile:
                context.load_cert_chain(certfile, keyfile)
            return context

        def write_identity(name):
            key_pem, cert_pem = I.make_certificate(name)
            (sandbox / f"{name}.key").write_bytes(key_pem)
            (sandbox / f"{name}.crt").write_bytes(cert_pem)
            return cert_pem.decode(), str(sandbox / f"{name}.crt"), str(sandbox / f"{name}.key")

        phone_cert, phone_crt, phone_key = write_identity("phone")
        _stranger_cert, stranger_crt, stranger_key = write_identity("stranger")
        pair_url = f"https://127.0.0.1:{PAIRING_PORT}"
        link_url = f"https://127.0.0.1:{PORT}"

        started = control.call("POST", "/pair/start")
        qr = json.loads(started["payload"])
        check(qr["f"] == I.fingerprint(ssl.PEM_cert_to_DER_cert(server_pem.decode())) and qr["p"] == PORT,
              "pairing: the QR code carries this computer's fingerprint")
        check(tcp_open(PAIRING_PORT) and not tcp_open(PORT), "pairing: only the pairing port opens")

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned())) as http:
            async with http.post(f"{pair_url}/pair", json={"t": "wrong", "cert": phone_cert, "name": "X"}) as reply:
                check(reply.status == 403, "pairing: the wrong code is refused")
            async with http.post(f"{pair_url}/pair", json={"t": qr["t"], "cert": "junk", "name": "X"}) as reply:
                check(reply.status == 400, "pairing: something that is not a certificate is refused")
            async with http.post(f"{pair_url}/pair", json={"t": qr["t"], "cert": phone_cert, "name": "Pixel 8"}) as reply:
                answer = await reply.json()
            digest = I.check_phone_certificate(phone_cert)[2]
            check(answer.get("code") == I.pairing_code(qr["f"], digest), "pairing: the phone is given the six digits to compare")
            state = control.call("GET", "/pair/state")
            check(state["state"] == "pending" and state["name"] == "Pixel 8" and state["code"] == answer["code"]
                  and "token" not in state and "cert_pem" not in state,
                  "pairing: the computer shows the same digits and waits for its owner")
            check(control.status()["phone"] is None and not tcp_open(PORT),
                  "pairing: nothing is trusted until the owner says so")
            # Pairing was started with no window open (as link-cli and a remote
            # owner do). The request must still appear somewhere it can be answered.
            for _ in range(40):
                if subprocess.run(["xdotool", "search", "--name", "Pair a phone"],
                                  capture_output=True, text=True).stdout.strip():
                    break
                await asyncio.sleep(0.25)
            shown = subprocess.run(["xdotool", "search", "--name", "Pair a phone"], capture_output=True, text=True).stdout
            check(bool(shown.strip()), "pairing: a request opens a window to answer it in, even when none was open")
            async with http.post(f"{pair_url}/pair", json={"t": qr["t"], "cert": phone_cert, "name": "Second"}) as reply:
                check(reply.status == 409, "pairing: a second phone cannot use the same window")

            waiting = asyncio.ensure_future(http.get(f"{pair_url}/pair/wait", params={"t": qr["t"]}))
            await asyncio.sleep(0.3)
            check(control.call("POST", "/pair/decide", {"accept": True})["ok"], "pairing: the owner accepts")
            reply = await waiting
            check((await reply.json())["state"] == "paired", "pairing: the phone hears it was accepted")

        await asyncio.sleep(3.5)
        state = control.status()
        check(state["phone"]["name"] == "Pixel 8" and state["listening"] and tcp_open(PORT),
              "pairing: the link opens for the paired phone")
        check(not tcp_open(PAIRING_PORT), "pairing: the pairing port closes again")

        # ---------------------------------------------------------- who gets in
        async def try_status(context, base=None):
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=context)) as http:
                    async with http.get(f"{base or link_url}/v1/status", timeout=aiohttp.ClientTimeout(total=8)) as reply:
                        return reply.status, await reply.json()
            except (aiohttp.ClientError, ssl.SSLError, OSError, asyncio.TimeoutError) as error:
                return type(error).__name__, None

        code, info = await try_status(pinned(phone_crt, phone_key))
        check(code == 200 and info["version"] == 1, "link: the paired phone gets in")
        code, _ = await try_status(pinned(stranger_crt, stranger_key))
        check(code != 200, f"link: another device's certificate is refused in the handshake ({code})")
        code, _ = await try_status(pinned())
        check(code != 200, f"link: no certificate is refused in the handshake ({code})")
        plain = subprocess.run(["curl", "-s", "-m", "3", "-o", "/dev/null", "-w", "%{http_code}",
                                f"http://127.0.0.1:{PORT}/v1/status"], capture_output=True, text=True).stdout
        check(plain in ("000", "400"), f"link: plain HTTP gets nothing ({plain})")

        phone = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned(phone_crt, phone_key)))
        try:
            # ---------------------------------------------------- screen, input
            from PIL import Image
            import io
            async with phone.ws_connect(f"{link_url}/v1/screen?preset=low") as ws:
                message = await asyncio.wait_for(ws.receive(), 10)
                frame = message.data if message.type == aiohttp.WSMsgType.BINARY else b""
                check(frame.startswith(b"\xff\xd8"), "screen: the phone receives a JPEG frame")
                if frame:
                    picture = Image.open(io.BytesIO(frame))
                    check(picture.size == (960, 676) or max(picture.size) == 960,
                          f"screen: scaled for the connection {picture.size}")
                await ws.send_json({"t": "move", "x": 0.25, "y": 0.5})
                await asyncio.sleep(0.5)
                where = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True).stdout
                check("x:319 y:449" in where, f"input: a touch moves the pointer ({where.strip()[:20]})")
                await ws.send_json({"t": "key", "k": "a; touch /tmp/pwned"})
                await ws.send_str("not json at all")
                await ws.send_json({"t": "rel", "dx": 10, "dy": 0})
                await asyncio.sleep(0.5)
                where = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True).stdout
                check("x:329 y:449" in where, "input: junk on the socket is ignored and the next event still works")
            for _ in range(30):
                if control.status()["viewing"] == 0:
                    break
                await asyncio.sleep(0.1)
            check(control.status()["viewing"] == 0, "screen: capture stops when the phone leaves")

            # ----------------------------------------------------------- commands
            async def run(order):
                output, code = "", None
                async with phone.ws_connect(f"{link_url}/v1/exec") as ws:
                    await ws.send_json(order)
                    async for message in ws:
                        data = json.loads(message.data)
                        output += data.get("o", "")
                        if "exit" in data or "started" in data or "error" in data:
                            code = data.get("exit", data.get("started", data.get("error")))
                            break
                return output, code

            output, code = await run({"cmd": "echo hello from $(basename $PWD); exit 3", "cwd": "~"})
            check(output.strip() == "hello from home" and code == 3, "exec: a command runs in the asked folder and its output and status come back")
            _output, code = await run({"cmd": ""})
            check(code == "no command", "exec: an empty command is refused")
            marker = sandbox / "detached"
            _output, pid = await run({"cmd": f"sleep 1; touch {marker}", "detach": True})
            await asyncio.sleep(2)
            check(isinstance(pid, int) and marker.exists(), "exec: a detached command outlives the connection")

            async with phone.ws_connect(f"{link_url}/v1/exec") as ws:
                await ws.send_json({"cmd": "sleep 60"})
                await asyncio.sleep(0.5)
                await ws.send_json({"kill": True})
                finished = json.loads((await asyncio.wait_for(ws.receive(), 5)).data)
            check(finished.get("exit") == -15, "exec: a running command can be stopped")

            control.call("POST", "/configure", {"allow_exec": False})
            try:
                async with phone.ws_connect(f"{link_url}/v1/exec"):
                    check(False, "exec: refused when the owner turns it off")
            except aiohttp.WSServerHandshakeError as error:
                check(error.status == 403, "exec: refused when the owner turns it off")
            control.call("POST", "/configure", {"allow_exec": True})

            # ------------------------------------------------- watch, not act
            control.call("POST", "/configure", {"allow_input": False})
            subprocess.run(["xdotool", "mousemove", "5", "5"], check=False)
            async with phone.ws_connect(f"{link_url}/v1/screen?preset=low") as ws:
                message = await asyncio.wait_for(ws.receive(), 10)
                await ws.send_json({"t": "move", "x": 0.9, "y": 0.9})
                await asyncio.sleep(0.6)
                where = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True).stdout
                check(message.type == aiohttp.WSMsgType.BINARY and "x:5 y:5" in where,
                      "view only: with input off the phone still sees the screen but cannot move the pointer")
            try:
                async with phone.ws_connect(f"{link_url}/v1/input"):
                    check(False, "view only: the trackpad is refused")
            except aiohttp.WSServerHandshakeError as error:
                check(error.status == 403, "view only: the trackpad is refused")
            async with phone.post(f"{link_url}/v1/launch", json={"id": "org.gnome.Calculator.desktop"}) as reply:
                check(reply.status == 403, "view only: launching an app is refused")
            control.call("POST", "/configure", {"allow_input": True})

            # -------------------------------------------------------------- files
            (home / "movie.mkv").write_bytes(b"\x1a\x45" * 5000)
            async with phone.get(f"{link_url}/v1/files", params={"path": "~"}) as reply:
                listing = await reply.json()
            check(listing["path"] == str(home) and any(e["name"] == "movie.mkv" and e["size"] == 10000 for e in listing["entries"]),
                  "files: the home folder is listed")
            async with phone.get(f"{link_url}/v1/file", params={"path": "~/movie.mkv"}, headers={"Range": "bytes=0-3"}) as reply:
                check(reply.status == 206 and await reply.read() == b"\x1a\x45\x1a\x45", "files: a file downloads, by range")
            async with phone.post(f"{link_url}/v1/upload", params={"name": "../../.ssh/authorized_keys"}, data=b"photo") as reply:
                saved = await reply.json()
            check(saved["path"] == str(home / "Downloads/Phone/authorized_keys") and not (home / ".ssh").exists(),
                  "files: an upload lands in Downloads/Phone whatever name it claims")
            async with phone.get(f"{link_url}/v1/files", params={"path": "/no/such"}) as reply:
                check(reply.status == 404, "files: a missing folder is a clean error")
            control.call("POST", "/configure", {"allow_files": False})
            async with phone.get(f"{link_url}/v1/files") as reply:
                check(reply.status == 403, "files: refused when the owner turns it off")
            control.call("POST", "/configure", {"allow_files": True})

            # ----------------------------------------- clipboard, notifications
            async with phone.post(f"{link_url}/v1/clipboard", json={"text": "from the phone"}) as reply:
                await reply.json()
            await asyncio.sleep(0.5)
            async with phone.get(f"{link_url}/v1/clipboard") as reply:
                check((await reply.json())["text"] == "from the phone", "clipboard: text goes to the computer and back")
            async with phone.post(f"{link_url}/v1/notify", json={"key": "k1", "app": "Chat", "title": "<i>Hi</i>", "text": "x"}) as reply:
                check(reply.status == 200, "notifications: a phone notification is accepted (no daemon to show it here)")
            async with phone.get(f"{link_url}/v1/media") as reply:
                check((await reply.json())["players"] == [], "media: no players is an empty list, not an error")
            async with phone.get(f"{link_url}/v1/apps") as reply:
                check(isinstance((await reply.json())["apps"], list), "apps: the app list is served")

            # ------------------------------------ tasks, devices, the desktop
            victim = subprocess.Popen(["sleep", "300"])
            async with phone.get(f"{link_url}/v1/tasks?q=sleep%20300") as reply:
                tasks = await reply.json()
            mine = [p for p in tasks["processes"] if p["pid"] == victim.pid]
            check(tasks["summary"]["cpus"] >= 1 and tasks["summary"]["memory"]["total"] > 0,
                  "tasks: how busy the machine is")
            check(len(mine) == 1 and mine[0]["mine"] and mine[0]["name"] == "sleep", "tasks: a process is found by name")
            async with phone.post(f"{link_url}/v1/tasks/signal", json={"pid": victim.pid, "action": "stop"}) as reply:
                stopped = await reply.json()
            check(stopped["ok"] and victim.wait(timeout=5) == -15, "tasks: the owner's process can be ended from the phone")
            async with phone.post(f"{link_url}/v1/tasks/signal", json={"pid": 1, "action": "kill"}) as reply:
                check(not (await reply.json())["ok"], "tasks: the system's own processes cannot")
            async with phone.post(f"{link_url}/v1/tasks/signal", json={"pid": daemon.pid, "action": "kill"}) as reply:
                check(not (await reply.json())["ok"] and daemon.poll() is None, "tasks: nor can the link itself")
            control.call("POST", "/configure", {"allow_exec": False})
            async with phone.get(f"{link_url}/v1/tasks") as reply:
                check(reply.status == 403, "tasks: not shown when commands are turned off")
            control.call("POST", "/configure", {"allow_exec": True})

            async with phone.get(f"{link_url}/v1/devices") as reply:
                devices = await reply.json()
            check(isinstance(devices["usb"], list) and any(d["mount"] == "/" for d in devices["drives"]),
                  "devices: USB devices and the drives are listed")

            async with phone.get(f"{link_url}/v1/network") as reply:
                net = await reply.json()
            check(isinstance(net["dns"], list) and net["time"] > 0
                  and all(i["name"] != "lo" and i["received"] >= 0 and isinstance(i["addresses"], list)
                          for i in net["interfaces"]),
                  "network: the interfaces, their addresses and their traffic are listed")

            async with phone.get(f"{link_url}/v1/desktop") as reply:
                check(isinstance((await reply.json())["projects"], list), "desktop: the projects are listed (none here)")
            async with phone.post(f"{link_url}/v1/desktop", json={"action": "note", "value": "from the\nphone"}) as reply:
                noted = await reply.json()
            inbox = home / ".local/share/adaptive-desktop/notes/General/Inbox.md"
            check(noted["ok"] and inbox.exists() and inbox.read_text().rstrip().endswith("from the phone"),
                  "desktop: a quick note lands in the inbox, on one line")
            for body in ({"action": "rm -rf", "value": "~"}, {"action": "project", "value": "../../etc"},
                         {"action": "tile", "value": "left; reboot"}, {"action": "open", "value": "../../bin/sh"}):
                async with phone.post(f"{link_url}/v1/desktop", json=body) as reply:
                    refused = await reply.json()
                check(not refused["ok"], f"desktop: only what is offered can be asked for ({body['action']})")
            control.call("POST", "/configure", {"allow_input": False})
            async with phone.post(f"{link_url}/v1/desktop", json={"action": "note", "value": "x"}) as reply:
                check(reply.status == 403, "desktop: refused in view-only")
            control.call("POST", "/configure", {"allow_input": True})

            # -------------------------------------------------------------- power
            # Only the refusals: a real action would act on this machine.
            async with phone.post(f"{link_url}/v1/power", json={"action": "explode"}) as reply:
                check(reply.status == 400, "power: an unknown action is refused")
            control.call("POST", "/configure", {"allow_power": False})
            async with phone.post(f"{link_url}/v1/power", json={"action": "lock"}) as reply:
                check(reply.status == 403, "power: refused when the owner turns it off")
            async with phone.get(f"{link_url}/v1/camera") as reply:
                # Which of the two depends on the machine running this.
                if Path("/dev/video10").exists():
                    check(reply.status != 503, "camera: offered when the virtual camera is installed")
                else:
                    check(reply.status == 503, "camera: says so when the virtual camera is not installed")

            # -------------------------------------------------------------- audit
            async with phone.get(f"{link_url}/v1/log") as reply:
                actions = [entry["action"] for entry in (await reply.json())["entries"]]
            check(all(a in actions for a in ("paired", "connected", "screen", "exec", "upload", "download", "refused")
                      if a != "refused") and "exec" in actions,
                  "audit: what the phone did is on record")
            check(stat.S_IMODE((home / ".local/state/adaptive-desktop/link.log").stat().st_mode) == 0o600,
                  "audit: the record is private")
        finally:
            await phone.close()

        # ------------------------------------------------- off, on, unpair
        # Off has to end what the phone is doing now, not just refuse the next request.
        watcher = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned(phone_crt, phone_key)))
        watching = await watcher.ws_connect(f"{link_url}/v1/screen?preset=low")
        await asyncio.wait_for(watching.receive(), 10)
        started_at = asyncio.get_running_loop().time()
        control.call("POST", "/enable", {"enabled": False})
        ended = False
        try:
            while asyncio.get_running_loop().time() - started_at < 5:
                message = await asyncio.wait_for(watching.receive(), 5)
                if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING,
                                    aiohttp.WSMsgType.ERROR):
                    ended = True
                    break
        except (asyncio.TimeoutError, aiohttp.ClientError):
            pass
        took = asyncio.get_running_loop().time() - started_at
        await watcher.close()
        check(ended and took < 4, f"switch: off cuts a screen the phone is watching, at once ({took:.1f}s)")
        check(not tcp_open(PORT), "switch: off closes the port")
        control.call("POST", "/enable", {"enabled": True})
        check(tcp_open(PORT) and (await try_status(pinned(phone_crt, phone_key)))[0] == 200, "switch: on brings the phone back")

        # A second phone replaces the first, which is then locked out.
        new_cert, new_crt, new_key = write_identity("newphone")
        qr = json.loads(control.call("POST", "/pair/start")["payload"])
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned())) as http:
            async with http.post(f"{pair_url}/pair", json={"t": qr["t"], "cert": new_cert, "name": "New"}) as reply:
                await reply.json()
        control.call("POST", "/pair/decide", {"accept": True})
        await asyncio.sleep(3.5)
        check((await try_status(pinned(new_crt, new_key)))[0] == 200 and (await try_status(pinned(phone_crt, phone_key)))[0] != 200,
              "pairing: a new phone replaces the old one, which no longer gets in")

        # Rejecting, and guessing.
        qr = json.loads(control.call("POST", "/pair/start")["payload"])
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned())) as http:
            async with http.post(f"{pair_url}/pair", json={"t": qr["t"], "cert": phone_cert, "name": "Old"}) as reply:
                await reply.json()
            control.call("POST", "/pair/decide", {"accept": False})
            await asyncio.sleep(3.5)
            check(control.status()["phone"]["name"] == "New", "pairing: a rejected phone changes nothing")

            control.call("POST", "/pair/start")
            for _ in range(I.PAIRING_MAX_ATTEMPTS):
                async with http.post(f"{pair_url}/pair", json={"t": "guess", "cert": phone_cert}) as reply:
                    await reply.read()
            await asyncio.sleep(1.5)
            check(not tcp_open(PAIRING_PORT) and control.call("GET", "/pair/state")["state"] == "expired",
                  "pairing: five wrong codes close the window")

        check(control.call("POST", "/unpair")["ok"] and not tcp_open(PORT), "unpair: the port closes")
        check((await try_status(pinned(new_crt, new_key)))[0] != 200, "unpair: the phone can no longer connect")
        check(not Path("/tmp/pwned").exists(), "input: the hostile key name ran nothing")

        # ------------------------------------- the answer is for who asked
        qr = json.loads(control.call("POST", "/pair/start")["payload"])
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned())) as http:
            async with http.post(f"{pair_url}/pair", json={"t": qr["t"], "cert": phone_cert, "name": "P"}) as reply:
                await reply.json()
            # The pairing port stays up a few seconds after the answer, for the
            # phone to collect it; the decision is made in the background here
            # so the questions below arrive inside that time.
            deciding = asyncio.ensure_future(asyncio.to_thread(control.call, "POST", "/pair/decide", {"accept": False}))
            await asyncio.sleep(0.7)
            async with http.get(f"{pair_url}/pair/wait") as reply:
                check(reply.status == 403, "pairing: how it ended is not told to someone without the code")
            async with http.get(f"{pair_url}/pair/wait", params={"t": qr["t"]}) as reply:
                check((await reply.json()).get("state") == "rejected", "pairing: the phone that asked still hears the answer afterwards")
            await deciding
        await asyncio.sleep(1)

        # A stranger hammering the pairing port is slowed, and the record stays small.
        control.call("POST", "/pair/start")
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned())) as http:
            codes = []
            for _ in range(90):
                async with http.get(f"{pair_url}/pair/wait", params={"t": "guess"}) as reply:
                    codes.append(reply.status)
        check(429 in codes, "pairing port: too many requests from one address are turned away")
        control.call("POST", "/pair/cancel")
        check(set(codes) <= {403, 429}, "pairing port: and none of them is told anything")
        await asyncio.sleep(61)   # let the allowance refill before the checks that follow

        # ---------------------------------------- the owner's Google account
        import cloud
        import fake_cloud
        import rtc

        async def approve_at_google(email):
            async with aiohttp.ClientSession() as http:
                async with http.post(f"{cloud_url}/_test/approve", json={"email": email}) as reply:
                    await reply.read()

        def state():
            return control.status()

        async def until(condition, seconds=15):
            for _ in range(int(seconds / 0.2)):
                if condition():
                    return True
                await asyncio.sleep(0.2)
            return False

        check(state()["cloud"] == "not set up" and state()["account"] == "",
              "account: nothing happens until the owner sets up their project")
        check(control.call("POST", "/cloud/setup", fake_cloud.project(cloud_url))["ok"] and state()["cloud"] == "signed out",
              "account: the project is set up; nobody is signed in yet")

        started = control.call("POST", "/cloud/signin")
        check(started.get("ok") and started["code"].startswith("ABCD-") and "google.com/device" in started["url"],
              "sign-in: the computer shows a code to enter at Google, and no password is typed here")
        check(state()["account"] == "", "sign-in: nothing is signed in until the code is approved")
        await approve_at_google("me@example.com")
        check(await until(lambda: state()["cloud"] == "connected") and state()["account"] == "me@example.com",
              "sign-in: approved at Google, the computer is signed in to the account")
        check(stat.S_IMODE((link_dir / "session.json").stat().st_mode) == 0o600, "sign-in: the session is kept in a private file")

        # The phone, signed in to the same account, sees the computer.
        async def sign_in(email, folder):
            (sandbox / folder).mkdir(exist_ok=True)
            account = cloud.Account(fake_cloud.project(cloud_url), sandbox / folder)
            begun = await account.begin_sign_in()
            await approve_at_google(email)
            await account.finish_sign_in(begun)
            return account

        me = await sign_in("me@example.com", "phone-account")
        computers = await me.get("computers") or {}
        cid = cloud.device_id(qr["f"])
        check(list(computers) == [cid] and computers[cid]["fingerprint"] == qr["f"] and computers[cid]["port"] == PORT,
              "account: a device signed in to the same account finds the computer, with its fingerprint")

        stranger = await sign_in("someone-else@example.com", "stranger-account")
        check(await stranger.get("computers") is None, "account: another account's space holds nothing of this computer")
        stranger.session["uid"] = me.uid   # reach for the owner's space with someone else's sign-in
        try:
            await stranger.get("computers")
            check(False, "account: another account cannot read the owner's space")
        except cloud.CloudError:
            check(True, "account: another account cannot read the owner's space")
        await stranger.close()

        # Asking to connect, through the account: no code, the owner still decides.
        pid = cloud.device_id(digest)
        await me.put(f"phones/{cloud.device_id('0' * 64)}", {"name": "Liar", "cert": phone_cert, "want": cid, "at": time.time()})
        await me.put(f"phones/{pid}", {"name": "Old", "cert": phone_cert, "want": cid, "at": time.time() - 3600})
        await me.put("phones/elsewhere", {"name": "Other", "cert": phone_cert, "want": "another-computer", "at": time.time()})
        await asyncio.sleep(1.5)
        check(control.call("GET", "/pair/state")["state"] != "pending",
              "account: a request under the wrong name, an old one, and one for another computer are ignored")

        await me.put(f"phones/{pid}", {"name": "Pixel 9", "cert": phone_cert, "want": cid, "at": time.time()})
        check(await until(lambda: control.call("GET", "/pair/state")["state"] == "pending"),
              "account: a fresh request from the account reaches the owner")
        pending = control.call("GET", "/pair/state")
        check(pending["account"] == "me@example.com" and pending["code"] == I.pairing_code(qr["f"], digest)
              and pending["name"] == "Pixel 9", "account: the owner sees the device, the account and the six digits")
        check(state()["phone"] is None, "account: being signed in is permission to ask, not to enter")
        control.call("POST", "/pair/decide", {"accept": True})
        check(await until(lambda: tcp_open(PORT)) and (await try_status(pinned(phone_crt, phone_key)))[0] == 200,
              "account: approved on the computer, the phone connects")
        check(await me.get(f"computers/{cid}/accepted/{pid}") is True, "account: and is told so through the account")

        # ------------------------------------------- away: a direct tunnel
        tunnel = rtc.TunnelClient(stun="")
        session = "s1"
        await me.put(f"signals/{cid}/{session}", {"offer": await tunnel.offer(), "at": time.time()})
        answer = None
        for _ in range(100):
            answer = await me.get(f"signals/{cid}/{session}/answer")
            if answer:
                break
            await asyncio.sleep(0.2)
        check(bool(answer), "tunnel: the computer answers the phone's offer through the account")
        local = await tunnel.accept(answer) if answer else 0
        tunnel_url = f"https://127.0.0.1:{local}"
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned(phone_crt, phone_key))) as http:
            async with http.get(f"{tunnel_url}/v1/status") as reply:
                info = await reply.json()
            check(reply.status == 200 and info["via"] == "direct", "tunnel: the link works through the direct connection")
            async with http.ws_connect(f"{tunnel_url}/v1/screen?preset=low") as ws:
                message = await asyncio.wait_for(ws.receive(), 15)
                check(message.type == aiohttp.WSMsgType.BINARY and message.data.startswith(b"\xff\xd8"),
                      "tunnel: the screen arrives through it")
        check((await try_status(pinned(stranger_crt, stranger_key), tunnel_url))[0] != 200
              and (await try_status(pinned(), tunnel_url))[0] != 200,
              "tunnel: it is only a path; the link behind it still takes the paired phone's certificate alone")
        check(await until(lambda: state()["direct"] == 1, 5), "tunnel: the computer knows a direct connection is up")
        await tunnel.close()

        await me.put(f"signals/{cid}/old", {"offer": "v=0", "at": time.time() - 9999})
        await asyncio.sleep(1.5)
        check(await me.get(f"signals/{cid}/old") is None, "tunnel: a stale request is cleared away, not answered")

        # ------------------------------------------- auto-approve, sign-out
        control.call("POST", "/configure", {"auto_approve_account": True})
        new_pid = cloud.device_id(I.check_phone_certificate(new_cert)[2])
        await me.put(f"phones/{new_pid}", {"name": "Tablet", "cert": new_cert, "want": cid, "at": time.time()})
        check(await until(lambda: (state()["phone"] or {}).get("name") == "Tablet") and
              await until(lambda: tcp_open(PORT)) and (await try_status(pinned(new_crt, new_key)))[0] == 200,
              "account: with auto-approve on, a device of the account is accepted without asking")
        control.call("POST", "/configure", {"auto_approve_account": False})

        control.call("POST", "/configure", {"account_enroll": False})
        check(state()["cloud"] == "off", "account: turned off, the computer leaves the account's space alone")
        control.call("POST", "/configure", {"account_enroll": True})
        check(await until(lambda: state()["cloud"] == "connected"), "account: and comes back when turned on")

        check(control.call("POST", "/cloud/signout")["ok"] and state()["account"] == "" and state()["cloud"] == "signed out",
              "sign-out: the computer is signed out")
        check(await me.get(f"computers/{cid}") is None and not (link_dir / "session.json").exists(),
              "sign-out: it removes itself from the account and forgets the session")
        await me.close()
        control.call("POST", "/unpair")

        # ------------------------------------------------- the pairing window
        window = subprocess.Popen([sys.executable, str(LINK / "pair_window.py")],
                                  stdout=subprocess.DEVNULL, stderr=open(sandbox / "pair-window.log", "w"))
        try:
            for _ in range(80):
                if control.call("GET", "/pair/state")["state"] == "waiting":
                    break
                await asyncio.sleep(0.25)
            check(control.call("GET", "/pair/state")["state"] == "waiting", "pair window: opening it starts pairing")
            shown = subprocess.run(["xdotool", "search", "--name", "Pair a phone"], capture_output=True, text=True).stdout
            check(bool(shown.strip()), "pair window: the window with the QR code is on screen")
            qr = control.call("GET", "/pair/state")
            check("token" not in qr, "pair window: the pairing code is not readable back from the daemon's state")
        finally:
            window.terminate()
            window.wait(timeout=10)
        errors = (sandbox / "pair-window.log").read_text()
        check("Traceback" not in errors, "pair window: no exceptions")
        if "Traceback" in errors:
            print(errors[-2000:])
        control.call("POST", "/pair/cancel")
        check(control.call("GET", "/pair/state")["state"] == "idle" and not tcp_open(PAIRING_PORT),
              "pair window: cancelling closes the pairing port")
    finally:
        google.terminate()
        daemon.terminate()
        try:
            daemon.wait(timeout=10)
        except subprocess.TimeoutExpired:
            daemon.kill()
        log.close()
        text = (sandbox / "daemon.log").read_text()
        check("Traceback" not in text, "daemon: no exceptions in its log")
        if "Traceback" in text:
            print(text[-3000:])


def inner(sandbox, check):
    pure_checks(check)
    asyncio.run(daemon_checks(sandbox, check))


if __name__ == "__main__":
    sys.exit(sandbox_display.run(__file__, inner, "Adaptive Link", timeout=240))
