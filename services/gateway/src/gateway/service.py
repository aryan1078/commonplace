"""CollabService: the one gRPC service clients talk to.

The gateway owns everything that is per-connection and not replicated
(tokens, Join sessions, presence) and forwards the rest: edits and reads to
the document service, LLM requests to the Assist service on its own server.
It is also where identity is enforced: an edit's user_id always comes from
the token, never from the client.
"""

import asyncio
import os
import contextlib
import logging
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass

import grpc

from collab.v1 import (
    assist_pb2,
    assist_pb2_grpc,
    document_pb2,
    gateway_pb2,
    gateway_pb2_grpc,
    presence_pb2,
)

from .auth import Session, TokenStore, UserStore
from .docs import DocsClient
from .presence import Cursor, Hub, Participant

log = logging.getLogger("gateway")

DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
OUTBOX_SIZE = 1024  # events queued for one Join stream; presence is dropped beyond this
ASSIST_TIMEOUT_S = 180.0  # a CPU model can be slow on long documents
ASSIST_CONNECT_TIMEOUT_S = 10.0  # how long to wait for an unreachable LLM server
MAX_HISTORY = 1000

S = gateway_pb2  # shorthand for the Status values


@dataclass
class JoinSession:
    session_id: str
    token: str
    username: str
    doc_id: str


def status_for(err: grpc.aio.AioRpcError) -> int:
    """Maps a backend's gRPC error onto the client-facing Status."""
    code = err.code()
    if code == grpc.StatusCode.ABORTED:
        return S.STALE_REVISION
    if code == grpc.StatusCode.INVALID_ARGUMENT:
        return S.INVALID_ARGUMENT
    if code == grpc.StatusCode.NOT_FOUND:
        return S.NOT_FOUND
    return S.UNAVAILABLE


def participant_to_proto(p: Participant) -> presence_pb2.Participant:
    msg = presence_pb2.Participant(
        session_id=p.session_id,
        name=p.name,
        color=p.color,
        last_edit_unix_ms=p.last_edit_unix_ms,
        editing=p.editing,
    )
    if p.cursor is not None:
        msg.cursor.CopyFrom(
            presence_pb2.CursorUpdate(revision=p.cursor.revision, anchor=p.cursor.anchor, head=p.cursor.head)
        )
    return msg


def _closed(status: int, reason: str) -> gateway_pb2.JoinEvent:
    return gateway_pb2.JoinEvent(closed=gateway_pb2.ClosedEvent(status=status, reason=reason))


