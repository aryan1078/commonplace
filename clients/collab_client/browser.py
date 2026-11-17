"""ASGI gRPC-Web edge. Only this port is exposed to browser visitors.

Each browser tab gets a separate in-memory client. Gateway login, Raft commits,
live gRPC subscriptions and AI calls use the same client as the desktop editor.
"""
import argparse
import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import secrets
import time
from urllib.parse import quote

import grpc
from sonora.asgi import grpcASGI
from sonora import protocol

from collab.v1 import browser_pb2, browser_pb2_grpc, gateway_pb2
from .client import CollabError
from .desktop import DesktopSession, merge_draft

UI = Path(__file__).parent / "ui"
RPC = "/collab.v1.BrowserService/Call"
MAX_BODY = 4 * 1024 * 1024


@dataclass
class Visitor:
    session: DesktopSession
    touched: float = field(default_factory=time.monotonic)
    active: int = 0
    login_attempts: list = field(default_factory=list)
    requests: OrderedDict = field(default_factory=OrderedDict)


class BrowserService(browser_pb2_grpc.BrowserServiceServicer):
    METHODS = {name: name for name in (
        "login", "logout", "poll", "open", "create", "save", "cursor",
        "history", "cluster", "assist", "accept")}
    METHODS["documents"] = "refresh_documents"

    def __init__(self, gateway, tls=False, certificates=None, max_sessions=64, ttl=1800):
        self.gateway, self.tls, self.certificates = gateway, tls, certificates
        self.max_sessions, self.ttl = max_sessions, ttl
        self.visitors = {}

    async def cleanup(self):
        now = time.monotonic()
        keys = [key for key, v in self.visitors.items()
                if not v.active and not any(not task.done() for _, task in v.requests.values())
                and now - v.touched > self.ttl]
        # Remove every expired key before yielding; overlapping cleanup passes
        # cannot close a session twice or reap one whose next request just began.
        expired = [self.visitors.pop(key) for key in keys]
        await asyncio.gather(*(v.session.logout() for v in expired), return_exceptions=True)

    async def close(self):
        visitors, self.visitors = self.visitors, {}
        await asyncio.gather(*(v.session.logout() for v in visitors.values()), return_exceptions=True)

    def reply(self, key, result):
        return browser_pb2.BrowserReply(session_key=key,
            result_json=json.dumps(result, ensure_ascii=False))

    async def Call(self, request, context):
        key, visitor = request.session_key, None
        try:
            args = json.loads(request.arguments_json or "[]")
            if not isinstance(args, list) or len(args) > 6:
                raise ValueError("Invalid request arguments.")
            if request.action == "settings" and not key:
                # Cleanup is periodic too; reclaim an idle slot before refusing.
                await self.cleanup()
                if len(self.visitors) >= self.max_sessions:
                    raise ValueError("The demo is busy. Try again in a few minutes.")
                key = secrets.token_urlsafe(32)
                self.visitors[key] = Visitor(DesktopSession(self.gateway, self.tls, self.certificates))
            visitor = self.visitors.get(key)
            if visitor is None:
                return self.reply("", {"ok": False, "expired": True,
                    "error": "Your browser session ended. Sign in again."})
            visitor.active += 1
            visitor.touched = time.monotonic()
            if request.action == "settings":
                result = {"gateway": "Commonplace online", "tls": True}
            elif request.action == "configure":
                # Browsers can never choose an internal destination or disable TLS.
                result = {}
            elif request.action == "merge":
                visitor.session.require_login()
                if any(not isinstance(s, str) or len(s) > 400000 for s in args[:3]):
                    raise ValueError("This draft is too large.")
                result = merge_draft(*args)
            elif request.action in self.METHODS:
                if request.action == "login":
                    now = time.monotonic()
                    visitor.login_attempts = [t for t in visitor.login_attempts if now - t < 60]
                    if len(visitor.login_attempts) >= 8:
                        raise ValueError("Too many sign-in attempts. Wait a minute and try again.")
                    visitor.login_attempts.append(now)
                method = getattr(visitor.session, self.METHODS[request.action])
                # The existing save path retains its operation ID for safe retry.
                if request.action in {"save", "create", "open", "accept", "login", "logout"}:
                    if not request.request_id or len(request.request_id) > 100:
                        raise ValueError("This action needs a valid request ID. Refresh the editor.")
                    signature = (request.action, hashlib.sha256(request.arguments_json.encode()).digest())
                    previous = visitor.requests.get(request.request_id)
                    if previous:
                        if previous[0] != signature:
                            raise ValueError("This request ID was already used for another action.")
                        task = previous[1]
                    else:
                        while len(visitor.requests) >= 128:
                            completed = next((key for key, (_, item) in visitor.requests.items() if item.done()), None)
                            if completed is None:
                                raise ValueError("Too many requests are pending. Wait for the current save.")
                            visitor.requests.pop(completed)
                        task = asyncio.create_task(method(*args))
                        visitor.requests[request.request_id] = (signature, task)
                    try:
                        result = await asyncio.shield(task)
                    except BaseException:
                        # Failed saves may still hold an ambiguous native operation;
                        # retry the method, which preserves that operation ID.
                        if task.done():
                            visitor.requests.pop(request.request_id, None)
                        raise
                else:
                    result = await method(*args)
                if isinstance(result, dict) and "gateway" in result:
                    result["gateway"] = "Commonplace online"
            else:
                raise ValueError("This action is not available.")
            return self.reply(key, {"ok": True, "data": result})
        except CollabError as error:
            return self.reply(key, {"ok": False, "error": str(error),
                "expired": error.status == gateway_pb2.UNAUTHENTICATED})
        except (grpc.RpcError, TimeoutError):
            return self.reply(key, {"ok": False,
                "error": "The document server is unavailable. Keep this tab open and retry your save."})
        except (ValueError, IndexError, KeyError, TypeError) as error:
            return self.reply(key, {"ok": False, "error": str(error)})
        except Exception:
            logging.exception("Browser request failed")
            return self.reply(key, {"ok": False, "error": "The request could not be completed. Try again."})
        finally:
            if visitor is not None:
                visitor.active -= 1
                visitor.touched = time.monotonic()


