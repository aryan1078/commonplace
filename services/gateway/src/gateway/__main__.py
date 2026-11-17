"""Runs the gateway (the application server clients connect to).

    python run.py gateway --port 50070 --docnodes localhost:50051 --assist localhost:50061
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path

import grpc
from grpc_reflection.v1alpha import reflection

from collab.v1 import gateway_pb2, gateway_pb2_grpc

from .auth import DEFAULT_TOKEN_TTL_S, TokenStore, UserStore, load_users
from .docs import CHANNEL_OPTIONS, DocsClient
from .presence import Hub
from .service import CollabService

log = logging.getLogger("gateway")

DEFAULT_USERS = Path(__file__).resolve().parents[4] / "config" / "users.json"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="gateway", description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=50070)
    parser.add_argument("--docnodes", default="localhost:50051", help="document service address")
    parser.add_argument("--assist", default="localhost:50061", help="Assist (LLM) service address")
    parser.add_argument("--users", type=Path, default=DEFAULT_USERS, help="users.json with password hashes")
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    return parser.parse_args(argv)


async def serve(args: argparse.Namespace) -> None:
    users = load_users(args.users)
    if not users:
        log.warning("no users in %s; add some with scripts/manage_users.py", args.users)
    ttl = float(os.getenv("GATEWAY_TOKEN_TTL_S", DEFAULT_TOKEN_TTL_S))
    docs = DocsClient(args.docnodes)
    assist_channel = grpc.aio.insecure_channel(args.assist, options=CHANNEL_OPTIONS)

    server = grpc.aio.server()
    gateway_pb2_grpc.add_CollabServiceServicer_to_server(
        CollabService(UserStore(users), TokenStore(ttl), docs, assist_channel, Hub()),
        server,
    )
    reflection.enable_server_reflection(
        [gateway_pb2.DESCRIPTOR.services_by_name["CollabService"].full_name, reflection.SERVICE_NAME], server
    )
    if bool(args.tls_cert) != bool(args.tls_key):
        raise ValueError("--tls-cert and --tls-key must be supplied together")
    if args.tls_cert:
        credentials = grpc.ssl_server_credentials([(args.tls_key.read_bytes(), args.tls_cert.read_bytes())])
        bound = server.add_secure_port(f"{args.host}:{args.port}", credentials)
    else:
        bound = server.add_insecure_port(f"{args.host}:{args.port}")
    if not bound:
        raise RuntimeError("gateway could not bind its port")
    await server.start()
    log.info("gateway listening on %s:%d (docnodes: %s, assist: %s, %d users, token TTL %.0fs)",
             args.host, args.port, args.docnodes, args.assist, len(users), ttl)
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(grace=1)
        await docs.close()
        await assist_channel.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(parse_args(argv)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
