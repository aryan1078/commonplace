"""Runs the document service.

    python run.py docnode --port 50051
"""

import argparse
import asyncio
import logging

import grpc
from grpc_reflection.v1alpha import reflection

from collab.v1 import document_pb2, document_pb2_grpc, raft_pb2_grpc
from .raft import RaftLog

from .oplog import LocalLog
from .server import DocumentServer
from .statemachine import StateMachine

log = logging.getLogger("docnode")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="docnode", description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="interface to listen on")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--address", help="this voter address, also present in --peers")
    parser.add_argument("--peers", default="", help="comma-separated fixed voter addresses")
    parser.add_argument("--data-dir", default="data/node")
    return parser.parse_args(argv)


async def serve(args: argparse.Namespace) -> None:
    sm = StateMachine()
    voters = [p.strip() for p in args.peers.split(",") if p.strip()]
    if voters and (args.address not in voters or len(voters) != 3 or len(set(voters)) != 3):
        raise ValueError("provide exactly three unique voters including --address")
    store = RaftLog(args.address, [p for p in voters if p != args.address], args.data_dir, sm) if voters else LocalLog(sm)
    server = grpc.aio.server()
    if voters:
        raft_pb2_grpc.add_RaftServiceServicer_to_server(store, server)
    document_pb2_grpc.add_DocumentServiceServicer_to_server(DocumentServer(store, sm), server)
    reflection.enable_server_reflection(
        [document_pb2.DESCRIPTOR.services_by_name["DocumentService"].full_name, reflection.SERVICE_NAME],
        server,
    )
    server.add_insecure_port(f"{args.host}:{args.port}")
    await server.start()
    if voters:
        await store.start()
    log.info("document service listening on %s:%d (%s)", args.host, args.port, "Raft" if voters else "volatile local mode")
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(grace=1)
        if voters:
            await store.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(parse_args(argv)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
