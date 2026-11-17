"""Exercise actual binary gRPC-Web framing through ASGI to the real gRPC stack."""
import asyncio
import json
import struct
import uuid

import httpx
from collab.v1 import browser_pb2
from collab_client.browser import BrowserApp, RPC, MAX_BODY
from stack import running_stack


class Browser:
    def __init__(self, http):
        self.http, self.key = http, ""

    async def call(self, action, *args, request_id=None):
        request = browser_pb2.BrowserRequest(session_key=self.key, action=action,
                                           arguments_json=json.dumps(args), request_id=request_id or uuid.uuid4().hex).SerializeToString()
        response = await self.http.post(RPC, content=b"\0" + struct.pack(">I", len(request)) + request,
            headers={"content-type": "application/grpc-web+proto", "origin": "https://course.example"})
        assert response.status_code == 200, response.text
        data = response.content
        assert data[0] == 0
        size = int.from_bytes(data[1:5], "big")
        reply = browser_pb2.BrowserReply.FromString(data[5:5 + size])
        assert b"grpc-status: 0" in data[5 + size:]
        self.key = reply.session_key
        return json.loads(reply.result_json)


def test_browser_login_two_users_live_edit_history_logout_and_no_destination_override():
    async def scenario():
        async with running_stack() as stack:
            app = BrowserApp(stack.gateway, ["https://course.example"])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo") as http:
                alice, bob = Browser(http), Browser(http)
                try:
                    assert (await alice.call("settings"))["ok"]
                    assert (await bob.call("settings"))["ok"]
                    assert alice.key != bob.key
                    assert not (await alice.call("poll"))["ok"]
                    assert not (await alice.call("login", "alice", "wrong"))["ok"]
                    assert (await alice.call("configure", "169.254.169.254:80", False))["ok"]
                    assert app.service.visitors[alice.key].session.gateway == stack.gateway
                    assert (await alice.call("login", "alice", "alice123"))["data"]["username"] == "alice"
                    assert (await bob.call("login", "bob", "bob123"))["data"]["username"] == "bob"
                    created = await alice.call("create", "Browser shared notes")
                    doc = created["data"]["document"]
                    assert (await bob.call("open", doc["id"]))["ok"]
                    save_id = uuid.uuid4().hex
                    saved = await alice.call("save", doc["id"], "", "Hello from the browser 🎉", doc["revision"], request_id=save_id)
                    assert saved["ok"], saved
                    # Simulate a committed save whose HTTP reply was lost.
                    retried = await alice.call("save", doc["id"], "", "Hello from the browser 🎉", doc["revision"], request_id=save_id)
                    assert retried == saved
                    assert len((await alice.call("history"))["data"]) == 2
                    assert not (await alice.call("save", doc["id"], "", "different", doc["revision"], request_id=save_id))["ok"]
                    for _ in range(50):
                        state = (await bob.call("poll"))["data"]
                        if state["document"]["text"] == "Hello from the browser 🎉":
                            break
                        await asyncio.sleep(.02)
                    assert state["document"]["text"] == "Hello from the browser 🎉"
                    assert {p["name"] for p in state["document"]["participants"]} == {"alice", "bob"}
                    revision = state["document"]["revision"]
                    assert (await bob.call("save", doc["id"], state["document"]["text"], "Both people can write.", revision))["ok"]
                    history = await bob.call("history")
                    assert history["data"][0]["author"] == "bob"
                    assert (await bob.call("assist", "summary"))["ok"]
                    assert not (await bob.call("__getattribute__", "client"))["ok"]
                    assert (await bob.call("logout"))["ok"]
                    assert (await bob.call("poll"))["expired"]
                    assert (await alice.call("poll"))["ok"]
                finally:
                    await app.service.close()
    asyncio.run(scenario())


def test_browser_origins_framing_static_files_limits_and_session_expiry():
    async def scenario():
        app = BrowserApp(discovery="https://api.github.com/example-registry")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo") as http:
            try:
                denied = await http.options(RPC, headers={"origin": "https://untrusted.example"})
                assert denied.status_code == 403
                allowed = await http.options(RPC, headers={"origin": "http://demo"})
                assert allowed.headers["access-control-allow-origin"] == "http://demo"
                assert (await http.get("/" )).text.count('data-client="browser"') == 1
                assert (await http.get("/browser.js")).headers["content-type"].startswith("text/javascript")
                assert "COMMONPLACE_DISCOVERY" not in (await http.get("/browser-config.js")).text
                public_config = await http.get("/browser-config.js", headers={"host": "demo.app.lhr.life"})
                assert "COMMONPLACE_DISCOVERY" in public_config.text
                assert (await http.get("/../desktop.py")).status_code == 404
                assert (await http.post(RPC, content=b"broken")).status_code == 400
                assert (await http.post(RPC, content=b"x" * (MAX_BODY + 1))).status_code == 413
                browser = Browser(http)
                # This test uses the permitted same origin.
                app.origins.add("https://course.example")
                assert (await browser.call("settings"))["ok"]
                old_key = browser.key
                app.service.visitors[old_key].touched -= 1900
                await app.service.cleanup()
                expired = await browser.call("poll")
                assert expired["expired"] and not browser.key
                assert (await browser.call("settings"))["ok"]
                app.service.max_sessions = 1
                assert not (await Browser(http).call("settings"))["ok"]
            finally:
                await app.service.close()
    asyncio.run(scenario())
