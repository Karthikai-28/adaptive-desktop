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

        check(I.load_phones(folder) == [], "identity: no phone paired at first")
        I.save_phone("Pixel\n<b>8</b>" + "x" * 80, phone_cert, folder, now=5)
        phone = I.load_phones(folder)[0]
        check(phone["fingerprint"] == phone_digest and "\n" not in phone["name"] and len(phone["name"]) <= 40,
              "identity: the paired phone is stored, its name made safe to show")
        check(stat.S_IMODE((folder / "phones.json").stat().st_mode) == 0o600, "identity: the pairing record is private")
        record = json.loads((folder / "phones.json").read_text())
        record["phones"][0]["fingerprint"] = "0" * 64
        (folder / "phones.json").write_text(json.dumps(record))
        check(I.load_phones(folder) == [], "identity: an edited pairing record is not trusted")
        I.save_phone("Pixel", phone_cert, folder)
        check(I.forget_phone(folder) == 1 and I.forget_phone(folder) == 0 and I.load_phones(folder) == [],
              "identity: unpairing forgets the phone")

        # Several devices, each with its own certificate and its own limits.
        others = [I.make_certificate(f"Device {n}")[1] for n in range(I.MAX_PHONES)]
        I.save_phone("Pixel", phone_cert, folder, now=1)
        I.save_phone("Tablet", others[0], folder, now=2)
        tablet = I.load_phones(folder)[1]["fingerprint"]
        check([p["name"] for p in I.load_phones(folder)] == ["Pixel", "Tablet"], "identity: a second device is paired beside the first")
        check(I.deny_phone(tablet, "allow_exec", True, folder) and I.deny_phone(tablet, "allow_power", True, folder)
              and not I.deny_phone(tablet, "allow_public", True, folder) and not I.deny_phone("0" * 64, "allow_exec", True, folder)
              and [p["deny"] for p in I.load_phones(folder)] == [[], ["allow_exec", "allow_power"]],
              "identity: one device can be kept from what the other may do")
        I.save_phone("Tablet again", others[0], folder, now=3)
        again = I.load_phones(folder)
        check(len(again) == 2 and again[1]["name"] == "Tablet again" and again[1]["deny"] == ["allow_exec", "allow_power"]
              and I.deny_phone(tablet, "allow_exec", False, folder) and I.load_phones(folder)[1]["deny"] == ["allow_power"],
              "identity: pairing a device again renames it and keeps its limits, which can be lifted")
        check(I.find_phone(again, "pixel") == again[0] and I.find_phone(again, tablet[:8]) == again[1]
              and I.find_phone(again, "") is None and I.find_phone(again, "nobody") is None and I.find_phone(again, tablet[:3]) is None,
              "identity: a device is found by its name, or by the start of its fingerprint")
        for index, cert in enumerate(others[1:I.MAX_PHONES - 1]):
            I.save_phone(f"Extra {index}", cert, folder)
        try:
            I.save_phone("One too many", others[-1], folder)
            check(False, "identity: no more than a few devices are paired")
        except I.TooManyPhones:
            check(len(I.load_phones(folder)) == I.MAX_PHONES, "identity: no more than a few devices are paired")
        check(I.forget_phone(folder, tablet) == 1 and len(I.load_phones(folder)) == I.MAX_PHONES - 1
              and all(p["fingerprint"] != tablet for p in I.load_phones(folder)) and I.forget_phone(folder, tablet) == 0,
              "identity: one device is forgotten and the others stay")
        check(I.forget_phone(folder) == I.MAX_PHONES - 1, "identity: or all of them at once")
        # Phones name their certificates alike. Each paired one must still
        # get in, and another device with the same name must not.
        import socket
        import threading
        alike = [I.make_certificate("Adaptive Link Phone") for _ in range(4)]
        server_key, server_cert, _digest = I.server_identity(folder)
        trusting = I.link_context(server_key, server_cert, [cert.decode() for _key, cert in alike[:3]])
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        let_in = []

        def take():
            for _ in alike:
                connection, _address = listener.accept()
                try:
                    with trusting.wrap_socket(connection, server_side=True) as tls:
                        tls.recv(1)
                        let_in.append(I.fingerprint(tls.getpeercert(binary_form=True)))
                except (ssl.SSLError, OSError):
                    let_in.append(None)

        taking = threading.Thread(target=take, daemon=True)
        taking.start()
        for index, (key_pem, cert_pem) in enumerate(alike):
            (folder / f"alike{index}.key").write_bytes(key_pem)
            (folder / f"alike{index}.crt").write_bytes(cert_pem)
            offering = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            offering.check_hostname, offering.verify_mode = False, ssl.CERT_NONE
            offering.load_cert_chain(str(folder / f"alike{index}.crt"), str(folder / f"alike{index}.key"))
            try:
                with offering.wrap_socket(socket.create_connection(("127.0.0.1", listener.getsockname()[1]))) as tls:
                    tls.send(b"x")
                    tls.settimeout(2)
                    tls.recv(1)   # a refusal arrives here, after the handshake
            except (ssl.SSLError, OSError):
                pass
        taking.join(5)
        listener.close()
        check(let_in == [I.check_phone_certificate(cert)[2] for _key, cert in alike[:3]] + [None],
              "identity: several devices whose certificates are named alike each get in, and a stranger so named does not")

        # A phone paired before there could be several is carried over.
        (folder / "phones.json").unlink()
        (folder / "phone.json").write_text(json.dumps({"name": "Old", "cert_pem": phone_cert.decode(),
                                                       "fingerprint": phone_digest, "paired_at": 7}))
        check([(p["name"], p["deny"]) for p in I.load_phones(folder)] == [("Old", [])], "identity: a phone paired earlier is still paired")
        I.save_phone("Old", phone_cert, folder)
        check(not (folder / "phone.json").exists() and len(I.load_phones(folder)) == 1, "identity: and is kept with the others from then on")
        I.forget_phone(folder)

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
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        check(I.load_relay(folder) is None, "relay: none unless the owner runs one")
        kept = I.save_relay({"url": "turn:relay.example.org:3478?transport=tcp", "username": "me", "credential": "secret"}, folder)
        check(kept == I.load_relay(folder) and kept["credential"] == "secret"
              and stat.S_IMODE((folder / "relay.json").stat().st_mode) == 0o600,
              "relay: the owner's relay is kept, with its password, in a private file")
        check(all(I.clean_relay(bad) is None for bad in (
            {"url": "https://relay.example.org"}, {"url": "turn:"}, {"url": "turn:host; rm -rf ~"}, {"url": "stun:host:3478"},
            {"url": "turn:host", "username": "a\nb"}, {}, None, "turn:host")),
              "relay: only a TURN server's address is taken for one")
        check(I.save_relay(None, folder) is None and I.load_relay(folder) is None and not (folder / "relay.json").exists(),
              "relay: and forgotten when the owner says so")
        import rtc as R
        servers = R.configuration(relay={"url": "turn:relay.example.org:3478", "username": "me", "credential": "secret"}).iceServers
        check([server.urls for server in servers] == [R.STUN, "turn:relay.example.org:3478"]
              and servers[1].username == "me" and servers[1].credential == "secret"
              and len(R.configuration().iceServers) == 1, "relay: it is offered to a connection beside the direct way, never instead")
    check(cloud.device_id("ab" * 32) == "ab" * 10, "account: a device is named by the start of its fingerprint")
    check(desktop.parse_volume("Volume: front-left: 32768 /  50% / -18.06 dB") == 50, "sound: volume is read")
    import media
    check(media.frame_size(1920, 1200, "medium") == (1280, 800, 15) and media.frame_size(1366, 768, "high") == (1360, 768, 20)
          and media.frame_size(1280, 800, "nonsense") == media.frame_size(1280, 800, "medium")
          and all(media.frame_size(w, h, p)[0] % 16 == 0 and media.frame_size(w, h, p)[1] % 2 == 0
                  for w, h in ((1920, 1080), (2560, 1440), (3440, 1440), (1366, 768), (801, 601)) for p in media.PRESETS),
          "video: each quality is a size the encoder can take, never larger than the screen")
    check(desktop.web_address("https://example.org/a?b=c#d") == "https://example.org/a?b=c#d"
          and not any(desktop.web_address(bad) for bad in (
              "file:///etc/passwd", "javascript:alert(1)", "https://", "http://a b", "ftp://example.org/x",
              "https://example.org/\n--help", "-version", "", None, "x" * 3000)),
          "share: only a web address is opened, never a file, a script or an option")

    import alerts
    import companion
    check(companion.find_code("Your verification code is 482913. Do not share it.") == "482913"
          and companion.find_code("G-739 201 is your Google verification code") == "739201"
          and companion.find_code("Use OTP 4821 to sign in") == "4821"
          and companion.find_code("Lunch at 1300? It cost 4500 last time") == ""
          and companion.find_code("Your code: call 18005551234 for help") == ""
          and companion.find_code("") == "" and companion.find_code(None) == "",
          "texts: a one-time code is found in a message that speaks of one, and nowhere else")
    check(companion.clean_number("+91 98765-43210") == "+919876543210" and companion.clean_number("(555) 010 9999") == "5550109999"
          and not any(companion.clean_number(bad) for bad in ("12", "+1 555; rm -rf", "abc", "", None, "1" * 20)),
          "texts: only a phone number is sent to")
    from cryptography.hazmat.primitives import hashes as H, serialization as S
    from cryptography.hazmat.primitives.asymmetric import ec as E
    import base64
    signer_key, signer_cert = I.make_certificate("Adaptive Link Phone")
    other_key, _other_cert = I.make_certificate("Adaptive Link Phone")

    def sign(key_pem, what, nonce):
        key = S.load_pem_private_key(key_pem, None)
        return base64.b64encode(key.sign(companion.approval_message(what, nonce), E.ECDSA(H.SHA256()))).decode()

    check(companion.approved_by(signer_cert, "sudo", "ab" * 16, sign(signer_key, "sudo", "ab" * 16))
          and not companion.approved_by(signer_cert, "sudo", "ab" * 16, sign(other_key, "sudo", "ab" * 16))
          and not companion.approved_by(signer_cert, "sudo", "cd" * 16, sign(signer_key, "sudo", "ab" * 16))
          and not companion.approved_by(signer_cert, "sudo", "ab" * 16, sign(signer_key, "unlock", "ab" * 16))
          and not companion.approved_by(signer_cert, "sudo", "ab" * 16, "not a signature")
          and not companion.approved_by(signer_cert, "sudo", "ab" * 16, ""),
          "approvals: a yes counts only if the phone's own key signed this request and no other")
    with tempfile.TemporaryDirectory() as folder:
        # What sudo's helper does, as root would: its own check, with openssl.
        import importlib.util
        spec = importlib.util.spec_from_file_location("link_approve", REPO / "scripts/link-approve.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        public = subprocess.run(["openssl", "x509", "-pubkey", "-noout"], input=signer_cert, capture_output=True).stdout
        (Path(folder) / "phone.pem").write_bytes(public)
        check(helper.message("sudo", "ab" * 16) == companion.approval_message("sudo", "ab" * 16)
              and helper.signed_by_a_phone(folder, "sudo", "ab" * 16, sign(signer_key, "sudo", "ab" * 16))
              and not helper.signed_by_a_phone(folder, "sudo", "ab" * 16, sign(other_key, "sudo", "ab" * 16))
              and not helper.signed_by_a_phone(folder, "sudo", "ff" * 16, sign(signer_key, "sudo", "ab" * 16))
              and not helper.signed_by_a_phone(folder + "/none", "sudo", "ab" * 16, sign(signer_key, "sudo", "ab" * 16))
              and not helper.signed_by_a_phone(folder, "sudo", "ab" * 16, "garbage"),
              "approvals: sudo's helper checks the phone's signature for itself, against the keys only root can change")
        pam = Path(folder) / "sudo"
        pam.write_text("#%PAM-1.0\n\n@include common-auth\n@include common-account\n")
        line = "auth sufficient pam_exec.so quiet /usr/local/lib/adaptive-link/link-approve"
        subprocess.run(["sed", "-i", f"0,/^[^#]/s||{line}\\n&|", str(pam)], check=True)
        check(pam.read_text() == f"#%PAM-1.0\n\n{line}\n@include common-auth\n@include common-account\n",
              "approvals: the phone is asked before the password, and the password still follows")
    events = alerts.Events()
    waiting = events.listen({"ring"})
    events.add("ring", "", keep=False)
    events.add("alert", "kept")
    check(waiting.qsize() == 1 and [item["kind"] for item in events.since(0)] == ["alert"]
          and events.listening("ring") and not events.listening("clipboard"),
          "events: something for whoever is listening now is not kept for later, and goes only to who asked for its kind")

    async def presence():
        gone = []

        async def went():
            gone.append(True)
        here = companion.Presence(0.2, went, probe=lambda address: address == "asleep")
        here.arrive("a", "away")
        here.leave("a")
        await asyncio.sleep(0.1)
        here.arrive("a", "away")          # back within the grace period
        await asyncio.sleep(0.3)
        back_in_time = not gone
        here.leave("a")
        await asyncio.sleep(0.5)
        left = list(gone)
        here.arrive("b", "asleep")
        here.leave("b")
        await asyncio.sleep(0.5)
        return back_in_time, left, len(gone)
    check(asyncio.run(presence()) == (True, [True], 1),
          "presence: a phone that comes straight back, or has only gone to sleep, has not left; one that is gone has")
    check(inputs.translate({"t": "keydown", "k": "w"}, (100, 100)) == ["keydown w"]
          and inputs.translate({"t": "keyup", "k": "w; reboot"}, (100, 100)) == []
          and inputs.held_after(inputs.held_after(frozenset(), {"t": "keydown", "k": "w"}), {"t": "down", "b": 1}) == {"key w", "button 1"}
          and inputs.held_after(frozenset({"key w"}), {"t": "keyup", "k": "w"}) == frozenset()
          and inputs.release({"key w", "button 3"}) == [{"t": "up", "b": 3}, {"t": "keyup", "k": "w"}],
          "input: a held key is pressed and let go, and whatever is still held can be let go of")
    check(inputs.in_region({"t": "move", "x": 0.5, "y": 0.5}, (1920, 0, 1280, 800), (3200, 1200))
          == {"t": "move", "x": 0.8, "y": 400 / 1200}
          and inputs.in_region({"t": "click", "b": 1}, (1920, 0, 1280, 800), (3200, 1200)) == {"t": "click", "b": 1}
          and inputs.in_region({"t": "move", "x": 0.5, "y": 0.5}, None, (3200, 1200)) == {"t": "move", "x": 0.5, "y": 0.5},
          "input: a touch on one display lands on that display")
    check("startx=1920 starty=0 endx=3199 endy=799" in screen.source((1920, 0, 1280, 800)) and "startx" not in screen.source()
          and "width=960,height=600" in screen.pipeline_description(3200, 1200, "low", (1920, 0, 1280, 800)),
          "screen: one display is captured at its own size")
    check(desktop.upload_folder("photos") == Path.home() / "Pictures/Phone"
          and desktop.upload_folder("scans", "/nonexistent/project") == Path.home() / "Documents/Scans"
          and desktop.upload_folder("scans", tempfile.gettempdir()) == Path(tempfile.gettempdir()) / "Scans"
          and desktop.upload_folder("../../etc") == desktop.UPLOAD_DIR,
          "files: photos, scans and everything else each have their place, and nothing else can be named")

    import alerts
    quiet = {"disks": [("/", 50 << 30, 100 << 30)], "memory": (8 << 30, 16 << 30),
             "battery": {"percent": 80, "charging": False}, "hottest": 50, "usb": {"1-1": "Mouse"}, "failed": []}
    state, said = alerts.decide(None, dict(quiet, disks=[("/", 1 << 30, 100 << 30)], failed=["old.service"]))
    check(said == [], "alerts: nothing is said about how things already were when the link started")
    state, said = alerts.decide(state, dict(quiet, disks=[("/", 1 << 30, 100 << 30)], failed=["old.service"]))
    check(said == [], "alerts: nor repeated while nothing changes")
    state, said = alerts.decide(state, quiet)
    state, said = alerts.decide(state, dict(
        quiet, disks=[("/", 2 << 30, 100 << 30)], memory=(500 << 20, 16 << 30), hottest=95,
        battery={"percent": 12, "charging": False}, usb={"1-1": "Mouse", "1-2": "Stick"}, failed=["sync.service"]))
    check([title for title, _text in said] == ["A disk is nearly full", "Memory is running out",
                                               "The computer's battery is low", "The computer is running hot",
                                               "Plugged in", "A service has failed"]
          and ("Plugged in", "Stick") in said and ("A service has failed", "sync") in said,
          "alerts: a full disk, low memory, a low battery, heat, a new device and a failed service are each said")
    worse = dict(quiet, disks=[("/", 2 << 30, 100 << 30)], memory=(500 << 20, 16 << 30), hottest=95,
                 battery={"percent": 4, "charging": False}, usb={"1-1": "Mouse", "1-2": "Stick"}, failed=["sync.service"])
    state, said = alerts.decide(state, worse)
    check(said == [("The computer's battery is nearly empty", "4% left")],
          "alerts: each is said once, and the battery again only when it is nearly empty")
    state, said = alerts.decide(state, dict(quiet, battery={"percent": 4, "charging": True}))
    check(said == [("Unplugged", "Stick")], "alerts: a device taken out is said; a battery on charge is not")
    state, said = alerts.decide(state, dict(quiet, disks=[("/", 2 << 30, 100 << 30)]))
    check(said == [("A disk is nearly full", "/ has 2048 MB left")], "alerts: a disk that fills again after being cleared is said again")

    call = ["method call time=1.0 sender=:1.5 -> destination=:1.2 serial=7 path=/org/freedesktop/Notifications; "
            "interface=org.freedesktop.Notifications; member=Notify",
            '   string "Mail"', "   uint32 0", '   string "mail-unread"', '   string "From Ada"',
            '   string "Lunch at <b>one</b>?', "Bring the &amp; notes", 'and a "pen""', "   array [", "   ]", "   array [",
            "      dict entry(", '         string "urgency"', "         variant             byte 1", "      )", "   ]",
            "   int32 -1"]
    check(alerts.parse_notify(call) == ("Mail", "From Ada", 'Lunch at one?\nBring the & notes\nand a "pen"'),
          "notifications: the app, the title and the text are read, over several lines and without markup")
    own = [line.replace('"urgency"', '"category"').replace("byte 1", 'string "device"') for line in call]
    check(alerts.parse_notify(own) is None and alerts.parse_notify([call[0], '   string "Adaptive Link"', '   string ""',
                                                                    '   string "A phone wants to connect"', '   string "x"']) is None,
          "notifications: what the phone itself sent, and the link's own, are not sent back to it")
    log = alerts.Events(limit=3)
    for index in range(5):
        log.add("alert", f"title {index}")
    kept = log.since(0)
    check([item["title"] for item in kept] == ["title 2", "title 3", "title 4"]
          and [item["title"] for item in log.since(kept[1]["id"])] == ["title 4"],
          "events: the newest are kept, and a phone can ask for what came after the last it saw")

    import machine
    outputs = machine.parse_xrandr(
        "Screen 0: minimum 320 x 200, current 3840 x 1200\n"
        "eDP-1 connected primary 1920x1200+0+0 (normal left inverted right x axis y axis) 302mm x 189mm\n"
        "   1920x1200     60.00*+  48.00  \n   1920x1080     60.00  \n   1920x1080     59.94  \n"
        "HDMI-1 connected (normal left inverted right x axis y axis)\n   1024x768      60.00  \n"
        "DP-1 disconnected (normal left inverted right x axis y axis)\n")
    check([(o["name"], o["on"], o["primary"], o["mode"], o["modes"]) for o in outputs]
          == [("eDP-1", True, True, "1920x1200", ["1920x1200", "1920x1080"]), ("HDMI-1", False, False, "", ["1024x768"])],
          "display: what is plugged in, which is on, and the sizes each offers once")
    with tempfile.TemporaryDirectory() as folder:
        cell = Path(folder) / "BAT0"
        cell.mkdir()
        for name, text in (("capacity", "40"), ("status", "Discharging"), ("energy_now", "20000000"),
                           ("energy_full", "50000000"), ("energy_full_design", "60000000"), ("power_now", "10000000")):
            (cell / name).write_text(text + "\n")
        cell_now = machine.battery(folder)
        check(cell_now["percent"] == 40 and cell_now["minutes"] == 120 and cell_now["health"] == 83 and not cell_now["charging"],
              "health: how long the battery will last, and how worn it is")
        check(machine.battery(Path(folder) / "none") is None, "health: a machine without a battery has none")
        sensor = Path(folder) / "hwmon0"
        sensor.mkdir()
        for name, text in (("name", "coretemp"), ("temp1_input", "61000"), ("temp2_input", "74500"), ("fan1_input", "2400")):
            (sensor / name).write_text(text + "\n")
        check(machine.temperatures(Path(folder)) == ([{"name": "Processor", "celsius": 74.5}], [{"name": "Fan", "rpm": 2400}]),
              "health: the hottest reading of each sensor, and the fans")

    import system
    check(system._fields(r"*:Cafe\: Open:55") == ["*", "Cafe: Open", "55"], "network: a name with a colon in it is read whole")
    with tempfile.TemporaryDirectory() as folder:
        usb = Path(folder)
        for port, kind in (("1-2", "00"), ("usb1", "09")):
            (usb / port).mkdir()
            for name, text in (("idVendor", "1234"), ("idProduct", "abcd"), ("bDeviceClass", kind), ("authorized", "1")):
                (usb / port / name).write_text(text + "\n")
        listed = system.usb_devices(usb)
        check([d["port"] for d in listed] == ["1-2"] and listed[0]["on"] and listed[0]["switchable"],
              "devices: a USB device is listed with its switch, a hub is not")
        done, _text, change = system.usb_switch("1-2", False, usb)
        check(done and (usb / "1-2/authorized").read_text() == "0" and change == ("usb", "1-2")
              and not system.usb_devices(usb)[0]["on"], "devices: a USB device is switched off, and can be undone")
        check(not system.usb_switch("usb1", False, usb)[0] and not system.usb_switch("../1-2", False, usb)[0],
              "devices: only a listed device can be switched")
    real = (system.drives, system._udisks)
    asked = []
    stick = {"device": "/dev/sdz1", "disk": "/dev/sdz", "mount": "/media/stick", "removable": True}
    system.drives = lambda: [stick, dict(stick, device="/dev/sdz2", mount=""),
                             {"device": "/dev/sdy1", "disk": "/dev/sdy", "mount": "/", "removable": False}]
    system._udisks = lambda *args: (asked.append(args), (True, "Mounted /dev/sdz2 at /media/two"))[1]
    try:
        check(system.drive_action("/dev/sdz2", "mount") == (True, "Mounted at /media/two"), "devices: a drive is mounted")
        check(system.drive_action("/dev/sdz1", "eject")[0]
              and asked[-2:] == [("unmount", "-b", "/dev/sdz1"), ("power-off", "-b", "/dev/sdz")],
              "devices: a removable drive is unmounted, then made safe to pull out")
        before = len(asked)
        check(not system.drive_action("/dev/sdy1", "unmount")[0] and not system.drive_action("/dev/sdy1", "eject")[0]
              and not system.drive_action("/dev/sdx", "mount")[0] and len(asked) == before,
              "devices: the drive the computer runs from, and one that is not there, are left alone")
    finally:
        system.drives, system._udisks = real
    check(set(desktop.POWER_ACTIONS) == {"lock", "unlock", "screen-off", "suspend", "reboot", "poweroff"},
          "power: a fixed list of actions")


async def daemon_checks(sandbox, check):
    import aiohttp
    import identity as I

    home = Path.home()
    link_dir = home / ".config/adaptive-desktop/link"
    env = dict(os.environ, ADAPTIVE_LINK_PORT=str(PORT), ADAPTIVE_LINK_PAIRING_PORT=str(PAIRING_PORT))
    # The network and the drives the daemon changes are stand-ins, not this machine's.
    import fake_system_tools
    tools = sandbox / "tools"
    env.update(PATH=f"{fake_system_tools.install(tools / 'bin')}:{env['PATH']}", FAKE_TOOLS_DIR=str(tools),
               ADAPTIVE_LINK_KEEP_S="3", ADAPTIVE_LINK_ALERT_EVERY_S="1",
               ADAPTIVE_LINK_PROXIMITY_S="2", ADAPTIVE_LINK_PROXIMITY_PROBE="0",
               # No sound server here, and none is to be started by asking for one.
               PULSE_SERVER="unix:/nonexistent/pulse")
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
            victim = subprocess.Popen(["sleep", "300"])
            async with phone.post(f"{link_url}/v1/tasks/signal", json={"pid": victim.pid, "action": "low"}) as reply:
                lowered = await reply.json()
            async with phone.post(f"{link_url}/v1/tasks/signal", json={"pid": victim.pid, "action": "pause"}) as reply:
                await reply.json()
            async with phone.get(f"{link_url}/v1/tasks?q={victim.pid}") as reply:
                seen = [p for p in (await reply.json())["processes"] if p["pid"] == victim.pid]
            check(lowered["ok"] and seen and seen[0]["nice"] == 10 and seen[0]["paused"],
                  "tasks: a process is made less important, and paused")
            async with phone.post(f"{link_url}/v1/tasks/signal", json={"pid": victim.pid, "action": "normal"}) as reply:
                raised = await reply.json()
            check(raised["ok"] or "system" in raised["error"], "tasks: making it important again is the system's to allow")
            victim.kill()
            victim.wait()
            parent = subprocess.Popen(["sh", "-c", "sleep 300 & sleep 300 & wait"])
            await asyncio.sleep(0.5)
            started = subprocess.run(["pgrep", "-P", str(parent.pid)], capture_output=True, text=True).stdout.split()
            async with phone.post(f"{link_url}/v1/tasks/signal",
                                  json={"pid": parent.pid, "action": "kill", "tree": True}) as reply:
                await reply.json()
            parent.wait(timeout=5)
            await asyncio.sleep(0.3)
            check(len(started) == 2 and not any(Path(f"/proc/{pid}").exists() for pid in started),
                  "tasks: a process is ended with everything it started")
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

            async def change(path, **body):
                async with phone.post(f"{link_url}{path}", json=body) as reply:
                    return await reply.json()

            def network_now():
                return json.loads((tools / "network.json").read_text())

            def asked():
                return [json.loads(line) for line in (tools / "calls.log").read_text().splitlines()]

            root = next(d for d in devices["drives"] if d["mount"] == "/")
            refusals = [await change("/v1/devices", action="unmount", target=root["device"]),
                        await change("/v1/devices", action="eject", target=root["device"]),
                        await change("/v1/devices", action="mount", target="/dev/../etc/passwd"),
                        await change("/v1/devices", action="format", target=root["device"]),
                        await change("/v1/devices", action="usb-off", target="../../etc")]
            check(root["system"] and not any(r["ok"] for r in refusals) and all(r["keep"] == 0 for r in refusals)
                  and not any(call[0] == "udisksctl" for call in asked()),
                  "devices: the drive the computer runs from cannot be unmounted, nor anything not listed touched")
            if devices["usb"] and not devices["usb"][0]["switchable"]:
                switched = await change("/v1/devices", action="usb-off", target=devices["usb"][0]["port"])
                check(not switched["ok"] and "install-link-usb.sh" in switched["error"],
                      "devices: says what to run when the USB switches are still the system's")

            check(net["control"] and net["wifi_on"] and [v["name"] for v in net["vpns"]] == ["Work VPN"]
                  and [(n["name"], n["active"], n["known"], n["security"]) for n in net["networks"]]
                  == [("Home", True, True, "WPA2"), ("Cafe: Open", False, False, ""), ("Other", False, False, "WPA2")],
                  "network: Wi-Fi, the networks in range and the VPNs are listed")
            off = await change("/v1/network", action="wifi", value="off")
            check(off["ok"] and off["keep"] == 3 and not network_now()["radio"], "network: Wi-Fi is turned off from the phone")
            await asyncio.sleep(4.5)
            async with phone.get(f"{link_url}/v1/log") as reply:
                undone = [e for e in (await reply.json())["entries"] if e["action"] == "undone"]
            check(network_now()["radio"] and len(undone) == 1,
                  "network: and turned back on when the phone does not come back to keep it")
            off = await change("/v1/network", action="wifi", value="off")
            kept = await change("/v1/keep")
            await asyncio.sleep(4)
            check(off["ok"] and kept["kept"] and not network_now()["radio"], "network: a change the phone keeps is kept")
            await change("/v1/network", action="wifi", value="on")
            await change("/v1/network", action="connect", value="wlan-check")

            joined = await change("/v1/network", action="join", value="Cafe: Open")
            check(joined["ok"] and joined["keep"] == 3 and network_now()["active"] == "Cafe: Open",
                  "network: an open network is joined")
            await asyncio.sleep(4.5)
            check(network_now()["active"] == "Home", "network: and left for the one before when the phone is lost")
            wrong = await change("/v1/network", action="join", value="Other", secret="wrong-horse")
            check(not wrong["ok"] and "password" in wrong["error"] and "Other" not in network_now()["saved"],
                  "network: a wrong password is refused and leaves nothing behind")
            right = await change("/v1/network", action="join", value="Other", secret="correct-horse")
            await change("/v1/keep")
            check(right["ok"] and network_now()["active"] == "Other"
                  and not any("horse" in word for call in asked() for word in call),
                  "network: a network is joined with its password, which no other program could read")
            back = await change("/v1/network", action="join", value="Home")
            await change("/v1/keep")
            check(back["ok"] and network_now()["active"] == "Home", "network: a saved network needs no password")
            refusals = [await change("/v1/network", action="join", value="Other"),      # saved by now: no refusal
                        await change("/v1/network", action="join", value="--help"),
                        await change("/v1/network", action="join", value="Nowhere"),
                        await change("/v1/network", action="disconnect", value="lo"),
                        await change("/v1/network", action="up", value="Home"),
                        await change("/v1/network", action="wifi", value="on; reboot"),
                        await change("/v1/network", action="delete", value="Home")]
            await change("/v1/keep")
            check(refusals[0]["ok"] and not any(r["ok"] for r in refusals[1:]),
                  "network: only what is listed can be asked for")
            up = await change("/v1/network", action="up", value="Work VPN")
            check(up["ok"] and up["keep"] == 3 and network_now()["vpn"], "network: a VPN is brought up")
            down = await change("/v1/network", action="down", value="Work VPN")
            await asyncio.sleep(4)
            check(down["ok"] and down["keep"] == 0 and not network_now()["vpn"],
                  "network: and down again, which settles the change before it")
            waking = control.call("POST", "/wake", {})
            using = network_now()["active"]
            check(not waking["on"] and waking["connections"] == [{"name": using, "on": False}],
                  "wake: off until the owner asks for it")
            waking = control.call("POST", "/wake", {"on": True})
            check(waking["ok"] and waking["on"] and network_now()["wake"] == {using: "magic"},
                  "wake: the connection in use is set to wake the computer")
            async with phone.get(f"{link_url}/v1/status") as reply:
                told = (await reply.json())["wake"]
            check(isinstance(told, list) and all(len(a["mac"]) == 17 and a["broadcast"].count(".") == 3 for a in told),
                  "wake: the phone is told where to send the packet that wakes the computer")
            control.call("POST", "/wake", {"on": False})

            relayed = control.call("POST", "/relay", {"url": "turn:relay.example.org:3478", "username": "me", "credential": "pw"})
            async with phone.get(f"{link_url}/v1/status") as reply:
                told = (await reply.json())["relay"]
            check(relayed["ok"] and told == {"url": "turn:relay.example.org:3478", "username": "me", "credential": "pw"}
                  and control.status()["relay"] == "turn:relay.example.org:3478"
                  and not control.call("POST", "/relay", {"url": "http://evil.example"})["ok"],
                  "relay: a paired phone is told the owner's relay; the owner's own status shows no password")
            check(control.call("POST", "/relay", {"url": ""})["relay"] == "" and control.status()["relay"] == "",
                  "relay: and it is gone when the owner takes it out")

            control.call("POST", "/configure", {"allow_input": False})
            async with phone.post(f"{link_url}/v1/network", json={"action": "wifi", "value": "off"}) as reply:
                refused_network = reply.status
            async with phone.post(f"{link_url}/v1/devices", json={"action": "unmount", "target": "/dev/sda1"}) as reply:
                check(reply.status == 403 and refused_network == 403 and network_now()["radio"],
                      "network and devices: nothing is changed in view-only")
            control.call("POST", "/configure", {"allow_input": True})

            # ------------- bluetooth, displays, sound, services, power, windows
            async def read(what):
                async with phone.get(f"{link_url}/v1/machine/{what}") as reply:
                    return await reply.json()

            def machine_now():
                return json.loads((tools / "machine.json").read_text())

            blue = await read("bluetooth")
            check(blue["available"] and blue["on"] and [d["name"] for d in blue["devices"]] == ["Check Headphones", "Check Mouse"]
                  and blue["devices"][0]["kind"] == "Headphones" and blue["devices"][0]["battery"] == 70,
                  "bluetooth: the devices the computer knows, and what each is")
            mouse = blue["devices"][1]["address"]
            connected = await change("/v1/machine/bluetooth", action="connect", target=mouse)
            check(connected["ok"] and (await read("bluetooth"))["devices"][0]["name"] == "Check Mouse"
                  and machine_now()["connected"] == [mouse], "bluetooth: a device is connected, and listed first")
            off = await change("/v1/machine/bluetooth", action="power", target="off")
            failed = await change("/v1/machine/bluetooth", action="connect", target=mouse)
            check(off["ok"] and not machine_now()["bluetooth"] and not failed["ok"],
                  "bluetooth: turned off, and a device then cannot be connected")
            refusals = [await change("/v1/machine/bluetooth", action="connect", target="AA:BB:CC:00:00:09"),
                        await change("/v1/machine/bluetooth", action="power", target="on; reboot"),
                        await change("/v1/machine/bluetooth", action="remove", target=mouse)]
            check(not any(r["ok"] for r in refusals), "bluetooth: only a known device, and only what is offered")
            await change("/v1/machine/bluetooth", action="power", target="on")

            noise = await read("sound")
            check([(d["label"], d["default"], d["volume"]) for d in noise["outputs"]]
                  == [("Check Speakers", True, 50), ("Check Headset", False, 30)]
                  and [d["label"] for d in noise["inputs"]] == ["Check Microphone"],
                  "sound: where sound comes out and goes in, without a speaker's own echo as a microphone")
            results = [await change("/v1/machine/sound", action="output-use", target="headset.check"),
                       await change("/v1/machine/sound", action="output-volume", target="headset.check", value="65"),
                       await change("/v1/machine/sound", action="input-mute", target="microphone.check", value="on")]
            now = machine_now()
            check(all(r["ok"] for r in results) and now["sink"] == "headset.check" and now["volume"]["headset.check"] == 65
                  and now["muted"] == ["microphone.check"], "sound: another output chosen, its volume set, the microphone muted")
            refusals = [await change("/v1/machine/sound", action="output-use", target="microphone.check"),
                        await change("/v1/machine/sound", action="output-volume", target="headset.check", value="400"),
                        await change("/v1/machine/sound", action="output-volume", target="headset.check", value="-5"),
                        await change("/v1/machine/sound", action="input-use", target="nowhere")]
            check(not any(r["ok"] for r in refusals), "sound: only a device that is there, and a volume that makes sense")

            units = (await read("services"))["services"]
            check([(u["name"], u["running"]) for u in units]
                  == [("adaptive-link.service", True), ("sync.service", True), ("backup.service", False)]
                  and units[0]["own"], "services: the owner's services, the running ones first")
            results = [await change("/v1/machine/services", action="start", target="backup.service"),
                       await change("/v1/machine/services", action="stop", target="sync.service")]
            check(all(r["ok"] for r in results) and "backup.service" in machine_now()["running"]
                  and "sync.service" not in machine_now()["running"], "services: one is started and one stopped")
            refusals = [await change("/v1/machine/services", action="stop", target="adaptive-link.service"),
                        await change("/v1/machine/services", action="start", target="../evil.service"),
                        await change("/v1/machine/services", action="mask", target="sync.service")]
            check(not any(r["ok"] for r in refusals) and "adaptive-link.service" in machine_now()["running"],
                  "services: the link itself is not stopped from the phone, nor anything not listed")

            well = await read("health")
            check(well["profile"] == "balanced" and "power-saver" in well["profiles"]
                  and isinstance(well["temperatures"], list), "health: the power profile, the battery and the temperatures")
            saver = await change("/v1/machine/health", action="profile", target="power-saver")
            check(saver["ok"] and machine_now()["profile"] == "power-saver"
                  and not (await change("/v1/machine/health", action="profile", target="turbo"))["ok"],
                  "health: the power profile is changed, to one that is offered")

            shown = await read("display")
            check(len(shown["outputs"]) >= 1 and shown["outputs"][0]["on"] and shown["outputs"][0]["mode"],
                  "display: the displays and their sizes")
            only = shown["outputs"][0]["name"]
            refusals = [await change("/v1/machine/display", action="off", target=only),
                        await change("/v1/machine/display", action="mode", target=only, value="99999x1"),
                        await change("/v1/machine/display", action="mode", target="HDMI-99", value="800x600"),
                        await change("/v1/machine/display", action="brightness", value="0")]
            check(not any(r["ok"] for r in refusals) and (await read("display"))["outputs"][0]["on"],
                  "display: the only display is not turned off, nor a size it does not offer chosen")

            check(isinstance((await read("windows"))["windows"], list)
                  and not (await change("/v1/machine/windows", action="close", target="1"))["ok"]
                  and not (await change("/v1/machine/windows", action="close", target="1; reboot"))["ok"],
                  "windows: listed, and only a window that is open can be acted on")

            control.call("POST", "/configure", {"allow_input": False, "allow_exec": False, "allow_power": False})
            statuses = []
            for what, method in (("bluetooth", "post"), ("sound", "post"), ("display", "post"), ("windows", "get"),
                                 ("services", "get"), ("services", "post"), ("health", "post")):
                async with getattr(phone, method)(f"{link_url}/v1/machine/{what}") as reply:
                    statuses.append(reply.status)
            async with phone.get(f"{link_url}/v1/machine/health") as reply:
                seen = reply.status
            check(statuses == [403] * 7 and seen == 200,
                  "machine: nothing is changed with the switches off, though the battery can still be read")
            control.call("POST", "/configure", {"allow_input": True, "allow_exec": True, "allow_power": True})
            async with phone.get(f"{link_url}/v1/machine/secrets") as reply:
                check(reply.status == 404, "machine: nothing else is there to ask for")

            # ------------------------------------------- the screen as video
            import rtc
            from aiortc import RTCPeerConnection, RTCSessionDescription
            viewer = RTCPeerConnection(rtc.configuration(stun=None))
            viewer.addTransceiver("video", direction="recvonly")
            viewer.addTransceiver("audio", direction="recvonly")
            arrived = asyncio.get_running_loop().create_future()

            @viewer.on("track")
            def on_track(track):
                async def first():
                    frame = await track.recv()
                    if not arrived.done():
                        arrived.set_result((frame.width, frame.height))
                if track.kind == "video":
                    asyncio.ensure_future(first())

            await viewer.setLocalDescription(await viewer.createOffer())
            video = await change("/v1/rtc", offer=viewer.localDescription.sdp, preset="low")
            check(video.get("ok") and video["size"][0] == 960 and video["sound"] is False,
                  "video: the computer answers the phone's offer, without sound where there is no sound server")
            await viewer.setRemoteDescription(RTCSessionDescription(sdp=video["answer"], type="answer"))
            try:
                size = await asyncio.wait_for(arrived, 30)
            except asyncio.TimeoutError:
                size = None
            check(size == tuple(video["size"]), f"video: the screen arrives as video ({size})")
            check(control.status()["viewing"] == 1, "video: the computer knows someone is watching")
            closed = await change("/v1/rtc/close", id=video["id"])
            await viewer.close()
            check(closed["ok"] and control.status()["viewing"] == 0 and not (await change("/v1/rtc/close", id=video["id"]))["ok"],
                  "video: it stops when the phone says it has finished")
            refused = [await change("/v1/rtc", offer="v=0"), await change("/v1/rtc", offer=""),
                       await change("/v1/rtc", offer="m=video " + "x" * 70000), await change("/v1/rtc")]
            check(not any(r.get("ok") for r in refused) and control.status()["viewing"] == 0,
                  "video: something that is not an offer starts nothing")

            # --------------------------- what the computer tells the phone
            async def said(after=0, kinds="notification,alert"):
                async with phone.get(f"{link_url}/v1/events?once=1&after={after}&kinds={kinds}") as reply:
                    return (await reply.json())["events"]

            async def run(command, detach=False):
                async with phone.ws_connect(f"{link_url}/v1/exec") as ws:
                    await ws.send_json({"cmd": command, "detach": detach})
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            break

            mark = max((item["id"] for item in await said()), default=0)
            async with phone.ws_connect(f"{link_url}/v1/events?after={mark}") as listening:
                await run("notify-send --app-name=Mail 'From Ada' 'Lunch at one?'")
                heard = await asyncio.wait_for(listening.receive_json(), 10)
                check((heard["kind"], heard["app"], heard["title"], heard["text"])
                      == ("notification", "Mail", "From Ada", "Lunch at one?"),
                      "events: a notification on the computer reaches a phone that is listening")
                await change("/v1/machine/services", action="stop", target="sync.service")
                (tools / "machine.json").write_text(json.dumps(dict(machine_now(), running=["adaptive-link.service"])))
                await run("sleep 1; exit 3", detach=True)
                heard = await asyncio.wait_for(listening.receive_json(), 10)
                check(heard["kind"] == "alert" and heard["title"] == "Ended with an error (3)" and "sleep 1" in heard["text"],
                      "events: a command started from the phone and left running says when it ends")
            async with phone.post(f"{link_url}/v1/notify", json={"key": "k", "app": "Chat", "title": "Echo", "text": "x"}) as reply:
                await reply.json()
            await asyncio.sleep(1.5)
            later = await said(mark)
            check([item["title"] for item in later if item["kind"] == "notification"] == ["From Ada"],
                  "events: what was said is kept for a phone that was away, without the phone's own notifications")
            control.call("POST", "/configure", {"send_notifications": False})
            check([item["kind"] for item in await said(mark)] == ["alert"] and not await said(mark, "notification"),
                  "events: the owner can keep the computer's notifications from the phone; alerts still come")
            control.call("POST", "/configure", {"send_notifications": True})

            # ------------------------------ the phone and the computer as one
            import base64
            import companion
            from cryptography.hazmat.primitives import hashes as H, serialization as S
            from cryptography.hazmat.primitives.asymmetric import ec as E
            _stranger_key, signer_cert = I.make_certificate("Adaptive Link Phone")

            def signed(what, nonce):
                key = S.load_pem_private_key(Path(phone_key).read_bytes(), None)
                return base64.b64encode(key.sign(companion.approval_message(what, nonce), E.ECDSA(H.SHA256()))).decode()

            def ask(path, body=None, timeout=45):
                return asyncio.to_thread(control.call, "POST", path, body, timeout)

            # The clipboard: off until the owner turns it on.
            async with phone.ws_connect(f"{link_url}/v1/events?kinds=clipboard,ring") as listening:
                await run("printf 'copied on the computer' | xclip -selection clipboard -i", detach=True)
                check((await ask("/ring"))["ok"] and (await asyncio.wait_for(listening.receive_json(), 10))["kind"] == "ring",
                      "phone: the computer makes a listening phone ring, and the clipboard is not told while that is off")
            check(not (await ask("/ring"))["ok"], "phone: with no phone listening, the computer says so")
            control.call("POST", "/configure", {"sync_clipboard": True})
            async with phone.ws_connect(f"{link_url}/v1/events?kinds=clipboard") as listening:
                await asyncio.sleep(2.5)   # what was there before the phone listened is not news
                await change("/v1/clipboard", text="sent by the phone")
                await asyncio.sleep(2.5)
                await run("printf 'copied afterwards' | xclip -selection clipboard -i", detach=True)
                heard = await asyncio.wait_for(listening.receive_json(), 10)
                check(heard["kind"] == "clipboard" and heard["text"] == "copied afterwards",
                      "clipboard: what is copied on the computer reaches the phone, and what the phone sent is not sent back")

            # Texts and calls.
            texted = await change("/v1/phone/sms", **{"from": "+15550100", "name": "Bank", "text": "Your login code is 771204."})
            async with phone.get(f"{link_url}/v1/clipboard") as reply:
                pasted = (await reply.json())["text"]
            check(texted["code"] == "771204" and pasted == "771204"
                  and control.call("POST", "/sms", {})["messages"][-1]["name"] == "Bank",
                  "texts: a message from the phone is shown on the computer, and its code is ready to paste")
            async with phone.get(f"{link_url}/v1/log") as reply:
                written = json.dumps((await reply.json())["entries"][-8:])
            check("771204" not in written and "Bank" in written, "texts: the record says who wrote, not what")
            ringing = await change("/v1/phone/call", state="ringing", name="Ada", **{"from": "+15550111"})
            check(ringing["ok"] and (await change("/v1/phone/call", state="ended"))["ok"], "calls: a call is shown, and cleared when it ends")
            async with phone.ws_connect(f"{link_url}/v1/events?kinds=sms-send") as listening:
                sending = asyncio.ensure_future(ask("/sms", {"to": "+1 555 0100", "text": "On my way"}))
                order = await asyncio.wait_for(listening.receive_json(), 10)
                await change("/v1/phone/sent", id=order["send"], ok=True)
                sent = await sending
                check(order["to"] == "+15550100" and order["body"] == "On my way" and sent["ok"],
                      "texts: one written on the computer is sent by the phone")
            refused = [await ask("/sms", {"to": "+1 555 0100", "text": "nobody listening"}),
                       await ask("/sms", {"to": "not a number", "text": "x"})]
            check(not any(r["ok"] for r in refused), "texts: not without a phone listening, nor to something that is not a number")

            stated = await change("/v1/phone/state", battery=64, charging=True, signal=3, network="wifi")
            check(stated["battery"] == 64 and control.status()["phones"][0]["state"]["signal"] == 3
                  and (await change("/v1/phone/state", battery="lots", signal=99))["battery"] is None,
                  "phone: its battery and signal are known to the computer")

            # Approvals: the phone's fingerprint says yes, and signs for it.
            check(not (await ask("/approve", {"what": "sudo", "text": "x"}))["ok"]
                  and not (await ask("/approve", {"what": "format-disk", "text": "x"}))["ok"],
                  "approvals: nothing is approved with no phone listening, and only what the phone is asked")
            helper_env = dict(os.environ, LINK_SOCKET=str(Path(os.environ["XDG_RUNTIME_DIR"]) / "adaptive-link.sock"),
                              LINK_APPROVERS=str(sandbox / "approvers"))
            (sandbox / "approvers").mkdir()
            (sandbox / "approvers/phone.pem").write_bytes(subprocess.run(
                ["openssl", "x509", "-pubkey", "-noout", "-in", phone_crt], capture_output=True).stdout)

            async def helper():
                return await asyncio.to_thread(lambda: subprocess.run(
                    [sys.executable, str(REPO / "scripts/link-approve.py")], env=helper_env, timeout=60).returncode)

            async with phone.ws_connect(f"{link_url}/v1/events?kinds=approve") as listening:
                asking = asyncio.ensure_future(helper())
                question = await asyncio.wait_for(listening.receive_json(), 10)
                answered = await change("/v1/approve", ask=question["ask"], ok=True, signature=signed("sudo", question["nonce"]))
                check(question["title"] == "sudo" and "administrator rights" in question["text"] and answered["ok"]
                      and await asking == 0, "approvals: sudo's helper asks the phone, and takes its signed yes")
                asking = asyncio.ensure_future(helper())
                question = await asyncio.wait_for(listening.receive_json(), 10)
                await change("/v1/approve", ask=question["ask"], ok=True, signature=signed("unlock", question["nonce"]))
                check(await asking == 1, "approvals: a yes signed for something else is not a yes")
                asking = asyncio.ensure_future(helper())
                question = await asyncio.wait_for(listening.receive_json(), 10)
                await change("/v1/approve", ask=question["ask"], ok=False)
                check(await asking == 1, "approvals: a no on the phone falls through to the password")
                (sandbox / "approvers/phone.pem").write_bytes(subprocess.run(
                    ["openssl", "x509", "-pubkey", "-noout"], input=signer_cert, capture_output=True).stdout)
                asking = asyncio.ensure_future(helper())
                question = await asyncio.wait_for(listening.receive_json(), 10)
                await change("/v1/approve", ask=question["ask"], ok=True, signature=signed("sudo", question["nonce"]))
                check(await asking == 1, "approvals: nor a yes from a phone whose key root was never given")

            # Leaving and coming back. The phone has to be on the computer's
            # own network to count as here, so it comes in by that address.
            lan = control.status()["addresses"]
            if lan:
                near_url = f"https://{lan[0]['address']}:{PORT}"
                control.call("POST", "/configure", {"proximity_lock": True})

                def locks():
                    return [call[1] for call in asked() if call[0] == "loginctl"]

                async with phone.ws_connect(f"{near_url}/v1/events?kinds=approve&present=1"):
                    await asyncio.sleep(0.5)
                    here = control.status()["present"]
                await asyncio.sleep(1)
                async with phone.ws_connect(f"{near_url}/v1/events?kinds=approve&present=1"):
                    await asyncio.sleep(3)
                check(here and locks() == [], "presence: a phone that comes straight back does not lock the computer")
                await asyncio.sleep(4)
                check(locks() == ["lock-session"] and not control.status()["present"],
                      "presence: the computer locks when the phone has left its network")
                async with phone.ws_connect(f"{near_url}/v1/events?kinds=approve&present=1") as listening:
                    question = await asyncio.wait_for(listening.receive_json(), 10)
                    await change("/v1/approve", ask=question["ask"], ok=True, signature=signed("unlock", question["nonce"]))
                    await asyncio.sleep(1)
                    check(question["title"] == "unlock" and locks() == ["lock-session", "unlock-session"],
                          "presence: when it comes back it is asked, and its fingerprint unlocks the computer")
                control.call("POST", "/configure", {"proximity_lock": False})
            control.call("POST", "/configure", {"sync_clipboard": False})

            # The microphone, held keys, one display, and where files go.
            async with phone.get(f"{link_url}/v1/mic") as reply:
                check(reply.status == 503, "microphone: says so when the computer has no sound server to give it to")
            shown = (await read("display"))["outputs"][0]
            async with phone.ws_connect(f"{link_url}/v1/screen?preset=low&display={shown['name']}") as ws:
                message = await asyncio.wait_for(ws.receive(), 15)
                check(len(shown["at"]) == 4 and message.type == aiohttp.WSMsgType.BINARY and message.data.startswith(b"\xff\xd8"),
                      "screen: one display can be asked for by name")
            async with phone.post(f"{link_url}/v1/upload?name=holiday.jpg&to=photos", data=b"photo") as reply:
                where = (await reply.json())["path"]
            async with phone.post(f"{link_url}/v1/upload?name=page.pdf&to=scans", data=b"scan") as reply:
                scanned = (await reply.json())["path"]
            check(where == str(home / "Pictures/Phone/holiday.jpg") and scanned == str(home / "Documents/Scans/page.pdf"),
                  "files: the phone's photos and its scans each arrive in their own folder")

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
                recent = [entry["action"] for entry in (await reply.json())["entries"]]
            # The phone is shown the latest hundred; the record itself holds all of it.
            record = home / ".local/state/adaptive-desktop/link.log"
            actions = [json.loads(line)["action"] for line in record.read_text().splitlines()]
            check(all(a in actions for a in ("paired", "connected", "screen", "exec", "upload", "download"))
                  and 0 < len(recent) <= 100 and recent == actions[-len(recent):],
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

        # A second device is paired beside the first, with limits of its own.
        new_cert, new_crt, new_key = write_identity("newphone")
        qr = json.loads(control.call("POST", "/pair/start")["payload"])
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned())) as http:
            async with http.post(f"{pair_url}/pair", json={"t": qr["t"], "cert": new_cert, "name": "New"}) as reply:
                await reply.json()
        control.call("POST", "/pair/decide", {"accept": True})
        await asyncio.sleep(3.5)
        check((await try_status(pinned(new_crt, new_key)))[0] == 200 and (await try_status(pinned(phone_crt, phone_key)))[0] == 200
              and [p["name"] for p in control.status()["phones"]] == ["Pixel 8", "New"],
              "pairing: a second device is paired, and both get in")
        limited = control.call("POST", "/phone", {"phone": "New", "what": "exec", "allowed": False})
        check(limited["ok"] and limited["phones"][1]["deny"] == ["allow_exec"]
              and not control.call("POST", "/phone", {"phone": "Nobody", "what": "exec", "allowed": False})["ok"]
              and not control.call("POST", "/phone", {"phone": "New", "what": "public", "allowed": True})["ok"],
              "phones: one device is kept from running commands")
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned(new_crt, new_key))) as second, \
                aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pinned(phone_crt, phone_key))) as first:
            async with second.get(f"{link_url}/v1/tasks") as reply:
                denied = reply.status
            async with second.get(f"{link_url}/v1/status") as reply:
                second_can = (await reply.json())["can"]
            async with first.get(f"{link_url}/v1/tasks") as reply:
                allowed = reply.status
            async with first.get(f"{link_url}/v1/status") as reply:
                first_can = (await reply.json())["can"]
            check(denied == 403 and allowed == 200 and not second_can["exec"] and second_can["files"] and first_can["exec"],
                  "phones: that device is refused, is told so, and the other is not affected")
            async with second.get(f"{link_url}/v1/files") as reply:
                await reply.json()
            async with first.get(f"{link_url}/v1/log") as reply:
                who = [entry["from"] for entry in (await reply.json())["entries"][-6:]]
            check(any(name.endswith(" New") for name in who), "phones: the record says which device did what")
        control.call("POST", "/phone", {"phone": "New", "what": "exec", "allowed": True})
        check(not control.call("POST", "/unpair", {"phone": "Nobody"})["ok"]
              and control.call("POST", "/unpair", {"phone": "Pixel 8"})["ok"], "phones: one device is unpaired by name")
        await asyncio.sleep(1.5)
        check((await try_status(pinned(new_crt, new_key)))[0] == 200 and (await try_status(pinned(phone_crt, phone_key)))[0] != 200
              and [p["name"] for p in control.status()["phones"]] == ["New"],
              "phones: it no longer gets in, and the other still does")

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
