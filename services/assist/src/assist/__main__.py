"""Runs the Assist (LLM) service.

    python run.py assist

Configured through environment variables or .env (see .env.example).
"""

import asyncio
import logging

import grpc

from collab.v1 import assist_pb2_grpc

from .config import Settings
from .providers import make_provider
from .server import AssistService

log = logging.getLogger("assist")


async def serve(settings: Settings) -> None:
    server = grpc.aio.server()
    assist_pb2_grpc.add_AssistServiceServicer_to_server(
        AssistService(make_provider(settings), settings), server
    )
    server.add_insecure_port(f"0.0.0.0:{settings.port}")
    await server.start()
    log.info(
        "assist service listening on port %d (provider=%s, model=%s, fast model=%s, base_url=%s)",
        settings.port,
        settings.provider,
        settings.model or "-",
        settings.fast_model or "-",
        settings.base_url or "-",
    )
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(grace=1)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(Settings.from_env()))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