class WebRPC(grpcASGI):
    def add_registered_method_handlers(self, service_name, handlers):
        # grpcio-tools also registers a generic handler, which Sonora uses.
        pass

    async def _do_unary_response(self, rpc_method, receive, send, wrap_message, context, coroutine):
        # Sonora 0.2.3 passes bytes to pack_trailers, whose formatter expects
        # strings. Emit standard `grpc-status: 0`, not Python bytes reprs.
        message = await coroutine if coroutine is not None else None
        payload = wrap_message(False, False, rpc_method.response_serializer(message)) if message is not None else b""
        trailers = [("grpc-status", str(context.code.value[0]))]
        if context.details:
            trailers.append(("grpc-message", quote(context.details)))
        for key, value in context._trailing_metadata or []:
            trailers.append((key.decode() if isinstance(key, bytes) else key,
                             value.decode() if isinstance(value, bytes) else value))
        payload += wrap_message(True, False, protocol.pack_trailers(trailers))
        headers = list(context._response_headers)
        headers.extend(context._initial_metadata or [])
        headers.append((b"content-length", str(len(payload)).encode()))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": payload})


class BrowserApp:
    def __init__(self, gateway="localhost:50070", origins=(), tls=False, certificates=None, origin_file=None, discovery=""):
        self.service = BrowserService(gateway, tls, certificates)
        self.rpc = WebRPC(enable_cors=False)
        browser_pb2_grpc.add_BrowserServiceServicer_to_server(self.service, self.rpc)
        self.origins = set(origins)
        self.origin_file = origin_file
        self.discovery = discovery

    async def reap(self):
        while True:
            await asyncio.sleep(60)
            await self.service.cleanup()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            task = None
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    task = asyncio.create_task(self.reap())
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    if task:
                        task.cancel()
                    await self.service.close()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        headers = dict(scope["headers"])
        origin = headers.get(b"origin", b"").decode("ascii", errors="replace")
        host = headers.get(b"host", b"").decode("ascii", errors="replace")
        tunnel_origins = []
        if self.origin_file and self.origin_file.exists():
            try:
                tunnel_origins = json.loads(self.origin_file.read_text(encoding="utf8"))
            except (OSError, ValueError):
                pass
        allowed = (not origin or origin in self.origins or origin in tunnel_origins
                   or origin in (f"http://{host}", f"https://{host}"))
        if not allowed:
            return await self.respond(send, 403, b"This origin is not allowed.")

        async def secured(event):
            if event["type"] == "http.response.start":
                response_headers = list(event.get("headers", []))
                response_headers.extend([(b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"), (b"cache-control", b"no-store"),
                    (b"x-frame-options", b"DENY")])
                if origin:
                    response_headers.extend([(b"access-control-allow-origin", origin.encode()),
                        (b"vary", b"Origin"), (b"access-control-allow-methods", b"POST, GET, OPTIONS"),
                        (b"access-control-allow-headers", b"content-type, x-grpc-web, grpc-timeout"),
                        (b"access-control-expose-headers", b"grpc-status, grpc-message")])
                event["headers"] = response_headers
            await send(event)

        if scope["method"] == "OPTIONS":
            return await self.respond(secured, 204, b"")
        if scope["path"] == RPC and scope["method"] == "POST":
            body = bytearray()
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                body.extend(event.get("body", b""))
                if len(body) > MAX_BODY:
                    return await self.respond(secured, 413, b"This request is too large.")
                if not event.get("more_body"):
                    break
            # Reject malformed framing before the protobuf deserializer runs.
            if (len(body) < 5 or body[0] != 0
                    or int.from_bytes(body[1:5], "big") != len(body) - 5
                    or not headers.get(b"content-type", b"").startswith(b"application/grpc-web+proto")):
                return await self.respond(secured, 400, b"Invalid gRPC-Web request.")
            try:
                browser_pb2.BrowserRequest.FromString(body[5:])
            except Exception:
                return await self.respond(secured, 400, b"Invalid protobuf message.")
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return {"type": "http.disconnect"}

            return await self.rpc(scope, replay, secured)
        if scope["method"] in ("GET", "HEAD"):
            if scope["path"] == "/healthz":
                return await self.respond(secured, 200, b'{"service":"commonplace-web","ready":true}', "application/json")
            name = "index.html" if scope["path"] == "/" else scope["path"].lstrip("/")
            if name in {"index.html", "style.css", "app.js", "browser.js", "browser-config.js"}:
                data = (UI / name).read_bytes()
                if name == "index.html":
                    data = data.replace(b'<html lang="en">', b'<html lang="en" data-client="browser">')
                if name == "browser-config.js" and self.discovery and host.endswith((".lhr.life", ".lhr.rocks")):
                    data += f"\nwindow.COMMONPLACE_DISCOVERY = {json.dumps(self.discovery)};\n".encode()
                mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}[Path(name).suffix]
                return await self.respond(secured, 200, b"" if scope["method"] == "HEAD" else data, mime)
        await self.respond(secured, 404, b"Not found.")

    @staticmethod
    async def respond(send, status, body, mime="text/plain"):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", f"{mime}; charset=utf-8".encode())]})
        await send({"type": "http.response.body", "body": body})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve the browser editor and gRPC-Web edge")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for a trusted LAN demo")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--gateway", default="localhost:50070")
    parser.add_argument("--allow-origin", action="append", default=["https://aryan1078.github.io"])
    parser.add_argument("--tls", action="store_true", help="Use TLS to the internal gateway")
    parser.add_argument("--ca-cert", type=Path)
    parser.add_argument("--origin-file", type=Path, help="Host-controlled list of current and earlier tunnel origins")
    parser.add_argument("--discovery", default="", help="Public endpoint registry for rotating demo tunnels")
    args = parser.parse_args(argv)
    import uvicorn
    app = BrowserApp(args.gateway, args.allow_origin, args.tls,
                     args.ca_cert.read_bytes() if args.ca_cert else None, args.origin_file, args.discovery)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, server_header=False,
                limit_concurrency=128, timeout_keep_alive=5)


if __name__ == "__main__":
    main()
