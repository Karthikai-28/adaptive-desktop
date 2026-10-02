"""Adaptive Link - the phone and the computer working as one.

The rest of the link is the phone reaching into the computer. This is the
two of them keeping each other company:

  clipboard   what is copied on one can be pasted on the other
  presence    the computer locks when the phone leaves its network, and asks
              the phone before unlocking when it comes back
  approvals   the phone's fingerprint says yes to something on the computer
              (unlocking it; sudo, through scripts/link-approve.py)
  the phone   its battery and signal, its calls and text messages shown on
              the computer, a text sent from the computer, and making it ring
  microphone  the phone's microphone as one the computer's apps can choose

What decides - what is a one-time code, what is a phone number, whether an
approval is really the phone's - has no machine in it and is checked directly
by verify-link.py.
"""

import asyncio
import base64
import re
import secrets
import shutil
import subprocess
import time

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

CLIPBOARD_EVERY_S = 1.5
CLIPBOARD_MAX = 20_000
APPROVAL_S = 30
MESSAGES_KEPT = 50
PRESENCE_PROBES = 4


# ----------------------------------------------------------------- deciding

_CODE = re.compile(r"(?<![\d.,])(\d{4,8})(?![\d.,]\d|\d)")
_CODE_WORDS = re.compile(r"\b(code|otp|pin|passcode|password|verification|verify|one[- ]time|2fa|login|sign[- ]?in)\b", re.I)


def find_code(text):
    """The one-time code in a text message, or "". Only a message that
    speaks of a code is looked at, so that a price or a year in an ordinary
    message is not taken for one."""
    text = str(text or "")
    if not _CODE_WORDS.search(text):
        return ""
    # "123 456" and "123-456" are one code, written in two halves.
    found = _CODE.findall(re.sub(r"(?<=\b\d{3})[- ](?=\d{3}\b)", "", text))
    return found[0] if found else ""


def clean_number(text):
    """A phone number fit to hand to the phone to send to, or ""."""
    number = re.sub(r"[\s().-]", "", str(text or ""))
    return number if re.fullmatch(r"\+?\d{3,15}", number) else ""


def approval_message(what, nonce):
    """What the phone signs to say yes: this request and no other."""
    return f"adaptive-link approve\n{what}\n{nonce}".encode()


def approved_by(cert_pem, what, nonce, signature_b64):
    """Whether a signature over this request was made by the key of this
    certificate - the phone's, which never leaves its hardware."""
    try:
        key = x509.load_pem_x509_certificate(cert_pem.encode() if isinstance(cert_pem, str) else cert_pem).public_key()
        key.verify(base64.b64decode(str(signature_b64), validate=True), approval_message(what, nonce),
                   ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError, AttributeError):
        return False


# ---------------------------------------------------------------- approvals

class Approvals:
    """Things waiting for a phone to say yes with its fingerprint."""

    def __init__(self, events):
        self._events = events
        self._waiting = {}

    async def ask(self, what, text, phones, nonce="", timeout=APPROVAL_S):
        """Ask the phones that are listening. Returns {"ok", "signature",
        "fingerprint"}; ok is false if nobody answers in time, says no, or
        signs with a key that is not a paired phone's."""
        if not self._events.listening("approve"):
            return {"ok": False, "why": "no phone is listening"}
        ident = secrets.token_hex(8)
        nonce = nonce if re.fullmatch(r"[0-9a-f]{16,64}", str(nonce)) else secrets.token_hex(16)
        answer = asyncio.get_running_loop().create_future()
        self._waiting[ident] = (what, nonce, answer, phones)
        self._events.add("approve", what, text, keep=False, data={"ask": ident, "nonce": nonce})
        try:
            return await asyncio.wait_for(answer, timeout)
        except asyncio.TimeoutError:
            return {"ok": False, "why": "the phone did not answer"}
        finally:
            self._waiting.pop(ident, None)
            self._events.add("approve-done", what, keep=False, data={"ask": ident})

    def answer(self, ident, ok, signature, phone):
        """The phone's answer to one request. Returns whether it was taken."""
        found = self._waiting.get(str(ident))
        if found is None:
            return False
        what, nonce, future, phones = found
        if future.done() or not any(phone["fingerprint"] == other["fingerprint"] for other in phones):
            return False
        if not ok:
            future.set_result({"ok": False, "why": "refused on the phone"})
        elif approved_by(phone["cert_pem"], what, nonce, signature):
            future.set_result({"ok": True, "signature": signature, "fingerprint": phone["fingerprint"], "nonce": nonce})
        else:
            future.set_result({"ok": False, "why": "the answer was not signed by the phone"})
        return True


# ----------------------------------------------------------------- presence

