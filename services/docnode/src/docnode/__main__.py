"""Runs the document service.

    python run.py docnode --port 50051
"""

import argparse
import asyncio
import logging

import grpc
from grpc_reflection.v1alpha import reflection

from collab.v1 import document_pb2, document_pb2_grpc

from .oplog import LocalLog
from .server import DocumentServer
from .statemachine import StateMachine

log = logging.getLogger("docnode")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="docnode", description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="interface to listen on")
    parser.add_argument("--port", type=int, default=50051)
    return parser.parse_args(argv)


async def serve(args: argparse.Namespace) -> None:
    sm = StateMachine()
    server = grpc.aio.server()
    document_pb2_grpc.add_DocumentServiceServicer_to_server(DocumentServer(LocalLog(sm), sm), server)
    reflection.enable_server_reflection(
        [document_pb2.DESCRIPTOR.services_by_name["DocumentService"].full_name, reflection.SERVICE_NAME],
        server,
    )
    server.add_insecure_port(f"{args.host}:{args.port}")
    await server.start()
    log.info("document service listening on %s:%d (single node)", args.host, args.port)
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(grace=1)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(parse_args(argv)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
