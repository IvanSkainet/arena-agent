"""gRPC-style secondary interface domain package."""

from arena.grpc.runtime import (
    GRPC_CONFIG,
    GRPC_METHOD_MAP,
    grpc_handler,
    grpc_server_loop,
    start_grpc_server,
    stop_grpc_server,
)
from arena.grpc.handlers import GrpcHandlers, make_grpc_handlers

__all__ = [
    "GRPC_CONFIG",
    "GRPC_METHOD_MAP",
    "grpc_handler",
    "grpc_server_loop",
    "start_grpc_server",
    "stop_grpc_server",
    "GrpcHandlers",
    "make_grpc_handlers",
]
