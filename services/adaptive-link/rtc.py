"""Adaptive Link - a direct connection between the phone and the computer
when they are not on the same network.

The two devices agree on a peer-to-peer connection (WebRTC: each tells the
other, through the account's space, where it can be reached, and they connect
straight to each other through their routers). Over it runs a plain tunnel:
every data channel the phone opens is joined to one TCP connection to the
link's own port on this machine.

So nothing about the link changes. What travels through the tunnel is the
same mutual TLS as on Wi-Fi, between the same two certificates; the tunnel
only carries its bytes. Whoever helped the two devices find each other - the
account's space, the public server that tells each its own address - sees
none of it, and could not use the tunnel if they reached it: its far end is
the link's port, which accepts the paired phone's certificate and nothing
else.

By default there is no relay. On networks that do not allow a direct
connection at all (some mobile carriers) the tunnel cannot be made, and the
phone says so - unless the owner runs a relay of their own (a TURN server)
and tells the link about it (link-cli.py relay). Then the two meet there
when they cannot meet directly. The relay carries the bytes and can read
none of them: it is the same tunnel, and the same mutual TLS inside it.
"""

import asyncio
import os
import sys
from pathlib import Path

# The peer-to-peer library lives beside the repository's other local tools.
# It goes last on the path, so the system's own packages keep precedence.
_PYDEPS = os.environ.get("ADAPTIVE_LINK_PYDEPS") or str(
    Path(__file__).resolve().parent.parent.parent / ".local" / "link-pydeps")
if _PYDEPS not in sys.path:
    sys.path.append(_PYDEPS)

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription  # noqa: E402

# Tells each device its own public address; it carries none of the traffic.
STUN = "stun:stun.l.google.com:19302"
CHUNK = 16 * 1024
# How much may wait in a channel before the sender pauses reading.
HIGH_WATER = 1024 * 1024
MAX_PEERS = 4
SDP_MAX = 64 * 1024


def configuration(stun=STUN, relay=None):
    """Where a connection may look for a way through: the server that tells
    each device its own address, and the owner's relay if there is one
    ({"url", "username", "credential"}, identity.load_relay)."""
    servers = [RTCIceServer(urls=stun)] if stun else []
    if relay:
        servers.append(RTCIceServer(urls=relay["url"], username=relay.get("username") or None,
                                    credential=relay.get("credential") or None))
    return RTCConfiguration(iceServers=servers)


def _kinds(sdp):
    """Which kinds of address a description carries, without the addresses:
    'host' is on its own network, 'srflx' is as the internet sees it."""
    found = {}
    for line in sdp.splitlines():
        if line.startswith("a=candidate:") and " typ " in line:
            parts = line.split()
            kind = parts[parts.index("typ") + 1] + ("6" if ":" in parts[4] else "")
            found[kind] = found.get(kind, 0) + 1
    return ", ".join(f"{count} {kind}" for kind, count in sorted(found.items())) or "no addresses"


def _addresses(sdp, kind):
    found = []
    for line in sdp.splitlines():
        parts = line.split()
        if line.startswith("a=candidate:") and "typ" in parts and parts[parts.index("typ") + 1] == kind:
            found.append(parts[4])
    return found


def _relation(offer, answer):
    """Where the two devices are in relation to each other, in words: it is
    what decides whether a direct connection can be made at all."""
    public = set(_addresses(offer, "srflx")) & set(_addresses(answer, "srflx"))
    mine = {a.rsplit(".", 1)[0] for a in _addresses(answer, "host") if "." in a}
    near = any(a.rsplit(".", 1)[0] in mine for a in _addresses(offer, "host") if "." in a)
    if near:
        return "the phone is on this computer's own network"
    if public:
        return "both are behind the same router, on different networks of it"
    # Which networks it is on, by the start of each address only.
    where = sorted({".".join(a.split(".")[:2]) + ".x" for a in _addresses(offer, "host") if "." in a})
    return "the phone is on another network" + (f" ({', '.join(where)})" if where else "")


async def _send_all(channel, data):
    """Send bytes on a data channel in pieces, waiting while it is backed up."""
    for start in range(0, len(data), CHUNK):
        while channel.readyState == "open" and channel.bufferedAmount > HIGH_WATER:
            await asyncio.sleep(0.01)
        if channel.readyState != "open":
            return False
        channel.send(data[start:start + CHUNK])
    return True


