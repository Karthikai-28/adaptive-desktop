"""The Agent Office (services/agent-office), from a paired phone.

The office listens on 127.0.0.1 only and turns away other hosts and origins, so a phone cannot
reach it directly, and nothing new is opened for it. Instead the link carries it, inside the same
mutual TLS as everything else, at home or away:

  /v1/office/api/<path>   the office's /api/<path> (GET and POST, bodies and query passed through)
  /v1/office/ws           its live updates, relayed both ways

Directing the office means directing agents that run commands, so it takes the commands switch
(allow_exec): a device held back from commands is held back from the office too.
"""
import asyncio
import json
import os
from pathlib import Path

import aiohttp
from aiohttp import WSMsgType, web

CONFIG = Path(__file__).resolve().parent.parent / "agent-office" / "config.json"
SWITCH = "allow_exec"


def office_port():
    if os.environ.get("OFFICE_PORT", "").isdigit():
        return int(os.environ["OFFICE_PORT"])
    try:
        return int(json.loads(CONFIG.read_text()).get("port", 8790))
    except (OSError, ValueError, TypeError):
        return 8790


def _error(status, message):
    return web.json_response({"ok": False, "error": message}, status=status)


class OfficeGateway:
    def __init__(self, link):
        self.link = link
        self._session = None

    def routes(self, add):
        add.add_get("/v1/office/ws", self.h_ws)
        add.add_get("/v1/office/api/{tail:.*}", self.h_api)
        add.add_post("/v1/office/api/{tail:.*}", self.h_api)

    def _http(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=3, sock_read=120))
        return self._session

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def base(self):
        return f"127.0.0.1:{office_port()}"

    async def h_api(self, request):
        if not self.link._allowed(SWITCH):
            return _error(403, "the office needs the commands switch, which is off for this device")
        tail = request.match_info["tail"]
        headers = {"X-Office": "1"} if request.method == "POST" else {}
        if request.content_type:
            headers["Content-Type"] = request.content_type
        body = await request.read() if request.method == "POST" else None
        if request.method == "POST":
            self.link.audit.write(request["peer"], "office", f"{tail}")
        try:
            async with self._http().request(request.method, f"http://{self.base}/api/{tail}",
                                            params=request.query, data=body, headers=headers) as up:
                out = web.StreamResponse(status=up.status, headers={
                    "Content-Type": up.headers.get("Content-Type", "application/octet-stream")})
                if up.content_length is not None:
                    out.content_length = up.content_length
                await out.prepare(request)
                async for chunk in up.content.iter_chunked(64 * 1024):
                    await out.write(chunk)
                await out.write_eof()
                return out
        except aiohttp.ClientConnectorError:
            return _error(503, "the office is not running on the computer")
        except asyncio.TimeoutError:
            return _error(504, "the office did not answer in time")

    async def h_ws(self, request):
        if not self.link._allowed(SWITCH):
            return _error(403, "the office needs the commands switch, which is off for this device")
        try:
            up = await self._http().ws_connect(f"ws://{self.base}/ws", origin=f"http://{self.base}",
                                               heartbeat=20, max_msg_size=0)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return _error(503, "the office is not running on the computer")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=0)
        await ws.prepare(request)
        self.link._track(ws)

        async def down():                       # office -> phone
            async for m in up:
                if m.type == WSMsgType.TEXT:
                    await ws.send_str(m.data)
                elif m.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

        async def upward():                     # phone -> office (keep-alives)
            async for m in ws:
                if m.type == WSMsgType.TEXT:
                    await up.send_str(m.data)
                elif m.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

        tasks = [asyncio.create_task(down()), asyncio.create_task(upward())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await up.close()
            await ws.close()
        return ws