class CollabService(gateway_pb2_grpc.CollabServiceServicer):
    def __init__(self, users: UserStore, tokens: TokenStore, docs: DocsClient,
                 assist_channel: grpc.aio.Channel, hub: Hub):
        self._users = users
        self._tokens = tokens
        self._docs = docs
        self._assist_channel = assist_channel
        self._assist = assist_pb2_grpc.AssistServiceStub(assist_channel)
        self._hub = hub
        self._sessions: dict[str, JoinSession] = {}

    # ------------------------------------------------------------------ auth

    async def ClusterStatus(self, request, context):
        if self._tokens.validate(request.token) is None:
            return gateway_pb2.ClusterStatusResponse(status=S.UNAUTHENTICATED)
        nodes = await self._docs.cluster_status(request.doc_id)
        return gateway_pb2.ClusterStatusResponse(status=S.OK, nodes=nodes, ai_mode=os.getenv("GATEWAY_AI_MODE", "Configured writing service"))

    async def Login(self, request, context):
        if not await self._users.check(request.username, request.password):
            log.info("failed login for %r", request.username)
            return gateway_pb2.LoginResponse(status=S.INVALID_CREDENTIALS, message="unknown user or wrong password")
        session = self._tokens.issue(request.username)
        log.info("%s logged in", request.username)
        return gateway_pb2.LoginResponse(
            status=S.OK, token=session.token, expires_at_unix_ms=int(session.expires_at * 1000)
        )

    async def Logout(self, request, context):
        session = self._tokens.validate(request.token)
        if session is None or not self._tokens.revoke(request.token):
            return gateway_pb2.LogoutResponse(status=S.UNAUTHENTICATED)
        log.info("%s logged out", session.username)
        return gateway_pb2.LogoutResponse(status=S.OK)

    # ------------------------------------------------------------------ post

    async def Post(self, request, context):
        session = self._tokens.validate(request.token)
        if session is None:
            return gateway_pb2.PostResponse(status=S.UNAUTHENTICATED, message="log in first")
        kind = request.WhichOneof("data")
        if kind == "edit":
            return await self._post_edit(session, request)
        if kind == "cursor":
            return self._post_cursor(session, request)
        return gateway_pb2.PostResponse(status=S.INVALID_ARGUMENT, message="set edit or cursor")

    async def _post_edit(self, session: Session, request) -> gateway_pb2.PostResponse:
        edit = request.edit
        if not DOC_ID_PATTERN.match(edit.doc_id):
            return gateway_pb2.PostResponse(
                status=S.INVALID_ARGUMENT, message="doc_id must be 1-100 letters, digits, '-' or '_'"
            )
        for op in edit.operations:
            # The gateway decides who made an edit and which document it is
            # for; a client cannot claim to be someone else.
            op.doc_id = edit.doc_id
            op.user_id = session.username
        try:
            result = await self._docs.submit(edit)
        except grpc.aio.AioRpcError as err:
            status = status_for(err)
            reply = gateway_pb2.PostResponse(status=status, message=err.details() or "")
            if status == S.STALE_REVISION:
                reply.current_revision = await self._current_revision(edit.doc_id, err)
            return reply

        joined = self._sessions.get(request.session_id)
        if result.applied and joined and joined.token == session.token and joined.doc_id == edit.doc_id:
            self._hub.mark_edited(edit.doc_id, joined.session_id)
        if result.applied:
            log.info("%s edited %s -> revision %d", session.username, edit.doc_id, result.revision)
        return gateway_pb2.PostResponse(status=S.OK, edit=result)

    async def _current_revision(self, doc_id: str, err: grpc.aio.AioRpcError) -> int:
        for key, value in err.trailing_metadata() or ():
            if key == "current-revision":
                return int(value)
        try:
            return (await self._docs.snapshot(doc_id)).revision
        except grpc.aio.AioRpcError:
            return 0

    def _post_cursor(self, session: Session, request) -> gateway_pb2.PostResponse:
        joined = self._sessions.get(request.session_id)
        if joined is None or joined.token != session.token:
            return gateway_pb2.PostResponse(status=S.NOT_FOUND, message="no such Join session for this token")
        c = request.cursor
        self._hub.update_cursor(joined.doc_id, joined.session_id, Cursor(c.revision, c.anchor, c.head))
        return gateway_pb2.PostResponse(status=S.OK)

    # ------------------------------------------------------------------- get

    async def Get(self, request, context):
        if self._tokens.validate(request.token) is None:
            return gateway_pb2.GetResponse(status=S.UNAUTHENTICATED, message="log in first")
        kind = request.WhichOneof("params")
        if kind is None:
            return gateway_pb2.GetResponse(status=S.INVALID_ARGUMENT, message="set one of the params")
        if kind != "documents" and not DOC_ID_PATTERN.match(getattr(request, kind).doc_id):
            return gateway_pb2.GetResponse(status=S.INVALID_ARGUMENT, message="invalid doc_id")
        try:
            items = await self._get_items(kind, getattr(request, kind))
        except grpc.aio.AioRpcError as err:
            return gateway_pb2.GetResponse(status=status_for(err), message=err.details() or "")
        return gateway_pb2.GetResponse(status=S.OK, items=items)

    async def _get_items(self, kind: str, params) -> list[gateway_pb2.Item]:
        if kind == "snapshot":
            snap = await self._docs.snapshot(params.doc_id)
            return [gateway_pb2.Item(id=snap.doc_id, snapshot=snap)]
        if kind == "history":
            limit = min(params.limit or MAX_HISTORY, MAX_HISTORY)
            reply = await self._docs.history(params.doc_id, params.from_revision, limit)
            return [gateway_pb2.Item(id=str(o.revision), operation=o) for o in reply.operations]
        if kind == "presence":
            return [
                gateway_pb2.Item(id=p.session_id, participant=participant_to_proto(p))
                for p in self._hub.participants(params.doc_id)
            ]
        return [gateway_pb2.Item(id=d.doc_id, document=d) for d in await self._docs.documents()]

    # ------------------------------------------------------------------ join

    async def Join(self, request, context) -> AsyncIterator[gateway_pb2.JoinEvent]:
        session = self._tokens.validate(request.token)
        if session is None:
            yield _closed(S.UNAUTHENTICATED, "log in first")
            return
        if not DOC_ID_PATTERN.match(request.doc_id):
            yield _closed(S.INVALID_ARGUMENT, "invalid doc_id")
            return
        try:
            snapshot = await self._docs.snapshot(request.doc_id)
        except grpc.aio.AioRpcError as err:
            yield _closed(S.UNAVAILABLE, f"document service: {err.details()}")
            return

        joined = JoinSession(secrets.token_hex(6), session.token, session.username, request.doc_id)
        outbox: asyncio.Queue[gateway_pb2.JoinEvent] = asyncio.Queue(maxsize=OUTBOX_SIZE)
        closing: list[gateway_pb2.JoinEvent] = []  # set once the stream must end

        def close_with(event: gateway_pb2.JoinEvent) -> None:
            if not closing:
                closing.append(event)
                with contextlib.suppress(asyncio.QueueFull):
                    outbox.put_nowait(event)  # wake the loop; if full it is busy anyway

        def on_presence(participants: list[Participant]) -> None:
            event = gateway_pb2.JoinEvent(
                presence=presence_pb2.PresenceEvent(
                    doc_id=request.doc_id, participants=[participant_to_proto(p) for p in participants]
                )
            )
            with contextlib.suppress(asyncio.QueueFull):
                outbox.put_nowait(event)  # presence is lossy by design

        yield gateway_pb2.JoinEvent(
            joined=gateway_pb2.JoinedEvent(session_id=joined.session_id, name=session.username, snapshot=snapshot)
        )
        log.info("%s joined %s (session %s)", session.username, request.doc_id, joined.session_id)

        self._sessions[joined.session_id] = joined
        leave = self._hub.join(request.doc_id, Participant(joined.session_id, session.username), on_presence)
        unregister = self._tokens.on_revoke(session, lambda: close_with(_closed(S.UNAUTHENTICATED, "logged out")))
        forward = asyncio.create_task(self._forward_operations(request.doc_id, snapshot.revision, outbox, close_with))
        try:
            while True:
                timeout = self._tokens.seconds_left(session)
                try:
                    event = await asyncio.wait_for(outbox.get(), timeout=max(timeout, 0.01))
                except TimeoutError:
                    close_with(_closed(S.UNAUTHENTICATED, "token expired"))
                    event = closing[0]
                if closing and event.WhichOneof("event") != "closed":
                    event = closing[0]  # stop promptly, even with a backlog
                yield event
                if event.WhichOneof("event") == "closed":
                    return
        finally:
            forward.cancel()
            unregister()
            leave()
            self._sessions.pop(joined.session_id, None)
            log.info("%s left %s (session %s)", session.username, request.doc_id, joined.session_id)

    async def _forward_operations(self, doc_id, from_revision, outbox, close_with) -> None:
        try:
            async for msg in self._docs.subscribe(doc_id, from_revision):
                await outbox.put(gateway_pb2.JoinEvent(operation=msg))
            close_with(_closed(S.UNAVAILABLE, "document stream ended"))
        except grpc.aio.AioRpcError as err:
            log.warning("subscription to %s ended: %s", doc_id, err.details())
            close_with(_closed(S.UNAVAILABLE, "lost connection to the document service; join again"))

    # ---------------------------------------------------------------- assist

    async def Assist(self, request, context) -> AsyncIterator[gateway_pb2.AssistEvent]:
        rid = request.request_id

        def event(status: int = S.OK, message: str = "", **result) -> gateway_pb2.AssistEvent:
            return gateway_pb2.AssistEvent(status=status, message=message, request_id=rid, **result)

        if self._tokens.validate(request.token) is None:
            yield event(S.UNAUTHENTICATED, "log in first")
            return
        task = request.WhichOneof("task")
        if task is None:
            yield event(S.INVALID_ARGUMENT, "set one task")
            return
        needs_doc = task == "ask" or (task == "summarize" and not request.summarize.HasField("document"))
        if needs_doc and not DOC_ID_PATTERN.match(request.doc_id):
            yield event(S.INVALID_ARGUMENT, "doc_id is required for this task")
            return

        try:
            # Fail fast if the LLM server is down, but wait out a reconnect:
            # the LLM calls themselves may legitimately take minutes.
            await asyncio.wait_for(self._assist_channel.channel_ready(), ASSIST_CONNECT_TIMEOUT_S)
        except TimeoutError:
            yield event(S.UNAVAILABLE, "the LLM server is not reachable")
            return
        try:
            if task == "check_grammar":
                yield event(grammar=await self._assist.CheckGrammar(request.check_grammar, timeout=ASSIST_TIMEOUT_S))
            elif task == "enhance":
                yield event(enhanced=await self._assist.Enhance(request.enhance, timeout=ASSIST_TIMEOUT_S))
            elif task == "autocomplete":
                async for piece in self._assist.Autocomplete(request.autocomplete, timeout=ASSIST_TIMEOUT_S):
                    yield event(autocomplete=piece)
            elif task == "summarize":
                req = assist_pb2.SummarizeRequest()
                req.CopyFrom(request.summarize)
                req.request_id = req.request_id or rid
                if not req.HasField("document"):  # summarize the current document
                    req.document.CopyFrom(await self._docs.snapshot(request.doc_id))
                async for piece in self._assist.Summarize(req, timeout=ASSIST_TIMEOUT_S):
                    yield event(summary=piece)
            else:  # ask: the handout's getLLMAnswer, with the document as context
                snapshot = await self._docs.snapshot(request.doc_id)
                answer = await self._assist.GetLLMAnswer(
                    assist_pb2.GetLLMAnswerRequest(request_id=rid, query=request.ask.question, context=snapshot),
                    timeout=ASSIST_TIMEOUT_S,
                )
                yield event(answer=answer)
        except grpc.aio.AioRpcError as err:
            log.warning("assist %s failed: %s %s", task, err.code().name, err.details())
            yield event(status_for(err), f"{err.code().name}: {err.details()}")

