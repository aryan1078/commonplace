"""Native HTML desktop editor. Its network client communicates over gRPC.

The local webview binding calls the existing Python client on one asyncio loop.
Passwords and tokens stay in process memory. No HTTP application server is used.
"""
import argparse
import asyncio
import difflib
import re
import threading
from pathlib import Path

import grpc
from google.protobuf.json_format import MessageToDict

from collab.v1 import assist_pb2, gateway_pb2
from .client import CollabClient, CollabError
from .textops import Change, apply_changes, rebase, utf16_len, map_position


def differences(before, after):
    """Use character boundaries, then convert positions to UTF-16 units."""
    return [Change(utf16_len(before[:i]), utf16_len(before[:j]), after[a:b])
            for tag, i, j, a, b in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
            if tag != "equal"]


def merge_draft(base, local, canonical, caret):
    remote = differences(base, canonical)
    pending = rebase(differences(base, local), remote)
    merged = apply_changes(canonical.encode("utf-16-le"), pending).decode("utf-16-le")
    # Cursor mapping follows the same text-position rules as edits.
    mapped = map_position(caret, differences(local, merged), True)
    return {"text": merged, "caret": mapped}


class DesktopSession:
    def __init__(self, gateway, tls=False, certificates=None):
        self.gateway, self.tls, self.certificates = gateway, tls, certificates
        self.client = None
        self.view = None
        self.documents = []
        self.suggestions = []
        self.pending_save = None
        self.mutation = asyncio.Lock()

    def require_login(self):
        if self.client is None or not self.client.token:
            raise CollabError(gateway_pb2.UNAUTHENTICATED, "Sign in to continue.")

    async def login(self, username, password):
        async with self.mutation:
            if self.client:
                await self._logout()
            client = CollabClient(self.gateway, tls=self.tls, root_certificates=self.certificates)
            try:
                reply = await asyncio.wait_for(client.login(username.strip(), password), 10)
                if reply.status != gateway_pb2.OK:
                    raise ValueError("The username or password is incorrect.")
            except BaseException:
                await client.close()
                raise
            self.client = client
            await self.refresh_documents()
            return self.state()

    async def configure(self, gateway, tls):
        if self.client:
            await self._logout()
        if not re.fullmatch(r"[A-Za-z0-9.:-]+:[0-9]{1,5}", gateway) or not 0 < int(gateway.rsplit(":", 1)[1]) < 65536:
            raise ValueError("Enter the server as hostname:port, for example localhost:50070.")
        self.gateway, self.tls = gateway, bool(tls)
        return {}

    async def settings(self):
        return {"gateway": self.gateway, "tls": self.tls}

    async def refresh_documents(self):
        self.require_login()
        status, items = await self.client.get("documents")
        if status != gateway_pb2.OK:
            raise CollabError(status)
        self.documents = [{"id": key, "revision": int(data.revision), "length": int(data.length)}
                          for key, data in items]
        return self.state()

    async def open(self, doc_id):
        async with self.mutation:
            self.require_login()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", doc_id):
                raise ValueError("Choose a document from the list.")
            view = await asyncio.wait_for(self.client.join(doc_id), 15)
            if self.view:
                await self.view.close()
            self.view = view
            self.suggestions = []
            return self.state()

    async def create(self, name):
        self.require_login()
        doc_id = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:80]
        if not doc_id:
            raise ValueError("Enter a document name using letters or numbers.")
        await self.refresh_documents()
        if any(item["id"] == doc_id for item in self.documents):
            raise ValueError("That document already exists. Choose it from the list.")
        await self.client.edit(doc_id, [], 0, max_attempts=3)
        await self.refresh_documents()
        return await self.open(doc_id)

    def state(self):
        self.require_login()
        result = {"username": self.client.username, "gateway": self.gateway,
                  "documents": self.documents, "document": None}
        if self.view:
            v = self.view
            if v.closed and v.closed.status == gateway_pb2.UNAUTHENTICATED:
                raise CollabError(gateway_pb2.UNAUTHENTICATED, "Your session ended. Sign in again.")
            result["document"] = {"id": v.doc_id, "text": v.text, "revision": v.revision,
                "connected": v.closed is None,
                "participants": [{"name": p.name, "color": p.color, "editing": p.editing,
                                  "session": p.session_id} for p in v.participants]}
        return result

    async def poll(self):
        if self.view and self.view.closed and self.view.closed.status == gateway_pb2.UNAVAILABLE:
            async with self.mutation:
                old = self.view
                replacement = await asyncio.wait_for(self.client.join(old.doc_id), 15)
                self.view = replacement
                await old.close()
        return self.state()

    async def save(self, doc_id, base_text, new_text, base_revision):
        async with self.mutation:
            self.require_login()
            if not self.view or self.view.doc_id != doc_id:
                raise ValueError("Reopen this document before saving.")
            if len(new_text) > 200000:
                raise ValueError("This editor supports documents up to 200,000 characters.")
            if self.view.closed and self.view.closed.status == gateway_pb2.UNAVAILABLE:
                old = self.view
                self.view = await asyncio.wait_for(self.client.join(doc_id), 15)
                await old.close()
            pending = self.pending_save
            if pending and pending["owner"] == self.client.username and pending["doc_id"] == doc_id:
                await self._submit_pending()
                canonical = self.view.text
                if base_text == pending["before"]:
                    new_text = merge_draft(pending["after"], new_text, canonical, utf16_len(new_text))["text"]
                    base_text, base_revision = canonical, self.view.revision
            changes = differences(base_text, new_text)
            if changes:
                from collab.v1 import common_pb2
                self.pending_save = {"owner": self.client.username, "doc_id": doc_id,
                    "before": base_text, "after": new_text, "revision": int(base_revision),
                    "operation_id": common_pb2.OpId(client_id=self.client.client_id, seq=self.client._seq + 1)}
                await self._submit_pending()
            return self.state()

    async def _submit_pending(self):
        pending = self.pending_save
        result = await self.client.edit(pending["doc_id"], differences(pending["before"], pending["after"]),
            pending["revision"], self.view.session_id, max_attempts=6, operation_id=pending["operation_id"])
        await self.view.wait_for_revision(result.revision, timeout=15)
        self.pending_save = None

    async def cursor(self, start, end):
        self.require_login()
        if self.view and not self.view.closed:
            await self.client.move_cursor(self.view, int(start), int(end))
        return {}

    async def history(self):
        self.require_login()
        if not self.view:
            return []
        operations = await self.client.history(self.view.doc_id)
        return [{"revision": int(c.revision), "author": c.operation.user_id,
                 "changes": [{"start": int(x.range.start), "end": int(x.range.end),
                              "text": x.insert} for x in c.operation.changes]}
                for c in reversed(operations)]

    async def cluster(self):
        self.require_login()
        reply = await self.client.stub.ClusterStatus(gateway_pb2.ClusterStatusRequest(
            token=self.client.token, doc_id=self.view.doc_id if self.view else ""), timeout=5)
        if reply.status != gateway_pb2.OK:
            raise CollabError(reply.status)
        return {"ai_mode": reply.ai_mode, "nodes": [MessageToDict(n, preserving_proto_field_name=True,
                              always_print_fields_with_no_presence=True) for n in reply.nodes]}

    async def assist(self, task, start=0, end=0, question="", mode="concise"):
        self.require_login()
        if not self.view or not self.view.text.strip():
            raise ValueError("Write something in the document first.")
        view, client = self.view, self.client
        if task == "grammar":
            suggestions = await client.check_grammar(view)
        elif task == "enhance":
            if start == end:
                raise ValueError("Select the text you want to rewrite in the document.")
            modes = {"concise": 1, "formal": 2, "clarify": 3, "expand": 4}
            suggestions = await client.enhance(view, int(start), int(end), modes[mode])
        elif task == "summary":
            text = ""
            revision = view.revision
            async for event in client.assist_stream(view.doc_id,
                    summarize=assist_pb2.SummarizeRequest(length=assist_pb2.SUMMARY_LENGTH_MEDIUM)):
                text += event.summary.delta
                revision = event.summary.revision
            return {"text": text, "revision": int(revision), "doc_id": view.doc_id}
        elif task == "ask":
            if not question.strip():
                raise ValueError("Enter a question about the document.")
            event = await client.ask(view.doc_id, question.strip())
            return {"text": event.answer.answer, "revision": int(event.answer.revision), "doc_id": view.doc_id}
        elif task == "complete":
            position = min(int(start), utf16_len(view.text))
            revision = view.revision
            text = ""
            async for event in client.assist_stream(view.doc_id, autocomplete=assist_pb2.AutocompleteRequest(
                    context=view.text_context(position, position), max_tokens=100)):
                text += event.autocomplete.delta
            from collab.v1 import common_pb2
            suggestions = [assist_pb2.Suggestion(anchor=common_pb2.TextAnchor(doc_id=view.doc_id,
                revision=revision, range=common_pb2.TextRange(start=position, end=position)),
                original="", replacement=text, reason="Suggested continuation")]
        else:
            raise ValueError("Choose an assistance tool.")
        if view is not self.view:
            raise ValueError("The document changed. Run the tool again in the current document.")
        self.suggestions = list(suggestions)
        return {"doc_id": view.doc_id, "suggestions": [{"index": i, "original": s.original,
                "replacement": s.replacement, "reason": s.reason, "revision": int(s.anchor.revision)}
                for i, s in enumerate(suggestions)]}

    async def accept(self, index):
        async with self.mutation:
            self.require_login()
            suggestion = self.suggestions[int(index)]
            if not self.view or suggestion.anchor.doc_id != self.view.doc_id:
                raise ValueError("This suggestion belongs to another document.")
            revision, text = self.view.revision, self.view._text
            changes = [Change(suggestion.anchor.range.start, suggestion.anchor.range.end, suggestion.replacement)]
            for c in await self.client.history(self.view.doc_id, suggestion.anchor.revision):
                if c.revision > revision:
                    break
                changes = rebase(changes, [Change(x.range.start, x.range.end, x.insert) for x in c.operation.changes])
            change = changes[0]
            if text[change.start*2:change.end*2].decode("utf-16-le") != suggestion.original:
                raise ValueError("Someone edited this passage. Check it again for a fresh suggestion.")
            result = await self.client.edit(self.view.doc_id, changes, revision, self.view.session_id)
            await self.view.wait_for_revision(result.revision, timeout=15)
            self.suggestions = []
            return self.state()

    async def _logout(self):
        if self.view:
            await self.view.close()
            self.view = None
        if self.client:
            try:
                await asyncio.wait_for(self.client.logout(), 3)
            except (grpc.RpcError, TimeoutError):
                pass
            finally:
                await self.client.close()
                self.client = None
        self.documents, self.suggestions = [], []

    async def logout(self):
        async with self.mutation:
            await self._logout()
        return {}