async def _join(channel, reader, writer, early=()):
    """Carry bytes both ways between a data channel and a TCP connection
    until either side ends."""
    for message in early:
        writer.write(message)

    @channel.on("message")
    def to_tcp(message):
        if isinstance(message, bytes) and not writer.is_closing():
            writer.write(message)

    @channel.on("close")
    def closed():
        if not writer.is_closing():
            writer.close()

    try:
        while True:
            data = await reader.read(CHUNK)
            if not data or not await _send_all(channel, data):
                break
    except (ConnectionError, OSError):
        pass
    finally:
        if not writer.is_closing():
            writer.close()
        if channel.readyState == "open":
            channel.close()


class TunnelServer:
    """The computer's end: answers a phone's offer, and joins each channel
    the phone opens to the link's port."""

    def __init__(self, port, stun=STUN, report=None, relay=None):
        self.port = port
        self.stun = stun
        self.relay = relay
        self._peers = set()
        # Told how each connection went, for the owner's log: a direct
        # connection that cannot be made is otherwise silent on this side.
        self._report = report or (lambda _what: None)

    async def answer(self, offer_sdp):
        """The answer to send back for a phone's offer."""
        if not isinstance(offer_sdp, str) or not 0 < len(offer_sdp) <= SDP_MAX:
            raise ValueError("not an offer")
        # Bounded: the oldest connection makes room for a new one.
        while len(self._peers) >= MAX_PEERS:
            await self._drop(next(iter(self._peers)))

        peer = RTCPeerConnection(configuration(self.stun, self.relay))
        self._peers.add(peer)

        @peer.on("datachannel")
        def opened(channel):
            if channel.label != "tcp":
                return   # the channel that only holds the connection open
            # Listened to from this very moment: a phone sends its first
            # bytes along with the channel itself, and they arrive before
            # the connection to the link's port has been made.
            early = []
            channel.on("message", lambda message: early.append(message) if isinstance(message, bytes) else None)
            asyncio.ensure_future(self._serve(channel, early))

        @peer.on("connectionstatechange")
        async def changed():
            if peer.connectionState in ("connected", "failed"):
                self._report(peer.connectionState)
            if peer.connectionState in ("failed", "closed", "disconnected"):
                await self._drop(peer)

        await peer.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
        await peer.setLocalDescription(await peer.createAnswer())
        self._report(f"phone offers {_kinds(offer_sdp)}; this computer {_kinds(peer.localDescription.sdp)}; "
                     f"{_relation(offer_sdp, peer.localDescription.sdp)}")
        return peer.localDescription.sdp

    async def _serve(self, channel, early):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        except OSError:
            channel.close()
            return
        channel.remove_all_listeners("message")
        if channel.readyState != "open":
            writer.close()
            return
        await _join(channel, reader, writer, early)

    async def _drop(self, peer):
        self._peers.discard(peer)
        try:
            await peer.close()
        except Exception:  # noqa: BLE001 - it is being thrown away
            pass

    async def close(self):
        for peer in list(self._peers):
            await self._drop(peer)

    @property
    def connected(self):
        return sum(1 for peer in self._peers if peer.connectionState == "connected")


class TunnelClient:
    """The phone's end, in Python: what the Android app does, for the checks
    (verify-link.py plays the phone with it). It listens on a local port and
    opens a channel for each connection made to it."""

    def __init__(self, stun=STUN):
        self.peer = RTCPeerConnection(configuration(stun))
        self._server = None
        self.port = 0
        # The first channel is made before the offer, so the offer describes
        # a connection that carries data channels at all.
        self._control = self.peer.createDataChannel("control")

    async def offer(self):
        await self.peer.setLocalDescription(await self.peer.createOffer())
        return self.peer.localDescription.sdp

    async def accept(self, answer_sdp, timeout=20):
        await self.peer.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))
        opened = asyncio.Event()
        if self._control.readyState == "open":
            opened.set()
        self._control.on("open", opened.set)
        await asyncio.wait_for(opened.wait(), timeout)
        self._server = await asyncio.start_server(self._accepted, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def _accepted(self, reader, writer):
        channel = self.peer.createDataChannel("tcp")
        opened = asyncio.Event()
        channel.on("open", opened.set)
        try:
            await asyncio.wait_for(opened.wait(), 15)
        except asyncio.TimeoutError:
            writer.close()
            return
        await _join(channel, reader, writer)

    async def close(self):
        if self._server is not None:
            self._server.close()
        await self.peer.close()
