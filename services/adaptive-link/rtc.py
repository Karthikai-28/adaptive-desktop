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

There is no relay. On networks that do not allow a direct connection at all
(some mobile carriers) the tunnel cannot be made, and the phone says so.
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


def configuration(stun=STUN):
    servers = [RTCIceServer(urls=stun)] if stun else []
    return RTCConfiguration(iceServers=servers)


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

    def __init__(self, port, stun=STUN):
        self.port = port
        self.stun = stun
        self._peers = set()

    async def answer(self, offer_sdp):
        """The answer to send back for a phone's offer."""
        if not isinstance(offer_sdp, str) or not 0 < len(offer_sdp) <= SDP_MAX:
            raise ValueError("not an offer")
        # Bounded: the oldest connection makes room for a new one.
        while len(self._peers) >= MAX_PEERS:
            await self._drop(next(iter(self._peers)))

        peer = RTCPeerConnection(configuration(self.stun))
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
            if peer.connectionState in ("failed", "closed", "disconnected"):
                await self._drop(peer)

        await peer.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
        await peer.setLocalDescription(await peer.createAnswer())
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
