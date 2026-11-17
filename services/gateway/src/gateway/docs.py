"""The gateway's connection to the document service.

All document access goes through this one class, so the rest of the gateway
does not care how many docnodes there are or which one to talk to.
"""

from collections.abc import AsyncIterator

import grpc
import asyncio
import time

from collab.v1 import common_pb2, document_pb2, document_pb2_grpc, raft_pb2, raft_pb2_grpc

SUBMIT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 5.0

# Reconnect quickly after a backend restarts. By default gRPC's reconnect
# backoff grows to two minutes, and while it waits every call fails at once.
CHANNEL_OPTIONS = [
    ("grpc.initial_reconnect_backoff_ms", 200),
    ("grpc.min_reconnect_backoff_ms", 200),
    ("grpc.max_reconnect_backoff_ms", 2000),
]


class DocsClient:
    """Calls wait (up to their deadline) for the connection instead of failing
    at once, so a docnode that is restarting looks slow, not broken."""

    def __init__(self, address: str):
        self._addresses = [a.strip() for a in address.split(",") if a.strip()]
        self._channels = {a: grpc.aio.insecure_channel(a, options=CHANNEL_OPTIONS) for a in self._addresses}
        self._stubs = {a: document_pb2_grpc.DocumentServiceStub(ch) for a,ch in self._channels.items()}
        self._preferred = self._addresses[0]

    async def close(self):
        await asyncio.gather(*(ch.close() for ch in self._channels.values()))

    async def _call(self, method, request, timeout):
        deadline = time.monotonic() + timeout
        error = None
        while time.monotonic() < deadline:
            addresses = [self._preferred, *[a for a in self._addresses if a != self._preferred]]
            for address in addresses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    reply = await getattr(self._stubs[address], method)(request, timeout=min(3.0, remaining))
                    self._preferred = address
                    return reply
                except grpc.aio.AioRpcError as err:
                    if err.code() not in (grpc.StatusCode.FAILED_PRECONDITION,
                                          grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                        raise
                    error = err
                    hints = dict(err.trailing_metadata() or ())
                    if hints.get("leader-addr") in self._stubs:
                        self._preferred = hints["leader-addr"]
            await asyncio.sleep(0.05)
        raise error

    async def cluster_status(self, doc_id):
        async def one(address, channel):
            try:
                return await raft_pb2_grpc.RaftServiceStub(channel).Status(
                    raft_pb2.StatusRequest(doc_id=doc_id), timeout=0.8)
            except grpc.aio.AioRpcError:
                return raft_pb2.StatusReply(node=address, role="unreachable")
        return await asyncio.gather(*(one(a,ch) for a,ch in self._channels.items()))

    async def submit(self, request: document_pb2.SubmitOperationsRequest) -> document_pb2.SubmitOperationsResponse:
        return await self._call("SubmitOperations", request, SUBMIT_TIMEOUT_S)

    async def snapshot(self, doc_id: str) -> common_pb2.DocumentSnapshot:
        reply = await self._call("GetSnapshot", document_pb2.GetSnapshotRequest(doc_id=doc_id), READ_TIMEOUT_S)
        return reply.snapshot

    async def history(self, doc_id: str, from_revision: int, limit: int) -> document_pb2.GetHistoryResponse:
        return await self._call("GetHistory",
            document_pb2.GetHistoryRequest(doc_id=doc_id, from_revision=from_revision, limit=limit),
            READ_TIMEOUT_S,
        )

    async def documents(self) -> list[document_pb2.DocumentInfo]:
        reply = await self._call("ListDocuments", document_pb2.ListDocumentsRequest(), READ_TIMEOUT_S)
        return list(reply.documents)

    async def subscribe(self, doc_id: str, from_revision: int) -> AsyncIterator[document_pb2.SubscribeResponse]:
        """Committed operations in order, reconnecting after transient failures.

        Leader discovery and the stream itself can both fail during elections.
        Retain the last delivered revision across either kind of interruption.
        """
        while True:
            stream = None
            try:
                await self.snapshot(doc_id)
                stream = self._stubs[self._preferred].Subscribe(
                    document_pb2.SubscribeRequest(doc_id=doc_id, from_revision=from_revision))
                async for msg in stream:
                    if msg.revision > from_revision:
                        from_revision = msg.revision
                        yield msg
            except grpc.aio.AioRpcError as err:
                if err.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.FAILED_PRECONDITION,
                                      grpc.StatusCode.DEADLINE_EXCEEDED):
                    raise
            finally:
                if stream is not None:
                    stream.cancel()
            await asyncio.sleep(0.1)
