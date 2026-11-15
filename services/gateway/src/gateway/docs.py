"""The gateway's connection to the document service.

All document access goes through this one class, so the rest of the gateway
does not care how many docnodes there are or which one to talk to.
"""

from collections.abc import AsyncIterator

import grpc

from collab.v1 import common_pb2, document_pb2, document_pb2_grpc

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
        self._channel = grpc.aio.insecure_channel(address, options=CHANNEL_OPTIONS)
        self._stub = document_pb2_grpc.DocumentServiceStub(self._channel)

    async def close(self) -> None:
        await self._channel.close()

    async def submit(self, request: document_pb2.SubmitOperationsRequest) -> document_pb2.SubmitOperationsResponse:
        return await self._stub.SubmitOperations(request, timeout=SUBMIT_TIMEOUT_S, wait_for_ready=True)

    async def snapshot(self, doc_id: str) -> common_pb2.DocumentSnapshot:
        reply = await self._stub.GetSnapshot(document_pb2.GetSnapshotRequest(doc_id=doc_id), timeout=READ_TIMEOUT_S, wait_for_ready=True)
        return reply.snapshot

    async def history(self, doc_id: str, from_revision: int, limit: int) -> document_pb2.GetHistoryResponse:
        return await self._stub.GetHistory(
            document_pb2.GetHistoryRequest(doc_id=doc_id, from_revision=from_revision, limit=limit),
            timeout=READ_TIMEOUT_S,
            wait_for_ready=True,
        )

    async def documents(self) -> list[document_pb2.DocumentInfo]:
        reply = await self._stub.ListDocuments(document_pb2.ListDocumentsRequest(), timeout=READ_TIMEOUT_S, wait_for_ready=True)
        return list(reply.documents)

    async def subscribe(self, doc_id: str, from_revision: int) -> AsyncIterator[document_pb2.SubscribeResponse]:
        """Every operation committed after from_revision, in order. Raises
        grpc.aio.AioRpcError if the document service goes away."""
        stream = self._stub.Subscribe(document_pb2.SubscribeRequest(doc_id=doc_id, from_revision=from_revision))
        try:
            async for msg in stream:
                yield msg
        finally:
            stream.cancel()
