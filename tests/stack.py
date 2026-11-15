"""Runs the whole system (docnode, fake-LLM assist, gateway) inside the test's
event loop, on free local ports, so tests exercise the real gRPC paths."""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

import grpc

from assist.config import Settings
from assist.providers.fake import FakeProvider
from assist.server import AssistService
from collab.v1 import assist_pb2_grpc, document_pb2_grpc, gateway_pb2_grpc
from docnode.oplog import LocalLog
from docnode.server import DocumentServer
from docnode.statemachine import StateMachine
from gateway.auth import TokenStore, UserStore, hash_password
from gateway.docs import DocsClient
from gateway.presence import Hub
from gateway.service import CollabService

# Few iterations: the tests check the logic, not the hashing cost.
USERS = {name: hash_password(f"{name}123", iterations=1000) for name in ("alice", "bob", "carol")}

ASSIST_SETTINGS = Settings(
    provider="fake", base_url="", api_key="", model="", fast_model="", reasoning_effort=None,
    port=0, max_input_chars=8000, max_summary_chars=60000, default_timeout_s=5,
)


@dataclass
class Stack:
    gateway: str  # address clients connect to
    stub: gateway_pb2_grpc.CollabServiceStub
    tokens: TokenStore
    sm: StateMachine


async def _server(add) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server()
    add(server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, port


@contextlib.asynccontextmanager
async def running_stack(token_ttl_s: float = 3600) -> AsyncIterator[Stack]:
    sm = StateMachine()
    docnode, doc_port = await _server(
        lambda s: document_pb2_grpc.add_DocumentServiceServicer_to_server(DocumentServer(LocalLog(sm), sm), s)
    )
    assist, assist_port = await _server(
        lambda s: assist_pb2_grpc.add_AssistServiceServicer_to_server(
            AssistService(FakeProvider(), ASSIST_SETTINGS), s
        )
    )
    docs = DocsClient(f"127.0.0.1:{doc_port}")
    assist_channel = grpc.aio.insecure_channel(f"127.0.0.1:{assist_port}")
    tokens = TokenStore(token_ttl_s)
    service = CollabService(UserStore(USERS), tokens, docs, assist_pb2_grpc.AssistServiceStub(assist_channel), Hub())
    gateway, gw_port = await _server(lambda s: gateway_pb2_grpc.add_CollabServiceServicer_to_server(service, s))
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{gw_port}")
    try:
        yield Stack(f"127.0.0.1:{gw_port}", gateway_pb2_grpc.CollabServiceStub(channel), tokens, sm)
    finally:
        await channel.close()
        await gateway.stop(None)
        await docs.close()
        await assist_channel.close()
        await assist.stop(None)
        await docnode.stop(None)