class DesktopAPI:
    """Thread-safe pywebview bridge. Public methods return serializable data."""
    def __init__(self, gateway, tls=False, certificates=None):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.session = DesktopSession(gateway, tls, certificates)

    def _call(self, method, *args):
        try:
            result = asyncio.run_coroutine_threadsafe(getattr(self.session, method)(*args), self.loop).result(timeout=210)
            return {"ok": True, "data": result}
        except CollabError as error:
            return {"ok": False, "error": str(error), "expired": error.status == gateway_pb2.UNAUTHENTICATED}
        except (grpc.RpcError, TimeoutError):
            return {"ok": False, "error": "The server is taking too long to respond. Check the connection and try again."}
        except (ValueError, IndexError, KeyError) as error:
            return {"ok": False, "error": str(error)}
        except Exception:
            import logging
            logging.exception("Desktop request failed")
            return {"ok": False, "error": "The request could not be completed. Try again."}

    def configure(self, gateway, tls): return self._call("configure", gateway, tls)
    def settings(self): return self._call("settings")
    def login(self, username, password): return self._call("login", username, password)
    def logout(self): return self._call("logout")
    def poll(self): return self._call("poll")
    def documents(self): return self._call("refresh_documents")
    def open(self, doc_id): return self._call("open", doc_id)
    def create(self, name): return self._call("create", name)
    def save(self, doc_id, before, after, revision): return self._call("save", doc_id, before, after, revision)
    def cursor(self, start, end): return self._call("cursor", start, end)
    def history(self): return self._call("history")
    def cluster(self): return self._call("cluster")
    def assist(self, task, start=0, end=0, question="", mode="concise"):
        return self._call("assist", task, start, end, question, mode)
    def accept(self, index): return self._call("accept", index)
    def merge(self, base, local, canonical, caret):
        return {"ok": True, "data": merge_draft(base, local, canonical, int(caret))}

    def shutdown(self):
        self._call("logout")
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the shared document editor")
    parser.add_argument("--gateway", default="localhost:50070")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--ca-cert", type=Path)
    args = parser.parse_args(argv)
    import webview
    api = DesktopAPI(args.gateway, args.tls, args.ca_cert.read_bytes() if args.ca_cert else None)
    window = webview.create_window("Commonplace — Shared documents", str(Path(__file__).parent / "ui/index.html"),
                                   js_api=api, width=1400, height=920, min_size=(1000, 680), maximized=True,
                                   background_color="#f6f4ee")
    def confirm_close():
        try:
            if window.evaluate_js("window.hasUnsavedChanges && window.hasUnsavedChanges()"):
                return window.create_confirmation_dialog("Unsaved changes",
                    "Some text is still waiting to save. Close and discard the unsaved text?")
        except Exception:
            pass
        return True
    window.events.closing += confirm_close
    window.events.closed += api.shutdown
    webview.start()
    return 0
