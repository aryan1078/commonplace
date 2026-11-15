"""The gateway when its LLM server restarts or is down."""

import asyncio
import contextlib
import socket

import grpc
import pytest

import gateway.service
from assist.providers.fake import FakeProvider
from assist.server import AssistService
from collab.v1 import assist_pb2, assist_pb2_grpc, common_pb2, gateway_pb2, gateway_pb2_grpc
from gateway.auth import TokenStore, UserStore
from gateway.docs import CHANNEL_OPTIONS, DocsClient
from gateway.presence import Hub
from gateway.service import CollabService
from stack import ASSIST_SETTINGS, USERS


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_assist(port: int) -> grpc.aio.Server:
    server = grpc.aio.server()
    assist_pb2_grpc.add_AssistServiceServicer_to_server(AssistService(FakeProvider(), ASSIST_SETTINGS), server)
    server.add_insecure_port(f"127.0.0.1:{port}")
    await server.start()
    return server


@contextlib.asynccontextmanager
async def gateway_for(assist_port: int):
    """A gateway whose LLM server is at assist_port. Its document service is
    absent: summarizing a given document does not need it."""
    tokens = TokenStore()
    docs = DocsClient(f"127.0.0.1:{free_port()}")
    assist_channel = grpc.aio.insecure_channel(f"127.0.0.1:{assist_port}", options=CHANNEL_OPTIONS)
    server = grpc.aio.server()
    gateway_pb2_grpc.add_CollabServiceServicer_to_server(
        CollabService(UserStore(USERS), tokens, docs, assist_channel, Hub()), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield gateway_pb2_grpc.CollabServiceStub(channel), tokens.issue("alice").token
    finally:
        await channel.close()
        await server.stop(None)
        await assist_channel.close()
        await docs.close()


async def summarize(stub, token) -> gateway_pb2.AssistEvent:
    request = gateway_pb2.AssistRequest(
        token=token, request_id="r", doc_id="d",
        summarize=assist_pb2.SummarizeRequest(
            document=common_pb2.DocumentSnapshot(doc_id="d", revision=1, text="We chose Raft. It is simple.")
        ),
    )
    return [e async for e in stub.Assist(request)][-1]


@pytest.fixture
def connect_timeout(monkeypatch):
    def set_timeout(seconds: float) -> None:
        monkeypatch.setattr(gateway.service, "ASSIST_CONNECT_TIMEOUT_S", seconds)

    return set_timeout


def test_llm_server_restart_is_survived(connect_timeout):
    connect_timeout(3.0)

    async def main():
        port = free_port()
        assist = await start_assist(port)
        try:
            async with gateway_for(port) as (stub, token):
                assert (await summarize(stub, token)).status == gateway_pb2.OK

                await assist.stop(None)  # the LLM server goes away...
                assert (await summarize(stub, token)).status == gateway_pb2.UNAVAILABLE

                assist = await start_assist(port)  # ...and comes back
                event = await summarize(stub, token)
                assert event.status == gateway_pb2.OK, event.message
        finally:
            await assist.stop(None)

    asyncio.run(main())


def test_llm_server_down_fails_fast(connect_timeout):
    connect_timeout(1.0)

    async def main():
        async with gateway_for(free_port()) as (stub, token):
            started = asyncio.get_running_loop().time()
            event = await summarize(stub, token)
            assert event.status == gateway_pb2.UNAVAILABLE and "not reachable" in event.message
            assert asyncio.get_running_loop().time() - started < 5

    asyncio.run(main())