def reachable(address):
    """Whether something still answers at this address on the network. A
    phone that has gone to sleep drops its connection but is still here."""
    if not address or not shutil.which("ping"):
        return False
    try:
        return subprocess.run(["ping", "-c", "1", "-W", "1", str(address)], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=3, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Presence:
    """Which paired phones are on the computer's own network now."""

    def __init__(self, grace, on_gone, probe=reachable):
        self.grace = grace
        self._on_gone = on_gone
        self._probe = probe
        self._here = {}       # fingerprint -> open connections
        self._address = {}    # fingerprint -> where it was last seen
        self._leaving = None
        self.locked_here = False   # the computer was locked because the phone left

    @property
    def anyone(self):
        return any(count > 0 for count in self._here.values())

    def arrive(self, fingerprint, address):
        self._here[fingerprint] = self._here.get(fingerprint, 0) + 1
        self._address[fingerprint] = address
        if self._leaving is not None:
            self._leaving.cancel()
            self._leaving = None

    def leave(self, fingerprint):
        self._here[fingerprint] = max(0, self._here.get(fingerprint, 0) - 1)
        if not self.anyone and self._leaving is None:
            self._leaving = asyncio.ensure_future(self._gone())

    async def _gone(self):
        """Nobody is connected. Give the phone the grace period to come
        back, asking the network now and then whether it is still there."""
        try:
            for _ in range(PRESENCE_PROBES):
                await asyncio.sleep(self.grace / PRESENCE_PROBES)
                if self.anyone:
                    return
            for address in set(self._address.values()):
                if await asyncio.to_thread(self._probe, address):
                    return   # asleep, not gone
            await self._on_gone()
        finally:
            self._leaving = None


# ------------------------------------------------------------------ the phone

class PhoneBook:
    """What the phones have said of themselves, and their recent messages.
    Kept in memory only: nothing of the phone's is written to disk here."""

    def __init__(self):
        self.state = {}       # fingerprint -> {battery, charging, signal, network, at}
        self.messages = []    # newest last: {at, from, name, text, phone}

    def set_state(self, fingerprint, data):
        def number(key, low, high):
            try:
                return max(low, min(high, int(data.get(key))))
            except (TypeError, ValueError):
                return None
        self.state[fingerprint] = {
            "battery": number("battery", 0, 100), "charging": data.get("charging") is True,
            "signal": number("signal", 0, 4),
            "network": str(data.get("network", ""))[:20], "at": int(time.time())}
        return self.state[fingerprint]

    def add_message(self, phone_name, sender, name, text):
        entry = {"at": int(time.time()), "from": str(sender or "")[:40], "name": str(name or "")[:60],
                 "text": str(text or "")[:1000], "phone": phone_name}
        self.messages = (self.messages + [entry])[-MESSAGES_KEPT:]
        return entry


# ---------------------------------------------------------------- clipboard

async def watch_clipboard(events, read, wanted, came_from_phone):
    """Tell the phones what is copied on the computer, as it is copied.
    `read` gets the clipboard; `wanted` says whether to look at all (the
    owner's switch, and a phone listening); `came_from_phone` is what a
    phone last put there, which is not to be sent back to it."""
    last = None
    while True:
        await asyncio.sleep(CLIPBOARD_EVERY_S)
        if not wanted():
            last = None
            continue
        try:
            text = await asyncio.to_thread(read)
        except Exception:  # noqa: BLE001 - a clipboard that cannot be read is tried again
            continue
        if last is None:
            last = text   # what was there before anyone listened is not news
            continue
        if text and text != last and text != came_from_phone() and len(text) <= CLIPBOARD_MAX:
            events.add("clipboard", "", keep=False, data={"text": text})
        last = text


# --------------------------------------------------------------- microphone

MIC_SINK = "adaptive_phone_mic"
MIC_SOURCE = "adaptive_phone_mic_source"
MIC_RATE = 16000


def _pactl(*args):
    try:
        done = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return done.returncode == 0, done.stdout.strip()


class Microphone:
    """The phone's microphone, as a microphone on the computer.

    PulseAudio is given a place for the sound to go that plays it nowhere
    (a null sink), and a source that is what arrives there, named "Phone
    Microphone". Apps choose it like any other. Both are taken away again
    when the phone stops.
    """

    def __init__(self):
        self._modules = []
        self._pipeline = None
        self._src = None

    def start(self):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        ok, sink = _pactl("load-module", "module-null-sink", f"sink_name={MIC_SINK}",
                          "sink_properties=device.description=Phone_Microphone_Feed")
        if not ok:
            return False
        self._modules.append(sink)
        ok, source = _pactl("load-module", "module-remap-source", f"master={MIC_SINK}.monitor",
                            f"source_name={MIC_SOURCE}", "source_properties=device.description=Phone_Microphone")
        if ok:
            self._modules.append(source)
        try:
            self._pipeline = Gst.parse_launch(
                "appsrc name=src is-live=true do-timestamp=true format=time "
                f"caps=audio/x-raw,format=S16LE,rate={MIC_RATE},channels=1,layout=interleaved "
                f"! audioconvert ! audioresample ! pulsesink device={MIC_SINK} sync=false")
        except Exception:  # noqa: BLE001 - GLib's own error for a pipeline it cannot build
            self.stop()
            return False
        self._src = self._pipeline.get_by_name("src")
        self._pipeline.set_state(Gst.State.PLAYING)
        self._gst = Gst
        return ok

    def push(self, pcm):
        if self._src is None or not pcm or len(pcm) % 2:
            return False
        return self._src.emit("push-buffer", self._gst.Buffer.new_wrapped(pcm)) == self._gst.FlowReturn.OK

    def stop(self):
        if self._pipeline is not None:
            self._pipeline.set_state(self._gst.State.NULL)
            self._pipeline = None
            self._src = None
        for module in reversed(self._modules):
            _pactl("unload-module", module)
        self._modules = []
