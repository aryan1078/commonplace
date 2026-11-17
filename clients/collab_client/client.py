"""The client library (node 5): the handout's login/logout/post/get, plus
`edit`, which hides the conflict protocol, and `join`, which keeps a live copy
of a document.

One CollabClient is one editing session: it has its own client_id and numbers
its operations 1, 2, 3, ... Edits from one client are sent one at a time (a
lock enforces it), because the server treats a lower seq arriving after a
higher one as an old retry.
"""

import asyncio
import random
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field

import grpc
from google.protobuf.message import Message

from collab.v1 import assist_pb2, common_pb2, document_pb2, gateway_pb2, gateway_pb2_grpc, presence_pb2

from .textops import Change, apply_changes, rebase, utf16_len

S = gateway_pb2
HISTORY_PAGE = 1000


def status_name(status: int) -> str:
    return gateway_pb2.Status.Name(status)


class CollabError(Exception):
    """A call failed with a non-OK Status."""

    def __init__(self, status: int, message: str = ""):
        super().__init__(f"{status_name(status)}: {message}" if message else status_name(status))
        self.status = status


@dataclass(frozen=True)
class EditResult:
    revision: int  # the document's revision after the edit
    attempts: int  # 1 if accepted at once; more if it was rebased or retried
    duplicate: bool  # True if an earlier attempt had already been applied


