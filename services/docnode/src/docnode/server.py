"""Exposes the document state machine over gRPC.

It only translates: protobuf messages in, state machine calls, protobuf
messages and gRPC status codes out. All decisions are made by the state
machine, and all writes go through the `Log` (local or Raft).
"""

import logging

import grpc

from collab.v1 import common_pb2, document_pb2, document_pb2_grpc

from .convert import batch_from_proto, committed_to_proto
from .oplog import Log, NotLeader
from .statemachine import ApplyError, InvalidOperation, StaleError, StateMachine
from .subscribe import SubscriberTooSlow

log = logging.getLogger("docnode")

SUBSCRIBE_BUFFER = 1024  # operations queued for one subscriber before it is dropped
MAX_OPS_PER_REQUEST = 1000  # largest SubmitOperations batch
MAX_HISTORY = 1000  # most operations returned by one GetHistory call

# Trailing metadata keys. Lowercase, as gRPC requires.
CURRENT_REVISION_KEY = "current-revision"
LEADER_KEY = "leader-addr"


class DocumentServer(document_pb2_grpc.DocumentServiceServicer):
    def __init__(self, log: Log, sm: StateMachine):
        self._log = log
        self._sm = sm

    async def GetSnapshot(self, request, context):
        await _require_doc_id(request.doc_id, context)
        text, revision = self._sm.snapshot(request.doc_id)
        return document_pb2.GetSnapshotResponse(
            snapshot=common_pb2.DocumentSnapshot(doc_id=request.doc_id, revision=revision, text=text)
        )

    async def SubmitOperations(self, request, context):
        if len(request.operations) > MAX_OPS_PER_REQUEST:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_OPS_PER_REQUEST} operations per request"
            )
        try:
            result = await self._log.propose(batch_from_proto(request.doc_id, request.operations))
        except StaleError as err:
            await context.abort(
                grpc.StatusCode.ABORTED, str(err), trailing_metadata=((CURRENT_REVISION_KEY, str(err.current)),)
            )
        except InvalidOperation as err:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(err))
        except NotLeader as err:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, str(err), trailing_metadata=((LEADER_KEY, err.leader),)
            )
        return document_pb2.SubmitOperationsResponse(
            revision=result.revision, applied=result.applied, duplicates=result.duplicates
        )

    async def Subscribe(self, request, context):
        await _require_doc_id(request.doc_id, context)
        try:
            sub = self._sm.subscribe(request.doc_id, request.from_revision, SUBSCRIBE_BUFFER)
        except ApplyError as err:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(err))
        try:
            for c in sub.backlog:
                yield committed_to_proto(c)
            while (c := await sub.next()) is not None:
                yield committed_to_proto(c)
            if isinstance(sub.error, SubscriberTooSlow):
                await context.abort(
                    grpc.StatusCode.UNAVAILABLE,
                    "subscriber fell behind; subscribe again from the last revision received",
                )
        finally:
            sub.close()  # also runs when the client goes away (the task is cancelled)

    async def GetHistory(self, request, context):
        await _require_doc_id(request.doc_id, context)
        limit = min(request.limit or MAX_HISTORY, MAX_HISTORY)
        try:
            ops = self._sm.history(request.doc_id, request.from_revision, limit)
        except ApplyError as err:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(err))
        _, revision = self._sm.snapshot(request.doc_id)
        return document_pb2.GetHistoryResponse(
            operations=[committed_to_proto(c) for c in ops], revision=revision
        )

    async def ListDocuments(self, request, context):
        return document_pb2.ListDocumentsResponse(
            documents=[
                document_pb2.DocumentInfo(doc_id=d.doc_id, revision=d.revision, length=d.length)
                for d in self._sm.documents()
            ]
        )


async def _require_doc_id(doc_id: str, context) -> None:
    if not doc_id:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "doc_id is required")
