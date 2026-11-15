"""Runs the real gRPC server on a local port and talks to it as a client would."""

import asyncio
import contextlib

import grpc
import pytest

from collab.v1 import common_pb2, document_pb2, document_pb2_grpc
from docnode.oplog import LocalLog
from docnode.server import CURRENT_REVISION_KEY, DocumentServer
from docnode.statemachine import StateMachine


@contextlib.asynccontextmanager
async def running_server():
    sm = StateMachine()
    server = grpc.aio.server()
    document_pb2_grpc.add_DocumentServiceServicer_to_server(DocumentServer(LocalLog(sm), sm), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield document_pb2_grpc.DocumentServiceStub(channel)
    finally:
        await channel.close()
        await server.stop(None)


def run_with_server(test):
    """Runs `async def test(stub)` against a fresh server."""

    async def main():
        async with running_server() as stub:
            await test(stub)

    asyncio.run(main())


def insert_op(client: str, seq: int, base: int, pos: int, s: str) -> common_pb2.Operation:
    return common_pb2.Operation(
        op_id=common_pb2.OpId(client_id=client, seq=seq),
        doc_id="doc",
        base_revision=base,
        changes=[common_pb2.TextChange(range=common_pb2.TextRange(start=pos, end=pos), insert=s)],
    )


async def submit(stub, *ops):
    return await stub.SubmitOperations(
        document_pb2.SubmitOperationsRequest(doc_id="doc", operations=ops), timeout=5
    )


def test_edit_snapshot_and_conflict():
    async def test(stub):
        res = await submit(stub, insert_op("alice", 1, 0, 0, "hello"))
        assert (res.revision, res.applied) == (1, 1)

        # Bob edited revision 0 too, so his edit is stale.
        with pytest.raises(grpc.aio.AioRpcError) as info:
            await submit(stub, insert_op("bob", 1, 0, 0, "X"))
        assert info.value.code() == grpc.StatusCode.ABORTED
        assert (CURRENT_REVISION_KEY, "1") in tuple(info.value.trailing_metadata())

        # Bob rebases onto revision 1 and resends.
        await submit(stub, insert_op("bob", 1, 1, 5, "!"))
        snap = (await stub.GetSnapshot(document_pb2.GetSnapshotRequest(doc_id="doc"))).snapshot
        assert (snap.text, snap.revision) == ("hello!", 2)

    run_with_server(test)


def test_retry_is_reported_as_duplicate():
    async def test(stub):
        op = insert_op("alice", 1, 0, 0, "x")
        await submit(stub, op)
        res = await submit(stub, op)
        assert (res.applied, res.duplicates, res.revision) == (0, 1, 1)

    run_with_server(test)


def test_invalid_edit_is_rejected():
    async def test(stub):
        with pytest.raises(grpc.aio.AioRpcError) as info:
            await submit(stub, insert_op("alice", 1, 0, 50, "x"))  # past the end
        assert info.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    run_with_server(test)


def test_subscribe_streams_history_then_live_edits():
    async def test(stub):
        await submit(stub, insert_op("alice", 1, 0, 0, "a"))
        stream = stub.Subscribe(document_pb2.SubscribeRequest(doc_id="doc", from_revision=0))

        first = await asyncio.wait_for(stream.read(), 5)  # from history
        assert (first.revision, first.operation.op_id.client_id) == (1, "alice")

        await submit(stub, insert_op("bob", 1, 1, 1, "b"))
        second = await asyncio.wait_for(stream.read(), 5)  # live
        assert (second.revision, second.operation.changes[0].insert) == (2, "b")
        assert second.operation.base_revision == 1
        stream.cancel()

    run_with_server(test)


def test_history_and_document_list():
    async def test(stub):
        await submit(stub, insert_op("alice", 1, 0, 0, "a"), insert_op("alice", 2, 1, 1, "b"))
        history = await stub.GetHistory(document_pb2.GetHistoryRequest(doc_id="doc", from_revision=1))
        assert [o.revision for o in history.operations] == [2] and history.revision == 2

        page = await stub.GetHistory(document_pb2.GetHistoryRequest(doc_id="doc", limit=1))
        assert [o.revision for o in page.operations] == [1]

        docs = await stub.ListDocuments(document_pb2.ListDocumentsRequest())
        assert [(d.doc_id, d.revision, d.length) for d in docs.documents] == [("doc", 2, 2)]

        with pytest.raises(grpc.aio.AioRpcError) as info:
            await stub.GetHistory(document_pb2.GetHistoryRequest(doc_id="doc", from_revision=9))
        assert info.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    run_with_server(test)