class CollabClient:
    def __init__(self, address: str, client_id: str | None = None, *, tls: bool = False, root_certificates: bytes | None = None):
        self._channel = (grpc.aio.secure_channel(address, grpc.ssl_channel_credentials(root_certificates))
                         if tls else grpc.aio.insecure_channel(address))
        self.stub = gateway_pb2_grpc.CollabServiceStub(self._channel)
        self.client_id = client_id or uuid.uuid4().hex
        self.token = ""
        self.username = ""
        self._seq = 0
        self._edit_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._channel.close()

    async def __aenter__(self) -> "CollabClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # ------------------------------------------------- the handout's functions

    async def login(self, username: str, password: str) -> gateway_pb2.LoginResponse:
        reply = await self.stub.Login(gateway_pb2.LoginRequest(username=username, password=password))
        if reply.status == S.OK:
            self.token, self.username = reply.token, username
        return reply

    async def logout(self) -> int:
        reply = await self.stub.Logout(gateway_pb2.LogoutRequest(token=self.token))
        self.token = ""
        return reply.status

    async def post(self, data: Message, session_id: str = "") -> gateway_pb2.PostResponse:
        """post(token, type, data): the type follows from data's message type
        (SubmitOperationsRequest is an edit, CursorUpdate a cursor move)."""
        request = gateway_pb2.PostRequest(token=self.token, session_id=session_id)
        if isinstance(data, document_pb2.SubmitOperationsRequest):
            request.edit.CopyFrom(data)
        elif isinstance(data, presence_pb2.CursorUpdate):
            request.cursor.CopyFrom(data)
        else:
            raise TypeError(f"cannot post a {type(data).__name__}")
        return await self.stub.Post(request, timeout=15)

    async def get(self, kind: str, **params) -> tuple[int, list[tuple[str, Message]]]:
        """get(token, type, params) -> (status, [(id, data)]).

        kind is "snapshot", "history", "presence" or "documents"; params are
        that kind's fields, e.g. get("history", doc_id="notes", from_revision=3).
        """
        param_types = {
            "snapshot": gateway_pb2.SnapshotParams,
            "history": gateway_pb2.HistoryParams,
            "presence": gateway_pb2.PresenceParams,
            "documents": gateway_pb2.DocumentsParams,
        }
        request = gateway_pb2.GetRequest(token=self.token, **{kind: param_types[kind](**params)})
        reply = await self.stub.Get(request, timeout=10)
        return reply.status, [(item.id, getattr(item, item.WhichOneof("data"))) for item in reply.items]

    # ------------------------------------------------------------- reads

    async def snapshot(self, doc_id: str) -> common_pb2.DocumentSnapshot:
        status, items = await self.get("snapshot", doc_id=doc_id)
        if status != S.OK:
            raise CollabError(status)
        return items[0][1]

    async def history(self, doc_id: str, from_revision: int = 0) -> list[document_pb2.SubscribeResponse]:
        """Every committed operation after from_revision, paging as needed."""
        ops: list[document_pb2.SubscribeResponse] = []
        while True:
            status, items = await self.get("history", doc_id=doc_id, from_revision=from_revision, limit=HISTORY_PAGE)
            if status != S.OK:
                raise CollabError(status)
            ops += [op for _, op in items]
            if len(items) < HISTORY_PAGE:
                return ops
            from_revision = ops[-1].revision

    # ------------------------------------------------------------- edits

    async def edit(self, doc_id: str, changes: Sequence[Change], base_revision: int,
                   session_id: str = "", max_attempts: int = 100,
                   operation_id: common_pb2.OpId | None = None) -> EditResult:
        """Submits one edit made against base_revision and makes sure it lands.

        On STALE_REVISION it fetches the operations it missed, moves its
        positions past them and sends again. On UNAVAILABLE it waits and sends
        the same thing again. Every attempt carries the same op_id, so the
        edit is applied exactly once whatever happens to earlier attempts.
        """
        async with self._edit_lock:
            if operation_id is None:
                self._seq += 1
                op_id = common_pb2.OpId(client_id=self.client_id, seq=self._seq)
            else:
                op_id = operation_id
                self._seq = max(self._seq, op_id.seq)
            changes, base = list(changes), base_revision
            for attempt in range(1, max_attempts + 1):
                op = common_pb2.Operation(op_id=op_id, doc_id=doc_id, base_revision=base, changes=[
                    common_pb2.TextChange(range=common_pb2.TextRange(start=c.start, end=c.end), insert=c.insert)
                    for c in changes
                ])
                try:
                    reply = await self.post(document_pb2.SubmitOperationsRequest(doc_id=doc_id, operations=[op]),
                                            session_id)
                    if reply.status == S.OK:
                        return EditResult(reply.edit.revision, attempt, reply.edit.duplicates > 0)
                    if reply.status == S.STALE_REVISION:
                        # Fetch every page before changing our base or positions.
                        # An election can interrupt this read as well as Post.
                        missed_ops = await self.history(doc_id, base)
                        for missed in missed_ops:
                            theirs = [Change(c.range.start, c.range.end, c.insert) for c in missed.operation.changes]
                            changes, base = rebase(changes, theirs), missed.revision
                        continue
                    if reply.status != S.UNAVAILABLE:
                        raise CollabError(reply.status, reply.message)
                except CollabError as error:
                    if error.status != S.UNAVAILABLE:
                        raise
                except grpc.aio.AioRpcError as error:
                    if error.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                        raise
                await asyncio.sleep(min(2.0, 0.05 * 2 ** min(attempt, 8)) * random.uniform(0.5, 1))
            raise CollabError(S.UNAVAILABLE, f"edit not accepted after {max_attempts} attempts")

    async def move_cursor(self, view: "DocumentView", anchor: int, head: int | None = None) -> int:
        cursor = presence_pb2.CursorUpdate(revision=view.revision, anchor=anchor, head=anchor if head is None else head)
        return (await self.post(cursor, view.session_id)).status

    # ------------------------------------------------------------- join

    async def join(self, doc_id: str, on_event: Callable[[gateway_pb2.JoinEvent], None] | None = None
                   ) -> "DocumentView":
        """Opens a document and returns its live copy (after `joined`)."""
        view = DocumentView(self, doc_id, on_event)
        await view.start()
        return view

    # ------------------------------------------------------------- assist

    async def assist_stream(self, doc_id: str, **task) -> AsyncIterator[gateway_pb2.AssistEvent]:
        request = gateway_pb2.AssistRequest(token=self.token, request_id=uuid.uuid4().hex, doc_id=doc_id, **task)
        async for event in self.stub.Assist(request):
            if event.status != S.OK:
                raise CollabError(event.status, event.message)
            yield event

    async def ask(self, doc_id: str, question: str) -> gateway_pb2.AssistEvent:
        return [e async for e in self.assist_stream(doc_id, ask=gateway_pb2.AskRequest(question=question))][0]

    async def check_grammar(self, view: "DocumentView") -> list[assist_pb2.Suggestion]:
        ctx = view.text_context(0, utf16_len(view.text))
        events = [e async for e in self.assist_stream(view.doc_id, check_grammar=assist_pb2.CheckGrammarRequest(context=ctx))]
        return list(events[0].grammar.suggestions)

    async def enhance(self, view: "DocumentView", start: int, end: int, mode: int) -> list[assist_pb2.Suggestion]:
        req = assist_pb2.EnhanceRequest(context=view.text_context(start, end), mode=mode)
        events = [e async for e in self.assist_stream(view.doc_id, enhance=req)]
        return list(events[0].enhanced.suggestions)


