#!/usr/bin/env python3
"""A stand-in for Google, for the link's checks.

verify-link.py cannot sign in to a real Google account, and should not
depend on the network. This serves, on localhost, just enough of the four
things the link uses to exercise all of its own code:

  /device/code, /token     Google's sign-in-by-code for devices
  /signin, /refresh        Firebase's exchange of that sign-in for a session
  /users/<uid>/...json     the Realtime Database, with its one rule enforced:
                           only the signed-in owner of <uid> may read or
                           write there - and its event stream

    POST /_test/approve {"email": ...}   the owner approving a code "at Google"

It proves the link's side of the conversation. That Google's side behaves as
documented is checked the first time a real account signs in.
"""

import asyncio
import hashlib
import json
import sys

from aiohttp import web


def uid_of(email):
    return hashlib.sha256(email.lower().encode()).hexdigest()[:24]


class FakeCloud:
    def __init__(self):
        self.tree = {}
        self.codes = {}       # device_code -> approved email, or None
        self.watchers = []    # (path parts, queue)
        self.refuse_refresh = False

    # ------------------------------------------------------------- sign-in

    async def device_code(self, request):
        form = await request.post()
        if not form.get("client_id"):
            return web.json_response({"error": "invalid_client"}, status=401)
        code = f"dev-{len(self.codes) + 1}"
        self.codes[code] = None
        return web.json_response({"device_code": code, "user_code": f"ABCD-{len(self.codes):04d}",
                                  "verification_url": "https://www.google.com/device",
                                  "interval": 1, "expires_in": 60})

    async def approve(self, request):
        email = (await request.json())["email"]
        for code, state in self.codes.items():
            if state is None:
                self.codes[code] = email
        return web.json_response({"ok": True})

    async def token(self, request):
        form = await request.post()
        email = self.codes.get(form.get("device_code"))
        if email is None:
            return web.json_response({"error": "authorization_pending"}, status=428)
        return web.json_response({"id_token": f"google:{email}"})

    async def sign_in(self, request):
        body = await request.json()
        token = dict(part.split("=", 1) for part in body["postBody"].split("&"))["id_token"]
        if not token.startswith("google:") or not request.query.get("key"):
            return web.json_response({"error": {"message": "INVALID_IDP_RESPONSE"}}, status=400)
        email = token[len("google:"):]
        uid = uid_of(email)
        return web.json_response({"localId": uid, "email": email, "emailVerified": True,
                                  "idToken": f"session:{uid}", "refreshToken": f"refresh:{uid}",
                                  "expiresIn": "3600"})

    async def refresh(self, request):
        form = await request.post()
        value = form.get("refresh_token", "")
        if self.refuse_refresh or not value.startswith("refresh:"):
            return web.json_response({"error": {"message": "TOKEN_EXPIRED"}}, status=400)
        return web.json_response({"id_token": f"session:{value[len('refresh:'):]}", "expires_in": "3600"})

    # ------------------------------------------------------------ database

    def _allowed(self, request, parts):
        # The database's one rule: users/<uid> belongs to whoever is signed in as <uid>.
        return len(parts) >= 2 and parts[0] == "users" and request.query.get("auth") == f"session:{parts[1]}"

    def _get(self, parts):
        node = self.tree
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def _set(self, parts, value):
        node = self.tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                return
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value

    def _notify(self, parts, value):
        for watched, queue in list(self.watchers):
            if parts[:len(watched)] == watched:
                queue.put_nowait(("/" + "/".join(parts[len(watched):]), value))
            elif watched[:len(parts)] == parts:
                queue.put_nowait(("/", self._get(watched)))

    async def database(self, request):
        path = request.match_info["path"]
        if not path.endswith(".json"):
            return web.Response(status=404)
        parts = [p for p in path[:-len(".json")].split("/") if p]
        if not self._allowed(request, parts):
            return web.json_response({"error": "Permission denied"}, status=401)

        if request.method == "GET" and "text/event-stream" in request.headers.get("Accept", ""):
            reply = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await reply.prepare(request)
            queue = asyncio.Queue()
            entry = (parts, queue)
            self.watchers.append(entry)
            try:
                await reply.write(f"event: put\ndata: {json.dumps({'path': '/', 'data': self._get(parts)})}\n\n".encode())
                while True:
                    try:
                        sub, value = await asyncio.wait_for(queue.get(), 20)
                        await reply.write(f"event: put\ndata: {json.dumps({'path': sub, 'data': value})}\n\n".encode())
                    except asyncio.TimeoutError:
                        await reply.write(b"event: keep-alive\ndata: null\n\n")
            except (ConnectionResetError, asyncio.CancelledError):
                pass
            finally:
                self.watchers.remove(entry)
            return reply

        if request.method == "GET":
            return web.json_response(self._get(parts))
        if request.method == "DELETE":
            self._set(parts, None)
            self._notify(parts, None)
            return web.json_response(None)
        value = await request.json()
        if request.method == "PATCH" and isinstance(value, dict):
            for key, item in value.items():
                self._set(parts + [key], item)
                self._notify(parts + [key], item)
        else:
            self._set(parts, value)
            self._notify(parts, value)
        return web.json_response(value)

    def app(self):
        app = web.Application()
        app.router.add_post("/device/code", self.device_code)
        app.router.add_post("/token", self.token)
        app.router.add_post("/signin", self.sign_in)
        app.router.add_post("/refresh", self.refresh)
        app.router.add_post("/_test/approve", self.approve)
        app.router.add_route("*", "/{path:users/.*}", self.database)
        return app


def project(base):
    """A cloud.json that points the link at this stand-in."""
    return {"api_key": "test-key", "database_url": base, "web_client_id": "web-client",
            "device_client_id": "device-client", "device_client_secret": "device-secret",
            "endpoints": {"device_code": f"{base}/device/code", "google_token": f"{base}/token",
                          "sign_in": f"{base}/signin", "refresh": f"{base}/refresh"}}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 47950
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    web.run_app(FakeCloud().app(), host=host, port=port, print=None)