@dataclass
class DocumentView:
    """A live copy of one document, kept current by a Join stream."""

    client: CollabClient
    doc_id: str
    on_event: Callable[[gateway_pb2.JoinEvent], None] | None = None
    session_id: str = ""
    revision: int = 0
    participants: list[presence_pb2.Participant] = field(default_factory=list)
    closed: gateway_pb2.ClosedEvent | None = None
    _text: bytes = b""
    _changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    _task: asyncio.Task | None = None

    @property
    def text(self) -> str:
        return self._text.decode("utf-16-le")

    async def start(self) -> None:
        self._stream = self.client.stub.Join(gateway_pb2.JoinRequest(token=self.client.token, doc_id=self.doc_id))
        first = await self._stream.read()
        if first is grpc.aio.EOF or first.WhichOneof("event") != "joined":
            closed = first.closed if first is not grpc.aio.EOF else gateway_pb2.ClosedEvent(status=S.UNAVAILABLE)
            raise CollabError(closed.status, closed.reason)
        joined = first.joined
        self.session_id = joined.session_id
        self._text, self.revision = joined.snapshot.text.encode("utf-16-le"), joined.snapshot.revision
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            # read(), not `async for`: gRPC forbids mixing the two on one call,
            # and start() already read the `joined` event.
            while (event := await self._stream.read()) is not grpc.aio.EOF:
                kind = event.WhichOneof("event")
                if kind == "operation":
                    op = event.operation
                    if op.revision != self.revision + 1:
                        raise RuntimeError(f"gap in the stream: at {self.revision}, got {op.revision}")
                    self._text = apply_changes(self._text, [
                        Change(c.range.start, c.range.end, c.insert) for c in op.operation.changes])
                    self.revision = op.revision
                elif kind == "presence":
                    self.participants = list(event.presence.participants)
                elif kind == "closed":
                    self.closed = event.closed
                if self.on_event:
                    self.on_event(event)
                async with self._changed:
                    self._changed.notify_all()
                if self.closed:
                    return
        except grpc.aio.AioRpcError as err:
            if err.code() != grpc.StatusCode.CANCELLED:
                self.closed = gateway_pb2.ClosedEvent(status=S.UNAVAILABLE, reason=err.details() or "")
        finally:
            if self.closed is None:
                self.closed = gateway_pb2.ClosedEvent(status=S.UNAVAILABLE, reason="stream ended")
            async with self._changed:
                self._changed.notify_all()

    async def wait_for(self, predicate: Callable[["DocumentView"], bool], timeout: float = 10) -> None:
        async def wait() -> None:
            async with self._changed:
                await self._changed.wait_for(lambda: predicate(self) or self.closed is not None)
        await asyncio.wait_for(wait(), timeout)

    async def wait_for_revision(self, revision: int, timeout: float = 10) -> None:
        await self.wait_for(lambda v: v.revision >= revision, timeout)
        if self.revision < revision:
            raise CollabError(self.closed.status if self.closed else S.UNAVAILABLE, "stream closed")

    async def edit(self, *changes: Change) -> EditResult:
        """Edits this document at the revision we currently see."""
        return await self.client.edit(self.doc_id, changes, self.revision, self.session_id)

    def text_context(self, start: int, end: int) -> assist_pb2.TextContext:
        """An LLM request context for [start, end) of the current text."""
        doc = self._text
        return assist_pb2.TextContext(
            request_id=uuid.uuid4().hex,
            anchor=common_pb2.TextAnchor(doc_id=self.doc_id, revision=self.revision,
                                         range=common_pb2.TextRange(start=start, end=end)),
            text=doc[2 * start: 2 * end].decode("utf-16-le"),
            before=doc[max(0, 2 * (start - 1500)): 2 * start].decode("utf-16-le", errors="ignore"),
            after=doc[2 * end: 2 * (end + 500)].decode("utf-16-le", errors="ignore"),
        )

    async def close(self) -> None:
        if self._task:
            self._stream.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
